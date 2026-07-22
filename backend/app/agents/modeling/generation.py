"""校验模型生成内容，并与服务端权威事实组合。

这里是外部模型候选内容进入业务域的信任边界：先按输出契约验证形状，再把卖点、人群、
视觉事实和禁词同用户已确认资料对照。校验失败统一转换为可分类的 Provider 响应错误。
"""

from collections.abc import Iterator

from pydantic import ValidationError

from app.agents.modeling.contracts import GeneratedCreativeDraft, GeneratedProductUnderstanding
from app.agents.modeling.provider import ProviderResponseError
from app.application.creative_agent import (
    CreativeDraft,
    CreativeRunInput,
    ProductAnalysis,
)


# 顶层方案文本字段注册在一个常量中，保证新增字段时能集中纳入事实与禁词扫描。
CREATIVE_TEXT_FIELDS = (
    # 创意方案中的顶层文案字段，服务端会统一扫描这些文本。
    "title",
    "strategy",
    "hook",
    "reasoning",
    "primary_selling_point",
    "target_audience",
    "call_to_action",
)
# 单镜头内需要进入事实校验的文本字段；数值和结构字段不属于自然语言声明。
SHOT_TEXT_FIELDS = ("purpose", "visual", "caption")


def build_input_based_analysis(run_input: CreativeRunInput) -> ProductAnalysis:
    """在模型不可用时，用用户已确认资料形成保守商品理解。

本地结果不推断图片细节、不新增卖点和人群；它只使后续确定性脚本策略可以基于用户
已经确认的输入继续工作。
    """

    # 没有 brief 无法形成任何事实基础，不能静默构造空分析。
    brief = run_input.brief
    if brief is None:
        raise ProviderResponseError("缺少商品资料，无法构造商品理解。")
    # 沿用 DTO 的必填判断，并把缺失项暴露给结果而不是假装资料充分。
    missing = run_input.missing_required_agent_inputs()
    return ProductAnalysis(
        product_summary=brief.product_name.strip(),
        inferred_category="用户资料未提供明确类目",
        inferred_selling_points=brief.selling_points(),
        inferred_audience=brief.target_audiences(),
        # 数量用于镜头策略；没有读取像素时不得生成 visual_observations。
        visual_evidence_count=len(
            [asset for asset in run_input.assets if asset.asset_type == "product_image"]
        ),
        visual_uncertainties=["未调用多模态模型，商品图片只作为后续镜头素材引用。"],
        material_conflicts=[],
        constraints=brief.forbidden_words(),
        missing_information=missing,
        # 本地路径只有“资料完整/不完整”两种确定结论，不伪造模型置信评分。
        readiness_score=100 if not missing else 0,
    )


def build_authoritative_analysis(
    *,
    payload: dict[str, object],
    run_input: CreativeRunInput,
    image_input_count: int = 0,
) -> ProductAnalysis:
    """校验模型商品理解，并把可变结论限制在用户确认资料范围内。

模型可贡献类目、图片观察和不确定项，但商品名、可用卖点、目标人群、禁词和图片数量
始终由 ``run_input`` 注入，模型无法通过 payload 覆盖这些权威字段。
    """

    brief = run_input.brief
    if brief is None:
        raise ProviderResponseError("缺少商品资料，无法校验商品理解。")
    try:
        # 先验证类型、长度和枚举等结构约束，再进行领域白名单验证。
        generated = GeneratedProductUnderstanding.model_validate(payload)
    except ValidationError as exc:
        raise ProviderResponseError("模型商品理解结果不符合结构化契约。") from exc

    # 商品卖点以用户确认清单为白名单，模型输出需要原样命中该清单。
    # 转为集合以便精确匹配并去重；不做近似匹配，避免模型悄然改写卖点含义。
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

    # 目标人群以用户输入为白名单，模型输出需要原样命中该清单。
    # 人群遵循同样的严格白名单策略。
    allowed_audience = set(brief.target_audiences())
    unsupported_audience = sorted(
        audience for audience in generated.selected_audience if audience not in allowed_audience
    )
    if unsupported_audience:
        raise ProviderResponseError(
            "商品理解返回了未确认目标人群：" + "、".join(unsupported_audience)
        )
    # 真实图片像素是 visual_observations 的证据来源。
    if generated.visual_observations and image_input_count <= 0:
        raise ProviderResponseError("模型未接收图片像素，却返回了图片可见事实。")

    # 最终 ProductAnalysis 由服务端重建，明确每个字段的事实所有者。
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
        material_conflicts=generated.material_conflicts,
        constraints=brief.forbidden_words(),
        missing_information=run_input.missing_required_agent_inputs(),
        readiness_score=generated.readiness_score,
    )


