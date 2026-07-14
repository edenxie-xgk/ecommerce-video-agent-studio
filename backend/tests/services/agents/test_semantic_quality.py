from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

from app.agents.modeling.provider import ModelJsonResponse, ProviderTransientError
from app.agents.planner import CreativePlanner
from app.agents.rules.drafts import build_local_draft
from app.application.creative_agent import (
    CreativeBriefInput,
    CreativeProjectInput,
    CreativeRunInput,
    ProductAnalysis,
)


def _generated_payload(
    project: CreativeProjectInput,
    brief: CreativeBriefInput,
    *,
    unsupported_copy: str,
) -> dict[str, object]:
    analysis = ProductAnalysis(
        product_summary=brief.product_name,
        inferred_category="强调转化的消费品",
        inferred_selling_points=["Lightweight", "sealed lid"],
        inferred_audience=["Commuters"],
        visual_evidence_count=1,
        constraints=[],
        missing_information=[],
        readiness_score=100,
    )
    draft = build_local_draft(
        project=project,
        brief=brief,
        analysis=analysis,
        campaign_goal="Increase product detail views",
    )
    payload = draft.model_dump(mode="json")
    payload.pop("analysis")
    concepts = payload["concepts"]
    assert isinstance(concepts, list)
    first_concept = concepts[0]
    assert isinstance(first_concept, dict)
    first_concept["hook"] = unsupported_copy
    return payload


class ReviewingProvider:
    configured = True

    def __init__(
        self,
        creative_payload: dict[str, object],
        review_payload: dict[str, object],
        *,
        fail_review: bool = False,
    ) -> None:
        self.creative_payload = creative_payload
        self.review_payload = review_payload
        self.fail_review = fail_review
        self.calls = 0

    def generate_json(self, **kwargs) -> ModelJsonResponse:
        self.calls += 1
        schema = kwargs["json_schema"]
        if "assessments" in schema.get("properties", {}):
            if self.fail_review:
                raise ProviderTransientError("semantic reviewer unavailable")
            return ModelJsonResponse(
                payload=deepcopy(self.review_payload),
                model_key="semantic-reviewer",
            )
        return ModelJsonResponse(
            payload=deepcopy(self.creative_payload),
            model_key="creative-generator",
        )


def test_semantic_review_blocks_unsupported_claim_outside_regex_patterns(
    project_factory: Callable[..., CreativeProjectInput],
    run_input_factory: Callable[..., CreativeRunInput],
    complete_brief: CreativeBriefInput,
) -> None:
    project = project_factory()
    claim = "采用专业实验标准，适合所有敏感人群"
    provider = ReviewingProvider(
        _generated_payload(project, complete_brief, unsupported_copy=claim),
        {
            "assessments": [
                {
                    "text": claim,
                    "field_path": "concepts[0].hook",
                    "status": "unsupported",
                    "evidence_key": None,
                    "reason": "确认事实没有实验标准或敏感人群适用范围。",
                }
            ]
        },
    )

    result = CreativePlanner(provider=provider).run(run_input_factory(project=project))

    assert provider.calls == 2
    assert not result.bundle.evaluation.passed
    assert result.bundle.action == "resolve_quality_issues"
    assert any(
        issue.code == "unsupported_semantic_claim"
        for issue in result.bundle.evaluation.issues
    )


def test_server_rejects_supported_claim_with_unknown_evidence_key(
    project_factory: Callable[..., CreativeProjectInput],
    run_input_factory: Callable[..., CreativeRunInput],
    complete_brief: CreativeBriefInput,
) -> None:
    project = project_factory()
    claim = "适合所有敏感人群"
    provider = ReviewingProvider(
        _generated_payload(project, complete_brief, unsupported_copy=claim),
        {
            "assessments": [
                {
                    "text": claim,
                    "field_path": "concepts[0].hook",
                    "status": "supported",
                    "evidence_key": "invented:99",
                    "reason": "模型声称存在证据。",
                }
            ]
        },
    )

    result = CreativePlanner(provider=provider).run(run_input_factory(project=project))

    assert not result.bundle.evaluation.passed
    assert any(issue.code == "invalid_claim_evidence" for issue in result.bundle.evaluation.issues)


def test_server_rejects_expanded_claim_even_with_existing_evidence_key(
    project_factory: Callable[..., CreativeProjectInput],
    run_input_factory: Callable[..., CreativeRunInput],
    complete_brief: CreativeBriefInput,
) -> None:
    project = project_factory()
    claim = "Lightweight and suitable for every medical condition"
    provider = ReviewingProvider(
        _generated_payload(project, complete_brief, unsupported_copy=claim),
        {
            "assessments": [
                {
                    "text": claim,
                    "field_path": "concepts[0].hook",
                    "status": "supported",
                    "evidence_key": "selling_point:0",
                    "reason": "模型错误地使用了轻便卖点作为证据。",
                }
            ]
        },
    )

    result = CreativePlanner(provider=provider).run(run_input_factory(project=project))

    assert not result.bundle.evaluation.passed
    assert any(issue.code == "invalid_claim_evidence" for issue in result.bundle.evaluation.issues)


def test_external_draft_fails_closed_when_semantic_review_is_unavailable(
    project_factory: Callable[..., CreativeProjectInput],
    run_input_factory: Callable[..., CreativeRunInput],
    complete_brief: CreativeBriefInput,
) -> None:
    project = project_factory()
    provider = ReviewingProvider(
        _generated_payload(project, complete_brief, unsupported_copy="A restrained product hook"),
        {
            "assessments": [
                {
                    "text": "Lightweight",
                    "field_path": "concepts[0].primary_selling_point",
                    "status": "supported",
                    "evidence_key": "selling_point:0",
                    "reason": "与确认卖点一致。",
                }
            ]
        },
        fail_review=True,
    )

    result = CreativePlanner(provider=provider).run(run_input_factory(project=project))

    assert provider.calls == 2
    assert not result.bundle.evaluation.passed
    assert result.bundle.action == "resolve_quality_issues"
    assert any(
        issue.code == "semantic_review_unavailable"
        for issue in result.bundle.evaluation.issues
    )
