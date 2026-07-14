"""定义与具体模型 Provider 无关的创意计划内容契约。"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


# 单个镜头推荐的视频生成方式；当前主要使用商品图驱动，文本生成保留为扩展入口。
GenerationMode = Literal[
    "image_to_video",  # 使用已验证商品图作为视觉锚点生成视频镜头。
    "text_to_video",  # 使用文本描述生成镜头，适合弱商品图依赖的扩展场景。
]


class ProductAnalysis(BaseModel):
    """保存 Agent 对商品事实、约束和资料完整度的判断。"""

    product_summary: str = Field(description="Agent 使用的标准商品名称或摘要。")
    inferred_category: str = Field(description="根据平台和资料推断的商品表达类别。")
    inferred_selling_points: list[str] = Field(
        default_factory=list,
        description="Agent 采用的已确认或保守推断卖点。",
    )
    inferred_audience: list[str] = Field(
        default_factory=list,
        description="Agent 采用的目标人群判断。",
    )
    visual_evidence_count: int = Field(ge=0, description="已验证且可用于镜头规划的图片引用数量。")
    constraints: list[str] = Field(
        default_factory=list,
        description="用户声明的禁用表达和内容约束。",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="阻断继续生成的必要信息字段。",
    )
    readiness_score: int = Field(
        ge=0,
        le=100,
        description="当前资料进入创意生成的就绪度评分。",
    )


class ShotPlan(BaseModel):
    """描述一个创意方向中的单个视频镜头。"""

    order: int = Field(ge=1, le=3, description="镜头在方案中的顺序。")
    duration_seconds: int = Field(ge=1, le=15, description="镜头时长，单位秒。")
    purpose: str = Field(min_length=1, max_length=500, description="镜头承担的叙事或转化目的。")
    visual: str = Field(min_length=1, max_length=1000, description="需要生成或呈现的画面描述。")
    caption: str = Field(min_length=1, max_length=500, description="镜头对应的字幕或口播文本。")
    generation_mode: GenerationMode = Field(description="推荐的视频生成方式。")


class CreativeConcept(BaseModel):
    """描述一个完整且可独立审核的创意方向。"""

    concept_key: str = Field(
        min_length=1,
        max_length=64,
        description="方案内稳定且唯一的方向标识。",
    )
    title: str = Field(min_length=1, max_length=120, description="创意方向标题。")
    strategy: str = Field(min_length=1, max_length=1000, description="创意方向的整体表达策略。")
    hook: str = Field(
        min_length=1, max_length=500, description="前三秒吸引用户继续观看的开场表达。"
    )
    reasoning: str = Field(
        min_length=1,
        max_length=1000,
        description="该方向适合目标平台和人群的理由。",
    )
    primary_selling_point: str = Field(
        min_length=1,
        max_length=500,
        description="方案重点表达的核心卖点。",
    )
    target_audience: str = Field(
        min_length=1,
        max_length=500,
        description="方案面向的主要目标人群。",
    )
    call_to_action: str = Field(
        min_length=1,
        max_length=500,
        description="结尾给用户的克制行动建议。",
    )
    shots: list[ShotPlan] = Field(
        min_length=3,
        max_length=3,
        description="组成 15 秒视频的三个镜头计划。",
    )


def validate_plan_concepts(concepts: list[CreativeConcept]) -> None:
    """校验方案标识唯一，并要求镜头列表本身依次排列为 1、2、3。"""

    concept_keys = [concept.concept_key for concept in concepts]
    if len(set(concept_keys)) != len(concept_keys):
        raise ValueError("创意方案 concept_key 必须唯一。")
    for concept in concepts:
        if [shot.order for shot in concept.shots] != [1, 2, 3]:
            raise ValueError(f"创意方案 {concept.concept_key} 的镜头顺序必须依次为 1、2、3。")


class CreativePlanContent(BaseModel):
    """定义本地策略和外部模型共同生成的中性创意计划内容。"""

    decision_reason: str = Field(
        min_length=1,
        max_length=2000,
        description="选择当前三个方向的整体决策理由。",
    )
    confidence: float = Field(ge=0, le=1, description="草案决策置信度。")
    concepts: list[CreativeConcept] = Field(
        min_length=3,
        max_length=3,
        description="进入质量评估的三个差异化创意方向。",
    )

    @model_validator(mode="after")
    def validate_plan_structure(self) -> Self:
        """保证方案标识唯一，并让每套方案严格包含顺序为 1、2、3 的镜头。"""

        validate_plan_concepts(self.concepts)
        return self


class CreativeDraft(CreativePlanContent):
    """保存服务端商品分析与模型或本地创意组合后的完整草案。"""

    analysis: ProductAnalysis = Field(description="服务端确定性规则生成的商品分析。")
