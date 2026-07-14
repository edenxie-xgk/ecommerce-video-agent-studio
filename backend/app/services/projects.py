from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from app.models.project import ProductBrief, ProjectAsset, VideoProject, utc_now


@dataclass(frozen=True)
class ProductBriefInput:
    product_name: str | None = None
    selling_points_text: str = ""
    target_audience_text: str = ""
    brand_tone: str = ""
    forbidden_words_text: str = ""


@dataclass(frozen=True)
class ProjectCreateInput:
    title: str
    target_platform: str
    product_brief: ProductBriefInput | None = None


class ProjectService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_projects(self) -> list[VideoProject]:
        return list(
            self._session.exec(
                select(VideoProject).order_by(VideoProject.id.desc())
            ).all()
        )

    def get_project(self, project_id: int) -> VideoProject | None:
        return self._session.get(VideoProject, project_id)

    def create_project(self, payload: ProjectCreateInput) -> VideoProject:
        project = VideoProject(
            title=payload.title,
            target_platform=payload.target_platform,
            language="zh-CN",
            aspect_ratio="9:16",
            duration_seconds=15,
            status="draft",
        )
        self._session.add(project)
        self._session.commit()
        self._session.refresh(project)

        if payload.product_brief:
            self.upsert_product_brief(project.id or 0, payload.product_brief)

        return project

    def upsert_product_brief(
        self,
        project_id: int,
        payload: ProductBriefInput,
    ) -> ProductBrief:
        brief = self._session.exec(
            select(ProductBrief).where(ProductBrief.project_id == project_id)
        ).first()
        if brief is None:
            brief = ProductBrief(
                project_id=project_id,
                product_name=payload.product_name or "未命名商品",
            )

        brief.product_name = payload.product_name or "未命名商品"
        brief.selling_points_text = payload.selling_points_text.strip()
        brief.target_audience_text = payload.target_audience_text.strip()
        brief.brand_tone = payload.brand_tone.strip()
        brief.forbidden_words_text = payload.forbidden_words_text.strip()
        brief.updated_at = utc_now()
        self._session.add(brief)

        project = self.get_project(project_id)
        if project is not None:
            # 保存商品资料只说明输入侧已更新；是否能启动 Agent 由生成前校验决定。
            project.status = "input_ready"
            project.updated_at = utc_now()
            self._session.add(project)

        self._session.commit()
        self._session.refresh(brief)
        return brief

    def get_product_brief(self, project_id: int) -> ProductBrief | None:
        return self._session.exec(
            select(ProductBrief).where(ProductBrief.project_id == project_id)
        ).first()

    def list_assets(self, project_id: int) -> list[ProjectAsset]:
        return list(
            self._session.exec(
                select(ProjectAsset)
                .where(ProjectAsset.project_id == project_id)
                .order_by(ProjectAsset.id.desc())
            ).all()
        )
