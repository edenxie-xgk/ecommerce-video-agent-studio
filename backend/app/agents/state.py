"""声明 LangGraph 持久化状态、运行时上下文和阶段产物读取方式。

读这个文件时关注一个分界：
- `AgentState` 会进入 checkpoint，因此字段必须是可 JSON 化、可恢复的快照。
- `PlannerContext` 承载当前进程里的运行依赖，例如模型 Provider。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

from app.agents.modeling.provider import CreativeModelProvider
from app.application.creative_agent import (
    CreativeDecisionBundle,
    CreativeDraft,
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

    # 输入快照来自应用层 DTO，checkpoint 重放时使用同一份业务输入。
    project: dict[str, Any]  # 项目事实快照。
    brief: dict[str, Any] | None  # 用户当前确认的商品资料快照。
    assets: list[dict[str, Any]]  # 已验证且可用于镜头规划的图片引用快照。
    campaign_goal: str  # 本次创意运行需要达成的营销目标。

    # 生成元数据也进 checkpoint，方便恢复后继续投影业务运行结果。
    provider_key: str  # 实际完成生成的 Provider 标识。
    model_key: str | None  # 实际完成生成的模型标识。
    revision_count: int  # 质量阶段已自动修订的次数，当前上限为一次。

    # 阶段产物用 dict 保存，读取时通过下面的 read_* 函数重新校验为 Pydantic 模型。
    analysis: NotRequired[dict[str, Any]]  # product_understanding 产生的商品分析。
    draft: NotRequired[dict[str, Any]]  # creative_script 产生的模型或本地草案。
    evaluation: NotRequired[dict[str, Any]]  # prompt_check 产生的质量评估。
    bundle: NotRequired[dict[str, Any]]  # 对应用层和数据库公开的最终决策。


# ---------------------------------------------------------------------------
# 阶段产物读取：dict -> 业务模型
# ---------------------------------------------------------------------------


def read_analysis(state: AgentState) -> ProductAnalysis:
    """读取商品分析阶段产物，并把 checkpoint dict 重新校验成业务模型。"""

    return ProductAnalysis.model_validate(state["analysis"])


def read_draft(state: AgentState) -> CreativeDraft:
    """读取创意生成阶段产物，并校验为当前草案契约。"""

    return CreativeDraft.model_validate(state["draft"])


def read_evaluation(state: AgentState) -> QualityEvaluation:
    """读取 Prompt Check 评估产物，并校验为质量门禁契约。"""

    return QualityEvaluation.model_validate(state["evaluation"])


def read_bundle(state: AgentState) -> CreativeDecisionBundle:
    """读取最终决策阶段产物，作为返回 API 和写入数据库前的最后一道校验。"""

    return CreativeDecisionBundle.model_validate(state["bundle"])
