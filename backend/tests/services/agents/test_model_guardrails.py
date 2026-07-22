from collections.abc import Callable
from copy import deepcopy

import pytest

from app.agents.modeling.generation import build_authoritative_draft
from app.agents.modeling.provider import ModelJsonResponse, ProviderResponseError
from app.agents.nodes.creative_script import build_local_draft, build_model_input
from app.agents.planner import CreativePlanner
from app.application.creative_agent import (
    CreativeBriefInput,
    CreativeProjectInput,
    CreativeRunInput,
    ProductAnalysis,
)


def _analysis_overriding_payload(
    project: CreativeProjectInput,
    brief: CreativeBriefInput,
) -> dict[str, object]:
    server_analysis = ProductAnalysis(
        product_summary="Portable thermal cup",
        inferred_category="强调转化的消费品",
        inferred_selling_points=["Lightweight", "sealed lid"],
        inferred_audience=["Commuters"],
        visual_evidence_count=1,
        constraints=["permanent"],
        missing_information=[],
        readiness_score=100,
    )
    draft = build_local_draft(
        project=project,
        brief=brief,
        analysis=server_analysis,
        campaign_goal="Increase product detail views",
    )
    payload = draft.model_dump(mode="json")
    payload["analysis"] = ProductAnalysis(
        product_summary="Forged product",
        inferred_category="Forged category",
        inferred_selling_points=["Invented medical claim"],
        inferred_audience=["Everyone"],
        visual_evidence_count=999,
        constraints=[],
        missing_information=[],
        readiness_score=100,
    ).model_dump(mode="json")
    return payload


