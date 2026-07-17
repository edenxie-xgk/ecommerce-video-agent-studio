"""校验模型生成内容，并与服务端权威事实组合。"""

from pydantic import ValidationError

from app.agents.modeling.contracts import GeneratedCreativeDraft, GeneratedProductUnderstanding
from app.agents.modeling.provider import ProviderResponseError
from app.application.creative_agent import (
    CreativeDraft,
    CreativeRunInput,
    ProductAnalysis,
)


def build_input_based_analysis(run_input: CreativeRunInput) -> ProductAnalysis:
    """在模型不可用时，用用户已确认资料形成保守商品理解。"""

    brief = run_input.brief
    if brief is None:
        raise ProviderResponseError("缺少商品资料，无法构造商品理解。")
    missing = run_input.missing_required_agent_inputs()
    return ProductAnalysis(
        product_summary=brief.product_name.strip(),
        inferred_category="用户资料未提供明确类目",
        inferred_selling_points=brief.selling_points(),
        inferred_audience=brief.target_audiences(),
        visual_evidence_count=len(
            [asset for asset in run_input.assets if asset.asset_type == "product_image"]
        ),
        visual_uncertainties=["未调用多模态模型，商品图片只作为后续镜头素材引用。"],
        constraints=brief.forbidden_words(),
        missing_information=missing,
        readiness_score=100 if not missing else 0,
    )


def build_authoritative_analysis(
    *,
    payload: dict[str, object],
    run_input: CreativeRunInput,
    image_input_count: int = 0,
) -> ProductAnalysis:
    """校验模型商品理解，并把可变结论限制在用户确认资料范围内。"""

    brief = run_input.brief
    if brief is None:
        raise ProviderResponseError("缺少商品资料，无法校验商品理解。")
    try:
        generated = GeneratedProductUnderstanding.model_validate(payload)
    except ValidationError as exc:
        raise ProviderResponseError("模型商品理解结果不符合结构化契约。") from exc

    allowed_selling_points = set(brief.selling_points())
    unsupported_selling_points = sorted(
        point
        for point in generated.selected_selling_points
        if point not in allowed_selling_points
    )
    if unsupported_selling_points:
        raise ProviderResponseError(
            "商品理解返回了未确认卖点：" + "、".join(unsupported_selling_points)
        )

    allowed_audience = set(brief.target_audiences())
    unsupported_audience = sorted(
        audience for audience in generated.selected_audience if audience not in allowed_audience
    )
    if unsupported_audience:
        raise ProviderResponseError(
            "商品理解返回了未确认目标人群：" + "、".join(unsupported_audience)
        )
    if generated.visual_observations and image_input_count <= 0:
        raise ProviderResponseError("模型未接收图片像素，却返回了图片可见事实。")

    return ProductAnalysis(
        product_summary=brief.product_name.strip(),
        inferred_category=generated.inferred_category,
        inferred_selling_points=generated.selected_selling_points,
        inferred_audience=generated.selected_audience,
        visual_evidence_count=len(
            [asset for asset in run_input.assets if asset.asset_type == "product_image"]
        ),
        visual_observations=generated.visual_observations,
        visual_uncertainties=generated.visual_uncertainties,
        constraints=brief.forbidden_words(),
        missing_information=run_input.missing_required_agent_inputs(),
        readiness_score=generated.readiness_score,
    )


def build_authoritative_draft(
    *,
    payload: dict[str, object],
    analysis: ProductAnalysis,
    allowed_selling_points: list[str],
) -> CreativeDraft:
    """校验模型创意内容，并组装完整的服务端草案。"""

    try:
        # 模型响应先按模型边界契约校验；完整 CreativeDraft 由服务端在本函数组装。
        generated = GeneratedCreativeDraft.model_validate(payload)
    except ValidationError as exc:
        raise ProviderResponseError("模型结果不符合创意草案契约。") from exc

    selling_point_whitelist = {
        selling_point.strip() for selling_point in allowed_selling_points if selling_point.strip()
    }
    unsupported_selling_points = sorted(
        {
            concept.primary_selling_point.strip()
            for concept in generated.concepts
            if concept.primary_selling_point.strip() not in selling_point_whitelist
        }
    )
    if unsupported_selling_points:
        raise ProviderResponseError(
            "模型返回了未经过确认的核心卖点：" + "、".join(unsupported_selling_points)
        )

    return CreativeDraft(
        analysis=analysis,
        decision_reason=generated.decision_reason,
        confidence=generated.confidence,
        concepts=generated.concepts,
    )
