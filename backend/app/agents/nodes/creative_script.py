"""实现 creative_script 节点：模型生成、重试分类和本地降级。"""

from __future__ import annotations

import re

from langgraph.errors import NodeError
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.agents.modeling.contracts import GeneratedCreativeDraft
from app.agents.modeling.generation import build_authoritative_draft
from app.agents.modeling.provider import ModelGenerationError
from app.agents.nodes import STORYBOARD_PROMPT
from app.agents.prompts import GENERATE_CREATIVE_DRAFT_PROMPT_REF, load_prompt_template
from app.agents.state import AgentState, PlannerContext
from app.application.creative_agent import (
    CreativeBriefInput,
    CreativeConcept,
    CreativeDraft,
    CreativeProjectInput,
    CreativeRunInput,
    ProductAnalysis,
    ShotPlan,
)


def creative_script_node(
    state: AgentState,
    runtime: Runtime[PlannerContext],
) -> Command:
    """根据当前 Provider 和已确认事实生成三套创意脚本草案。"""

    run_input = state["run_input"]
    analysis = state["analysis"]
    brief = run_input.brief
    selling_points = [
        part.strip(" -。.!！?？")
        for part in re.split(r"[\n,，、;；]+", brief.selling_points_text if brief else "")
        if part.strip(" -。.!！?？")
    ]
    if not runtime.context.provider.configured or not selling_points:
        # 本地策略使用已确认事实生成草案，适合模型配置缺失或卖点白名单为空的场景。
        return Command(
            update=_local_generation_update(run_input=run_input, analysis=analysis),
            goto=STORYBOARD_PROMPT,
        )

    prompt_template = load_prompt_template(GENERATE_CREATIVE_DRAFT_PROMPT_REF)
    response = runtime.context.provider.generate_json(
        system_prompt=prompt_template.system_prompt,
        input_payload=build_model_input(run_input, selling_points=selling_points),
        json_schema=GeneratedCreativeDraft.model_json_schema(),
    )
    draft = build_authoritative_draft(
        payload=response.payload,
        # 使用 product_understanding 节点产出的商品分析，保持商品事实来源统一。
        analysis=analysis,
        allowed_selling_points=selling_points,
    )
    return Command(
        update={
            "draft": draft,
            "provider_key": "openai_compatible",
            "model_key": response.model_key,
        },
        goto=STORYBOARD_PROMPT,
    )


def generation_error_handler(state: AgentState, error: NodeError) -> Command:
    """将已分类的模型错误降级为本地生成。"""

    if not isinstance(error.error, ModelGenerationError):
        # 程序错误继续向上抛出，保留真实失败原因。
        raise error.error
    return Command(
        update=_local_generation_update(
            run_input=state["run_input"],
            analysis=state["analysis"],
        ),
        goto=STORYBOARD_PROMPT,
    )


def _local_generation_update(
    *,
    run_input: CreativeRunInput,
    analysis: ProductAnalysis,
) -> dict[str, object]:
    """构造模型不可用或失败时的确定性草案状态。"""

    # 本地草案沿用 product_understanding 阶段的商品分析。
    draft = build_local_draft(
        project=run_input.project,
        brief=run_input.brief,
        analysis=analysis,
        campaign_goal=run_input.campaign_goal,
    )
    return {
        "draft": draft,
        "provider_key": "local",
        "model_key": None,
    }


def build_model_input(
    run_input: CreativeRunInput,
    *,
    selling_points: list[str],
) -> dict[str, object]:
    """构造 creative_script 节点发送给 Provider 的字段白名单。"""

    project = run_input.project
    brief = run_input.brief
    assets = run_input.assets
    target_audience = [
        part.strip(" -。.!！?？")
        for part in re.split(r"[\n,，、;；]+", brief.target_audience_text if brief else "")
        if part.strip(" -。.!！?？")
    ]
    forbidden_expressions = [
        part.strip(" -。.!！?？")
        for part in re.split(r"[\n,，、;；]+", brief.forbidden_words_text if brief else "")
        if part.strip(" -。.!！?？")
    ]
    # 外部模型接收当前创意任务需要的事实集合。
    return {
        "product_name": brief.product_name if brief else "",
        "selling_points": selling_points,
        "target_audience": target_audience,
        "brand_tone": brief.brand_tone if brief else "",
        "forbidden_expressions": forbidden_expressions,
        "target_platform": project.target_platform,
        "campaign_goal": run_input.campaign_goal,
        "duration_seconds": project.duration_seconds,
        "aspect_ratio": project.aspect_ratio,
        "product_image_count": len(assets),
        "product_asset_ids": [asset.id for asset in assets],
    }


def build_local_draft(
    *,
    project: CreativeProjectInput,
    brief: CreativeBriefInput | None,
    analysis: ProductAnalysis,
    campaign_goal: str,
) -> CreativeDraft:
    """在模型不可用时提供可解释、无额外成本的确定性方案。"""

    # 本地策略复用 product_understanding 节点的商品分析，生成稳定可解释的兜底方案。
    product_name = analysis.product_summary
    selling_points = analysis.inferred_selling_points
    audience = analysis.inferred_audience[0]
    tone = (brief.brand_tone if brief else "").strip()
    goal = campaign_goal.strip() or "让目标用户快速理解商品价值并产生进一步了解意愿"
    # 平台决定表达结构，商品事实来自 product_understanding 节点。
    concepts = (
        _xiaohongshu_concepts(product_name, selling_points, audience, tone)
        if project.target_platform == "xiaohongshu"
        else _douyin_concepts(product_name, selling_points, audience, tone)
    )
    return CreativeDraft(
        analysis=analysis,
        decision_reason=(
            f"围绕“{goal}”设计三个差异化方向，并优先用商品图片驱动关键镜头，"
            "降低包装和外观失真风险。"
        ),
        confidence=0.88 if brief and brief.selling_points_text else 0.78,
        concepts=concepts,
    )


