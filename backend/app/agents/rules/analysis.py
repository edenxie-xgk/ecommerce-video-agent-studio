"""处理 Agent 输入快照、商品资料分析和外部模型输入映射。

模模块是 `analyze` 阶段的规则层：负责恢复 checkpoint 中的应用层 DTO 快照，
并根据确定性规则生成 ProductAnalysis。
"""

from __future__ import annotations

import re

from app.agents.state import AgentState
from app.application.creative_agent import (
    CreativeAssetInput,
    CreativeBriefInput,
    CreativeProjectInput,
    ProductAnalysis,
)


# ---------------------------------------------------------------------------
# Checkpoint 快照恢复
# ---------------------------------------------------------------------------


def restore_inputs(
    state: AgentState,
) -> tuple[
    CreativeProjectInput,
    CreativeBriefInput | None,
    list[CreativeAssetInput],
]:
    """把 checkpoint 快照重新校验为应用输入契约。"""

    # LangGraph checkpoint 里保存的是 dict；节点入口统一恢复成 DTO。
    project = CreativeProjectInput.model_validate(state["project"])
    brief_payload = state.get("brief")
    brief = CreativeBriefInput.model_validate(brief_payload) if brief_payload else None
    assets = [CreativeAssetInput.model_validate(asset) for asset in state.get("assets", [])]
    return project, brief, assets


# ---------------------------------------------------------------------------
# 商品资料完整度分析
# ---------------------------------------------------------------------------


def analyze_product(
    project: CreativeProjectInput,
    brief: CreativeBriefInput | None,
    assets: list[CreativeAssetInput],
) -> ProductAnalysis:
    """根据确定性资料完整度规则生成商品分析。"""

    product_name = (brief.product_name if brief else "").strip()
    # 用户输入的卖点作为模型生成的卖点白名单。
    selling_points = confirmed_selling_points(brief)
    audience = split_phrases(brief.target_audience_text if brief else "")
    constraints = split_phrases(brief.forbidden_words_text if brief else "")
    missing: list[str] = []

    # 商品名称和至少一张已验证图片引用是当前版模生成可审核方案的硬门槛。
    if not product_name or product_name == "未命名商品":
        missing.append("product_name")
    if not assets:
        missing.append("product_images")

    # 就绪度用于解释资料质量，missing_information 保存硬门槛缺失项。
    readiness_score = 100
    if "product_name" in missing:
        readiness_score -= 45
    if "product_images" in missing:
        readiness_score -= 40
    if not selling_points:
        readiness_score -= 10
    if not audience:
        readiness_score -= 5

    platform_category = (
        "强调转化的消费品" if project.target_platform == "douyin" else "适合种草表达的消费品"
    )
    # product_summary 是后续生成与质量检查引用商品的标准名称。
    summary = product_name or "待确认商品"

    return ProductAnalysis(
        product_summary=summary,
        inferred_category=platform_category,
        inferred_selling_points=selling_points or ["外观与使用价值需要结合商品图进一步表达"],
        inferred_audience=audience or [default_audience(project.target_platform)],
        visual_evidence_count=len(assets),
        constraints=constraints,
        missing_information=missing,
        readiness_score=max(readiness_score, 0),
    )


# ---------------------------------------------------------------------------
# Provider 输入白名单
# ---------------------------------------------------------------------------


def build_model_input(
    *,
    project: CreativeProjectInput,
    brief: CreativeBriefInput | None,
    assets: list[CreativeAssetInput],
    campaign_goal: str,
) -> dict[str, object]:
    """构造 Provider 输入的字段白名单。"""

    # 外部模型接收当前创意任务需要的事实集合。
    return {
        "product_name": brief.product_name if brief else "",
        "selling_points": confirmed_selling_points(brief),
        "target_audience": split_phrases(brief.target_audience_text if brief else ""),
        "brand_tone": brief.brand_tone if brief else "",
        "forbidden_expressions": split_phrases(brief.forbidden_words_text if brief else ""),
        "target_platform": project.target_platform,
        "campaign_goal": campaign_goal,
        "duration_seconds": project.duration_seconds,
        "aspect_ratio": project.aspect_ratio,
        "product_image_count": len(assets),
        "product_asset_ids": [asset.id for asset in assets],
    }


def confirmed_selling_points(brief: CreativeBriefInput | None) -> list[str]:
    """返回用户明确提供的模型卖点白名单。"""

    return split_phrases(brief.selling_points_text if brief else "")


def split_phrases(value: str) -> list[str]:
    """把用户自由文模切分成稳定的业务短语列表。"""

    # 用户会混用中文顿号、英文逗号、换行和分号；这里统一切成可比较的短语。
    return [
        part.strip(" -。.!！?？")
        for part in re.split(r"[\n,，、;；]+", value)
        if part.strip(" -。.!！?？")
    ]


def default_audience(platform: str) -> str:
    """在用户未提供人群时返回符合平台语境的保守描述。"""

    if platform == "xiaohongshu":
        return "希望先看真实体验和细节再做决定的用户"
    return "希望快速判断商品价值的短视频用户"

