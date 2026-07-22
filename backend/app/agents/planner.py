"""实现应用层 CreativeAgentPort，并负责调用已编译的 LangGraph。

``CreativePlanner`` 是应用服务与 Agent 实现之间的适配器：应用层只看见输入、最终
决策和执行标识，不需要依赖 LangGraph 的状态、线程配置或 checkpoint API。
"""

from __future__ import annotations

from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.graph import build_creative_graph
from app.agents.nodes.prompt_check import review_storyboard_prompt_bundle
from app.agents.state import AgentState, build_checkpoint_serializer
from app.application.creative_agent import (
    CreativeAgentResult,
    CreativeRunInput,
    CreativeDecisionBundle,
    StoryboardPromptBundle,
)


class CreativePlanner:
    """向业务服务公开的 LangGraph 创意决策入口。

    该类负责把应用 DTO 放进图状态，再把图产物投影成公开结果。
    """

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver[str] | None = None,
    ) -> None:
        """注入 checkpoint，并编译一次可复用的图。

        Provider 由节点按当前 Settings 延迟取得；构造函数只决定图状态如何保存。
        """

        # 图编译后可复用；checkpoint 决定状态存在内存还是 SQLite。
        self._graph = build_creative_graph(
            checkpointer or InMemorySaver(serde=build_checkpoint_serializer())
        )

    def run(
        self,
        run_input: CreativeRunInput,
        *,
        execution_id: str | None = None,
    ) -> CreativeAgentResult:
        """创建新图执行；传入 execution_id 时采用应用层生成的新运行标识。"""

        # 先在图外阻断资料不完整的运行，避免产生只执行到中途的 checkpoint。
        self._assert_ready_for_agent(run_input)
        # 未传入标识时生成一次性线程 ID；调用方传入时通常用于持久化业务运行关联。
        effective_execution_id = execution_id or uuid4().hex
        config = self._config(effective_execution_id)
        # 新运行使用新的 checkpoint 线程，保证业务运行之间状态独立。
        if self._graph.get_state(config).values:
            raise ValueError("execution_id 已存在运行状态；新运行必须使用新的标识。")
        # 仅写入图运行必须的初始值。后续 analysis/draft/evaluation 由对应节点追加。
        state: AgentState = self._graph.invoke(
            {
                # 初始状态保存本次运行的业务输入。
                "run_input": run_input,
                "provider_key": "local",
                "model_key": None,
                "product_understanding_provider_key": "local",
                "product_understanding_model_key": None,
                "revision_count": 0,
            },
            config,
        )
        # 不把整个内部状态泄漏给应用层，只投影它真正需要的结果和模型元数据。
        return self._result_from_state(state, execution_id=effective_execution_id)

    def _config(self, execution_id: str) -> dict[str, dict[str, str]]:
        """在 Agent 内部把执行标识映射为 LangGraph 线程配置。"""

        # 业务层叫 execution_id，LangGraph 原生配置字段叫 thread_id。
        return {"configurable": {"thread_id": execution_id}}

    def review_storyboard_prompts(
        self,
        *,
        decision: CreativeDecisionBundle,
        storyboard_prompts: StoryboardPromptBundle,
        require_semantic_review: bool = False,
    ) -> CreativeDecisionBundle:
        """复检用户编辑后的分镜 Prompt，不重新运行商品理解和创意脚本节点。"""

        # 人工改 Prompt 属于已有决策的复检，因此刻意跳过商品理解和创意脚本生成。
        return review_storyboard_prompt_bundle(
            decision=decision,
            storyboard_prompts=storyboard_prompts,
            require_semantic_review=require_semantic_review,
        )

    def _assert_ready_for_agent(self, run_input: CreativeRunInput) -> None:
        """检查直接调用端口时需要满足的启动硬门槛。"""

        # 由输入 DTO 统一维护必填规则，避免 Agent 与 API 层出现两套判断。
        missing = run_input.missing_required_agent_inputs()
        if missing:
            raise ValueError("Agent 输入资料不完整：" + "、".join(missing))

    def _result_from_state(
        self,
        state: AgentState,
        *,
        execution_id: str,
    ) -> CreativeAgentResult:
        """投影业务层关心的运行元数据。"""

        # ``bundle`` 是门禁节点承诺一定产出的字段；缺失时保留 KeyError 以暴露图错误。
        return CreativeAgentResult(
            bundle=state["bundle"],
            provider_key=str(state.get("provider_key") or "local"),
            model_key=state.get("model_key"),
            product_understanding_provider_key=str(
                state.get("product_understanding_provider_key") or "local"
            ),
            product_understanding_model_key=state.get("product_understanding_model_key"),
            execution_id=execution_id,
        )

