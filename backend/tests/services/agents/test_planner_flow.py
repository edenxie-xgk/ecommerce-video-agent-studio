from collections.abc import Callable

import pytest

from app.agents.planner import CreativePlanner
from app.agents.modeling.provider import ProviderRequestError, ProviderTransientError
from app.application.creative_agent import (
    CreativeBriefInput,
    CreativeProjectInput,
    CreativeRunInput,
)


def test_planner_rejects_incomplete_direct_inputs(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
    project_factory: Callable[..., CreativeProjectInput],
) -> None:
    with pytest.raises(ValueError, match="Agent 输入资料不完整"):
        local_planner.run(
            run_input_factory(
                project=project_factory(title="Test"),
                brief=None,
                assets=[],
            )
        )


def test_planner_evaluates_three_concepts(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
    project_factory: Callable[..., CreativeProjectInput],
) -> None:
    result = local_planner.run(
        run_input_factory(
            project=project_factory(target_platform="xiaohongshu"),
            campaign_goal="Explain commuting value",
        )
    )

    assert result.bundle.action == "review_plan"
    assert len(result.bundle.concepts) == 3
    assert result.bundle.evaluation.passed
    assert all(
        sum(shot.duration_seconds for shot in concept.shots) == 15
        for concept in result.bundle.concepts
    )


class FailingProvider:
    configured = True

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, **_kwargs):
        self.calls += 1
        raise ProviderTransientError("provider unavailable")


def test_model_node_retries_then_routes_to_local_fallback(
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    provider = FailingProvider()
    planner = CreativePlanner(provider=provider)

    result = planner.run(run_input_factory())

    assert provider.calls == 2
    assert result.provider_key == "local"
    assert result.bundle.action == "review_plan"


class UnexpectedCallProvider:
    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured
        self.calls = 0

    def generate_json(self, **_kwargs):
        self.calls += 1
        raise AssertionError("provider should not be called")


def test_planner_uses_local_strategy_without_selling_points(
    run_input_factory: Callable[..., CreativeRunInput],
    complete_brief: CreativeBriefInput,
) -> None:
    provider = UnexpectedCallProvider()
    for empty_value in ("", "  ,，、;；\n"):
        brief_without_selling_points = complete_brief.model_copy(
            update={"selling_points_text": empty_value}
        )
        result = CreativePlanner(provider=provider).run(
            run_input_factory(brief=brief_without_selling_points)
        )

        assert result.provider_key == "local"
        assert result.bundle.action == "review_plan"
    assert provider.calls == 0


class ProgrammingErrorProvider:
    configured = True

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, **_kwargs):
        self.calls += 1
        raise RuntimeError("unexpected provider adapter bug")


def test_model_node_does_not_retry_or_hide_unknown_programming_errors(
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    provider = ProgrammingErrorProvider()

    with pytest.raises(RuntimeError, match="unexpected provider adapter bug"):
        CreativePlanner(provider=provider).run(run_input_factory())

    assert provider.calls == 1


class RequestErrorProvider:
    configured = True

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, **_kwargs):
        self.calls += 1
        raise ProviderRequestError("invalid provider request")


def test_non_retryable_provider_error_falls_back_after_one_attempt(
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    provider = RequestErrorProvider()

    result = CreativePlanner(provider=provider).run(run_input_factory())

    assert provider.calls == 1
    assert result.provider_key == "local"
    assert result.bundle.action == "review_plan"


def test_new_run_rejects_an_execution_id_with_existing_checkpoint(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    execution_id = "must-not-be-reused"
    local_planner.run(run_input_factory(), execution_id=execution_id)

    with pytest.raises(ValueError, match="execution_id 已存在"):
        local_planner.run(run_input_factory(), execution_id=execution_id)
