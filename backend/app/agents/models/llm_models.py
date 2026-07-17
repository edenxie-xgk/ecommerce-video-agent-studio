"""声明 Agent 当前可用的大模型实例。"""

from functools import lru_cache

from app.agents.modeling.provider import CreativeModelProvider, OpenAICompatibleProvider
from app.core.config import get_settings


@lru_cache
def openai_model() -> CreativeModelProvider:
    """返回文本节点使用的 OpenAI-compatible JSON 模型。"""

    settings = get_settings()
    return OpenAICompatibleProvider(
        base_url=settings.text_llm_base_url,
        api_key=settings.text_llm_api_key,
        model_key=settings.text_llm_model,
        timeout_seconds=settings.text_llm_timeout_seconds,
    )


@lru_cache
def openai_product_understanding_model() -> CreativeModelProvider:
    """返回商品理解节点使用的 OpenAI-compatible 多模态模型。"""

    settings = get_settings()
    return OpenAICompatibleProvider(
        base_url=settings.multimodal_llm_base_url,
        api_key=settings.multimodal_llm_api_key,
        model_key=settings.multimodal_llm_model,
        timeout_seconds=settings.multimodal_llm_timeout_seconds,
    )
