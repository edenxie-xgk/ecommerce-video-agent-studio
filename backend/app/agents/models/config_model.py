"""声明每个 Agent 节点当前使用哪个模型。

保留这一层映射可以让节点表达业务用途，而无需直接耦合某个 Provider 构造函数；后续
替换某一阶段模型时，只需要修改这里的装配关系。
"""

from app.agents.modeling.provider import CreativeModelProvider
from app.agents.models.llm_models import openai_model, openai_product_understanding_model


def product_understanding_model() -> CreativeModelProvider:
    """返回商品理解节点使用的多模态模型 Provider。"""

    # 商品理解可以携带商品图，因此与纯文本创意/审核模型分开配置。
    return openai_product_understanding_model()


def creative_script_model() -> CreativeModelProvider:
    """返回创意脚本节点使用的文本模型 Provider。"""

    # 脚本阶段只消费已校验的结构化事实与分析结果。
    return openai_model()


def prompt_check_model() -> CreativeModelProvider:
    """返回语义审核节点使用的文本模型 Provider。"""

    # 当前审核和脚本共享文本模型配置，但保留独立函数以便以后拆分。
    return openai_model()
