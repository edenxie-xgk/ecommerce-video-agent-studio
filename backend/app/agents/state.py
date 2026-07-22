"""声明 LangGraph 会持久化的 AgentState。

图中每个节点都接收同一个状态字典，并只追加或替换自己负责的阶段产物。
这里把跨节点约定集中定义，避免节点之间通过未声明的临时字段耦合。
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.application.creative_agent import (
    CreativeDecisionBundle,
    CreativeDraft,
    CreativeRunInput,
    ProductAnalysis,
    QualityEvaluation,
    StoryboardPromptBundle,
)


class AgentState(TypedDict):
    """LangGraph 状态；初始字段必填，阶段产物由对应节点逐步补充。"""

    # 业务输入来自应用层 DTO，是整条图执行的事实来源。
    run_input: CreativeRunInput  # 本次运行的完整输入。

    # 生成元数据随状态一起流转，用于最终投影业务运行结果。
    provider_key: str  # 完成创意脚本生成的 Provider 标识。
    model_key: str | None  # 完成创意脚本生成的模型标识。
    product_understanding_provider_key: str  # 完成商品理解的 Provider 标识。
    product_understanding_model_key: str | None  # 完成商品理解的模型标识。
    revision_count: int  # 当前自动质量修订次数。

    # 阶段产物由对应节点生成，后续节点直接读取业务模型对象。
    analysis: NotRequired[ProductAnalysis]  # product_understanding 产生的商品分析。
    draft: NotRequired[CreativeDraft]  # creative_script 产生的模型或本地草案。
    storyboard_prompts: NotRequired[StoryboardPromptBundle]  # storyboard_prompt 产生的视频指令。
    evaluation: NotRequired[QualityEvaluation]  # prompt_check 产生的质量评估。
    bundle: NotRequired[CreativeDecisionBundle]  # 对应用层和数据库公开的最终决策。


# LangGraph 的 JSONPlus 序列化器需要显式白名单，才能在 SQLite checkpoint 恢复这些
# Pydantic 业务对象；这里使用模块路径和类名，而不是直接引用类，以符合其配置格式。
CHECKPOINT_MODEL_TYPES = (
    ("app.application.creative_agent_port", "CreativeRunInput"),
    ("app.application.creative_plan", "ProductAnalysis"),
    ("app.application.creative_plan", "CreativeDraft"),
    ("app.application.creative_plan", "StoryboardShotPrompt"),
    ("app.application.creative_plan", "StoryboardConceptPrompt"),
    ("app.application.creative_plan", "StoryboardPromptBundle"),
    ("app.application.creative_decision", "QualityEvaluation"),
    ("app.application.creative_decision", "CreativeDecisionBundle"),
)


def build_checkpoint_serializer() -> JsonPlusSerializer:
    """创建允许恢复 AgentState 业务模型的 LangGraph 序列化器。

    checkpoint 中既包含普通标量，也包含应用层 Pydantic 模型。未经白名单注册的模型在
    恢复时会丢失类型信息，因此所有会写入状态的业务模型都必须列在上方元组中。
    """

    # 仅允许上方列出的应用模型参与 msgpack 恢复，缩小反序列化边界。
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_MODEL_TYPES)
