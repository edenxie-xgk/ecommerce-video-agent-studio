"""构建供视频生成和人工审核共用的结构化分镜 Prompt。"""

from __future__ import annotations

from app.application.creative_agent import (
    CreativeAssetInput,
    CreativeDraft,
    CreativeRunInput,
    StoryboardConceptPrompt,
    StoryboardPromptBundle,
    StoryboardShotPrompt,
)


def build_storyboard_prompt_bundle(
    *,
    run_input: CreativeRunInput,
    draft: CreativeDraft,
) -> StoryboardPromptBundle:
    """把 CreativeDraft 中的三镜头脚本转换成稳定的视频生成 Prompt。"""

    product_assets = [
        asset for asset in run_input.assets if asset.asset_type == "product_image"
    ]
    asset_refs = [format_asset_reference(asset) for asset in product_assets]
    negative_prompt = build_global_negative_prompt(draft=draft)
    return StoryboardPromptBundle(
        product_summary=draft.analysis.product_summary,
        target_platform=run_input.project.target_platform,
        aspect_ratio=run_input.project.aspect_ratio,
        duration_seconds=run_input.project.duration_seconds,
        product_asset_refs=asset_refs,
        global_negative_prompt=negative_prompt,
        concepts=[
            StoryboardConceptPrompt(
                concept_key=concept.concept_key,
                title=concept.title,
                primary_selling_point=concept.primary_selling_point,
                target_audience=concept.target_audience,
                shot_prompts=[
                    StoryboardShotPrompt(
                        order=shot.order,
                        duration_seconds=shot.duration_seconds,
                        generation_mode=shot.generation_mode,
                        image_reference=select_image_reference(
                            shot_order=shot.order,
                            product_asset_refs=asset_refs,
                        ),
                        source_purpose=shot.purpose,
                        positive_prompt=build_positive_prompt(
                            run_input=run_input,
                            draft=draft,
                            concept_title=concept.title,
                            concept_strategy=concept.strategy,
                            shot_visual=shot.visual,
                            shot_order=shot.order,
                            shot_duration=shot.duration_seconds,
                            caption=shot.caption,
                        ),
                        negative_prompt=negative_prompt,
                        caption=shot.caption,
                    )
                    for shot in concept.shots
                ],
            )
            for concept in draft.concepts
        ],
    )


def build_positive_prompt(
    *,
    run_input: CreativeRunInput,
    draft: CreativeDraft,
    concept_title: str,
    concept_strategy: str,
    shot_visual: str,
    shot_order: int,
    shot_duration: int,
    caption: str,
) -> str:
    """拼出单镜头正向 Prompt，保留脚本来源和视频生成约束。"""

    product_name = draft.analysis.product_summary
    brand_tone = run_input.brief.brand_tone.strip() if run_input.brief else ""
    tone_clause = f"整体表达保持{brand_tone}。" if brand_tone else "整体表达真实克制。"
    platform_clause = platform_prompt_clause(run_input.project.target_platform)
    return (
        f"生成{run_input.project.aspect_ratio}竖屏短视频第{shot_order}镜头，"
        f"时长{shot_duration}秒。商品主体是{product_name}，保持主体清晰、比例稳定、"
        f"不要改变商品外观。方案标题：{concept_title}。表达策略：{concept_strategy}。"
        f"画面执行：{shot_visual}。{platform_clause}{tone_clause}"
        f"字幕安全区保留在画面下方，字幕或口播：{caption}"
    )


def build_global_negative_prompt(*, draft: CreativeDraft) -> str:
    """汇总全部镜头共同遵守的事实、画面和合规约束。"""

    constraints = [
        "不要改变商品颜色、形状、Logo、包装和关键可见结构。",
        "不要添加未确认的容量、材质、认证、排名、价格、功效或医疗表达。",
        "不要出现夸张承诺、绝对化用语、虚假对比和不可验证参数。",
        "不要遮挡商品主体，不要让字幕覆盖商品关键细节。",
    ]
    if draft.analysis.constraints:
        constraints.append("避免出现用户禁用表达：" + "、".join(draft.analysis.constraints) + "。")
    if draft.analysis.visual_uncertainties:
        constraints.append(
            "不要把以下不确定信息写成确定事实："
            + "、".join(draft.analysis.visual_uncertainties)
            + "。"
        )
    return "".join(constraints)


def platform_prompt_clause(target_platform: str) -> str:
    """返回目标平台对应的镜头节奏提示。"""

    if target_platform == "xiaohongshu":
        return "画面节奏自然，强调真实体验、细节质感和清晰信息密度。"
    return "画面节奏紧凑，前三秒信息明确，镜头运动轻快但不夸张。"


def format_asset_reference(asset: CreativeAssetInput) -> str:
    """把素材记录格式化成视频生成侧可追踪的图片引用。"""

    parts = [f"storage_key={asset.storage_key}", f"mime_type={asset.mime_type}"]
    if asset.id is not None:
        parts.insert(0, f"asset_id={asset.id}")
    return "; ".join(parts)


def select_image_reference(
    *,
    shot_order: int,
    product_asset_refs: list[str],
) -> str | None:
    """按镜头顺序稳定选择商品图片引用。"""

    if not product_asset_refs:
        return None
    return product_asset_refs[(shot_order - 1) % len(product_asset_refs)]
