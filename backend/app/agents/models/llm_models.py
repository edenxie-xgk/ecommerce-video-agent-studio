"""按应用 Settings 构造并缓存 Agent 可用的大模型实例。

这里不执行请求；只把不同阶段所需的配置映射为统一的 OpenAI-compatible Provider。
``lru_cache`` 使单个进程内相同配置的实例可复用。
"""

from functools import lru_cache

from app.agents.modeling.provider import CreativeModelProvider, OpenAICompatibleProvider
from app.core.config import get_settings


@lru_cache
def openai_model() -> CreativeModelProvider:
    """返回创意脚本和语义审核共用的文本 JSON 模型。"""

    # Settings 允许 API 地址、密钥、模型名和超时分别由部署环境提供。
    settings = get_settings()
    return OpenAICompatibleProvider(
        base_url=settings.text_llm_base_url,
        api_key=settings.text_llm_api_key,
        model_key=settings.text_llm_model,
        timeout_seconds=settings.text_llm_timeout_seconds,
    )


@lru_cache
def openai_product_understanding_model() -> CreativeModelProvider:
    """返回商品理解节点使用的 OpenAI-compatible 多模态 JSON 模型。"""

    # 多模态模型可独立于文本模型切换，以适配具备视觉输入能力的服务。
    settings = get_settings()
    return OpenAICompatibleProvider(
        base_url=settings.multimodal_llm_base_url,
        api_key=settings.multimodal_llm_api_key,
        model_key=settings.multimodal_llm_model,
        timeout_seconds=settings.multimodal_llm_timeout_seconds,
    )
