"""实现 storyboard_prompt 节点：确认草案已经具备三镜头分镜结构。"""

from langgraph.types import Command

from app.agents.nodes import PROMPT_CHECK
from app.agents.state import AgentState, read_draft


def storyboard_prompt_node(state: AgentState) -> Command:
    """校验创意草案中的分镜结构，并进入 Prompt 检测节点。"""

    # CreativeDraft 的 Pydantic 契约已经要求每套方案都有 3 个镜头。
    read_draft(state)
    return Command(goto=PROMPT_CHECK)
