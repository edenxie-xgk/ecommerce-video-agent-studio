"""实现 storyboard_prompt 节点：把创意脚本转换成视频生成 Prompt。

节点本身刻意保持很薄：分镜构造规则放在应用层的共享函数中，使首次图运行与用户编辑
后的复检能够复用同一套 Prompt 数据结构和素材引用约束。
"""

from __future__ import annotations

from langgraph.types import Command

from app.agents.nodes import PROMPT_CHECK
from app.agents.state import AgentState
from app.application.storyboard_prompts import build_storyboard_prompt_bundle


def storyboard_prompt_node(state: AgentState) -> Command:
    """根据已校验草案生成三套视频 Prompt，并进入质量检测节点。"""

    # 只读取前一节点写入的 run_input 与 draft；素材选择和负面约束由共享构造器处理。
    bundle = build_storyboard_prompt_bundle(
        run_input=state["run_input"],
        draft=state["draft"],
    )
    # 将可执行分镜写入状态，再由 prompt_check 同时审核脚本和视频生成指令。
    return Command(update={"storyboard_prompts": bundle}, goto=PROMPT_CHECK)
