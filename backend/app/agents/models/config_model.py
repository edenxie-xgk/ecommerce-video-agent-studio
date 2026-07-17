"""声明每个 Agent 节点当前使用哪个模型。"""

from app.agents.modeling.provider import CreativeModelProvider
from app.agents.models.llm_models import openai_model, openai_product_understanding_model


def product_understanding_model() -> CreativeModelProvider:
    """商品理解节点使用的模型。"""

    return openai_product_understanding_model()


def creative_script_model() -> CreativeModelProvider:
    """创意脚本节点使用的模型。"""

    return openai_model()


def prompt_check_model() -> CreativeModelProvider:
    """语义审核节点使用的模型。"""

    return openai_model()
