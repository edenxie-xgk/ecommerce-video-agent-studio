from collections.abc import Callable

from app.agents.planner import CreativePlanner
from app.agents.nodes.prompt_check import iter_reviewable_text
from app.application.creative_agent import (
    CreativeAgentResult,
    CreativeBriefInput,
    CreativeProjectInput,
    CreativeRunInput,
)
from app.application.creative_runs import CreativeRunService
from app.models.creative import WorkflowRun
from app.models.project import VideoProject


def test_revision_removes_custom_forbidden_words_from_all_scanned_fields(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
    complete_brief: CreativeBriefInput,
) -> None:
    forbidden_word = "restricted"
    brief = complete_brief.model_copy(
        update={
            "selling_points_text": f"Lightweight, {forbidden_word} claim",
            "forbidden_words_text": forbidden_word,
        }
    )

    result = local_planner.run(run_input_factory(brief=brief))

    assert result.bundle.revision_count == 1
    assert result.bundle.evaluation.passed
    assert result.bundle.action == "review_plan"
    assert all(
        all(forbidden_word not in value for value in iter_reviewable_text(concept))
        for concept in result.bundle.concepts
    )


def test_unrepairable_risky_product_name_is_blocked_in_agent_and_run_status(
    local_planner: CreativePlanner,
    project_factory: Callable[..., CreativeProjectInput],
    run_input_factory: Callable[..., CreativeRunInput],
    recording_session,
) -> None:
    result = local_planner.run(
        run_input_factory(
            project=project_factory(project_id=1, title="Risky product name"),
            brief=CreativeBriefInput(
                project_id=1,
                product_name="永久牌保温杯",
                selling_points_text="轻便易携",
                target_audience_text="通勤人群",
                brand_tone="真实克制",
                forbidden_words_text="",
            ),
            campaign_goal="说明通勤价值",
        )
    )

    assert result.bundle.revision_count == 1
    assert not result.bundle.evaluation.passed
    assert result.bundle.action == "resolve_quality_issues"
    assert any(issue.severity == "blocked" for issue in result.bundle.evaluation.issues)

    project = VideoProject(id=1, title="Risky product name")
    run = WorkflowRun(project_id=1, checkpoint_thread_id="blocked-quality-thread")
    service = CreativeRunService(recording_session, local_planner)  # type: ignore[arg-type]
    projected = service._apply_result(
        run,
        project,
        CreativeAgentResult(
            # 应用层仍必须防御其他 Agent 实现返回的不一致 action。
            bundle=result.bundle.model_copy(update={"action": "review_plan"}),
            provider_key=result.provider_key,
            model_key=result.model_key,
        ),
    )

    assert projected.status == "waiting_confirmation"
    assert CreativeRunService.public_status(projected) == "quality_blocked"
    assert CreativeRunService.action(projected) == "resolve_quality_issues"
    assert projected.completed_at is not None
    assert project.status == "quality_blocked"
