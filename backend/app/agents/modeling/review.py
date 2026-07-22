"""调用模型执行商品声明语义审核，并把结果限制在服务端证据注册表内。

该层负责把脚本和分镜中的待审核文本、以及服务端拥有的证据注册表传给模型。模型的
审核结论仍会在 ``prompt_check.apply_semantic_claim_review`` 中被二次校验。
"""

from __future__ import annotations

from pydantic import ValidationError

from app.agents.modeling.contracts import SemanticClaimReview
from app.agents.modeling.provider import CreativeModelProvider, ProviderResponseError
from app.agents.prompts import REVIEW_CREATIVE_CLAIMS_PROMPT_REF, load_prompt_template
from app.application.creative_agent import CreativeDraft, StoryboardPromptBundle


def review_creative_claims(
    *,
    provider: CreativeModelProvider,
    draft: CreativeDraft,
    confirmed_facts: dict[str, str],
    storyboard_prompts: StoryboardPromptBundle | None = None,
) -> SemanticClaimReview:
    """审核脚本和可执行分镜 Prompt 中的事实声明。

    ``confirmed_facts`` 用键值对而不是纯字符串列表传递，使模型必须回传可追溯的
    evidence_key；可选的分镜参数让首次生成和人工改 Prompt 使用同一个审核入口。
    """

    # 审核提示模板定义审核标准，业务代码只填入事实与待检查的实际内容。
    prompt_template = load_prompt_template(REVIEW_CREATIVE_CLAIMS_PROMPT_REF)
    response = provider.generate_json(
        system_prompt=prompt_template.system_prompt,
        input_payload={
            # 将 dict 转成显式对象列表，避免模型把字典键和值的角色混淆。
            "confirmed_facts": [
                {"evidence_key": key, "value": value}
                for key, value in confirmed_facts.items()
            ],
            # 传输 JSON 模式的数据，确保枚举/嵌套模型可被 Provider 的 json.dumps 编码。
            "concepts": [concept.model_dump(mode="json") for concept in draft.concepts],
            "storyboard_prompt_positive_prompts": (
                # 语义审核仅检查最终会提交给视频模型的正向 Prompt，负向约束不产生商品声明。
                [
                    {
                        "concept_key": concept.concept_key,
                        "shot_order": shot.order,
                        "positive_prompt": shot.positive_prompt,
                    }
                    for concept in storyboard_prompts.concepts
                    for shot in concept.shot_prompts
                ]
                if storyboard_prompts is not None
                else []
            ),
        },
        json_schema=SemanticClaimReview.model_json_schema(),
    )
    try:
        # Provider 只确认 JSON 对象形状；审核专用 Pydantic 模型确认字段及状态枚举。
        review = SemanticClaimReview.model_validate(response.payload)
    except ValidationError as exc:
        raise ProviderResponseError("模型声明审核结果不符合结构化契约。") from exc
    return review
