"""调用模型执行商品声明语义审核，并把结果限制在服务端证据注册表内。"""

from __future__ import annotations

from pydantic import ValidationError

from app.agents.modeling.contracts import SemanticClaimReview
from app.agents.modeling.provider import CreativeModelProvider, ProviderResponseError
from app.agents.prompts import REVIEW_CREATIVE_CLAIMS_PROMPT_REF, load_prompt_template
from app.agents.rules.analysis import split_phrases
from app.application.creative_agent import CreativeBriefInput, CreativeDraft


def review_creative_claims(
    *,
    provider: CreativeModelProvider,
    draft: CreativeDraft,
    brief: CreativeBriefInput,
) -> tuple[SemanticClaimReview, dict[str, str]]:
    """审核模型草案中的事实声明，并返回服务端认可的证据注册表。"""

    confirmed_facts = build_confirmed_fact_registry(brief)
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
    return review, confirmed_facts


def build_confirmed_fact_registry(brief: CreativeBriefInput) -> dict[str, str]:
    """为模型和服务端裁决生成稳定、不可伪造的事实证据 key。"""

    facts = {"product_name": brief.product_name.strip()}
    facts.update(
        {
            f"selling_point:{index}": value
            for index, value in enumerate(split_phrases(brief.selling_points_text))
        }
    )
    facts.update(
        {
            f"target_audience:{index}": value
            for index, value in enumerate(split_phrases(brief.target_audience_text))
        }
    )
    return facts
