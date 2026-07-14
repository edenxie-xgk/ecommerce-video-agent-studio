"""声明仅用于外部模型 Provider 边界的结构化输出契约。

外部模型返回创意内容字段。服务端负责把模型结果与权威商品分析组合成
完整 `CreativeDraft`。
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.application.creative_plan import CreativePlanContent


class GeneratedCreativeDraft(CreativePlanContent):
    """定义外部模型可以生成的创意字段。"""


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
