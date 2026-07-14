"""注册创意工作流的自动运行段拓扑和执行策略。"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.agents.modeling.provider import RetryableModelGenerationError
from app.agents.nodes import (
    CREATIVE_SCRIPT,
    PRODUCT_UNDERSTANDING,
    PROMPT_CHECK,
    REVIEW_COST_GATE,
    STORYBOARD_PROMPT,
)
from app.agents.nodes.product_understanding import product_understanding_node
from app.agents.nodes.creative_script import creative_script_node, generation_error_handler
from app.agents.nodes.prompt_check import prompt_check_node
from app.agents.nodes.review_cost_gate import review_cost_gate_node
from app.agents.nodes.storyboard_prompt import storyboard_prompt_node
from app.agents.state import AgentState, PlannerContext


def build_creative_graph(checkpointer: BaseCheckpointSaver[str]):
    """编译商品理解、脚本、分镜、Prompt 检测和审核门禁自动节点。"""

    graph = StateGraph(AgentState, context_schema=PlannerContext)
    # 商品理解生成 ProductAnalysis，作为后续脚本和审核判断的事实基础。
    graph.add_node(
        PRODUCT_UNDERSTANDING,
        product_understanding_node,
        destinations=(CREATIVE_SCRIPT,),
    )
    # 脚本节点配置模型错误重试，并在可分类失败时回落到本地确定性草案。
    graph.add_node(
        CREATIVE_SCRIPT,
        creative_script_node,
        retry_policy=RetryPolicy(
            max_attempts=2,
            retry_on=(RetryableModelGenerationError,),
        ),
        error_handler=generation_error_handler,
        destinations=(STORYBOARD_PROMPT,),
    )
    # 分镜 Prompt 节点确认草案已具备三镜头结构。
    graph.add_node(STORYBOARD_PROMPT, storyboard_prompt_node, destinations=(PROMPT_CHECK,))
    # Prompt Check 节点完成质量评估和一次自动修订。
    graph.add_node(PROMPT_CHECK, prompt_check_node, destinations=(REVIEW_COST_GATE,))
    # 审核门禁节点封装最终决策。
    graph.add_node(REVIEW_COST_GATE, review_cost_gate_node)

    # 当前自动段：商品理解 -> 脚本 -> 分镜 Prompt -> Prompt Check -> Review Gate。
    graph.add_edge(START, PRODUCT_UNDERSTANDING)
    graph.add_edge(REVIEW_COST_GATE, END)
    return graph.compile(checkpointer=checkpointer, name="commerce_creative_agent")

