"""校验模型生成内容，并与服务端权威事实组合。"""

from pydantic import ValidationError

from app.agents.modeling.contracts import GeneratedCreativeDraft
from app.agents.modeling.provider import ProviderResponseError
from app.application.creative_agent import (
    CreativeDraft,
    ProductAnalysis,
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
