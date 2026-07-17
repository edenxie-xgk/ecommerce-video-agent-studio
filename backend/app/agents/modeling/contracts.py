"""声明仅用于外部模型 Provider 边界的结构化输出契约。

这些契约只描述模型可以返回的候选字段；节点会再用服务端事实做校验和组装。
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.application.creative_plan import CreativePlanContent


class GeneratedCreativeDraft(CreativePlanContent):
    """定义外部模型可以生成的创意字段。"""


class GeneratedProductUnderstanding(BaseModel):
    """定义模型在商品理解阶段可以返回的字段。"""

    inferred_category: str = Field(
        min_length=1,
        max_length=200,
        description="根据商品名称、卖点、目标人群和素材引用推断的商品表达类别。",
    )
    selected_selling_points: list[str] = Field(
        min_length=1,
        max_length=8,
        description="从输入 selling_points 中原样选出的本轮创意可使用卖点。",
    )
    selected_audience: list[str] = Field(
        min_length=1,
        max_length=8,
        description="从输入 target_audience 中原样选出的本轮创意目标人群。",
    )
    readiness_score: int = Field(
        ge=0,
        le=100,
        description="模型对当前资料进入创意规划的就绪度评分。",
    )
    visual_observations: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="仅根据已发送图片像素得到的可见事实；没有图片像素时必须为空。",
    )
    visual_uncertainties: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="图片无法确认或需要用户补充的信息，例如材质、容量、功效参数。",
    )


class SemanticClaimAssessment(BaseModel):
    """描述语义审核从创意文案中提取的一条可验证商品声明。"""

    text: str = Field(min_length=1, max_length=500, description="文案中的商品事实声明原文。")
    field_path: str = Field(
        min_length=1,
        max_length=200,
        description="声明在创意草案中的字段路径。",
    )
    status: Literal["supported", "unsupported", "ambiguous"] = Field(
        description="声明是否能由已确认事实直接支持。"
    )
    evidence_key: str | None = Field(
        default=None,
        max_length=100,
        description="支持该声明的已确认事实 key；无证据时为空。",
    )
    reason: str = Field(min_length=1, max_length=500, description="审核结论的简短理由。")


class SemanticClaimReview(BaseModel):
    """保存模型对完整创意草案中商品事实声明的结构化审核。"""

    assessments: list[SemanticClaimAssessment] = Field(
        min_length=1,
        max_length=100,
        description="从全部方案和镜头文案中提取的商品声明审核结果。",
    )
