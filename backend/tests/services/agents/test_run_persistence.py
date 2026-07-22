from collections.abc import Callable

import pytest

from app.agents.planner import CreativePlanner
from app.api.routes import _creative_run_to_response
from app.application.creative_agent import CreativeAgentResult, CreativeRunInput
from app.application.creative_runs import (
    DECISION_PAYLOAD_SCHEMA_VERSION,
    CreativeRunService,
    StoryboardPromptRevisionConflictError,
)
from app.models.creative import AgentRun, CreativeRun, WorkflowRun
from app.models.project import ProductBrief, ProjectAsset, VideoProject
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select


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
    assert decision_payload["schema_version"] == DECISION_PAYLOAD_SCHEMA_VERSION
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


def test_product_understanding_provider_metadata_is_recorded_on_its_node(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    """商品理解节点应保存自己的模型元数据，不使用创意脚本节点的元数据。"""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    planner_result = local_planner.run(run_input_factory())
    result = CreativeAgentResult(
        bundle=planner_result.bundle,
        provider_key=planner_result.provider_key,
        model_key=planner_result.model_key,
        product_understanding_provider_key="openai_compatible",
        product_understanding_model_key="vision-model",
    )

    with Session(engine) as session:
        project = VideoProject(id=1, title="Provider metadata")
        run = WorkflowRun(project_id=1, checkpoint_thread_id="provider-metadata")
        session.add(project)
        session.add(run)
        session.commit()
        session.refresh(run)

        CreativeRunService(session, local_planner)._apply_result(run, project, result)
        product_node = session.exec(
            select(AgentRun).where(AgentRun.agent_type == "product_understanding")
        ).one()
        creative_node = session.exec(
            select(AgentRun).where(AgentRun.agent_type == "creative_script")
        ).one()

    assert product_node.provider_key == "openai_compatible"
    assert product_node.model_key == "vision-model"
    assert creative_node.provider_key == planner_result.provider_key
    assert creative_node.model_key == planner_result.model_key


def test_storyboard_review_rechecks_and_persists_on_the_existing_run(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    """人工修改分镜 Prompt 应更新原运行、投影状态并记录新的 Prompt Check 节点。"""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    result = local_planner.run(run_input_factory())

    with Session(engine) as session:
        project = VideoProject(id=1, title="Storyboard review")
        run = WorkflowRun(project_id=1, checkpoint_thread_id="storyboard-review")
        session.add(project)
        session.add(run)
        session.commit()
        session.refresh(run)

        service = CreativeRunService(session, local_planner)
        service._apply_result(run, project, result)
        decision = CreativeRunService.parse_result(run)
        assert decision is not None
        first_concept = decision.storyboard_prompts.concepts[0]
        first_shot = first_concept.shot_prompts[0].model_copy(
            update={"positive_prompt": "Portable thermal cup 永久保温，适合通勤使用。"}
        )
        edited_concept = first_concept.model_copy(
            update={"shot_prompts": [first_shot, *first_concept.shot_prompts[1:]]}
        )
        edited_prompts = decision.storyboard_prompts.model_copy(
            update={"concepts": [edited_concept, *decision.storyboard_prompts.concepts[1:]]}
        )

        updated_run = service.review_storyboard_prompts(
            project_id=1,
            run_id=run.id or 0,
            storyboard_prompts=edited_prompts,
            expected_prompt_revision=0,
        )
        with pytest.raises(StoryboardPromptRevisionConflictError, match="其他编辑"):
            service.review_storyboard_prompts(
                project_id=1,
                run_id=run.id or 0,
                storyboard_prompts=edited_prompts,
                expected_prompt_revision=0,
            )
        session.refresh(project)
        reviewed_decision = CreativeRunService.parse_result(updated_run)
        prompt_checks = session.exec(
            select(AgentRun).where(AgentRun.agent_type == "prompt_check")
        ).all()

    assert updated_run.id == run.id
    assert CreativeRunService.public_status(updated_run) == "quality_blocked"
    assert CreativeRunService.prompt_revision_count(updated_run) == 1
    assert CreativeRunService.prompt_revision(updated_run) == 1
    assert reviewed_decision is not None
    assert reviewed_decision.action == "resolve_quality_issues"
    assert project.status == "quality_blocked"
    assert len(prompt_checks) == 2


def test_schema_one_decision_is_adapted_without_mutating_history(
    local_planner: CreativePlanner,
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    """旧结果缺少分镜时按当前项目素材构造可审核视图，不写回原载荷。"""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    result = local_planner.run(run_input_factory())
    legacy_decision = result.bundle.model_dump(mode="json")
    legacy_decision.pop("storyboard_prompts")
    analysis = legacy_decision["analysis"]
    assert isinstance(analysis, dict)
    analysis.pop("material_conflicts")

    with Session(engine) as session:
        project = VideoProject(id=1, title="Legacy storyboard", status="ready_for_review")
        brief = ProductBrief(
            project_id=1,
            product_name="Portable thermal cup",
            selling_points_text="Lightweight, sealed lid",
            target_audience_text="Commuters",
            brand_tone="Clean and practical",
            forbidden_words_text="permanent",
        )
        asset = ProjectAsset(
            project_id=1,
            asset_type="product_image",
            storage_key="legacy-product.jpg",
            mime_type="image/jpeg",
            asset_metadata={"verified": True},
        )
        run = WorkflowRun(
            project_id=1,
            checkpoint_thread_id="schema-one-storyboard",
            status="waiting_confirmation",
            run_metadata={
                "campaign_goal": "Explain the commuting value",
                "decision_payload": {"schema_version": 1, "decision": legacy_decision},
            },
        )
        session.add(project)
        session.add(brief)
        session.add(asset)
        session.add(run)
        session.commit()
        session.refresh(run)

        service = CreativeRunService(session, local_planner)
        adapted = service.decision_for_run(run)
        response = _creative_run_to_response(run, result=adapted)

    assert adapted is not None
    assert len(adapted.storyboard_prompts.concepts) == 3
    assert adapted.storyboard_prompts.product_asset_refs == [
        "asset_id=1; storage_key=legacy-product.jpg; mime_type=image/jpeg"
    ]
    assert response.result == adapted
    assert response.error_message is None
    payload = run.run_metadata["decision_payload"]
    assert isinstance(payload, dict)
    assert payload["schema_version"] == 1
