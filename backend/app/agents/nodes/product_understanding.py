"""实现 product_understanding 节点：生成可追溯的商品理解。

该节点是模型输入进入创意流程的第一道事实边界。它可以借助商品图片补充可见观察，
但商品名称、卖点、人群和禁词始终由用户确认的 brief 拥有，不能被模型覆盖。
"""

from __future__ import annotations

import base64
from pathlib import Path

from langgraph.types import Command

from app.agents.modeling.contracts import GeneratedProductUnderstanding
from app.agents.modeling.generation import (
    build_authoritative_analysis,
    build_input_based_analysis,
)
from app.agents.modeling.provider import ModelImageInput
from app.agents.models import config_model
from app.agents.nodes import CREATIVE_SCRIPT
from app.agents.prompts import ANALYZE_PRODUCT_PROMPT_REF, load_prompt_template
from app.agents.state import AgentState
from app.application.creative_agent import CreativeAssetInput
from app.core.config import BACKEND_ROOT, get_settings


def product_understanding_node(state: AgentState) -> Command:
    """用模型理解商品资料，并把通过服务端校验的结果写入状态。

    Provider 未配置时走本地保守分析；Provider 已配置却失败时抛出可重试错误，由图的
    RetryPolicy 处理，不把“模型暂不可用”误当作用户输入本身有效。
    """

    # run_input 是状态中的权威业务输入，后续节点应基于本变量继续传递事实。
    run_input = state["run_input"]
    # 模型由配置映射层提供，节点不依赖特定 OpenAI SDK 或具体模型名。
    provider = config_model.product_understanding_model()
    if not provider.configured:
        # 未配置多模态模型时，直接用用户已确认资料生成可继续流转的商品分析。
        return Command(
            update={
                "analysis": build_input_based_analysis(run_input),
                "product_understanding_provider_key": "local",
                "product_understanding_model_key": None,
            },
            goto=CREATIVE_SCRIPT,
        )

    # 配置了模型却没有 brief 时不能继续，因为模型输入无法构造可靠事实边界。
    brief = run_input.brief
    if brief is None:
        raise ValueError("商品资料缺失，不能执行商品理解节点。")

    # 图片像素单独转成模型输入；素材清单保留业务元数据，便于模型对照引用。
    # 读取成功的图片才会发给模型；原始素材清单仍完整保留在 product_assets 中。
    image_inputs = build_product_image_inputs(run_input.assets)
    # 这份元数据不包含像素本身，供模型将视觉内容与具体上传素材记录对应。
    product_assets = [
        {
            "asset_id": asset.id,
            "storage_key": asset.storage_key,
            "mime_type": asset.mime_type,
            "size_bytes": asset.size_bytes,
            "metadata": asset.asset_metadata,
            # 明确标记该素材是否实际读入，避免模型把不可读图片当作已观察证据。
            "visual_input_included": any(
                image.label == f"asset_id={asset.id}; storage_key={asset.storage_key}"
                for image in image_inputs
            ),
        }
        for asset in run_input.assets
        if asset.asset_type == "product_image"
    ]
    # Prompt 资源版本化管理，节点只引用稳定的模板标识。
    prompt_template = load_prompt_template(ANALYZE_PRODUCT_PROMPT_REF)
    # Provider 只负责返回 JSON 候选结果；字段合法性和事实边界由服务端继续校验。
    response = provider.generate_json(
        system_prompt=prompt_template.system_prompt,
        input_payload={
            # 以下字段是模型允许参考的明确白名单；不传递未确认的自由文本或文件路径。
            "product_name": brief.product_name.strip(),
            "selling_points": brief.selling_points(),
            "target_audience": brief.target_audiences(),
            "brand_tone": brief.brand_tone.strip(),
            "forbidden_expressions": brief.forbidden_words(),
            "target_platform": run_input.project.target_platform,
            "campaign_goal": run_input.campaign_goal,
            "duration_seconds": run_input.project.duration_seconds,
            "product_assets": product_assets,
            # 用数量约束模型：没有像素输入时不得凭空产出视觉观察。
            "visual_input_count": len(image_inputs),
        },
        json_schema=GeneratedProductUnderstanding.model_json_schema(),
        image_inputs=image_inputs,
    )
    # 商品名称、卖点、人群等权威事实以用户输入为准，模型只补充类目和视觉判断。
    # 生成层会把模型候选输出与 brief 白名单逐项对照，并重建最终业务模型。
    analysis = build_authoritative_analysis(
        payload=response.payload,
        run_input=run_input,
        image_input_count=len(image_inputs),
    )
    # Command 同时写入阶段产物、审计用模型元数据，并指定下一节点。
    return Command(
        update={
            "analysis": analysis,
            "product_understanding_provider_key": "openai_compatible",
            "product_understanding_model_key": response.model_key,
        },
        goto=CREATIVE_SCRIPT,
    )


def build_product_image_inputs(assets: list[CreativeAssetInput]) -> list[ModelImageInput]:
    """把已上传商品图读取为多模态模型可接收的图片输入。

    此函数是本地文件读取边界：只允许读取 asset storage 根目录下、类型为
    ``product_image`` 的已登记素材；任一不可读文件都被跳过而非中断整次商品理解。
    """

    # Settings 可以配置相对或绝对素材路径；相对路径以 backend 根目录解释。
    settings = get_settings()
    storage_root = Path(settings.asset_storage_path).expanduser()
    if not storage_root.is_absolute():
        storage_root = BACKEND_ROOT / storage_root
    # resolve 归一化 ``..`` 和符号链接后的路径，供下方相对路径安全检查使用。
    storage_root = storage_root.resolve()

    image_inputs: list[ModelImageInput] = []
    for asset in assets:
        # 视频、文档等其他资产不能作为多模态商品图发送。
        if asset.asset_type != "product_image":
            continue
        # 即使 storage_key 恶意包含 ``..``，relative_to 校验也会阻止越过素材根目录。
        image_path = (storage_root / asset.storage_key).resolve()
        try:
            # storage_key 需要落在素材根目录内，读取范围限定在本地素材库。
            image_path.relative_to(storage_root)
            image_bytes = image_path.read_bytes()
        except (FileNotFoundError, OSError, ValueError):
            # 缺失或不可读的图片不进入模型输入，后续 visual_input_included 会标记为 false。
            continue
        # base64 编码让 Provider 能通过 JSON 请求携带二进制图片，无需暴露本地文件路径。
        image_inputs.append(
            ModelImageInput(
                label=f"asset_id={asset.id}; storage_key={asset.storage_key}",
                mime_type=asset.mime_type,
                base64_data=base64.b64encode(image_bytes).decode("ascii"),
            )
        )
    return image_inputs
