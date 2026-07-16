"""实现 product_understanding 节点：生成服务端权威商品分析。"""

from __future__ import annotations

import re

from langgraph.types import Command

from app.agents.nodes import CREATIVE_SCRIPT
from app.agents.state import AgentState
from app.application.creative_agent import ProductAnalysis


def product_understanding_node(state: AgentState) -> Command:
    """生成商品理解结果。"""

    run_input = state["run_input"]
    project = run_input.project
    brief = run_input.brief
    assets = run_input.assets
    product_name = (brief.product_name if brief else "").strip()
    # 用户输入的卖点作为模型生成的卖点白名单。
    selling_points = [
        part.strip(" -。.!！?？")
        for part in re.split(r"[\n,，、;；]+", brief.selling_points_text if brief else "")
        if part.strip(" -。.!！?？")
    ]
    audience = [
        part.strip(" -。.!！?？")
        for part in re.split(r"[\n,，、;；]+", brief.target_audience_text if brief else "")
        if part.strip(" -。.!！?？")
    ]
    constraints = [
        part.strip(" -。.!！?？")
        for part in re.split(r"[\n,，、;；]+", brief.forbidden_words_text if brief else "")
        if part.strip(" -。.!！?？")
    ]
    missing: list[str] = []

    # 商品名称和至少一张已验证图片引用是当前版模生成可审核方案的硬门槛。
    if not product_name:
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
    default_audience = (
        "希望先看真实体验和细节再做决定的用户"
        if project.target_platform == "xiaohongshu"
        else "希望快速判断商品价值的短视频用户"
    )

    analysis = ProductAnalysis(
        product_summary=summary,
        inferred_category=platform_category,
        inferred_selling_points=selling_points or ["外观与使用价值需要结合商品图进一步表达"],
        inferred_audience=audience or [default_audience],
        visual_evidence_count=len(assets),
        constraints=constraints,
        missing_information=missing,
        readiness_score=max(readiness_score, 0),
    )
    # 商品分析写入状态后，交给 creative_script 节点制定创意草案。
    return Command(
        update={"analysis": analysis},
        goto=CREATIVE_SCRIPT,
    )
