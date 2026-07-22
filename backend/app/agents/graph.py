"""注册创意工作流的自动运行段拓扑和执行策略。

本模块只声明 LangGraph 编排，不承担商品理解、文案生成或质量判断。节点之间的
阶段跳转由 ``Command.goto`` 明确给出，图上的边只定义自动流程的入口和终点。
"""

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
from app.agents.nodes.creative_script import creative_script_node, generation_error_handler
from app.agents.nodes.product_understanding import product_understanding_node
from app.agents.nodes.prompt_check import prompt_check_node
from app.agents.nodes.review_cost_gate import review_cost_gate_node
from app.agents.nodes.storyboard_prompt import storyboard_prompt_node
from app.agents.state import AgentState


def build_creative_graph(checkpointer: BaseCheckpointSaver[str]):
    """编译商品理解、脚本、分镜、Prompt 检测和审核门禁自动节点。

    参数 ``checkpointer`` 由运行时提供。开发测试可使用内存实现，正式应用使用
    SQLite；图定义保持一致，因而节点无需感知状态的存储位置。
    """

    # StateGraph 以 AgentState 约束每个节点读取和写入的共享状态结构。
    graph = StateGraph(AgentState)
    # 商品理解在模型未配置时使用本地事实整理；模型已配置但调用失败时交给请求层提示重试。
    graph.add_node(
        PRODUCT_UNDERSTANDING,
        product_understanding_node,
        # 只有临时 Provider 错误才值得在图内重试；输入/契约错误应立即暴露。
        retry_policy=RetryPolicy(
            max_attempts=2,
            retry_on=(RetryableModelGenerationError,),
        ),
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
        # 可分类的脚本模型错误会转为本地确定性草案，其他程序错误继续失败。
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
    # 节点内部通过 Command.goto 串联中间阶段；显式边只固定图的总入口和总出口。
    graph.add_edge(START, PRODUCT_UNDERSTANDING)
    graph.add_edge(REVIEW_COST_GATE, END)
    return graph.compile(checkpointer=checkpointer, name="commerce_creative_agent")


