"""实现 storyboard_prompt 节点：确认草案已经具备三镜头分镜结构。"""

from langgraph.types import Command

from app.agents.nodes import PROMPT_CHECK
from app.agents.state import AgentState


def storyboard_prompt_node(state: AgentState) -> Command:
    """进入 Prompt 检测节点。"""

    return Command(goto=PROMPT_CHECK)
