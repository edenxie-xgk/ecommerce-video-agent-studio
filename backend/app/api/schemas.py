from __future__ import annotations

from pydantic import BaseModel, Field

from app.application.creative_agent import CreativeDecisionBundle, StoryboardPromptBundle


class ProductBriefPayload(BaseModel):
    product_name: str | None = Field(default=None, description="用户确认的准确商品名称。")
    selling_points_text: str = Field(default="", description="用户确认的商品卖点文本。")
    target_audience_text: str = Field(default="", description="用户确认的目标人群文本。")
    brand_tone: str = Field(default="", description="品牌语气或表达风格。")
    forbidden_words_text: str = Field(default="", description="必须避免的风险表达。")


class ProductBriefResponse(ProductBriefPayload):
    id: int = Field(description="商品资料 ID。")
    project_id: int = Field(description="所属项目 ID。")


class ProjectCreatePayload(BaseModel):
    title: str = Field(..., min_length=1, description="项目标题。")
    target_platform: str = Field(
        default="douyin",
        pattern="^(douyin|xiaohongshu)$",
        description="目标内容平台。",
    )
    product_brief: ProductBriefPayload | None = Field(
        default=None,
        description="创建项目时可选的初始商品资料。",
    )


class ProjectResponse(BaseModel):
    id: int = Field(description="项目 ID。")
    title: str = Field(description="项目标题。")
    target_platform: str = Field(description="目标内容平台。")
    language: str = Field(description="内容语言。")
    aspect_ratio: str = Field(description="目标视频画面比例。")
    duration_seconds: int = Field(description="目标视频时长，单位秒。")
    status: str = Field(description="项目当前业务状态。")
    product_brief: ProductBriefResponse | None = Field(
        default=None,
        description="项目当前保存的商品资料。",
    )
    created_at: str = Field(description="项目创建时间。")
    updated_at: str = Field(description="项目更新时间。")


class ProjectAssetResponse(BaseModel):
    id: int = Field(description="素材 ID。")
    project_id: int = Field(description="所属项目 ID。")
    type: str = Field(description="素材业务类型。")
    file_path: str = Field(description="前端可访问或展示的文件路径。")
    original_filename: str | None = Field(default=None, description="用户上传时的原始文件名。")
    mime_type: str | None = Field(default=None, description="素材 MIME 类型。")
    size_bytes: int | None = Field(default=None, description="素材大小，单位字节。")
    created_at: str = Field(description="素材创建时间。")


class StoryboardPromptUpdatePayload(BaseModel):
    """接收用户确认后的分镜 Prompt 编辑内容。"""

    expected_prompt_revision: int = Field(
        ge=0,
        description="用户开始编辑时读取到的分镜 Prompt 版本，用于拒绝过期覆盖。",
    )
    storyboard_prompts: StoryboardPromptBundle = Field(
        description="用户修改后的三套分镜视频执行 Prompt。"
    )


class CreativeRunResponse(BaseModel):
    id: int = Field(description="创意运行 ID。")
    project_id: int = Field(description="所属项目 ID。")
    campaign_goal: str | None = Field(
        default=None,
        description="创建该运行时使用的营销目标快照。",
    )
    status: str = Field(description="创意运行状态。")
    action: str | None = Field(description="Agent 建议用户执行的下一步动作。")
    confidence: float | None = Field(description="当前决策置信度。")
    provider: str = Field(description="实际完成生成的 Provider 标识。")
    model: str | None = Field(description="实际完成生成的模型标识。")
    revision_count: int = Field(description="自动修订次数。")
    prompt_revision_count: int = Field(description="用户编辑并复检分镜 Prompt 的次数。")
    prompt_revision: int = Field(description="当前分镜 Prompt 的乐观锁版本。")
    result: CreativeDecisionBundle | None = Field(description="通过校验的创意决策结果。")
    started_at: str = Field(description="运行开始时间。")
    completed_at: str | None = Field(description="运行完成时间。")
    error_message: str | None = Field(description="不可恢复错误信息。")
