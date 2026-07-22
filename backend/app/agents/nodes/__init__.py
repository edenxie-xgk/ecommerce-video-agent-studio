"""声明创意工作流节点名称，名称保持和工作流文档一致。

这些常量既是 LangGraph 中稳定的节点 ID，也用于节点 ``Command.goto`` 跳转；不要把
展示文案直接作为 ID，以免文案调整导致已持久化的图状态无法对应。
"""

PRODUCT_UNDERSTANDING = "product_understanding"  # 商品理解节点：生成 ProductAnalysis。
CREATIVE_SCRIPT = "creative_script"  # 脚本节点：生成三套创意方向和镜头计划。
STORYBOARD_PROMPT = "storyboard_prompt"  # 分镜 Prompt 节点：确认脚本已具备镜头结构。
PROMPT_CHECK = "prompt_check"  # Prompt 检测节点：执行质量和风险评估，可自动修订一次。
REVIEW_COST_GATE = "review_cost_gate"  # 审核门禁节点：形成面向用户的最终动作。

__all__ = [
    "CREATIVE_SCRIPT",
    "PROMPT_CHECK",
    "PRODUCT_UNDERSTANDING",
    "REVIEW_COST_GATE",
    "STORYBOARD_PROMPT",
]
