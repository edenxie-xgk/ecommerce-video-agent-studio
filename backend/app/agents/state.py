"""声明 LangGraph 持久化状态和运行时上下文。

读这个文件时关注一个分界：
- `AgentState` 保存本次图执行会流转的业务对象。
- `PlannerContext` 承载当前进程里的运行依赖，例如模型 Provider。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NotRequired, TypedDict

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.agents.modeling.provider import CreativeModelProvider
from app.application.creative_agent import (
    CreativeDecisionBundle,
    CreativeDraft,
    CreativeRunInput,
    ProductAnalysis,
    QualityEvaluation,
)


# ---------------------------------------------------------------------------
# 运行时依赖
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannerContext:
    """当前进程运行时使用的依赖。"""

    provider: CreativeModelProvider


# ---------------------------------------------------------------------------
# 可恢复状态：写入 LangGraph checkpoint
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    """LangGraph 状态；初始字段必填，阶段产物由对应节点逐步补充。"""

    # 业务输入来自应用层 DTO，是整条图执行的事实来源。
    run_input: CreativeRunInput  # 本次运行的完整输入。

    # 生成元数据随状态一起流转，用于最终投影业务运行结果。
    provider_key: str  # 完成创意脚本生成的 Provider 标识。
    model_key: str | None  # 完成创意脚本生成的模型标识。
    revision_count: int  # 当前自动质量修订次数。

    # 阶段产物由对应节点生成，后续节点直接读取业务模型对象。
    analysis: NotRequired[ProductAnalysis]  # product_understanding 产生的商品分析。
    draft: NotRequired[CreativeDraft]  # creative_script 产生的模型或本地草案。
    evaluation: NotRequired[QualityEvaluation]  # prompt_check 产生的质量评估。
    bundle: NotRequired[CreativeDecisionBundle]  # 对应用层和数据库公开的最终决策。


# ---------------------------------------------------------------------------
# Checkpoint 序列化
# ---------------------------------------------------------------------------


CHECKPOINT_MODEL_TYPES = (
    ("app.application.creative_agent_port", "CreativeRunInput"),
    ("app.application.creative_plan", "ProductAnalysis"),
    ("app.application.creative_plan", "CreativeDraft"),
    ("app.application.creative_decision", "QualityEvaluation"),
    ("app.application.creative_decision", "CreativeDecisionBundle"),
)


def build_checkpoint_serializer() -> JsonPlusSerializer:
    """创建允许恢复 AgentState 业务模型的 LangGraph 序列化器。"""

    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_MODEL_TYPES)
