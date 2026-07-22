"""实现 review_cost_gate 节点：封装最终审核结果和下一步动作。

它不重新评分也不再访问模型，而是将状态中已经完成的草案、分镜和质量结论收敛成应用
层可持久化、可展示的 ``CreativeDecisionBundle``。
"""

from typing import Any

from app.agents.state import AgentState
from app.application.creative_agent import CreativeDecisionBundle


def review_cost_gate_node(state: AgentState) -> dict[str, Any]:
    """把 Prompt Check 的质量结论封装为应用层可公开的决策结果。"""

    # 工厂方法根据 evaluation 决定下一步 action，并保留自动修订次数供审计与界面展示。
    bundle = CreativeDecisionBundle.from_draft_evaluation(
        draft=state["draft"],
        storyboard_prompts=state["storyboard_prompts"],
        evaluation=state["evaluation"],
        revision_count=state["revision_count"],
    )
    # StateGraph 会把返回字典合并进 AgentState，供 Planner 在图结束后读取。
    return {"bundle": bundle}
