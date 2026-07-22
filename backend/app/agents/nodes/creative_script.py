"""实现 creative_script 节点：模型生成、重试分类和本地降级。

创意脚本只消费已经通过商品理解阶段校验的 ``ProductAnalysis``。外部模型可提供表达和
镜头创意，但服务端会把生成结果重新绑定到已确认卖点、人群、禁词和视觉不确定项。
"""

from __future__ import annotations

from langgraph.errors import NodeError
from langgraph.types import Command

from app.agents.modeling.contracts import GeneratedCreativeDraft
from app.agents.modeling.generation import build_authoritative_draft
from app.agents.modeling.provider import ModelGenerationError
from app.agents.models import config_model
from app.agents.nodes import STORYBOARD_PROMPT
from app.agents.prompts import GENERATE_CREATIVE_DRAFT_PROMPT_REF, load_prompt_template
from app.agents.state import AgentState
from app.application.creative_agent import (
    CreativeBriefInput,
    CreativeConcept,
    CreativeDraft,
    CreativeProjectInput,
    CreativeRunInput,
    ProductAnalysis,
    ShotPlan,
)


def creative_script_node(state: AgentState) -> Command:
    """根据当前 Provider 和已确认事实生成三套创意脚本草案。"""

    # run_input 用于平台和项目规格；analysis 是上一阶段已校验的商品证据包。
    run_input = state["run_input"]
    analysis = state["analysis"]
    if analysis.material_conflicts:
        # 商品理解阶段发现资料冲突时，停止进入脚本生成，等待用户修正输入。
        raise ValueError(
            "商品图片与商品资料存在冲突，已停止生成脚本。请先修正资料或更换图片："
            + "；".join(analysis.material_conflicts)
        )
    # selling_points 同时决定模型能否生成、以及本地草案可使用的事实集合。
    brief = run_input.brief
    selling_points = brief.selling_points() if brief else []
    # 使用文本模型；商品图片的可见信息已经浓缩在 analysis 中。
    provider = config_model.creative_script_model()
    if not provider.configured or not selling_points:
        # 本地策略使用已确认事实生成草案，适合模型配置缺失的场景。
        return Command(
            update=_local_generation_update(run_input=run_input, analysis=analysis),
            goto=STORYBOARD_PROMPT,
        )

    # 模板定义创意输出结构与平台语境，业务字段由 build_model_input 明确筛选。
    prompt_template = load_prompt_template(GENERATE_CREATIVE_DRAFT_PROMPT_REF)
    response = provider.generate_json(
        system_prompt=prompt_template.system_prompt,
        input_payload=build_model_input(
            run_input,
            analysis=analysis,
            selling_points=selling_points,
        ),
        json_schema=GeneratedCreativeDraft.model_json_schema(),
    )
    # 不直接信任 response.payload；先验证候选内容没有越过用户确认的事实边界。
    draft = build_authoritative_draft(
        payload=response.payload,
        # 使用 product_understanding 节点产出的商品分析，保持商品事实来源统一。
        analysis=analysis,
        allowed_selling_points=selling_points,
        allowed_audience=brief.target_audiences() if brief else [],
        forbidden_words=analysis.constraints,
        uncertain_visual_facts=analysis.visual_uncertainties,
    )
    # 记录真实模型名，最终结果可说明本次草案的来源和降级情况。
    return Command(
        update={
            "draft": draft,
            "provider_key": "openai_compatible",
            "model_key": response.model_key,
        },
        goto=STORYBOARD_PROMPT,
    )


def generation_error_handler(state: AgentState, error: NodeError) -> Command:
    """将已分类的模型错误降级为本地生成。

    此回调由 LangGraph 在图内重试耗尽后调用。只有 Provider 明确分类过的失败才允许本地
    兜底，避免把代码缺陷、状态损坏等问题隐藏成看似成功的草案。
    """

    if not isinstance(error.error, ModelGenerationError):
        # 程序错误继续向上抛出，保留真实失败原因。
        raise error.error
    # 与正常路径相同地写入 draft 和来源字段，保证下游无需区分异常来源。
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
    # 明确把来源标为 local，语义审核和界面据此区分外部模型输出。
    return {
        "draft": draft,
        "provider_key": "local",
        "model_key": None,
    }


