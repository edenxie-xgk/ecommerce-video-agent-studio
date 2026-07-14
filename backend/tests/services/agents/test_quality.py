from app.agents.rules.quality import (
    REVIEWABLE_CONCEPT_TEXT_FIELDS,
    REVIEWABLE_SHOT_TEXT_FIELDS,
    evaluate_concept,
    iter_reviewable_text,
    revise_draft,
    rewrite_reviewable_text,
)
from app.application.creative_agent import (
    CreativeConcept,
    CreativeDraft,
    ProductAnalysis,
    QualityEvaluation,
    QualityIssue,
    ShotPlan,
)


def _concept(
    key: str,
    marker: str,
    durations: tuple[int, int, int] = (3, 7, 5),
) -> CreativeConcept:
    return CreativeConcept(
        concept_key=key,
        title=f"{marker} title",
        strategy=f"{marker} strategy",
        hook=f"{marker} hook",
        reasoning=f"{marker} reasoning",
        primary_selling_point=f"{marker} selling point",
        target_audience=f"{marker} audience",
        call_to_action=f"{marker} action",
        shots=[
            ShotPlan(
                order=order,
                duration_seconds=duration,
                purpose=f"{marker} purpose {order}",
                visual=f"{marker} visual {order}",
                caption=f"{marker} caption {order}",
                generation_mode="image_to_video",
            )
            for order, duration in enumerate(durations, start=1)
        ],
    )


def _draft(marker: str, durations: tuple[int, int, int] = (3, 7, 5)) -> CreativeDraft:
    return CreativeDraft(
        analysis=ProductAnalysis(
            product_summary="Product",
            inferred_category="Consumer product",
            inferred_selling_points=["Confirmed point"],
            inferred_audience=["Audience"],
            visual_evidence_count=1,
            constraints=[marker],
            missing_information=[],
            readiness_score=100,
        ),
        decision_reason="Initial decision",
        confidence=0.8,
        concepts=[_concept(f"concept-{index}", marker, durations) for index in range(1, 4)],
    )


def _failed_evaluation() -> QualityEvaluation:
    issue = QualityIssue(
        severity="blocked",
        code="risky_claim",
        message="Risky claim",
        recommendation="Remove risky claim.",
    )
    return QualityEvaluation.from_scores(
        dimension_scores={
            "product_fidelity": 100,
            "platform_fit": 88,
            "conversion_clarity": 100,
            "compliance": 60,
        },
        issues=[issue],
        recommended_changes=[issue.recommendation],
    )


def test_reviewable_field_registry_covers_all_copy_fields() -> None:
    concept_copy_fields = {
        name
        for name, field in CreativeConcept.model_fields.items()
        if field.annotation is str and name != "concept_key"
    }
    shot_copy_fields = {
        name for name, field in ShotPlan.model_fields.items() if field.annotation is str
    }

    assert set(REVIEWABLE_CONCEPT_TEXT_FIELDS) == concept_copy_fields
    assert set(REVIEWABLE_SHOT_TEXT_FIELDS) == shot_copy_fields


def test_scanner_and_rewriter_share_the_same_reviewable_text_fields() -> None:
    marker = "restricted"
    concept = _concept("concept-1", marker)

    blocked = evaluate_concept(
        concept=concept,
        product_summary="Product",
        expected_duration=15,
        forbidden_words=[marker],
    )
    rewritten = rewrite_reviewable_text(
        concept,
        lambda value: value.replace(marker, "approved"),
    )
    reevaluated = evaluate_concept(
        concept=rewritten,
        product_summary="Product",
        expected_duration=15,
        forbidden_words=[marker],
    )

    assert any(issue.severity == "blocked" for issue in blocked.issues)
    assert all(marker not in value for value in iter_reviewable_text(rewritten))
    assert not any(issue.severity == "blocked" for issue in reevaluated.issues)
    assert rewritten.concept_key == concept.concept_key
    assert [shot.order for shot in rewritten.shots] == [1, 2, 3]
    assert [shot.duration_seconds for shot in rewritten.shots] == [3, 7, 5]


def test_deterministic_gate_blocks_unconfirmed_ranking_certification_and_parameter_claims() -> None:
    concept = _concept("concept-1", "ordinary")
    concept.hook = "全网销量第一，官方认证，防水十米"

    evaluation = evaluate_concept(
        concept=concept,
        product_summary="Product",
        expected_duration=15,
        forbidden_words=[],
        confirmed_facts=["ordinary selling point"],
    )

    assert not evaluation.passed
    assert any(issue.code == "unsupported_claim_pattern" for issue in evaluation.issues)


def test_deterministic_gate_accepts_parameter_claim_confirmed_verbatim() -> None:
    concept = _concept("concept-1", "ordinary")
    concept.hook = "防水十米"

    evaluation = evaluate_concept(
        concept=concept,
        product_summary="Product",
        expected_duration=15,
        forbidden_words=[],
        confirmed_facts=["防水十米"],
    )

    assert evaluation.passed


def test_revise_draft_preserves_existing_normalization_and_protection_behavior() -> None:
    marker = "restricted"
    draft = _draft(marker, durations=(1, 1, 1))
    draft.concepts[0].call_to_action = ""

    revised = revise_draft(
        draft=draft,
        evaluation=_failed_evaluation(),
        product_name="Product",
        forbidden_words=[marker],
    )

    assert revised.confidence == draft.confidence
    assert "Remove risky claim" in revised.decision_reason
    assert revised.concepts[0].call_to_action == "查看商品详情并按需选择。"
    for concept in revised.concepts:
        assert all(marker not in value for value in iter_reviewable_text(concept))
        assert [shot.duration_seconds for shot in concept.shots] == [3, 7, 5]
        assert all("Product" in shot.visual for shot in concept.shots)

    protected = revise_draft(
        draft=_draft("永久"),
        evaluation=_failed_evaluation(),
        product_name="永久牌商品",
        forbidden_words=[],
    )
    assert any("永久" in value for value in iter_reviewable_text(protected.concepts[0]))
