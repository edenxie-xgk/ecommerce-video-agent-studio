"""实现 product_understanding 节点：生成服务端权威商品分析。"""

from langgraph.types import Command

from app.agents.nodes import CREATIVE_SCRIPT
from app.agents.rules.analysis import (
    analyze_product,
    restore_inputs,
)
from app.agents.state import AgentState


def product_understanding_node(state: AgentState) -> Command:
    """校验输入快照，生成商品理解结果。"""

    project, brief, assets = restore_inputs(state)
    analysis = analyze_product(project, brief, assets)
    if analysis.missing_information:
        # 端口直调时保留硬门槛校验，返回明确的输入缺失原因。
        raise ValueError("Agent 输入资料不完整：" + "、".join(analysis.missing_information))

    # 商品分析写入状态后，交给 creative_script 节点制定创意草案。
    return Command(
        update={"analysis": analysis.model_dump(mode="json")},
        goto=CREATIVE_SCRIPT,
    )