def _douyin_concepts(
    product_name: str,
    selling_points: list[str],
    audience: str,
    tone: str,
) -> list[CreativeConcept]:
    """生成强调前三秒注意力和转化动作的抖音方案。"""

    # 三个方向共享同一批事实，但在叙事入口上拉开差异。
    primary = selling_points[0]
    # 卖点不足两个时复用主卖点，保持三个方向都引用已确认事实。
    secondary = selling_points[1] if len(selling_points) > 1 else primary
    return [
        _concept(
            key="pain-point",
            title="前三秒痛点切入",
            strategy="用具体使用困扰抢注意力，再用商品细节完成证明。",
            hook=f"还在为日常选择反复纠结？先看{product_name}解决了什么。",
            reasoning="抖音需要快速建立问题与商品之间的关系。",
            selling_point=primary,
            audience=audience,
            cta=f"点开了解{product_name}的更多细节。",
            product_name=product_name,
            tone=tone,
        ),
        _concept(
            key="product-proof",
            title="细节证明价值",
            strategy="把商品主体、关键细节和真实使用过程作为主要证据。",
            hook=f"15 秒看懂{product_name}值不值得关注。",
            reasoning="通过可见细节减少空泛口播，增强可信度。",
            selling_point=secondary,
            audience=audience,
            cta="先收藏，再根据自己的使用场景判断。",
            product_name=product_name,
            tone=tone,
        ),
        _concept(
            key="conversion",
            title="场景到行动",
            strategy="从目标用户的高频场景进入，最后给出清晰行动建议。",
            hook=f"如果你也是{audience}，这个使用场景值得看完。",
            reasoning="场景共鸣和明确 CTA 更适合转化导向素材。",
            selling_point=primary,
            audience=audience,
            cta=f"进入商品页，确认{product_name}是否适合你。",
            product_name=product_name,
            tone=tone,
        ),
    ]


def _xiaohongshu_concepts(
    product_name: str,
    selling_points: list[str],
    audience: str,
    tone: str,
) -> list[CreativeConcept]:
    """生成强调真实体验、细节和场景清单的小红书方案。"""

    # 小红书模板偏“体验/细节/场景”，表达保持克制。
    primary = selling_points[0]
    # 本地方案从已有卖点中组合表达。
    secondary = selling_points[1] if len(selling_points) > 1 else primary
    return [
        _concept(
            key="real-review",
            title="真实体验笔记",
            strategy="用第一人称体验表达，不做过度承诺。",
            hook=f"最近在用{product_name}，先说我最在意的一个细节。",
            reasoning="真实、克制的体验表达更符合小红书内容语境。",
            selling_point=primary,
            audience=audience,
            cta="收藏这条，选购时对照自己的需求。",
            product_name=product_name,
            tone=tone,
        ),
        _concept(
            key="detail-aesthetic",
            title="细节质感展示",
            strategy="以干净构图展示外观、材质和使用细节。",
            hook=f"{product_name}好不好用，先从这些细节看起。",
            reasoning="视觉质感和信息密度共同支撑种草判断。",
            selling_point=secondary,
            audience=audience,
            cta="需要同类商品时，可以把它加入备选。",
            product_name=product_name,
            tone=tone,
        ),
        _concept(
            key="scenario-list",
            title="适用场景清单",
            strategy="用三个高频场景解释商品适合谁、什么时候使用。",
            hook=f"这三种情况下，我会想到{product_name}。",
            reasoning="清单式结构便于用户快速对号入座。",
            selling_point=primary,
            audience=audience,
            cta="评论区说说你最常遇到的是哪个场景。",
            product_name=product_name,
            tone=tone,
        ),
    ]


def _concept(
    *,
    key: str,
    title: str,
    strategy: str,
    hook: str,
    reasoning: str,
    selling_point: str,
    audience: str,
    cta: str,
    product_name: str,
    tone: str,
) -> CreativeConcept:
    """把平台策略标准化为固定三镜头的可审核方案。"""

    normalized_tone = tone.strip(" -。.!！?？；;，,")
    tone_note = f"，保持{normalized_tone}的表达气质" if normalized_tone else ""
    # 固定 3/7/5 秒可以让本地方案天然满足当前 15 秒产品约束。
    # 三个镜头结构固定为：开场抓注意力 -> 商品证据 -> 行动建议。
    return CreativeConcept(
        concept_key=key,
        title=title,
        strategy=strategy,
        hook=hook,
        reasoning=reasoning,
        primary_selling_point=selling_point,
        target_audience=audience,
        call_to_action=cta,
        shots=[
            ShotPlan(
                order=1,
                duration_seconds=3,
                purpose="建立注意力和观看理由",
                visual=f"{product_name}主体快速进入画面，保留包装和外观细节{tone_note}",
                caption=hook,
                generation_mode="image_to_video",
            ),
            ShotPlan(
                order=2,
                duration_seconds=7,
                purpose="用可见证据解释核心价值",
                visual=f"{product_name}细节特写与真实使用动作，重点证明：{selling_point}",
                caption=f"重点看：{selling_point}",
                generation_mode="image_to_video",
            ),
            ShotPlan(
                order=3,
                duration_seconds=5,
                purpose="总结价值并引导下一步",
                visual=f"{product_name}完整商品镜头，画面留出字幕安全区",
                caption=cta,
                generation_mode="image_to_video",
            ),
        ],
    )