def build_model_input(
    run_input: CreativeRunInput,
    *,
    analysis: ProductAnalysis,
    selling_points: list[str],
) -> dict[str, object]:
    """构造 creative_script 节点发送给 Provider 的字段白名单。

    此处通过重组字典而不是直接 dump ``run_input``，避免内部字段、存储路径或未确认数据
    被意外发送给外部模型，也让模型可见上下文保持可审计。
    """

    # 将嵌套 DTO 取到局部变量，便于下方只暴露真正需要的字段。
    project = run_input.project
    brief = run_input.brief
    assets = run_input.assets
    target_audience = brief.target_audiences() if brief else []
    forbidden_expressions = brief.forbidden_words() if brief else []
    # 外部模型接收当前创意任务需要的事实集合。
    return {
        "product_name": analysis.product_summary,
        "selling_points": selling_points,
        "target_audience": target_audience,
        "brand_tone": brief.brand_tone if brief else "",
        "forbidden_expressions": forbidden_expressions,
        # product_analysis 是 PRODUCT_UNDERSTANDING 对后续创意节点的证据交接包。
        "product_analysis": {
            "inferred_category": analysis.inferred_category,
            "selected_selling_points": analysis.inferred_selling_points,
            "selected_audience": analysis.inferred_audience,
            "visual_evidence_count": analysis.visual_evidence_count,
            "visual_observations": analysis.visual_observations,
            "visual_uncertainties": analysis.visual_uncertainties,
            "material_conflicts": analysis.material_conflicts,
            "readiness_score": analysis.readiness_score,
        },
        "target_platform": project.target_platform,
        "campaign_goal": run_input.campaign_goal,
        "duration_seconds": project.duration_seconds,
        "aspect_ratio": project.aspect_ratio,
        # 图片数量仅供模型理解素材充分程度；像素并不在该文本模型调用中传输。
        "product_image_count": len(
            [asset for asset in assets if asset.asset_type == "product_image"]
        ),
        "product_asset_ids": [asset.id for asset in assets if asset.asset_type == "product_image"],
    }


def build_local_draft(
    *,
    project: CreativeProjectInput,
    brief: CreativeBriefInput | None,
    analysis: ProductAnalysis,
    campaign_goal: str,
) -> CreativeDraft:
    """在模型不可用时提供可解释、无额外成本的确定性方案。

    本地策略不追求语言多样性，而以固定结构确保商品露出、已确认卖点和 CTA 均可被后续
    质量门禁验证；因此它是可预测的服务降级，而不是第二个不可控模型。
    """

    # 本地策略复用 product_understanding 节点的商品分析，生成稳定可解释的兜底方案。
    # 仅从上游 analysis 读取商品事实，绝不根据 campaign_goal 推断产品属性。
    product_name = analysis.product_summary
    selling_points = analysis.inferred_selling_points
    audience = analysis.inferred_audience[0]
    tone = (brief.brand_tone if brief else "").strip()
    # 目标可为空；使用中性默认值避免把空字符串插入用户可见决策理由。
    goal = campaign_goal.strip() or "让目标用户快速理解商品价值并产生进一步了解意愿"
    visual_evidence = _local_visual_evidence(analysis)
    # 将 0-100 就绪度压入保守的本地置信区间，不宣称达到外部模型级别的确定性。
    confidence = max(0.55, min(0.88, analysis.readiness_score / 100))
    if analysis.visual_uncertainties:
        # 图片仍有无法确认的信息时，本地草案降低置信度并保持克制表达。
        confidence = max(0.55, confidence - 0.05)
    # 平台决定表达结构，商品事实来自 product_understanding 节点。
    concepts = (
        _xiaohongshu_concepts(product_name, selling_points, audience, tone, visual_evidence)
        if project.target_platform == "xiaohongshu"
        else _douyin_concepts(product_name, selling_points, audience, tone, visual_evidence)
    )
    # 任何平台分支最后都输出同一 CreativeDraft 契约，供分镜与质量节点统一消费。
    return CreativeDraft(
        analysis=analysis,
        decision_reason=(
            f"围绕“{goal}”设计三个差异化方向，镜头只引用已确认卖点和图片可见事实。"
        ),
        confidence=round(confidence, 2),
        concepts=concepts,
    )


