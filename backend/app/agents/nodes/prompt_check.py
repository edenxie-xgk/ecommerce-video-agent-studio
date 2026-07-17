"""实现 prompt_check 节点：评估 Prompt 风险并执行一次自动修订。"""

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
from app.agents.state import AgentState
from app.application.creative_agent import (
    CreativeConcept,
    CreativeDraft,
    QualityEvaluation,
    QualityIssue,
)
from app.application.creative_decision import QUALITY_DIMENSIONS


SYSTEM_RISKY_REPLACEMENTS = {
    # 系统级风险词在自动修订时改成更克制、可审核的表达。
    "绝对": "更",  # 改为相对表达。
    "百分百": "尽量",  # 改为保守表达。
    "永久": "长期",  # 改为时间范围表达。
    "治疗": "改善使用体验",  # 改为使用体验表达。
}

# 可确定识别且不应依赖模型判断的高风险商品声明模式。
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
    """评估三套方案，必要时修订一次，并把质量结论写回 checkpoint。"""

    run_input = state["run_input"]
    project = run_input.project
    brief = run_input.brief
    forbidden_words = brief.forbidden_words() if brief else []
    confirmed_fact_registry: dict[str, str] = {}
    if brief:
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
    confirmed_facts = list(confirmed_fact_registry.values())
    draft = state["draft"]
    revision_count = state["revision_count"]
    evaluation = _evaluate_draft(
        draft,
        expected_duration=project.duration_seconds,
        forbidden_words=forbidden_words,
        confirmed_facts=confirmed_facts,
    )

    if not evaluation.passed and revision_count < 1:
        # 自动修订执行确定性修复，并控制在一次修订内。
        draft = revise_draft(
            draft=draft,
            evaluation=evaluation,
            product_name=draft.analysis.product_summary,
            forbidden_words=forbidden_words,
        )
        revision_count += 1
        evaluation = _evaluate_draft(
            draft,
            expected_duration=project.duration_seconds,
            forbidden_words=forbidden_words,
            confirmed_facts=confirmed_facts,
        )

    # 外部模型草案进入语义复核。
    if evaluation.passed and state["provider_key"] == "openai_compatible":
        if brief is None:
            evaluation = semantic_review_unavailable(evaluation)
        else:
            try:
                review = review_creative_claims(
                    provider=config_model.prompt_check_model(),
                    draft=draft,
                    confirmed_facts=confirmed_fact_registry,
                )
                evaluation = apply_semantic_claim_review(
                    evaluation,
                    review=review,
                    confirmed_facts=confirmed_fact_registry,
                )
            except ModelGenerationError:
                evaluation = semantic_review_unavailable(evaluation)

    return Command(
        update={
            "draft": draft,
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

    # 质量门禁按 concepts 原始顺序执行，保证结果稳定、可复现。
    evaluations = [
        evaluate_concept(
            concept=concept,
            product_summary=draft.analysis.product_summary,
            expected_duration=expected_duration,
            forbidden_words=forbidden_words,
            confirmed_facts=confirmed_facts,
        )
        for concept in draft.concepts
    ]
    return aggregate_evaluations(evaluations)


def iter_reviewable_text(concept: CreativeConcept) -> Iterator[str]:
    """按稳定顺序遍历质量门禁需要检查的全部方案文本。"""

    for field_name in REVIEWABLE_CONCEPT_TEXT_FIELDS:
        yield getattr(concept, field_name)
    for shot in concept.shots:
        for field_name in REVIEWABLE_SHOT_TEXT_FIELDS:
            yield getattr(shot, field_name)


def rewrite_reviewable_text(
    concept: CreativeConcept,
    transform: Callable[[str], str],
) -> CreativeConcept:
    """对质量门禁检查的全部文本执行同一改写，并保留非文本字段。"""

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
    """执行 prompt_check 节点的时长、商品名称引用和风险表达质量门禁。"""

    issues: list[QualityIssue] = []
    fidelity = 100
    platform_fit = 88
    conversion_clarity = 100
    compliance = 100

    # 时长、CTA 和商品露出使用确定性规则评分。
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
    """返回规则命中且未被任何已确认事实原文支持的高风险声明。"""

    normalized_facts = [fact.strip().lower() for fact in confirmed_facts if fact.strip()]
    detected: list[tuple[str, str]] = []
    for code, pattern in HIGH_RISK_CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            claim = match.group(0).strip()
            normalized_claim = claim.lower()
            if any(normalized_claim in fact for fact in normalized_facts):
                continue
            item = (code, claim)
            if item not in detected:
                detected.append(item)
    return detected


def apply_semantic_claim_review(
    evaluation: QualityEvaluation,
    *,
    review: SemanticClaimReview,
    confirmed_facts: dict[str, str],
) -> QualityEvaluation:
    """把模型审核转换为服务端问题，并由确定性评分规则重新计算通过状态。"""

    semantic_issues: list[QualityIssue] = []
    for assessment in review.assessments:
        evidence_value = confirmed_facts.get(assessment.evidence_key or "")
        normalized_assessment_text = re.sub(
            r"[\s，,。.!！?？、;；:：\-]+", "", assessment.text
        ).lower()
        normalized_evidence_value = (
            re.sub(r"[\s，,。.!！?？、;；:：\-]+", "", evidence_value).lower()
            if evidence_value is not None
            else None
        )
        evidence_is_valid = normalized_assessment_text == normalized_evidence_value
        if assessment.status == "supported" and evidence_is_valid:
            continue

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

    if not semantic_issues:
        return evaluation
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


def semantic_review_unavailable(evaluation: QualityEvaluation) -> QualityEvaluation:
    """外部模型草案无法完成语义复核时采用 fail-closed 结果。"""

    issue = QualityIssue(
        severity="blocked",
        code="semantic_review_unavailable",
        message="外部模型生成的草案未能完成商品声明语义审核。",
        recommendation="恢复审核模型后重试，或改用本地确定性方案。",
    )
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
    """聚合三套方案的评估结果，形成当前轮次唯一的质量结论。"""

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
    """修复 prompt_check 节点可确定判断的问题。"""

    protected_words = {
        word
        for word in [*SYSTEM_RISKY_REPLACEMENTS, *forbidden_words]
        if word and word in product_name
    }
    revised: list[CreativeConcept] = []
    sanitize = partial(
        remove_risky_claims,
        forbidden_words=forbidden_words,
        protected_words=protected_words,
    )
    for concept in draft.concepts:
        shots = list(concept.shots)
        # 修订保持原有创意方向，并纠正确定性问题。
        if sum(shot.duration_seconds for shot in shots) != 15:
            shots = [
                shots[0].model_copy(update={"duration_seconds": 3}),
                shots[1].model_copy(update={"duration_seconds": 7}),
                shots[2].model_copy(update={"duration_seconds": 5}),
            ]
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

    feedback = (
        "；".join(change.rstrip("。") for change in evaluation.recommended_changes)
        or "加强商品露出和行动建议"
    )
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
    """改写系统风险词并移除自定义禁词，同时保护已确认商品名。"""

    result = value
    for source, target in SYSTEM_RISKY_REPLACEMENTS.items():
        if source in protected_words:
            continue
        result = result.replace(source, target)
    for forbidden_word in sorted(set(forbidden_words), key=len, reverse=True):
        if not forbidden_word or forbidden_word in protected_words:
            continue
        result = result.replace(forbidden_word, "")
    return result.strip()


