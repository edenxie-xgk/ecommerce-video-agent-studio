"""调用模型执行商品声明语义审核，并把结果限制在服务端证据注册表内。"""

from __future__ import annotations

from pydantic import ValidationError

from app.agents.modeling.contracts import SemanticClaimReview
from app.agents.modeling.provider import CreativeModelProvider, ProviderResponseError
from app.agents.prompts import REVIEW_CREATIVE_CLAIMS_PROMPT_REF, load_prompt_template
from app.application.creative_agent import CreativeDraft


def review_creative_claims(
    *,
    provider: CreativeModelProvider,
    draft: CreativeDraft,
    confirmed_facts: dict[str, str],
) -> SemanticClaimReview:
    """审核模型草案中的事实声明。"""

    prompt_template = load_prompt_template(REVIEW_CREATIVE_CLAIMS_PROMPT_REF)
    response = provider.generate_json(
        system_prompt=prompt_template.system_prompt,
        input_payload={
            "confirmed_facts": [
                {"evidence_key": key, "value": value}
                for key, value in confirmed_facts.items()
            ],
            "concepts": [concept.model_dump(mode="json") for concept in draft.concepts],
        },
        json_schema=SemanticClaimReview.model_json_schema(),
    )
    try:
        review = SemanticClaimReview.model_validate(response.payload)
    except ValidationError as exc:
        raise ProviderResponseError("模型声明审核结果不符合结构化契约。") from exc
    return review
