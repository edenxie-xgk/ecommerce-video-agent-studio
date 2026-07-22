"""实现 prompt_check 节点：评估 Prompt 风险并执行一次自动修订。

质量门禁分两层：确定性规则检查脚本和分镜的结构、商品引用、禁词及可识别高风险声明；
外部模型生成的草案在规则通过后还会进行 fail-closed 语义审核。人工编辑分镜时复用
本模块的同一套规则，但不会隐式重写既有创意脚本。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import partial
import re
from typing import Literal, TypeAlias

from langgraph.types import Command

from app.agents.modeling.contracts import SemanticClaimReview
from app.agents.modeling.provider import ModelGenerationError
from app.agents.modeling.review import review_creative_claims
from app.agents.models import config_model
from app.agents.nodes import REVIEW_COST_GATE
from app.application.storyboard_prompts import build_storyboard_prompt_bundle
from app.agents.state import AgentState
from app.application.creative_agent import (
    CreativeConcept,
    CreativeDecisionBundle,
    CreativeDraft,
    QualityEvaluation,
    QualityIssue,
    StoryboardPromptBundle,
)
from app.application.creative_decision import QUALITY_DIMENSIONS


# 自动修订可安全替换的系统风险词。键同时也是确定性风险扫描的一部分，值是比原词更
# 克制的默认措辞；用户自定义禁词不会被替换为其他营销表述，而是直接删除。
SYSTEM_RISKY_REPLACEMENTS = {
    # 系统级风险词在自动修订时改成更克制、可审核的表达。
    "绝对": "更",  # 改为相对表达。
    "百分百": "尽量",  # 改为保守表达。
    "永久": "长期",  # 改为时间范围表达。
    "治疗": "改善使用体验",  # 改为使用体验表达。
}

# 商品名在不同 Prompt 中可能有空格、横线或标点差异。规范化只放宽格式，不放宽商品
# 身份：规范化后的完整商品名仍必须出现在正向 Prompt 内。
PRODUCT_REFERENCE_NORMALIZATION_PATTERN = re.compile(r"[\s，,。.!！?？、;；:：\-_]+")

# 可确定识别且不应依赖模型判断的高风险商品声明模式。
# 每项由稳定问题 code 和正则组成。这里只包含可以确定识别的声明；更细微的语义夸张
# 交由后面的模型审核，避免正则对正常文案产生过多误报。
HIGH_RISK_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ranking_claim",
        re.compile(
            r"(?:(?:全网|行业|全国|全球)(?:销量|排名)?(?:第一|冠军|领先)"
            r"|(?:销量|排名)(?:第一|冠军)|行业天花板|遥遥领先)"
        ),
    ),
    (
        "certification_claim",
        re.compile(r"(?:官方|权威|国家|国际).{0,8}(?:认证|认可|背书)"),
    ),
    (
        "numeric_parameter_claim",
        re.compile(
            r"(?:\d+(?:\.\d+)?|[一二两三四五六七八九十百]+)\s*"
            r"(?:%|米|小时|天|分钟|年|次|倍|毫升|ml|克|kg|公斤)"
        ),
    ),
    (
        "efficacy_claim",
        re.compile(r"(?:提升|降低|增加|改善|见效|治愈).{0,12}(?:免疫|疾病|症状|\d+%)"),
    ),
)

# ---------------------------------------------------------------------------
# 扫描字段注册表
# ---------------------------------------------------------------------------

ConceptTextField: TypeAlias = Literal[
    "title",  # 方案标题。
    "strategy",  # 整体表达策略。
    "hook",  # 前三秒吸引观看的开场。
    "reasoning",  # 方案适配平台和人群的理由。
    "primary_selling_point",  # 该方案主打的卖点。
    "target_audience",  # 该方案面向的目标人群。
    "call_to_action",  # 结尾行动建议。
]
ShotTextField: TypeAlias = Literal[
    "purpose",  # 镜头承担的叙事或转化目的。
    "visual",  # 镜头画面描述。
    "caption",  # 镜头字幕或口播。
]

REVIEWABLE_CONCEPT_TEXT_FIELDS: tuple[ConceptTextField, ...] = (
    "title",
    "strategy",
    "hook",
    "reasoning",
    "primary_selling_point",
    "target_audience",
    "call_to_action",
)
REVIEWABLE_SHOT_TEXT_FIELDS: tuple[ShotTextField, ...] = (
    "purpose",
    "visual",
    "caption",
)


def prompt_check_node(state: AgentState) -> Command:
    """评估三套方案，必要时修订一次，并把质量结论写回 checkpoint。

    自动运行最多修订一轮：第一轮先暴露全部确定性问题，第二轮验证本地修复结果。若仍然
    不通过，必须交给人工审核，避免无限自动改写让原始创意逐渐失真。
    """

    # 项目规格控制总时长；brief 提供禁词和确认事实，二者不能由草案自行决定。
    run_input = state["run_input"]
    project = run_input.project
    brief = run_input.brief
    forbidden_words = brief.forbidden_words() if brief else []
    # 证据注册表使用稳定 key，供语义模型引用；值仍来自用户确认的 brief 而非模型分析。
    confirmed_fact_registry: dict[str, str] = {}
    if brief:
        # 商品名是唯一基础事实；卖点和人群用索引 key 保留顺序与可追溯性。
        confirmed_fact_registry = {"product_name": brief.product_name.strip()}
        confirmed_fact_registry.update(
            {
                f"selling_point:{index}": value
                for index, value in enumerate(brief.selling_points())
            }
        )
        confirmed_fact_registry.update(
            {
                f"target_audience:{index}": value
                for index, value in enumerate(brief.target_audiences())
            }
        )
    # 确定性正则扫描只需事实值；语义审核还需要上方的 key-value 对。
    confirmed_facts = list(confirmed_fact_registry.values())
    draft = state["draft"]
    revision_count = state["revision_count"]
    # 第一层只检查脚本文本，不在此处读取或重建分镜 Prompt。
    evaluation = _evaluate_draft(
        draft,
        expected_duration=project.duration_seconds,
        forbidden_words=forbidden_words,
        confirmed_facts=confirmed_facts,
    )

    # 该标志决定现有分镜是否失效：草案被修订时，分镜必须依据新草案重新生成。
    draft_was_revised = False
    if not evaluation.passed and revision_count < 1:
        # 自动修订执行确定性修复，并控制在一次修订内。
        draft = revise_draft(
            draft=draft,
            evaluation=evaluation,
            product_name=draft.analysis.product_summary,
            forbidden_words=forbidden_words,
        )
        # 状态中的计数会持久化，防止同一执行在恢复后再次自动修订。
        revision_count += 1
        draft_was_revised = True
        # 用相同规则复检修订结果，确保“已自动改写”不等于“已通过”。
        evaluation = _evaluate_draft(
            draft,
            expected_duration=project.duration_seconds,
            forbidden_words=forbidden_words,
            confirmed_facts=confirmed_facts,
        )

    # 分镜 Prompt 是后续视频节点的直接输入，必须和脚本草案一起通过当前门禁。
    # 正常路径复用 storyboard_prompt 节点产物；仅缺失或草案变化时才重建。
    storyboard_prompts = state.get("storyboard_prompts")
    if storyboard_prompts is None or draft_was_revised:
        storyboard_prompts = build_storyboard_prompt_bundle(
            run_input=run_input,
            draft=draft,
        )
    # 将分镜检查与脚本检查合并为一个对外可见的质量结论。
    evaluation = evaluate_storyboard_prompts(
        base_evaluation=evaluation,
        storyboard_prompts=storyboard_prompts,
        product_summary=draft.analysis.product_summary,
        forbidden_words=forbidden_words,
        confirmed_facts=confirmed_facts,
    )

    # 外部模型草案进入语义复核。
    # 本地确定性草案不需要再经过模型复核；外部模型草案只有在规则层通过后才发起复核。
    if evaluation.passed and state["provider_key"] == "openai_compatible":
        if brief is None:
            evaluation = semantic_review_unavailable(evaluation)
        else:
            evaluation = review_semantic_claims(
                evaluation=evaluation,
                draft=draft,
                storyboard_prompts=storyboard_prompts,
                confirmed_facts=confirmed_fact_registry,
            )

    # 将最终草案、与之对应的分镜、评估及修订次数作为一个一致快照写回 checkpoint。
    return Command(
        update={
            "draft": draft,
            "storyboard_prompts": storyboard_prompts,
            "evaluation": evaluation,
            "revision_count": revision_count,
        },
        goto=REVIEW_COST_GATE,
    )


def _evaluate_draft(
    draft: CreativeDraft,
    *,
    expected_duration: int,
    forbidden_words: list[str],
    confirmed_facts: list[str],
) -> QualityEvaluation:
    """按方案顺序执行确定性评估并聚合为唯一质量结论。"""

    # 本函数保持为薄包装，确保图内首次评估和人工复检调用完全相同的概念评估逻辑。
    return _evaluate_concepts(
        concepts=draft.concepts,
        product_summary=draft.analysis.product_summary,
        expected_duration=expected_duration,
        forbidden_words=forbidden_words,
        confirmed_facts=confirmed_facts,
    )


def _evaluate_concepts(
    *,
    concepts: list[CreativeConcept],
    product_summary: str,
    expected_duration: int,
    forbidden_words: list[str],
    confirmed_facts: list[str],
) -> QualityEvaluation:
    """评估已有方案文本，供首次运行和人工修改分镜后共享。"""

    # 质量门禁按 concepts 原始顺序执行，保证结果稳定、可复现。
    evaluations = [
        evaluate_concept(
            concept=concept,
            product_summary=product_summary,
            expected_duration=expected_duration,
            forbidden_words=forbidden_words,
            confirmed_facts=confirmed_facts,
        )
        for concept in concepts
    ]
    return aggregate_evaluations(evaluations)


def review_storyboard_prompt_bundle(
    *,
    decision: CreativeDecisionBundle,
    storyboard_prompts: StoryboardPromptBundle,
    require_semantic_review: bool,
) -> CreativeDecisionBundle:
    """校验并复检用户编辑后的分镜 Prompt，保留原始创意脚本不被隐式改写。

    对人工编辑采用“先规范化和保护不可变字段、再评分”的顺序。此接口不会调用
    ``revise_draft``，因为用户只请求修改视频执行 Prompt，脚本属于另一份决策内容。
    """

    # 规范化确保编辑只影响允许的执行字段，并补齐不可移除的全局负面约束。
    normalized_prompts = normalize_storyboard_prompt_edit(
        decision=decision,
        storyboard_prompts=storyboard_prompts,
    )
    confirmed_fact_registry = confirmed_fact_registry_from_decision(decision)
    confirmed_facts = list(confirmed_fact_registry.values())
    # 脚本评估重新执行，防止历史决策或手工构造输入绕过当前规则版本。
    evaluation = _evaluate_concepts(
        concepts=decision.concepts,
        product_summary=decision.analysis.product_summary,
        expected_duration=normalized_prompts.duration_seconds,
        forbidden_words=decision.analysis.constraints,
        confirmed_facts=confirmed_facts,
    )
    evaluation = evaluate_storyboard_prompts(
        base_evaluation=evaluation,
        storyboard_prompts=normalized_prompts,
        product_summary=decision.analysis.product_summary,
        forbidden_words=decision.analysis.constraints,
        confirmed_facts=confirmed_facts,
    )
    # 外部生成的原计划要求语义审核时，人工编辑后的正向 Prompt 也必须同样复核。
    if evaluation.passed and require_semantic_review:
        evaluation = review_semantic_claims(
            evaluation=evaluation,
            draft=CreativeDraft(
                analysis=decision.analysis,
                decision_reason=decision.decision_reason,
                confidence=decision.confidence,
                concepts=decision.concepts,
            ),
            storyboard_prompts=normalized_prompts,
            confirmed_facts=confirmed_fact_registry,
        )
    # 从原决策复制全部审计字段，只覆盖本次复检允许变化的 action、分镜和评估。
    payload = decision.model_dump(mode="python")
    payload.update(
        {
            "action": "review_plan" if evaluation.passed else "resolve_quality_issues",
            "storyboard_prompts": normalized_prompts,
            "evaluation": evaluation,
        }
    )
    return CreativeDecisionBundle.model_validate(payload)


def confirmed_fact_registry_from_decision(
    decision: CreativeDecisionBundle,
) -> dict[str, str]:
    """还原人工复检所需的确认事实注册表。

    人工复检没有最初 ``CreativeRunInput``，因此从已经持久化的 analysis 恢复相同形状的
    注册表。这里仅使用 analysis 中已经被商品理解校验过的字段。
    """

    # 与首次运行的 key 命名保持一致，使语义审核无须区分首次生成和人工复检。
    return {
        "product_name": decision.analysis.product_summary,
        **{
            f"selling_point:{index}": value
            for index, value in enumerate(decision.analysis.inferred_selling_points)
        },
        **{
            f"target_audience:{index}": value
            for index, value in enumerate(decision.analysis.inferred_audience)
        },
    }


def normalize_storyboard_prompt_edit(
    *,
    decision: CreativeDecisionBundle,
    storyboard_prompts: StoryboardPromptBundle,
) -> StoryboardPromptBundle:
    """只允许人工调整视频执行字段，保护脚本事实、素材范围和全局安全约束。

    用户可以调整正负 Prompt、生成方式和图片引用等视频执行参数，但不能借编辑分镜的
    名义替换商品身份、项目规格、创意方向、镜头时长、脚本字幕或可用素材范围。
    """

    # original 是持久化决策中的可信基线，绝不以客户端提交的字段作为约束来源。
    original = decision.storyboard_prompts
    immutable_bundle_fields = (
        "product_summary",
        "target_platform",
        "aspect_ratio",
        "duration_seconds",
        "product_asset_refs",
        "global_negative_prompt",
    )
    # bundle 级字段影响整条视频任务的身份与安全约束，必须逐字段完全一致。
    for field_name in immutable_bundle_fields:
        if getattr(storyboard_prompts, field_name) != getattr(original, field_name):
            raise ValueError(f"不允许修改分镜 Prompt 的{field_name}。")

    # 方向的数量和顺序也属于稳定业务身份，后续按 concept_key 关联审核与界面状态。
    original_concepts = original.concepts
    edited_concepts = storyboard_prompts.concepts
    if [concept.concept_key for concept in edited_concepts] != [
        concept.concept_key for concept in original_concepts
    ]:
        raise ValueError("不允许改变分镜 Prompt 的创意方向或顺序。")

    # 使用基线和编辑值的并行 zip；前置顺序检查保证 strict=True 的长度断言可读且安全。
    normalized_concepts = []
    for original_concept, edited_concept in zip(original_concepts, edited_concepts, strict=True):
        # 主卖点和目标人群来自脚本事实，编辑分镜不得改变其业务含义。
        immutable_concept_fields = (
            "title",
            "primary_selling_point",
            "target_audience",
        )
        for field_name in immutable_concept_fields:
            if getattr(edited_concept, field_name) != getattr(original_concept, field_name):
                raise ValueError(f"不允许修改分镜 Prompt 的{field_name}。")

        # 每一镜的叙事顺序、时长、来源目的和字幕来自脚本，均不属于视频 Prompt 编辑范围。
        normalized_shots = []
        for original_shot, edited_shot in zip(
            original_concept.shot_prompts,
            edited_concept.shot_prompts,
            strict=True,
        ):
            immutable_shot_fields = ("order", "duration_seconds", "source_purpose", "caption")
            for field_name in immutable_shot_fields:
                if getattr(edited_shot, field_name) != getattr(original_shot, field_name):
                    raise ValueError(f"不允许修改分镜 Prompt 的{field_name}。")
            # 允许重写负向 Prompt，但不能删除系统全局约束；缺失时自动附加回来。
            negative_prompt = edited_shot.negative_prompt.strip()
            global_negative_prompt = original.global_negative_prompt
            if global_negative_prompt not in negative_prompt:
                negative_prompt = f"{negative_prompt}\n{global_negative_prompt}".strip()
            # model_copy 保留经 Pydantic 校验的其他可编辑字段，只替换标准化后的负向 Prompt。
            normalized_shots.append(
                edited_shot.model_copy(update={"negative_prompt": negative_prompt})
            )
        normalized_concepts.append(
            edited_concept.model_copy(update={"shot_prompts": normalized_shots})
        )

    # 返回新的不可变模型，不原地修改调用方传入的 API 对象。
    return storyboard_prompts.model_copy(update={"concepts": normalized_concepts})


def evaluate_storyboard_prompts(
    *,
    base_evaluation: QualityEvaluation,
    storyboard_prompts: StoryboardPromptBundle,
    product_summary: str,
    forbidden_words: list[str],
    confirmed_facts: list[str],
) -> QualityEvaluation:
    """检查视频执行 Prompt 的商品引用、生成方式和风险表达，并合并脚本门禁结果。"""

    # Prompt 层单独评分，便于保留来自脚本和分镜的不同问题码。
    prompt_evaluation = _evaluate_storyboard_prompt_bundle(
        storyboard_prompts=storyboard_prompts,
        product_summary=product_summary,
        forbidden_words=forbidden_words,
        confirmed_facts=confirmed_facts,
    )
    return merge_evaluations(base_evaluation, prompt_evaluation)


def _evaluate_storyboard_prompt_bundle(
    *,
    storyboard_prompts: StoryboardPromptBundle,
    product_summary: str,
    forbidden_words: list[str],
    confirmed_facts: list[str],
) -> QualityEvaluation:
    """对用户可编辑的每镜视频 Prompt 执行独立、确定性的安全检查。

    每个问题同时降低对应维度和写入 ``QualityIssue``；评分下限会被裁到 0，但问题列表
    保留所有命中，便于用户知道应如何修复而不是只看到一个总分。
    """

    issues: list[QualityIssue] = []
    product_fidelity = 100
    platform_fit = 100
    conversion_clarity = 100
    compliance = 100
    # 系统风险词与当前商品品牌禁词合并，扫描只针对正向 Prompt 的可生成内容。
    risky_words = [*SYSTEM_RISKY_REPLACEMENTS, *forbidden_words]

    for concept in storyboard_prompts.concepts:
        for shot in concept.shot_prompts:
            # context 只用于面向用户的定位信息，不参与任何规则判断。
            context = f"{concept.title} 第{shot.order}镜头"
            positive_prompt = shot.positive_prompt.strip()
            if not contains_product_reference(positive_prompt, product_summary):
                product_fidelity -= 20
                issues.append(
                    QualityIssue(
                        severity="blocked",
                        code="prompt_missing_product_reference",
                        message=f"{context} 的正向 Prompt 没有明确商品主体。",
                        recommendation=f"在正向 Prompt 中明确写出“{product_summary}”并保持商品主体清晰。",
                    )
                )
            # 商品展示镜必须明确引用当前项目验证过的商品图，保证商品一致性。
            if shot.generation_mode == "image_to_video" and shot.image_reference is None:
                product_fidelity -= 25
                issues.append(
                    QualityIssue(
                        severity="blocked",
                        code="prompt_missing_image_reference",
                        message=f"{context} 选择了商品展示，但没有商品图片引用。",
                        recommendation="商品展示镜头请选择当前项目中已验证的商品图片。",
                    )
                )
            # 场景动作镜不能携带商品图引用，避免生成模式与素材约束冲突。
            if shot.generation_mode == "text_to_video" and shot.image_reference is not None:
                platform_fit -= 20
                issues.append(
                    QualityIssue(
                        severity="blocked",
                        code="prompt_generation_mode_conflict",
                        message=f"{context} 的场景动作镜头保留了商品图片引用。",
                        recommendation="场景动作镜头请移除商品图片引用，或切换为商品展示。",
                    )
                )

            # 集合去重再排序，确保同一 Prompt 多次出现一个风险词仍只报告一次且顺序稳定。
            detected_words = sorted(
                {word for word in risky_words if word and word in positive_prompt}
            )
            if detected_words:
                compliance -= min(40, len(detected_words) * 15)
                issues.append(
                    QualityIssue(
                        severity="blocked",
                        code="prompt_risky_claim",
                        message=f"{context} 的正向 Prompt 检测到风险表达：{'、'.join(detected_words)}。",
                        recommendation="删除风险表达，改为可验证、有限定条件的画面描述。",
                    )
                )

            # 视频时长属于生成规格，不是商品参数，先移除后再扫描未确认的量化声明。
            claim_text = re.sub(
                r"时长\s*[0-9一二两三四五六七八九十百]+\s*秒", "", positive_prompt
            )
            unsupported_patterns = detect_unconfirmed_claim_patterns(
                claim_text,
                confirmed_facts=confirmed_facts,
            )
            if unsupported_patterns:
                compliance -= min(60, len(unsupported_patterns) * 20)
                issues.append(
                    QualityIssue(
                        severity="blocked",
                        code="prompt_unsupported_claim_pattern",
                        message=(
                            f"{context} 的正向 Prompt 检测到缺少确认依据的高风险声明："
                            + "、".join(claim for _, claim in unsupported_patterns)
                            + "。"
                        ),
                        recommendation="删除该声明，或先把对应参数、认证或功效加入已确认商品事实。",
                    )
                )

    # ``from_scores`` 统一计算 passed 和推荐修改，节点不在这里自行推断通过状态。
    return QualityEvaluation.from_scores(
        dimension_scores={
            "product_fidelity": max(product_fidelity, 0),
            "platform_fit": max(platform_fit, 0),
            "conversion_clarity": max(conversion_clarity, 0),
            "compliance": max(compliance, 0),
        },
        issues=issues,
    )


def contains_product_reference(text: str, product_summary: str) -> bool:
    """在不放宽商品身份要求的前提下，忽略大小写、空白和标点格式差异。"""

    # 双方使用同一规则删除格式字符，防止“产品-名称”和“产品名称”产生无意义误报。
    normalized_reference = PRODUCT_REFERENCE_NORMALIZATION_PATTERN.sub(
        "", product_summary
    ).lower()
    normalized_text = PRODUCT_REFERENCE_NORMALIZATION_PATTERN.sub("", text).lower()
    return bool(normalized_reference) and normalized_reference in normalized_text


def merge_evaluations(
    base_evaluation: QualityEvaluation,
    prompt_evaluation: QualityEvaluation,
) -> QualityEvaluation:
    """合并脚本和分镜 Prompt 两层门禁；每个维度以更保守的结果为准。

    门禁不是取平均分：任一层的低分都代表实际风险，因此合并后维度取最小值；同码同消息
    的问题被去重，避免因同一规则在两层触发而重复显示。
    """

    issues_by_key: dict[tuple[str, str], QualityIssue] = {}
    for issue in [*base_evaluation.issues, *prompt_evaluation.issues]:
        # setdefault 保留首次出现的对象与顺序，提供稳定的用户展示结果。
        issues_by_key.setdefault((issue.code, issue.message), issue)
    issues = list(issues_by_key.values())
    return QualityEvaluation.from_scores(
        dimension_scores={
            dimension: min(
                base_evaluation.dimension_scores[dimension],
                prompt_evaluation.dimension_scores[dimension],
            )
            for dimension in QUALITY_DIMENSIONS
        },
        issues=issues,
        recommended_changes=list(
            dict.fromkeys(
                [
                    *base_evaluation.recommended_changes,
                    *prompt_evaluation.recommended_changes,
                ]
            )
        ),
    )


def iter_reviewable_text(concept: CreativeConcept) -> Iterator[str]:
    """按稳定顺序遍历质量门禁需要检查的全部方案文本。"""

    # 先产出概念字段，再按镜头顺序产出镜头文本，供扫描与自动改写共用。
    for field_name in REVIEWABLE_CONCEPT_TEXT_FIELDS:
        yield getattr(concept, field_name)
    for shot in concept.shots:
        for field_name in REVIEWABLE_SHOT_TEXT_FIELDS:
            yield getattr(shot, field_name)


def rewrite_reviewable_text(
    concept: CreativeConcept,
    transform: Callable[[str], str],
) -> CreativeConcept:
    """对质量门禁检查的全部文本执行同一改写，并保留非文本字段。

    自动修订使用字段注册表覆盖所有应扫描文本，而不是手写逐字段赋值；新增审核字段时只需
    更新注册表，扫描和改写就会同步覆盖它。
    """

    # 概念本体与其镜头均通过 model_copy 产生新对象，避免修改原始草案。
    concept_updates: dict[str, object] = {
        field_name: transform(getattr(concept, field_name))
        for field_name in REVIEWABLE_CONCEPT_TEXT_FIELDS
    }
    concept_updates["shots"] = [
        shot.model_copy(
            update={
                field_name: transform(getattr(shot, field_name))
                for field_name in REVIEWABLE_SHOT_TEXT_FIELDS
            }
        )
        for shot in concept.shots
    ]
    return concept.model_copy(update=concept_updates)


def evaluate_concept(
    *,
    concept: CreativeConcept,
    product_summary: str,
    expected_duration: int,
    forbidden_words: list[str],
    confirmed_facts: list[str] | None = None,
) -> QualityEvaluation:
    """执行 prompt_check 节点的时长、商品名称引用和风险表达质量门禁。

    分数从基准值递减而非从零累加，使没有命中问题的方案拥有可解释的满分；警告会影响
    对应维度但不一定阻断，``QualityEvaluation`` 最终根据问题严重度决定是否通过。
    """

    issues: list[QualityIssue] = []
    # 四个维度与应用层 QUALITY_DIMENSIONS 对齐，不能在节点内临时增加展示维度。
    fidelity = 100
    platform_fit = 88
    conversion_clarity = 100
    compliance = 100

    # 时长、CTA 和商品露出使用确定性规则评分。
    # 镜头时长相加是视频交付规格，必须严格等于项目期望时长。
    duration = sum(shot.duration_seconds for shot in concept.shots)
    if duration != expected_duration:
        conversion_clarity -= 15
        issues.append(
            QualityIssue(
                severity="blocked",
                code="duration_mismatch",
                message=f"{concept.title} 的镜头总时长为 {duration} 秒。",
                recommendation=f"调整为 {expected_duration} 秒。",
            )
        )
    if not concept.call_to_action.strip():
        conversion_clarity -= 20
        issues.append(
            QualityIssue(
                severity="warning",
                code="missing_cta",
                message=f"{concept.title} 缺少行动建议。",
                recommendation="补充克制、明确的 CTA。",
            )
        )
    # 脚本层的商品露出检查针对 visual 字段；分镜层还会检查正向 Prompt 中的引用。
    product_shots = [shot for shot in concept.shots if product_summary in shot.visual]
    if len(product_shots) < 2:
        fidelity -= 15
        issues.append(
            QualityIssue(
                severity="warning",
                code="weak_product_presence",
                message=f"{concept.title} 的商品露出不足。",
                recommendation="至少两个镜头明确展示商品主体或细节。",
            )
        )

    # 系统风险词与用户品牌约束合并检查，任一命中都会阻断通过。
    risky_words = [*SYSTEM_RISKY_REPLACEMENTS, *forbidden_words]
    # 单空格拼接所有用户可见字段，供短语和正则规则跨字段稳定扫描。
    flattened_copy = " ".join(iter_reviewable_text(concept))
    detected = sorted({word for word in risky_words if word and word in flattened_copy})
    if detected:
        compliance -= min(40, len(detected) * 15)
        issues.append(
            QualityIssue(
                severity="blocked",
                code="risky_claim",
                message=f"{concept.title} 检测到风险表达：{'、'.join(detected)}。",
                recommendation="改为可验证、有限定条件的相对表达。",
            )
        )

    unsupported_patterns = detect_unconfirmed_claim_patterns(
        flattened_copy,
        confirmed_facts=confirmed_facts or [],
    )
    if unsupported_patterns:
        compliance -= min(60, len(unsupported_patterns) * 20)
        issues.append(
            QualityIssue(
                severity="blocked",
                code="unsupported_claim_pattern",
                message=(
                    f"{concept.title} 检测到缺少确认依据的高风险声明："
                    + "、".join(claim for _, claim in unsupported_patterns)
                    + "。"
                ),
                recommendation="删除该声明，或先把对应参数、认证或功效加入已确认商品事实。",
            )
        )

    # 防止多个问题把评分减为负数，维度分数的公共下限为 0。
    scores = {
        "product_fidelity": max(fidelity, 0),
        "platform_fit": platform_fit,
        "conversion_clarity": max(conversion_clarity, 0),
        "compliance": max(compliance, 0),
    }
    return QualityEvaluation.from_scores(
        dimension_scores=scores,
        issues=issues,
    )


def detect_unconfirmed_claim_patterns(
    text: str,
    *,
    confirmed_facts: list[str],
) -> list[tuple[str, str]]:
    """返回规则命中且未被任何已确认事实原文支持的高风险声明。

    该函数只在命中高风险模式时才要求证据。已确认事实包含相同声明原文即可放行，不对
    “相似但不等价”的文本做猜测；这能使合规判断保持确定、可审计。
    """

    # 仅忽略首尾空格和大小写；保留单位、数字和语义内容以避免放宽事实边界。
    normalized_facts = [fact.strip().lower() for fact in confirmed_facts if fact.strip()]
    detected: list[tuple[str, str]] = []
    for code, pattern in HIGH_RISK_CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            claim = match.group(0).strip()
            normalized_claim = claim.lower()
            # 证据可以是更长的原始事实描述，只要完整包含当前命中的声明。
            if any(normalized_claim in fact for fact in normalized_facts):
                continue
            item = (code, claim)
            # 相同模式在同一文本多次出现仅报告一次，减少重复问题噪声。
            if item not in detected:
                detected.append(item)
    return detected


def apply_semantic_claim_review(
    evaluation: QualityEvaluation,
    *,
    review: SemanticClaimReview,
    confirmed_facts: dict[str, str],
) -> QualityEvaluation:
    """把模型审核转换为服务端问题，并由确定性评分规则重新计算通过状态。

    模型宣称“supported”也不会被直接信任：服务端会把声明和它给出的 evidence_key 对应
    值去除格式字符后做等值比较。任何不支持、模糊或证据不等值的结论均会 fail-closed。
    """

    semantic_issues: list[QualityIssue] = []
    for assessment in review.assessments:
        # 未知 key 返回 None，随后会被判定为 evidence_is_valid=False。
        evidence_value = confirmed_facts.get(assessment.evidence_key or "")
        normalized_assessment_text = re.sub(
            r"[\s，,。.!！?？、;；:：\-]+", "", assessment.text
        ).lower()
        normalized_evidence_value = (
            re.sub(r"[\s，,。.!！?？、;；:：\-]+", "", evidence_value).lower()
            if evidence_value is not None
            else None
        )
        # 只放宽标点和空白格式；不允许模型用部分匹配或同义改写伪造证据。
        evidence_is_valid = normalized_assessment_text == normalized_evidence_value
        if assessment.status == "supported" and evidence_is_valid:
            continue

        # 三类问题分别保留 code，供 API 与前端区分“错误证据”“无证据”“表述模糊”。
        if assessment.status == "supported":
            code = "invalid_claim_evidence"
            message = (
                f"声明“{assessment.text}”引用了无效或不等值的确认事实："
                f"{assessment.evidence_key or '未提供'}。"
            )
        elif assessment.status == "unsupported":
            code = "unsupported_semantic_claim"
            message = f"声明“{assessment.text}”没有已确认商品事实支持。"
        else:
            code = "ambiguous_semantic_claim"
            message = f"声明“{assessment.text}”存在强化或证据不足。"
        semantic_issues.append(
            QualityIssue(
                severity="blocked",
                code=code,
                message=f"{message} 位置：{assessment.field_path}。",
                recommendation="删除或收敛该声明，或补充可追溯的确认事实后重新审核。",
            )
        )

    # 没有新增问题时直接返回原对象，保留前面确定性评估的完整内容。
    if not semantic_issues:
        return evaluation
    # 语义问题同时影响商品忠实度和合规性；其余维度仍沿用确定性规则结果。
    scores = dict(evaluation.dimension_scores)
    scores["product_fidelity"] = max(0, scores["product_fidelity"] - 20)
    scores["compliance"] = max(0, scores["compliance"] - 30)
    issues = [*evaluation.issues, *semantic_issues]
    return QualityEvaluation.from_scores(
        dimension_scores=scores,
        issues=issues,
        recommended_changes=list(
            dict.fromkeys(
                [*evaluation.recommended_changes, *(issue.recommendation for issue in semantic_issues)]
            )
        ),
    )


def review_semantic_claims(
    *,
    evaluation: QualityEvaluation,
    draft: CreativeDraft,
    storyboard_prompts: StoryboardPromptBundle,
    confirmed_facts: dict[str, str],
) -> QualityEvaluation:
    """对脚本和正向分镜 Prompt 执行统一的 fail-closed 语义审核。

    调用失败不会默认为审核通过：外部模型草案缺少这一步验证时，必须由用户恢复服务后
    重试，或改用本地确定性方案。
    """

    try:
        # Provider 的具体协议被 modeling.review 隔离；本层只处理是否可完成审核。
        review = review_creative_claims(
            provider=config_model.prompt_check_model(),
            draft=draft,
            storyboard_prompts=storyboard_prompts,
            confirmed_facts=confirmed_facts,
        )
    except ModelGenerationError:
        # 模型、网络、响应契约等已分类失败统一转为一个阻断性质量问题。
        return semantic_review_unavailable(evaluation)
    return apply_semantic_claim_review(
        evaluation,
        review=review,
        confirmed_facts=confirmed_facts,
    )


def semantic_review_unavailable(evaluation: QualityEvaluation) -> QualityEvaluation:
    """外部模型草案无法完成语义复核时采用 fail-closed 结果。"""

    issue = QualityIssue(
        severity="blocked",
        code="semantic_review_unavailable",
        message="外部模型生成的草案未能完成商品声明语义审核。",
        recommendation="恢复审核模型后重试，或改用本地确定性方案。",
    )
    # 只降低合规性，保留其他已计算维度，帮助用户区分服务不可用与文案本身的问题。
    scores = dict(evaluation.dimension_scores)
    scores["compliance"] = max(0, scores["compliance"] - 30)
    return QualityEvaluation.from_scores(
        dimension_scores=scores,
        issues=[*evaluation.issues, issue],
        recommended_changes=list(
            dict.fromkeys([*evaluation.recommended_changes, issue.recommendation])
        ),
    )


def aggregate_evaluations(
    evaluations: list[QualityEvaluation],
) -> QualityEvaluation:
    """聚合三套方案的评估结果，形成当前轮次唯一的质量结论。

    维度总分使用各方案平均值，问题列表则保留全部方案的问题。这样总览可比较整体质量，
    而人工审核仍能定位到每个具体方案的失败原因。
    """

    # 防御式处理：正常草案应有三套方案，空集合必须显式阻断而不是报告高分。
    if not evaluations:
        issue = QualityIssue(
            severity="blocked",
            code="missing_evaluation",
            message="没有收到可聚合的方案评估结果。",
            recommendation="重新执行方案评估。",
        )
        return QualityEvaluation.from_scores(
            dimension_scores={
                "product_fidelity": 0,
                "platform_fit": 0,
                "conversion_clarity": 0,
                "compliance": 0,
            },
            issues=[issue],
            recommended_changes=["重新执行方案评估"],
        )

    # 所有单方案评估使用同一 Schema，因此维度集合以首条记录为准。
    # 四维得分均值四舍五入为整数，与应用层对外评分契约保持一致。
    dimension_scores = {
        dimension: round(
            sum(evaluation.dimension_scores[dimension] for evaluation in evaluations)
            / len(evaluations)
        )
        for dimension in QUALITY_DIMENSIONS
    }
    issues = [issue for evaluation in evaluations for issue in evaluation.issues]
    return QualityEvaluation.from_scores(
        dimension_scores=dimension_scores,
        issues=issues,
        recommended_changes=list(dict.fromkeys(issue.recommendation for issue in issues)),
    )


def revise_draft(
    *,
    draft: CreativeDraft,
    evaluation: QualityEvaluation,
    product_name: str,
    forbidden_words: list[str],
) -> CreativeDraft:
    """修复 prompt_check 节点可确定判断的问题。

    此函数仅做无歧义的机械修复：归一化镜头时长、补齐商品露出和 CTA、处理已登记风险
    词。它不会新增卖点、变更人群、切换创意方向，亦不会尝试自动修复语义证据不足。
    """

    # 商品名中可能恰好包含系统风险词或品牌禁词；这类字符是身份的一部分，不能删除。
    protected_words = {
        word
        for word in [*SYSTEM_RISKY_REPLACEMENTS, *forbidden_words]
        if word and word in product_name
    }
    # partial 固定当前商品的禁词上下文，让每个文本字段使用完全一致的改写规则。
    revised: list[CreativeConcept] = []
    sanitize = partial(
        remove_risky_claims,
        forbidden_words=forbidden_words,
        protected_words=protected_words,
    )
    for concept in draft.concepts:
        # 转为 list 以便只替换需要改动的 ShotPlan，原始 concept 始终保持不可变。
        shots = list(concept.shots)
        # 修订保持原有创意方向，并纠正确定性问题。
        if sum(shot.duration_seconds for shot in shots) != 15:
            shots = [
                shots[0].model_copy(update={"duration_seconds": 3}),
                shots[1].model_copy(update={"duration_seconds": 7}),
                shots[2].model_copy(update={"duration_seconds": 5}),
            ]
        # 任何未显式写出商品名的镜头都加上最小商品露出描述，修复脚本层忠实度问题。
        shots = [
            shot.model_copy(
                update={
                    "visual": (
                        shot.visual
                        if product_name in shot.visual
                        else f"{product_name}清晰出现在画面中；{shot.visual}"
                    ),
                }
            )
            for shot in shots
        ]
        # CTA 缺失时使用中性动作；其余可扫描文本经过同一个 sanitize 函数改写。
        revised.append(
            rewrite_reviewable_text(
                concept.model_copy(
                    update={
                        "call_to_action": (concept.call_to_action or "查看商品详情并按需选择。"),
                        "shots": shots,
                    }
                ),
                sanitize,
            )
        )

    # 推荐修改汇总进决策理由，去掉句号后用分号连接，避免形成连续重复标点。
    feedback = (
        "；".join(change.rstrip("。") for change in evaluation.recommended_changes)
        or "加强商品露出和行动建议"
    )
    # 不修改 analysis 或 confidence；自动修订只作用于可展示的脚本内容。
    return draft.model_copy(
        update={
            "decision_reason": f"{draft.decision_reason} 已根据质量评估自动修订：{feedback}。",
            "concepts": revised,
            "confidence": draft.confidence,
        }
    )


def remove_risky_claims(
    value: str,
    forbidden_words: list[str],
    protected_words: set[str],
) -> str:
    """改写系统风险词并移除自定义禁词，同时保护已确认商品名。

    替换顺序先处理系统词、再按长度从长到短删除用户禁词，避免短禁词先删除后破坏更长
    禁词的完整匹配。结果会 strip，确保删除词后不会留下多余首尾空白。
    """

    # 用局部变量连续累积改写，调用方传入的原字符串不受影响。
    result = value
    for source, target in SYSTEM_RISKY_REPLACEMENTS.items():
        # 商品身份中出现的词受保护，避免修订把商品名本身改坏。
        if source in protected_words:
            continue
        result = result.replace(source, target)
    # 集合去重后最长优先，处理“功效”和“功效保证”这类重叠禁词。
    for forbidden_word in sorted(set(forbidden_words), key=len, reverse=True):
        if not forbidden_word or forbidden_word in protected_words:
            continue
        result = result.replace(forbidden_word, "")
    # 清理删除词后可能留下的首尾空白，保持用户展示和后续扫描稳定。
    return result.strip()