def _local_visual_evidence(analysis: ProductAnalysis) -> str:
    """把商品理解中的图片事实压缩成本地镜头可直接使用的一句话。"""

    # 只用图片数量构造泛化描述，不把缺少视觉证据的内容虚构成商品特性。
    image_label = "多张商品图" if analysis.visual_evidence_count > 1 else "商品主图"
    # 本地镜头只取前两个可见事实，保持画面描述短而稳。
    visible_facts = "、".join(analysis.visual_observations[:2])
    if visible_facts:
        return f"{image_label}展示{visible_facts}"
    return f"{image_label}保持商品主体清晰可见"


def _douyin_concepts(
    product_name: str,
    selling_points: list[str],
    audience: str,
    tone: str,
    visual_evidence: str,
) -> list[CreativeConcept]:
    """生成强调前三秒注意力和转化动作的抖音方案。"""

    # 三个方向共享同一批事实，但在叙事入口上拉开差异。
    primary = selling_points[0]
    # 卖点不足两个时复用主卖点，保持三个方向都引用已确认事实。
    secondary = selling_points[1] if len(selling_points) > 1 else primary
    # 顺序固定为痛点、证据、转化，且 concept_key 会被后续分镜编辑复检作为稳定身份。
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
            visual_evidence=visual_evidence,
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
            visual_evidence=visual_evidence,
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
            visual_evidence=visual_evidence,
        ),
    ]


def _xiaohongshu_concepts(
    product_name: str,
    selling_points: list[str],
    audience: str,
    tone: str,
    visual_evidence: str,
) -> list[CreativeConcept]:
    """生成强调真实体验、细节和场景清单的小红书方案。"""

    # 小红书模板偏“体验/细节/场景”，表达保持克制。
    primary = selling_points[0]
    # 本地方案从已有卖点中组合表达。
    secondary = selling_points[1] if len(selling_points) > 1 else primary
    # 顺序固定为体验、细节、场景，确保同一输入每次本地降级都产生可预测结果。
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
            visual_evidence=visual_evidence,
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
            visual_evidence=visual_evidence,
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
            visual_evidence=visual_evidence,
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
    visual_evidence: str,
) -> CreativeConcept:
    """把平台策略标准化为固定三镜头的可审核方案。"""

    # 清除用户输入结尾常见标点，避免拼接到镜头描述时出现重复符号。
    normalized_tone = tone.strip(" -。.!！?？；;，,")
    tone_note = f"，保持{normalized_tone}的表达气质" if normalized_tone else ""
    # 固定 3/7/5 秒可以让本地方案天然满足当前 15 秒产品约束。
    # 三个镜头结构固定为：开场抓注意力 -> 商品证据 -> 行动建议。
    # 顶层概念字段同时用于用户展示和 prompt_check 的风险扫描。
    return CreativeConcept(
        concept_key=key,
        title=title,
        strategy=strategy,
        hook=hook,
        reasoning=reasoning,
        primary_selling_point=selling_point,
        target_audience=audience,
        call_to_action=cta,
        # ``image_to_video`` 强制三镜均以已上传商品图为基础，分镜构造器会分配实际引用。
        shots=[
            ShotPlan(
                order=1,
                duration_seconds=3,
                purpose="建立注意力和观看理由",
                visual=f"{visual_evidence}，{product_name}主体快速进入画面{tone_note}",
                caption=hook,
                generation_mode="image_to_video",
            ),
            ShotPlan(
                order=2,
                duration_seconds=7,
                purpose="用可见证据解释核心价值",
                visual=f"{visual_evidence}，细节特写重点证明：{selling_point}",
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
