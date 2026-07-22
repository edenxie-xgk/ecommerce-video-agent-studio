from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from app.agents.modeling.provider import OpenAICompatibleProvider
from app.agents.models import config_model
from app.agents.planner import CreativePlanner
from app.api.deps import get_db
from app.api.routes import router
from app.application.creative_agent import (
    CreativeAssetInput,
    CreativeBriefInput,
    CreativeProjectInput,
    CreativeRunInput,
)
from app.application.creative_runs import CreativeRunService
from app.models.creative import WorkflowRun
from app.models.project import ProductBrief, ProjectAsset, VideoProject


def test_storyboard_prompt_review_api_rejects_stale_editor_version(
    monkeypatch,
) -> None:
    """接口应返回新版运行，并拒绝来自旧编辑页面的覆盖请求。"""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    provider = OpenAICompatibleProvider(
        base_url=None,
        api_key=None,
        model_key=None,
        timeout_seconds=45,
    )
    monkeypatch.setattr(config_model, "product_understanding_model", lambda: provider)
    monkeypatch.setattr(config_model, "creative_script_model", lambda: provider)
    monkeypatch.setattr(config_model, "prompt_check_model", lambda: provider)
    planner = CreativePlanner()
    try:
        project = VideoProject(id=1, title="API review", status="ready_for_review")
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
            storage_key="api-product.jpg",
            mime_type="image/jpeg",
            asset_metadata={"verified": True},
        )
        run = WorkflowRun(project_id=1, checkpoint_thread_id="api-storyboard-review")
        session.add(project)
        session.add(brief)
        session.add(asset)
        session.add(run)
        session.commit()
        session.refresh(run)

        run_input = CreativeRunInput(
            project=CreativeProjectInput(
                id=1,
                title="API review",
                target_platform="douyin",
                language="zh-CN",
                aspect_ratio="9:16",
                duration_seconds=15,
                status="ready_for_review",
            ),
            brief=CreativeBriefInput(
                project_id=1,
                product_name="Portable thermal cup",
                selling_points_text="Lightweight, sealed lid",
                target_audience_text="Commuters",
                brand_tone="Clean and practical",
                forbidden_words_text="permanent",
            ),
            assets=[
                CreativeAssetInput(
                    id=1,
                    project_id=1,
                    storage_key="api-product.jpg",
                    mime_type="image/jpeg",
                )
            ],
            campaign_goal="Explain the commuting value",
        )
        service = CreativeRunService(session, planner)
        service._apply_result(run, project, planner.run(run_input))
        current = CreativeRunService.parse_result(run)
        assert current is not None

        app = FastAPI()
        app.include_router(router)
        app.state.creative_agent = planner

        def override_db() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        payload = {
            "expected_prompt_revision": 0,
            "storyboard_prompts": current.storyboard_prompts.model_dump(mode="json"),
        }

        first_response = client.put(
            "/api/v1/projects/1/creative-runs/1/storyboard-prompts",
            json=payload,
        )
        stale_response = client.put(
            "/api/v1/projects/1/creative-runs/1/storyboard-prompts",
            json=payload,
        )
    finally:
        session.close()

    assert first_response.status_code == 200
    first_payload = first_response.json()
    assert first_payload["id"] == 1
    assert first_payload["prompt_revision"] == 1
    assert first_payload["prompt_revision_count"] == 1
    assert first_payload["result"]["storyboard_prompts"] == payload["storyboard_prompts"]
    assert stale_response.status_code == 409
    assert "已被其他编辑更新" in stale_response.json()["detail"]
