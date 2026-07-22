"""打印 PRODUCT_UNDERSTANDING 到 CREATIVE_SCRIPT 的最小串联结果。

这个脚本不经过数据库和 HTTP 接口，只构造一次运行输入，然后按当前图里的顺序手动调用：
1. product_understanding_node 生成商品理解 analysis。
2. creative_script_node 使用 analysis 生成创意脚本 draft。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import sys
from pathlib import Path
from uuid import uuid4

sys.path.append(str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.agents.modeling.provider import OpenAICompatibleProvider
from app.agents.models import config_model
from app.agents.nodes.creative_script import creative_script_node
from app.agents.nodes.product_understanding import product_understanding_node
from app.application.creative_agent import (
    CreativeAssetInput,
    CreativeBriefInput,
    CreativeProjectInput,
    CreativeRunInput,
)
from app.core.config import BACKEND_ROOT, get_settings


IMAGE_MIME_TYPES_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
SUPPORTED_IMAGE_MIME_TYPES = set(IMAGE_MIME_TYPES_BY_SUFFIX.values())


def main() -> None:
    args = parse_args()
    if args.force_local_product_understanding:
        # 让开始节点走本地商品理解，适合只验证节点串联结构。
        config_model.product_understanding_model = lambda: local_provider()
    if args.force_local_creative:
        # 让脚本节点走本地创意兜底，适合没有文本模型配置时打印完整草案。
        config_model.creative_script_model = lambda: local_provider()

    run_input = build_run_input(args)
    copied_images = [asset.model_dump(mode="json") for asset in run_input.assets]

    # PRODUCT_UNDERSTANDING 是当前自动图的第一个业务节点。
    product_command = product_understanding_node({"run_input": run_input})
    analysis = product_command.update.get("analysis")

    flow = ["product_understanding"]
    output: dict[str, object] = {
        "flow": flow,
        "copied_images": copied_images,
        "product_understanding": {
            "goto": product_command.goto,
            "provider": product_command.update.get("product_understanding_provider_key"),
            "model": product_command.update.get("product_understanding_model_key"),
            "analysis": to_jsonable(analysis),
        },
    }
    if analysis is None:
        output["status"] = "failed"
        output["error_at"] = "product_understanding"
        output["error_message"] = "PRODUCT_UNDERSTANDING 没有返回 analysis。"
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    try:
        # creative_script 只读取 run_input 和上一个节点产出的 analysis。
        creative_command = creative_script_node(
            {
                "run_input": run_input,
                "analysis": analysis,
                "provider_key": "local",
                "model_key": None,
                "revision_count": 0,
            }
        )
    except Exception as exc:
        # 例如图片和资料冲突时，creative_script 会在这里停止。
        output["status"] = "blocked"
        flow.append("creative_script")
        output["handoff"] = build_handoff_summary()
        output["error_at"] = "creative_script"
        output["error_message"] = str(exc)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    output["status"] = "succeeded"
    flow.append("creative_script")
    output["handoff"] = build_handoff_summary()
    output["creative_script"] = {
        "goto": creative_command.goto,
        "provider": creative_command.update.get("provider_key"),
        "model": creative_command.update.get("model_key"),
        "draft": to_jsonable(creative_command.update.get("draft")),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def build_run_input(args: argparse.Namespace) -> CreativeRunInput:
    project_id = args.project_id
    assets = copy_images_to_asset_storage(
        project_id=project_id,
        image_paths=args.image,
    )
    return CreativeRunInput(
        project=CreativeProjectInput(
            id=project_id,
            title=args.project_title,
            target_platform=args.target_platform,
            language="zh-CN",
            aspect_ratio="9:16",
            duration_seconds=args.duration_seconds,
            status="start_to_creative_script_print_test",
        ),
        brief=CreativeBriefInput(
            project_id=project_id,
            product_name=args.product_name,
            selling_points_text=args.selling_points,
            target_audience_text=args.target_audience,
            brand_tone=args.brand_tone,
            forbidden_words_text=args.forbidden_words,
        ),
        assets=assets,
        campaign_goal=args.campaign_goal,
    )


def build_handoff_summary() -> dict[str, object]:
    return {
        "from": "product_understanding.analysis",
        "to": "creative_script.state.analysis",
        "creative_script_uses": [
            "inferred_selling_points",
            "inferred_audience",
            "visual_observations",
            "visual_uncertainties",
            "material_conflicts",
            "constraints",
            "readiness_score",
        ],
    }


def copy_images_to_asset_storage(
    *,
    project_id: int,
    image_paths: list[Path],
) -> list[CreativeAssetInput]:
    storage_root = resolve_asset_storage_root()
    assets: list[CreativeAssetInput] = []
    for index, image_path in enumerate(image_paths, start=1):
        source = image_path.resolve()
        mime_type = guess_image_mime_type(source)
        storage_key = Path("node_print_tests") / str(project_id) / f"{uuid4().hex}{source.suffix}"
        destination = storage_root / storage_key
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        assets.append(
            CreativeAssetInput(
                id=index,
                project_id=project_id,
                asset_type="product_image",
                storage_key=storage_key.as_posix(),
                mime_type=mime_type,
                size_bytes=destination.stat().st_size,
                asset_metadata={
                    "original_filename": source.name,
                    "source_for": "start_to_creative_script_print_test",
                },
            )
        )
    return assets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从 PRODUCT_UNDERSTANDING 跑到 CREATIVE_SCRIPT，并打印两个节点的数据。"
    )
    parser.add_argument("--image", type=Path, action="append", required=True, help="商品图片路径。")
    parser.add_argument("--product-name", required=True, help="商品名称。")
    parser.add_argument("--selling-points", required=True, help="商品卖点，支持逗号或换行分隔。")
    parser.add_argument("--target-audience", required=True, help="目标人群，支持逗号或换行分隔。")
    parser.add_argument("--brand-tone", default="", help="品牌语气。")
    parser.add_argument("--forbidden-words", default="", help="必须避免的表达。")
    parser.add_argument(
        "--campaign-goal",
        default="让目标用户快速理解商品价值，并愿意进一步查看商品详情",
        help="本次营销目标。",
    )
    parser.add_argument("--target-platform", default="douyin", choices=["douyin", "xiaohongshu"])
    parser.add_argument("--project-title", default="START 到 CREATIVE_SCRIPT 节点打印测试")
    parser.add_argument("--project-id", type=int, default=999003)
    parser.add_argument("--duration-seconds", type=int, default=15)
    parser.add_argument(
        "--force-local-product-understanding",
        action="store_true",
        help="强制商品理解节点走本地逻辑，不调用多模态模型。",
    )
    parser.add_argument(
        "--force-local-creative",
        action="store_true",
        help="强制脚本节点走本地逻辑，不调用文本模型。",
    )
    return parser.parse_args()


def resolve_asset_storage_root() -> Path:
    settings = get_settings()
    storage_root = Path(settings.asset_storage_path).expanduser()
    if not storage_root.is_absolute():
        storage_root = BACKEND_ROOT / storage_root
    storage_root.mkdir(parents=True, exist_ok=True)
    return storage_root.resolve()


def guess_image_mime_type(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"找不到商品图片：{path}")
    mime_type = IMAGE_MIME_TYPES_BY_SUFFIX.get(path.suffix.lower()) or mimetypes.guess_type(
        path.name
    )[0]
    if mime_type == "image/jpg":
        mime_type = "image/jpeg"
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ValueError(f"只支持 JPEG、PNG、WebP 图片：{path}")
    return mime_type


def local_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url=None,
        api_key=None,
        model_key=None,
        timeout_seconds=45,
    )


def to_jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


if __name__ == "__main__":
    main()