def test_creative_model_input_includes_product_understanding_evidence(
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    """creative_script 调用模型时应携带商品理解阶段的证据包。"""

    analysis = ProductAnalysis(
        product_summary="Portable thermal cup",
        inferred_category="通勤保温杯",
        inferred_selling_points=["Lightweight", "sealed lid"],
        inferred_audience=["Commuters"],
        visual_evidence_count=1,
        visual_observations=["blue body", "visible handle"],
        visual_uncertainties=["actual insulation duration is unknown"],
        material_conflicts=[],
        constraints=["permanent"],
        missing_information=[],
        readiness_score=82,
    )

    payload = build_model_input(
        run_input_factory(),
        analysis=analysis,
        selling_points=analysis.inferred_selling_points,
    )

    assert payload["product_name"] == "Portable thermal cup"
    assert payload["product_analysis"] == {
        "inferred_category": "通勤保温杯",
        "selected_selling_points": ["Lightweight", "sealed lid"],
        "selected_audience": ["Commuters"],
        "visual_evidence_count": 1,
        "visual_observations": ["blue body", "visible handle"],
        "visual_uncertainties": ["actual insulation duration is unknown"],
        "material_conflicts": [],
        "readiness_score": 82,
    }


def test_creative_payload_rejects_unconfirmed_audience(
    project_factory: Callable[..., CreativeProjectInput],
    complete_brief: CreativeBriefInput,
) -> None:
    """模型草案面向的人群需要命中用户确认清单。"""

    analysis = ProductAnalysis(
        product_summary="Portable thermal cup",
        inferred_category="通勤保温杯",
        inferred_selling_points=["Lightweight", "sealed lid"],
        inferred_audience=["Commuters"],
        visual_evidence_count=1,
        constraints=[],
        missing_information=[],
        readiness_score=100,
    )
    payload = build_local_draft(
        project=project_factory(),
        brief=complete_brief,
        analysis=analysis,
        campaign_goal="Increase product detail views",
    ).model_dump(mode="json")
    payload.pop("analysis")
    payload["concepts"][0]["target_audience"] = "Everyone"

    with pytest.raises(ProviderResponseError, match="未经过确认的目标人群"):
        build_authoritative_draft(
            payload=payload,
            analysis=analysis,
            allowed_selling_points=["Lightweight", "sealed lid"],
            allowed_audience=["Commuters"],
            forbidden_words=[],
            uncertain_visual_facts=[],
        )


def test_creative_payload_rejects_visual_uncertainty_as_fact(
    project_factory: Callable[..., CreativeProjectInput],
    complete_brief: CreativeBriefInput,
) -> None:
    """图片无法确认的信息不能进入最终创意文案。"""

    uncertainty = "actual insulation duration is unknown"
    analysis = ProductAnalysis(
        product_summary="Portable thermal cup",
        inferred_category="通勤保温杯",
        inferred_selling_points=["Lightweight", "sealed lid"],
        inferred_audience=["Commuters"],
        visual_evidence_count=1,
        visual_uncertainties=[uncertainty],
        constraints=[],
        missing_information=[],
        readiness_score=80,
    )
    payload = build_local_draft(
        project=project_factory(),
        brief=complete_brief,
        analysis=analysis,
        campaign_goal="Increase product detail views",
    ).model_dump(mode="json")
    payload.pop("analysis")
    payload["concepts"][0]["hook"] = f"{uncertainty}，但适合通勤展示。"

    with pytest.raises(ProviderResponseError, match="图片无法确认的信息"):
        build_authoritative_draft(
            payload=payload,
            analysis=analysis,
            allowed_selling_points=["Lightweight", "sealed lid"],
            allowed_audience=["Commuters"],
            forbidden_words=[],
            uncertain_visual_facts=[uncertainty],
        )


class AnalysisOverridingProvider:
    configured = True

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requested_schema: dict[str, object] | None = None
        self.creative_schema: dict[str, object] | None = None
        self.calls = 0

    def generate_json(self, **kwargs) -> ModelJsonResponse:
        self.calls += 1
        self.requested_schema = kwargs["json_schema"]
        properties = self.requested_schema.get("properties", {})
        if "selected_selling_points" in properties:
            return ModelJsonResponse(
                payload={
                    "inferred_category": "强调转化的消费品",
                    "selected_selling_points": ["Lightweight", "sealed lid"],
                    "selected_audience": ["Commuters"],
                    "readiness_score": 100,
                },
                model_key="analysis-overrider",
            )
        if "assessments" in properties:
            return ModelJsonResponse(
                payload={
                    "assessments": [
                        {
                            "text": "Lightweight",
                            "field_path": "concepts[0].primary_selling_point",
                            "status": "supported",
                            "evidence_key": "selling_point:0",
                            "reason": "与已确认卖点完全一致。",
                        }
                    ]
                },
                model_key="analysis-overrider",
            )
        self.creative_schema = self.requested_schema
        return ModelJsonResponse(
            payload=deepcopy(self.payload),
            model_key="analysis-overrider",
        )


class InventedSellingPointProvider(AnalysisOverridingProvider):
    def generate_json(self, **kwargs) -> ModelJsonResponse:
        properties = kwargs["json_schema"].get("properties", {})
        response = super().generate_json(**kwargs)
        if "concepts" not in properties:
            return response
        concepts = response.payload["concepts"]
        assert isinstance(concepts, list)
        for concept in concepts:
            assert isinstance(concept, dict)
            concept["primary_selling_point"] = "Invented unverified claim"
        return response


def test_creative_payload_cannot_override_authoritative_product_analysis(
    project_factory: Callable[..., CreativeProjectInput],
    run_input_factory: Callable[..., CreativeRunInput],
    complete_brief: CreativeBriefInput,
    use_agent_provider,
) -> None:
    project = project_factory()
    provider = AnalysisOverridingProvider(_analysis_overriding_payload(project, complete_brief))
    use_agent_provider(provider)

    result = CreativePlanner().run(run_input_factory(project=project))

    assert provider.creative_schema is not None
    assert "analysis" not in provider.creative_schema["properties"]
    assert result.provider_key == "openai_compatible"
    assert result.model_key == "analysis-overrider"
    assert result.bundle.analysis.product_summary == "Portable thermal cup"
    assert result.bundle.analysis.visual_evidence_count == 1
    assert result.bundle.analysis.inferred_selling_points == ["Lightweight", "sealed lid"]


def test_unverified_model_selling_point_retries_then_falls_back_locally(
    project_factory: Callable[..., CreativeProjectInput],
    run_input_factory: Callable[..., CreativeRunInput],
    complete_brief: CreativeBriefInput,
    use_agent_provider,
) -> None:
    project = project_factory()
    provider = InventedSellingPointProvider(_analysis_overriding_payload(project, complete_brief))
    use_agent_provider(provider)

    result = CreativePlanner().run(run_input_factory(project=project))

    assert result.provider_key == "local"
    assert provider.calls == 3
    assert result.bundle.action == "review_plan"
    assert {concept.primary_selling_point for concept in result.bundle.concepts}.issubset(
        set(result.bundle.analysis.inferred_selling_points)
    )
