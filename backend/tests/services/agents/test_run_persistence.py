from collections.abc import Callable

from app.agents.planner import CreativePlanner
from app.api.routes import _creative_run_to_response
from app.application.creative_agent import CreativeRunInput
from app.application.creative_runs import CreativeRunService
from app.models.creative import CreativeRun, WorkflowRun
from app.models.project import VideoProject


def test_run_result_uses_versioned_payload_and_round_trips(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
    recording_session,
) -> None:
    result = local_planner.run(run_input_factory())
    run = WorkflowRun(project_id=1, checkpoint_thread_id="versioned-result")
    project = VideoProject(id=1, title="Versioned result")
    service = CreativeRunService(recording_session, local_planner)  # type: ignore[arg-type]

    service._apply_result(run, project, result)

    decision_payload = run.run_metadata["decision_payload"]
    assert isinstance(decision_payload, dict)
    assert decision_payload["schema_version"] == 1
    assert "decision" in decision_payload
    assert CreativeRunService.parse_result(run) == result.bundle


def test_parse_result_accepts_legacy_unversioned_payload(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    result = local_planner.run(run_input_factory())
    run = CreativeRun(
        id=1,
        project_id=1,
        thread_id="legacy-result",
        output_payload=result.bundle.model_dump(mode="json"),
    )

    assert CreativeRunService.parse_result(run) == result.bundle


def test_parse_result_isolates_incompatible_or_unknown_payload_versions(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    result = local_planner.run(run_input_factory())
    incompatible = result.bundle.model_dump(mode="json")
    incompatible["evaluation"]["overall_score"] = 0
    run = WorkflowRun(
        id=2,
        project_id=1,
        checkpoint_thread_id="incompatible-result",
        run_metadata={"decision_payload": incompatible},
    )
    assert CreativeRunService.parse_result(run) is None
    response = _creative_run_to_response(run)
    assert response.result is None
    assert response.error_message == "历史创意结果与当前契约不兼容，请重新生成。"

    run.run_metadata = {"decision_payload": {"schema_version": 999, "decision": incompatible}}
    assert CreativeRunService.parse_result(run) is None


def test_failed_run_projection_clears_stale_decision_and_updates_project(
    local_planner: CreativePlanner,
    recording_session,
) -> None:
    run = WorkflowRun(
        project_id=1,
        checkpoint_thread_id="failed-run",
        status="running",
        run_metadata={
            "action": "review_plan",
            "confidence": 0.99,
            "model_key": "stale-model",
            "decision_payload": {"stale": "decision"},
        },
    )
    project = VideoProject(id=1, title="Failed run", status="running")
    service = CreativeRunService(recording_session, local_planner)  # type: ignore[arg-type]

    service._mark_failed(run, project, RuntimeError("checkpoint unavailable"))

    assert run.status == "failed"
    assert CreativeRunService.action(run) is None
    assert CreativeRunService.confidence(run) is None
    assert CreativeRunService.model_key(run) is None
    assert CreativeRunService.parse_result(run) is None
    assert run.error_message == "checkpoint unavailable"
    assert run.completed_at is not None
    assert project.status == "failed"
