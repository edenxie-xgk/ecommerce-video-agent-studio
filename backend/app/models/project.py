from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """生成数据库记录使用的 UTC 时间。"""

    return datetime.now(timezone.utc)


class VideoProject(SQLModel, table=True):
    """创意项目，作为商品资料、素材和智能体决策记录的归属对象。"""

    __tablename__ = "video_projects"

    id: int | None = Field(default=None, primary_key=True, description="项目 ID。")
    title: str = Field(description="项目标题。")
    target_platform: str = Field(default="douyin", description="目标平台。")
    language: str = Field(default="zh-CN", description="项目语言。")
    aspect_ratio: str = Field(default="9:16", description="默认画面比例。")
    duration_seconds: int = Field(default=15, description="默认视频时长。")
    status: str = Field(default="draft", description="项目状态。")
    budget_limit: Decimal | None = Field(default=None, description="项目预算上限。")
    estimated_cost_total: Decimal = Field(default=Decimal("0"), description="预估总成本。")
    actual_cost_total: Decimal = Field(default=Decimal("0"), description="实际总成本。")
    created_at: datetime = Field(default_factory=utc_now, description="创建时间。")
    updated_at: datetime = Field(default_factory=utc_now, description="更新时间。")


class ProductBrief(SQLModel, table=True):
    """商品资料，供创意智能体分析和制定方案。"""

    __tablename__ = "product_briefs"

    id: int | None = Field(default=None, primary_key=True, description="商品资料 ID。")
    project_id: int = Field(foreign_key="video_projects.id", description="所属项目 ID。")
    product_name: str = Field(description="商品名称。")
    selling_points_text: str = Field(default="", description="商品卖点文本。")
    target_audience_text: str = Field(default="", description="目标人群文本。")
    brand_tone: str = Field(default="", description="品牌语气或风格要求。")
    forbidden_words_text: str = Field(default="", description="禁用词或风险表达。")
    confirmed_at: datetime | None = Field(default=None, description="商品资料确认时间。")
    created_at: datetime = Field(default_factory=utc_now, description="创建时间。")
    updated_at: datetime = Field(default_factory=utc_now, description="更新时间。")


class ProjectAsset(SQLModel, table=True):
    """项目素材，当前用于保存后端上传后的商品图引用。"""

    __tablename__ = "project_assets"

    id: int | None = Field(default=None, primary_key=True, description="素材 ID。")
    project_id: int = Field(foreign_key="video_projects.id", description="所属项目 ID。")
    asset_type: str = Field(default="product_image", description="素材类型。")
    storage_key: str = Field(description="后端保存素材后的存储 key。")
    mime_type: str = Field(description="素材 MIME 类型。")
    size_bytes: int | None = Field(default=None, description="素材大小，单位字节。")
    asset_metadata: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSON),
        description="素材元数据。",
    )
    created_at: datetime = Field(default_factory=utc_now, description="创建时间。")
