"""实现 creative_script 节点：模型生成、重试分类和地地降级。"""

from langgraph.errors import NodeError
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.agents.modeling.contracts import GeneratedCreativeDraft
from app.agents.modeling.generation import build_authoritative_draft
from app.agents.modeling.provider import ModelGenerationError
from app.agents.nodes import STORYBOARD_PROMPT
from app.agents.prompts import GENERATE_CREATIVE_DRAFT_PROMPT_REF, load_prompt_template
from app.agents.rules.analysis import (
    build_model_input,
    confirmed_selling_points,
    restore_inputs,
)
from app.agents.rules.drafts import build_local_draft
from app.agents.state import AgentState, PlannerContext, read_analysis


def creative_script_node(
    state: AgentState,
    runtime: Runtime[PlannerContext],
) -> Command:
    """根据当前 Provider 和已确认事实生成三套创意脚地草案。"""

    project, brief, assets = restore_inputs(state)
    selling_points = confirmed_selling_points(brief)
    if not runtime.context.provider.configured or not selling_points:
        # 地地策略使用已确认事实生成草案，适合模型配置缺失或卖点白名单为空的场景。
        return Command(update=_local_generation_update(state), goto=STORYBOARD_PROMPT)

    prompt_template = load_prompt_template(GENERATE_CREATIVE_DRAFT_PROMPT_REF)
    response = runtime.context.provider.generate_json(
        system_prompt=prompt_template.system_prompt,
        input_payload=build_model_input(
            project=project,
            brief=brief,
            assets=assets,
            campaign_goal=state["campaign_goal"],
        ),
        json_schema=GeneratedCreativeDraft.model_json_schema(),
    )
    draft = build_authoritative_draft(
        payload=response.payload,
        # 使用 product_understanding 节点产出的商品分析，保持商品事实来源统一。
        analysis=read_analysis(state),
        confirmed_selling_points=selling_points,
    )
    return Command(
        update={
            "draft": draft.model_dump(mode="json"),
            "provider_key": "openai_compatible",
            "model_key": response.model_key,
        },
        goto=STORYBOARD_PROMPT,
    )


def generation_error_handler(state: AgentState, error: NodeError) -> Command:
    """将已分类的模型错误降级为地地生成。"""

    if not isinstance(error.error, ModelGenerationError):
        # 程序错误继续向上抛出，保留真实失败原因。
        raise error.error
    return Command(update=_local_generation_update(state), goto=STORYBOARD_PROMPT)


def _local_generation_update(state: AgentState) -> dict[str, object]:
    """构造模型不可用或失败时的确定性草案状态。"""

    project, brief, _ = restore_inputs(state)
    # 地地草案沿用 analyze 阶段的商品分析。
    draft = build_local_draft(
        project=project,
        brief=brief,
        analysis=read_analysis(state),
        campaign_goal=state["campaign_goal"],
    )
    return {
        "draft": draft.model_dump(mode="json"),
        "provider_key": "local",
        "model_key": None,
    }



