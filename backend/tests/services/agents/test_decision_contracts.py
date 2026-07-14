from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.application.creative_agent import (
    CreativeConcept,
    CreativeDecisionBundle,
    CreativeDraft,
    ProductAnalysis,
    QualityEvaluation,
    QualityIssue,
    ShotPlan,
)


def _analysis(*, missing_information: list[str] | None = None) -> ProductAnalysis:
    return ProductAnalysis(
        product_summary="便携保温杯",
        inferred_category="强调转化的消费品",
        inferred_selling_points=["轻便易携"],
        inferred_audience=["通勤人群"],
        visual_evidence_count=1,
        constraints=[],
        missing_information=missing_information or [],
        readiness_score=100 if not missing_information else 55,
    )


def _evaluation(*, passed: bool) -> QualityEvaluation:
    issues = []
    changes = []
    if not passed:
        issues = [
            QualityIssue(
                severity="blocked",
                code="risky_claim",
                message="检测到风险表达。",
                recommendation="改为可验证的相对表达。",
            )
        ]
        changes = ["改为可验证的相对表达。"]
    return QualityEvaluation.from_scores(
        dimension_scores={
            "product_fidelity": 90,
            "platform_fit": 90,
            "conversion_clarity": 90,
            "compliance": 90 if passed else 40,
        },
        issues=issues,
        recommended_changes=changes,
    )


def _concept(key: str) -> CreativeConcept:
    return CreativeConcept(
        concept_key=key,
        title=f"方案 {key}",
        strategy="用商品事实组织三个镜头。",
        hook="先看这个商品细节。",
        reasoning="适合目标平台的短视频节奏。",
        primary_selling_point="轻便易携",
        target_audience="通勤人群",
        call_to_action="按需查看商品详情。",
        shots=[
            ShotPlan(
                order=order,
                duration_seconds=duration,
                purpose="展示商品事实",
                visual="便携保温杯清晰出现在画面中",
                caption="轻便易携",
                generation_mode="image_to_video",
            )
            for order, duration in ((1, 3), (2, 7), (3, 5))
        ],
    )


def _draft() -> CreativeDraft:
    return CreativeDraft(
        decision_reason="围绕通勤场景形成三套差异化方向。",
        confidence=0.88,
        concepts=[_concept("one"), _concept("two"), _concept("three")],
        analysis=_analysis(),
    )


@pytest.mark.parametrize(
    ("passed", "expected_action"),
    ((True, "review_plan"), (False, "resolve_quality_issues")),
)
def test_draft_evaluation_factory_derives_action(
    passed: bool,
    expected_action: str,
) -> None:
    decision = CreativeDecisionBundle.from_draft_evaluation(
        draft=_draft(),
        evaluation=_evaluation(passed=passed),
        revision_count=1,
    )

    assert decision.action == expected_action
    assert len(decision.concepts) == 3
    assert decision.evaluation.passed is passed


def test_review_plan_rejects_failed_or_blocked_evaluation() -> None:
    decision = CreativeDecisionBundle.from_draft_evaluation(
        draft=_draft(),
        evaluation=_evaluation(passed=True),
        revision_count=0,
    )
    payload = decision.model_dump()
    payload["evaluation"] = _evaluation(passed=False).model_dump()

    with pytest.raises(ValidationError, match="必须已经通过最终质量门禁"):
        CreativeDecisionBundle.model_validate(payload)


def test_review_plan_rejects_forged_passed_evaluation_with_blocked_issue() -> None:
    draft = _draft()
    forged_evaluation = QualityEvaluation.model_construct(
        overall_score=90,
        dimension_scores={
            "product_fidelity": 90,
            "platform_fit": 90,
            "conversion_clarity": 90,
            "compliance": 90,
        },
        passed=True,
        issues=[
            QualityIssue(
                severity="blocked",
                code="forged_block",
                message="伪造的阻断问题。",
                recommendation="拒绝该结果。",
            )
        ],
        recommended_changes=["拒绝该结果。"],
    )

    with pytest.raises(ValidationError, match="通过状态必须由总分和阻断问题"):
        CreativeDecisionBundle(
            action="review_plan",
            decision_reason=draft.decision_reason,
            confidence=draft.confidence,
            analysis=draft.analysis,
            concepts=draft.concepts,
            evaluation=forged_evaluation,
        )


