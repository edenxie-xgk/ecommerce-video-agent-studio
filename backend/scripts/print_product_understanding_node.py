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
    storage_root = resolve_asset_storage_root()
    project_id = args.project_id

    assets: list[CreativeAssetInput] = []
    for index, image_path in enumerate(args.image, start=1):
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
                    "source_for": "product_understanding_node_print_test",
                },
            )
        )

    run_input = CreativeRunInput(
        project=CreativeProjectInput(
            id=project_id,
            title=args.project_title,
            target_platform=args.target_platform,
            language="zh-CN",
            aspect_ratio="9:16",
            duration_seconds=args.duration_seconds,
            status="node_print_test",
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

    command = product_understanding_node({"run_input": run_input})
    output = {
        "goto": command.goto,
        "provider": command.update.get("product_understanding_provider_key"),
        "model": command.update.get("product_understanding_model_key"),
        "analysis": to_jsonable(command.update.get("analysis")),
        "copied_images": [asset.model_dump(mode="json") for asset in assets],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只运行 PRODUCT_UNDERSTANDING 节点，并打印节点返回的数据。"
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
    parser.add_argument("--project-title", default="PRODUCT_UNDERSTANDING 节点打印测试")
    parser.add_argument("--project-id", type=int, default=999001)
    parser.add_argument("--duration-seconds", type=int, default=15)
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


def to_jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


if __name__ == "__main__":
    main()
