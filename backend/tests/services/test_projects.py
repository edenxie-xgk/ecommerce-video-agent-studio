from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.project import VideoProject
from app.services.projects import ProductBriefInput, ProjectService


def test_saving_brief_marks_project_input_ready_without_running_agent() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        project = VideoProject(title="Input ready test", status="draft")
        session.add(project)
        session.commit()
        session.refresh(project)

        ProjectService(session).upsert_product_brief(
            project.id or 0,
            ProductBriefInput(product_name="便携保温杯"),
        )

        session.refresh(project)
        assert project.status == "input_ready"