def test_resolve_quality_issues_rejects_passed_evaluation() -> None:
    decision = CreativeDecisionBundle.from_draft_evaluation(
        draft=_draft(),
        evaluation=_evaluation(passed=False),
        revision_count=1,
    )
    payload = decision.model_dump()
    payload["evaluation"] = _evaluation(passed=True).model_dump()

    with pytest.raises(ValidationError, match="只能用于未通过最终质量门禁"):
        CreativeDecisionBundle.model_validate(payload)


def test_resolve_quality_issues_requires_an_actionable_issue() -> None:
    draft = _draft()
    failed_without_issue = QualityEvaluation.from_scores(
        dimension_scores={
            "product_fidelity": 70,
            "platform_fit": 70,
            "conversion_clarity": 70,
            "compliance": 70,
        },
        issues=[],
    )

    with pytest.raises(ValidationError, match="可处理的质量问题"):
        CreativeDecisionBundle.from_draft_evaluation(
            draft=draft,
            evaluation=failed_without_issue,
            revision_count=1,
        )


def test_quality_evaluation_requires_the_complete_dimension_set() -> None:
    payload = _evaluation(passed=True).model_dump()
    payload["dimension_scores"].pop("compliance")

    with pytest.raises(ValidationError, match="完整包含四个规定维度"):
        QualityEvaluation.model_validate(payload)


def test_quality_evaluation_rejects_forged_total_and_passed_flag() -> None:
    payload = _evaluation(passed=True).model_dump()
    payload["overall_score"] = 0
    with pytest.raises(ValidationError, match="总分必须等于"):
        QualityEvaluation.model_validate(payload)

    payload = _evaluation(passed=True).model_dump()
    payload["passed"] = False
    with pytest.raises(ValidationError, match="通过状态必须"):
        QualityEvaluation.model_validate(payload)


def test_decision_bundle_rechecks_duplicate_concept_keys() -> None:
    decision = CreativeDecisionBundle.from_draft_evaluation(
        draft=_draft(),
        evaluation=_evaluation(passed=True),
        revision_count=0,
    )
    payload = decision.model_dump()
    payload["concepts"][1]["concept_key"] = payload["concepts"][0]["concept_key"]

    with pytest.raises(ValidationError, match="concept_key 必须唯一"):
        CreativeDecisionBundle.model_validate(payload)


def test_evaluated_decision_requires_three_complete_concepts() -> None:
    decision = CreativeDecisionBundle.from_draft_evaluation(
        draft=_draft(),
        evaluation=_evaluation(passed=True),
        revision_count=0,
    )
    payload = decision.model_dump()
    payload["concepts"] = []

    with pytest.raises(ValidationError, match="必须包含三套完整创意方案"):
        CreativeDecisionBundle.model_validate(payload)


def test_evaluated_decision_rejects_missing_information() -> None:
    decision = CreativeDecisionBundle.from_draft_evaluation(
        draft=_draft(),
        evaluation=_evaluation(passed=True),
        revision_count=0,
    )
    payload = deepcopy(decision.model_dump())
    payload["analysis"]["missing_information"] = ["product_name"]

    with pytest.raises(ValidationError, match="不能保留阻断生成的缺失信息"):
        CreativeDecisionBundle.model_validate(payload)


def test_direct_construction_remains_supported_for_valid_decisions() -> None:
    draft = _draft()
    decision = CreativeDecisionBundle(
        action="review_plan",
        decision_reason=draft.decision_reason,
        confidence=draft.confidence,
        analysis=draft.analysis,
        concepts=draft.concepts,
        evaluation=_evaluation(passed=True),
        revision_count=0,
    )

    assert decision.action == "review_plan"
