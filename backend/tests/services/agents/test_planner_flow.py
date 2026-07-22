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


def test_storyboard_prompt_review_blocks_user_added_risky_claim(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    """人工调整视频执行 Prompt 后，必须由 Prompt Check 阻断新增的风险表达。"""

    decision = local_planner.run(run_input_factory()).bundle
    original_prompts = decision.storyboard_prompts
    first_concept = original_prompts.concepts[0]
    first_shot = first_concept.shot_prompts[0].model_copy(
        update={
            "positive_prompt": "为 Portable thermal cup 生成永久保温效果的商品展示镜头。",
            "negative_prompt": "避免模糊画面。",
        }
    )
    edited_concept = first_concept.model_copy(
        update={"shot_prompts": [first_shot, *first_concept.shot_prompts[1:]]}
    )
    edited_prompts = original_prompts.model_copy(
        update={"concepts": [edited_concept, *original_prompts.concepts[1:]]}
    )

    reviewed = local_planner.review_storyboard_prompts(
        decision=decision,
        storyboard_prompts=edited_prompts,
    )

    assert reviewed.action == "resolve_quality_issues"
    assert not reviewed.evaluation.passed
    assert any(issue.code == "prompt_risky_claim" for issue in reviewed.evaluation.issues)
    assert (
        original_prompts.global_negative_prompt
        in reviewed.storyboard_prompts.concepts[0].shot_prompts[0].negative_prompt
    )


def test_storyboard_prompt_review_normalizes_product_reference_formatting(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    """商品名的大小写、空白和连字符差异不应触发无意义的主体缺失阻断。"""

    decision = local_planner.run(run_input_factory()).bundle
    first_concept = decision.storyboard_prompts.concepts[0]
    first_shot = first_concept.shot_prompts[0].model_copy(
        update={
            "positive_prompt": "portable-thermal cup 主体居中展示，保持外观稳定。",
        }
    )
    edited_prompts = decision.storyboard_prompts.model_copy(
        update={
            "concepts": [
                first_concept.model_copy(
                    update={"shot_prompts": [first_shot, *first_concept.shot_prompts[1:]]}
                ),
                *decision.storyboard_prompts.concepts[1:],
            ]
        }
    )

    reviewed = local_planner.review_storyboard_prompts(
        decision=decision,
        storyboard_prompts=edited_prompts,
    )

    assert not any(
        issue.code == "prompt_missing_product_reference" for issue in reviewed.evaluation.issues
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
    use_agent_provider,
) -> None:
    provider = FailingProvider()
    use_agent_provider(provider, product_understanding=False)
    planner = CreativePlanner()

    result = planner.run(run_input_factory())

    assert provider.calls == 2
    assert result.provider_key == "local"
    assert result.bundle.action == "review_plan"


def test_product_understanding_model_failure_stops_run(
    use_agent_provider,
    run_input_factory,
) -> None:
    """商品理解模型已配置时，调用失败应暴露给请求层。"""

    class FailingProductUnderstandingProvider:
        configured = True

        def __init__(self) -> None:
            self.calls = 0

        def generate_json(self, **_kwargs):
            self.calls += 1
            raise ProviderTransientError("product understanding provider unavailable")

    provider = use_agent_provider(FailingProductUnderstandingProvider())

    with pytest.raises(ProviderTransientError, match="product understanding provider unavailable"):
        CreativePlanner().run(run_input_factory())

    assert provider.calls == 2


class UnexpectedCallProvider:
    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured
        self.calls = 0

    def generate_json(self, **_kwargs):
        self.calls += 1
        raise AssertionError("provider should not be called")


def test_planner_rejects_missing_selling_points_before_agent_run(
    run_input_factory: Callable[..., CreativeRunInput],
    complete_brief: CreativeBriefInput,
    use_agent_provider,
) -> None:
    provider = UnexpectedCallProvider()
    use_agent_provider(provider)
    for empty_value in ("", "  ,，、;；\n"):
        brief_without_selling_points = complete_brief.model_copy(
            update={"selling_points_text": empty_value}
        )
        with pytest.raises(ValueError, match="selling_points"):
            CreativePlanner().run(
                run_input_factory(brief=brief_without_selling_points)
            )

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
    use_agent_provider,
) -> None:
    provider = ProgrammingErrorProvider()
    use_agent_provider(provider)

    with pytest.raises(RuntimeError, match="unexpected provider adapter bug"):
        CreativePlanner().run(run_input_factory())

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
    use_agent_provider,
) -> None:
    provider = RequestErrorProvider()
    use_agent_provider(provider, product_understanding=False)

    result = CreativePlanner().run(run_input_factory())

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
