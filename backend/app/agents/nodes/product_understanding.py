"""实现 product_understanding 节点：生成可追溯的商品理解。"""

from __future__ import annotations

import base64
from pathlib import Path

from langgraph.errors import NodeError
from langgraph.types import Command

from app.agents.modeling.contracts import GeneratedProductUnderstanding
from app.agents.modeling.generation import (
    build_authoritative_analysis,
    build_input_based_analysis,
)
from app.agents.modeling.provider import ModelGenerationError, ModelImageInput
from app.agents.models import config_model
from app.agents.nodes import CREATIVE_SCRIPT
from app.agents.prompts import ANALYZE_PRODUCT_PROMPT_REF, load_prompt_template
from app.agents.state import AgentState
from app.application.creative_agent import CreativeAssetInput
from app.core.config import BACKEND_ROOT, get_settings


def product_understanding_node(state: AgentState) -> Command:
    """用模型理解商品资料，并把通过服务端校验的结果写入状态。"""

    run_input = state["run_input"]
    provider = config_model.product_understanding_model()
    if not provider.configured:
        return Command(
            update={
                "analysis": build_input_based_analysis(run_input),
                "product_understanding_provider_key": "local",
                "product_understanding_model_key": None,
            },
            goto=CREATIVE_SCRIPT,
        )

    brief = run_input.brief
    if brief is None:
        raise ValueError("商品资料缺失，不能执行商品理解节点。")

    image_inputs = build_product_image_inputs(run_input.assets)
    product_assets = [
        {
            "asset_id": asset.id,
            "storage_key": asset.storage_key,
            "mime_type": asset.mime_type,
            "size_bytes": asset.size_bytes,
            "metadata": asset.asset_metadata,
            "visual_input_included": any(
                image.label == f"asset_id={asset.id}; storage_key={asset.storage_key}"
                for image in image_inputs
            ),
        }
        for asset in run_input.assets
        if asset.asset_type == "product_image"
    ]
    prompt_template = load_prompt_template(ANALYZE_PRODUCT_PROMPT_REF)
    response = provider.generate_json(
        system_prompt=prompt_template.system_prompt,
        input_payload={
            "product_name": brief.product_name.strip(),
            "selling_points": brief.selling_points(),
            "target_audience": brief.target_audiences(),
            "brand_tone": brief.brand_tone.strip(),
            "forbidden_expressions": brief.forbidden_words(),
            "target_platform": run_input.project.target_platform,
            "campaign_goal": run_input.campaign_goal,
            "duration_seconds": run_input.project.duration_seconds,
            "product_assets": product_assets,
            "visual_input_count": len(image_inputs),
        },
        json_schema=GeneratedProductUnderstanding.model_json_schema(),
        image_inputs=image_inputs,
    )
    analysis = build_authoritative_analysis(
        payload=response.payload,
        run_input=run_input,
        image_input_count=len(image_inputs),
    )
    return Command(
        update={
            "analysis": analysis,
            "product_understanding_provider_key": "openai_compatible",
            "product_understanding_model_key": response.model_key,
        },
        goto=CREATIVE_SCRIPT,
    )


def build_product_image_inputs(assets: list[CreativeAssetInput]) -> list[ModelImageInput]:
    """把已上传商品图读取为多模态模型可接收的图片输入。"""

    settings = get_settings()
    storage_root = Path(settings.asset_storage_path).expanduser()
    if not storage_root.is_absolute():
        storage_root = BACKEND_ROOT / storage_root
    storage_root = storage_root.resolve()

    image_inputs: list[ModelImageInput] = []
    for asset in assets:
        if asset.asset_type != "product_image":
            continue
        image_path = (storage_root / asset.storage_key).resolve()
        try:
            image_path.relative_to(storage_root)
            image_bytes = image_path.read_bytes()
        except (FileNotFoundError, OSError, ValueError):
            continue
        image_inputs.append(
            ModelImageInput(
                label=f"asset_id={asset.id}; storage_key={asset.storage_key}",
                mime_type=asset.mime_type,
                base64_data=base64.b64encode(image_bytes).decode("ascii"),
            )
        )
    return image_inputs


def product_understanding_error_handler(state: AgentState, error: NodeError) -> Command:
    """模型理解失败时，回落为只使用用户已确认资料的商品理解。"""

    if not isinstance(error.error, ModelGenerationError):
        raise error.error
    return Command(
        update={
            "analysis": build_input_based_analysis(state["run_input"]),
            "product_understanding_provider_key": "local",
            "product_understanding_model_key": None,
        },
        goto=CREATIVE_SCRIPT,
    )




