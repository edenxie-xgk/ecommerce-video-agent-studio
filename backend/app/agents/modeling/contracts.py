"""声明仅用于外部模型 Provider 边界的结构化输出契约。

这些 Pydantic 模型是“模型响应的最小可接受形状”，并非最终业务对象。模型生成的卖点、
人群或声明仍是不可信候选值；节点会再使用用户确认的事实白名单完成校验和组装。
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.application.creative_plan import CreativePlanContent


class GeneratedCreativeDraft(CreativePlanContent):
    """定义外部模型可以生成的创意字段。

    复用内容结构而不继承完整 ``CreativeDraft``，是为了阻止模型伪造 analysis 等
    服务端拥有字段；完整草案只能由 ``build_authoritative_draft`` 创建。
    """


class GeneratedProductUnderstanding(BaseModel):
    """定义模型在商品理解阶段可以返回的字段。

    ``selected_*`` 只是从输入白名单中挑选可用于当前创意的一部分，不能创建新的商品
    卖点或用户人群；这一原样匹配约束在生成层再次强制执行。
    """

    # 类目是模型可以补充的表达性判断，不作为产品硬事实向外承诺。
    inferred_category: str = Field(
        min_length=1,
        max_length=200,
        description="根据商品名称、卖点、目标人群和素材引用推断的商品表达类别。",
    )
    # 卖点必须由调用节点提供的 selling_points 原样选出。
    selected_selling_points: list[str] = Field(
        min_length=1,
        max_length=8,
        description="从输入 selling_points 中原样选出的本轮创意可使用卖点。",
    )
    # 人群必须由调用节点提供的 target_audience 原样选出。
    selected_audience: list[str] = Field(
        min_length=1,
        max_length=8,
        description="从输入 target_audience 中原样选出的本轮创意目标人群。",
    )
    # 就绪度仅描述资料充分程度，范围固定为 0 到 100 便于后续评分使用。
    readiness_score: int = Field(
        ge=0,
        le=100,
        description="模型对当前资料进入创意规划的就绪度评分。",
    )
    # 只有实际发送了图片像素时，视觉观察才允许非空。
    visual_observations: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="仅根据已发送图片像素得到的可见事实；没有图片像素时必须为空。",
    )
    # 无法由图片确认的信息显式记录，以便后续文案避免把它写成事实。
    visual_uncertainties: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="图片无法确认或需要用户补充的信息，例如材质、容量、功效参数。",
    )
    # 严重冲突会阻止继续生成脚本，强制用户先修正商品资料。
    material_conflicts: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="图片可见事实与输入商品名称、卖点或目标使用场景直接冲突的问题。",
    )


class SemanticClaimAssessment(BaseModel):
    """描述语义审核从创意文案中提取的一条可验证商品声明。

    审核模型只能指向 ``confirmed_facts`` 提供的 evidence_key；服务端会复验声明文本是否
    和该证据值等值，防止模型以看似合理的键名为未经确认的陈述背书。
    """

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

    # 至少要求一项评估，避免模型返回空列表被错误当作“没有问题”。
    assessments: list[SemanticClaimAssessment] = Field(
        min_length=1,
        max_length=100,
        description="从全部方案和镜头文案中提取的商品声明审核结果。",
    )
