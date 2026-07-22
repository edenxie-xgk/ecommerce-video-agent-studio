from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.agents.modeling.provider import OpenAICompatibleProvider
from app.agents.models import config_model
from app.agents.nodes.creative_script import creative_script_node
from app.application.creative_agent import (
    CreativeBriefInput,
    CreativeProjectInput,
    CreativeRunInput,
    ProductAnalysis,
)


def main() -> None:
    args = parse_args()
    if args.force_local:
        # 强制使用本地兜底，便于只验证 creative_script 节点的数据结构。
        local_provider = OpenAICompatibleProvider(
            base_url=None,
            api_key=None,
            model_key=None,
            timeout_seconds=45,
        )
        config_model.creative_script_model = lambda: local_provider

    run_input = CreativeRunInput(
        project=CreativeProjectInput(
            id=args.project_id,
            title=args.project_title,
            target_platform=args.target_platform,
            language="zh-CN",
            aspect_ratio="9:16",
            duration_seconds=args.duration_seconds,
            status="creative_script_node_print_test",
        ),
        brief=CreativeBriefInput(
            project_id=args.project_id,
            product_name=args.product_name,
            selling_points_text=args.selling_points,
            target_audience_text=args.target_audience,
            brand_tone=args.brand_tone,
            forbidden_words_text=args.forbidden_words,
        ),
        assets=[],
        campaign_goal=args.campaign_goal,
    )
    analysis = ProductAnalysis(
        product_summary=args.product_name,
        inferred_category=args.inferred_category,
        inferred_selling_points=split_text(args.selling_points),
        inferred_audience=split_text(args.target_audience),
        visual_evidence_count=args.visual_evidence_count,
        visual_observations=split_text(args.visual_observations),
        visual_uncertainties=split_text(args.visual_uncertainties),
        material_conflicts=split_text(args.material_conflicts),
        constraints=split_text(args.forbidden_words),
        missing_information=[],
        readiness_score=args.readiness_score,
    )

    command = creative_script_node(
        {
            "run_input": run_input,
            "analysis": analysis,
            "provider_key": "local",
            "model_key": None,
            "revision_count": 0,
        }
    )
    output = {
        "goto": command.goto,
        "provider": command.update.get("provider_key"),
        "model": command.update.get("model_key"),
        "draft": to_jsonable(command.update.get("draft")),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只运行 CREATIVE_SCRIPT 节点，并打印节点返回的数据。"
    )
    parser.add_argument("--product-name", required=True, help="商品名称。")
    parser.add_argument("--selling-points", required=True, help="商品卖点，支持逗号或换行分隔。")
    parser.add_argument("--target-audience", required=True, help="目标人群，支持逗号或换行分隔。")
    parser.add_argument("--brand-tone", default="", help="品牌语气。")
    parser.add_argument("--forbidden-words", default="", help="必须避免的表达。")
    parser.add_argument("--inferred-category", default="通勤消费品", help="商品理解阶段推断的表达类目。")
    parser.add_argument(
        "--visual-observations",
        default="",
        help="图片中可见事实，支持逗号或换行分隔。",
    )
    parser.add_argument(
        "--visual-uncertainties",
        default="",
        help="图片无法确认的信息，支持逗号或换行分隔。",
    )
    parser.add_argument(
        "--material-conflicts",
        default="",
        help="商品资料和图片的冲突；传入后节点应直接报错。",
    )
    parser.add_argument("--visual-evidence-count", type=int, default=1, help="商品图片证据数量。")
    parser.add_argument("--readiness-score", type=int, default=90, help="商品资料就绪度，0-100。")
    parser.add_argument(
        "--campaign-goal",
        default="让目标用户快速理解商品价值，并愿意进一步查看商品详情",
        help="本次营销目标。",
    )
    parser.add_argument("--target-platform", default="douyin", choices=["douyin", "xiaohongshu"])
    parser.add_argument("--project-title", default="CREATIVE_SCRIPT 节点打印测试")
    parser.add_argument("--project-id", type=int, default=999002)
    parser.add_argument("--duration-seconds", type=int, default=15)
    parser.add_argument(
        "--force-local",
        action="store_true",
        help="强制走本地兜底，不调用文本模型。",
    )
    return parser.parse_args()


def split_text(value: str) -> list[str]:
    return [
        part.strip(" -。.!！?？；;，,")
        for part in value.replace("\n", ",").replace("、", ",").split(",")
        if part.strip(" -。.!！?？；;，,")
    ]


def to_jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


if __name__ == "__main__":
    main()