def build_authoritative_draft(
    *,
    payload: dict[str, object],
    analysis: ProductAnalysis,
    allowed_selling_points: list[str],
    allowed_audience: list[str],
    forbidden_words: list[str],
    uncertain_visual_facts: list[str],
) -> CreativeDraft:
    """校验模型创意内容，并组装完整的服务端草案。

    该函数不试图判断营销文案是否“好”，而是保证模型不会越过已确认卖点、人群、禁词
    和视觉不确定项的边界；质量与合规评分由 prompt_check 节点负责。
    """

    try:
        # 模型响应先按模型边界契约校验；完整 CreativeDraft 由服务端在本函数组装。
        generated = GeneratedCreativeDraft.model_validate(payload)
    except ValidationError as exc:
        raise ProviderResponseError("模型结果不符合创意草案契约。") from exc

    # 先去除输入两端空格，确保同一事实只存在一种用于比对的标准形式。
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

    # 方案面向的人群必须来自用户确认的人群清单。
    # 目标人群也需逐方案验证，不能因一套方案合格而放过另一套。
    audience_whitelist = {audience.strip() for audience in allowed_audience if audience.strip()}
    unsupported_audience = sorted(
        {
            concept.target_audience.strip()
            for concept in generated.concepts
            if concept.target_audience.strip() not in audience_whitelist
        }
    )
    if unsupported_audience:
        raise ProviderResponseError(
            "模型返回了未经过确认的目标人群：" + "、".join(unsupported_audience)
        )

    # 创意文本统一展开后，再做禁用词和不确定视觉事实扫描。
    # 先一次性展开所有用户可见文本，再执行一致的短语扫描。
    draft_text = list(_creative_text_values(generated))
    forbidden_hits = _phrases_found(draft_text, forbidden_words)
    if forbidden_hits:
        raise ProviderResponseError("模型创意内容包含禁用表达：" + "、".join(forbidden_hits))

    uncertainty_hits = _phrases_found(draft_text, uncertain_visual_facts)
    if uncertainty_hits:
        raise ProviderResponseError(
            "模型把图片无法确认的信息写成确定表达：" + "、".join(uncertainty_hits)
        )

    # analysis 从上游节点传入，阻止模型响应伪造或替换商品理解结论。
    return CreativeDraft(
        analysis=analysis,
        decision_reason=generated.decision_reason,
        confidence=generated.confidence,
        concepts=generated.concepts,
    )


def _creative_text_values(generated: GeneratedCreativeDraft) -> Iterator[str]:
    """按稳定顺序收集模型创意草案中的全部可展示文本。"""

    # decision_reason 也会展示给用户，需要和方案文案接受同一套边界校验。
    yield generated.decision_reason
    # 保持 concepts 和 shots 的输入顺序，便于测试、审计和错误定位稳定复现。
    for concept in generated.concepts:
        for field_name in CREATIVE_TEXT_FIELDS:
            yield getattr(concept, field_name)
        for shot in concept.shots:
            for field_name in SHOT_TEXT_FIELDS:
                yield getattr(shot, field_name)


def _phrases_found(text_values: list[str], phrases: list[str]) -> list[str]:
    """返回在创意文本中直接出现的业务短语。

    这里采用精确子串匹配而非语义推断：它用于确定性的禁词和已知不确定事实拦截，复杂
    的同义表达由后续可选语义审核处理。
    """

    # 换行避免相邻字段拼接出不存在的跨字段短语。
    haystack = "\n".join(text_values)
    return sorted({phrase.strip() for phrase in phrases if phrase.strip() and phrase in haystack})
