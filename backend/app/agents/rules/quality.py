"""执行创意方案的确定性质量门禁、聚合和修订。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import partial
from typing import Literal, TypeAlias

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


# ---------------------------------------------------------------------------
# 单方案评分
# ---------------------------------------------------------------------------


def evaluate_concept(
    *,
    concept: CreativeConcept,
    product_summary: str,
    expected_duration: int,
    forbidden_words: list[str],
) -> QualityEvaluation:
    """执行确定性的时长、商品名称引用和风险表达质量门禁。"""

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
                severity="warning",
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


# ---------------------------------------------------------------------------
# 三方案聚合
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 自动修订
# ---------------------------------------------------------------------------


def revise_draft(
    *,
    draft: CreativeDraft,
    evaluation: QualityEvaluation,
    product_name: str,
    forbidden_words: list[str],
) -> CreativeDraft:
    """修复质量门禁可确定判断的问题。"""

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
