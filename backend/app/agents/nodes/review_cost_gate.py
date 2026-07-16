"""实现 review_cost_gate 节点：封装最终审核结果和下一步动作。"""

from typing import Any

from app.agents.state import AgentState
from app.application.creative_agent import CreativeDecisionBundle


def review_cost_gate_node(state: AgentState) -> dict[str, Any]:
    """把 Prompt Check 的质量结论封装为应用层可公开的决策结果。"""

    bundle = CreativeDecisionBundle.from_draft_evaluation(
        draft=state["draft"],
        evaluation=state["evaluation"],
        revision_count=state["revision_count"],
    )
    return {"bundle": bundle}
