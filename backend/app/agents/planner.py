"""实现应用层 CreativeAgentPort，并负责调用已编译的 LangGraph。"""

from __future__ import annotations

from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.graph import build_creative_graph
from app.agents.modeling.provider import CreativeModelProvider, OpenAICompatibleProvider
from app.agents.state import AgentState, PlannerContext, read_bundle
from app.application.creative_agent import (
    CreativeAgentResult,
    CreativeRunInput,
)


class CreativePlanner:
    """向业务服务公开的 LangGraph 创意决策入口。

    该类负责把应用 DTO 放进图状态，再把图产物投影成公开结果。
    """

    def __init__(
        self,
        provider: CreativeModelProvider | None = None,
        checkpointer: BaseCheckpointSaver[str] | None = None,
    ) -> None:
        """注入 Provider 和 checkpoint，并编译一次可复用的图。"""

        # Provider 是可替换依赖：生产环境走 OpenAI-compatible，测试可以注入假的 Provider。
        self._provider = provider or OpenAICompatibleProvider()
        # 图编译后可复用；checkpoint 决定状态存在内存还是 SQLite。
        self._graph = build_creative_graph(checkpointer or InMemorySaver())

    def run(
        self,
        run_input: CreativeRunInput,
        *,
        execution_id: str | None = None,
    ) -> CreativeAgentResult:
        """创建新图执行；传入 execution_id 时采用应用层生成的新运行标识。"""

        effective_execution_id = execution_id or uuid4().hex
        config = self._config(effective_execution_id)
        # 新运行使用新的 checkpoint 线程，保证业务运行之间状态独立。
        if self._graph.get_state(config).values:
            raise ValueError("execution_id 已存在运行状态；新运行必须使用新的标识。")
        state: AgentState = self._graph.invoke(
            {
                # 初始状态保存可持久化的业务输入快照。
                "project": run_input.project.model_dump(mode="json"),
                "brief": (run_input.brief.model_dump(mode="json") if run_input.brief else None),
                "assets": [asset.model_dump(mode="json") for asset in run_input.assets],
                "campaign_goal": run_input.campaign_goal,
                "provider_key": "local",
                "model_key": None,
                "revision_count": 0,
            },
            config,
            # Provider 通过运行时 Context 注入，随当前进程配置生效。
            context=PlannerContext(provider=self._provider),
        )
        return self._result_from_state(state, execution_id=effective_execution_id)

    def _config(self, execution_id: str) -> dict[str, dict[str, str]]:
        """在 Agent 内部把执行标识映射为 LangGraph 线程配置。"""

        # 业务层叫 execution_id，LangGraph 原生配置字段叫 thread_id。
        return {"configurable": {"thread_id": execution_id}}

    def _result_from_state(
        self,
        state: AgentState,
        *,
        execution_id: str,
    ) -> CreativeAgentResult:
        """校验最终 bundle，并投影业务层关心的运行元数据。"""

        bundle = read_bundle(state)
        return CreativeAgentResult(
            bundle=bundle,
            provider_key=str(state.get("provider_key") or "local"),
            model_key=state.get("model_key"),
            execution_id=execution_id,
        )
