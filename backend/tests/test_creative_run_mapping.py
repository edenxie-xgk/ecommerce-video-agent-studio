"""验证数据库记录只通过显式映射进入 Agent。"""

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.application.creative_runs import CreativeRunService
from app.models.creative import WorkflowRun
from app.models.project import ProductBrief, ProjectAsset, VideoProject


def test_database_records_are_mapped_to_agent_contracts() -> None:
    """应用服务应筛选字段，而不是把 SQLModel 对象直接传入 Agent。"""

    project = VideoProject(
        id=1,
        title="Portable cup",
        target_platform="douyin",
        language="zh-CN",
        aspect_ratio="9:16",
        duration_seconds=15,
        status="draft",
    )
    brief = ProductBrief(
        id=2,
        project_id=1,
        product_name="Portable cup",
        selling_points_text="Lightweight",
        target_audience_text="Commuters",
        brand_tone="Clean",
        forbidden_words_text="permanent",
    )
    asset = ProjectAsset(
        id=3,
        project_id=1,
        asset_type="product_image",
        storage_key="product.jpg",
        mime_type="image/jpeg",
        size_bytes=128,
        asset_metadata={"original_filename": "cup.jpg"},
    )

    run_input = CreativeRunService._to_run_input(
        project=project,
        brief=brief,
        assets=[asset],
        campaign_goal="Explain commuting value",
    )

    assert not isinstance(run_input.project, VideoProject)
    assert run_input.project.model_dump() == {
        "id": 1,
        "title": "Portable cup",
        "target_platform": "douyin",
        "language": "zh-CN",
        "aspect_ratio": "9:16",
        "duration_seconds": 15,
        "status": "draft",
    }
    assert run_input.brief is not None
    assert run_input.brief.product_name == "Portable cup"
    assert [item.storage_key for item in run_input.assets] == ["product.jpg"]


def test_incomplete_inputs_do_not_create_run_or_call_agent() -> None:
    """启动前硬门槛缺失时，应用服务直接拒绝，不进入 Agent 图。"""

    class AgentShouldNotRun:
        called = False

        def run(self, *_args, **_kwargs):
            self.called = True
            raise AssertionError("Agent should not run when required inputs are missing.")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    agent = AgentShouldNotRun()

    with Session(engine) as session:
        project = VideoProject(title="Missing inputs", status="input_ready")
        session.add(project)
        session.commit()
        session.refresh(project)

        service = CreativeRunService(session, agent)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="资料未达到启动硬门槛"):
            service.generate(project_id=project.id or 0, campaign_goal="测试启动边界")

        assert not agent.called
        assert session.exec(select(WorkflowRun)).all() == []
