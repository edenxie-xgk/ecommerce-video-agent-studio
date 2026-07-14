"""声明仅用于外部模型 Provider 边界的结构化输出契约。

外部模型返回创意内容字段。服务端负责把模型结果与权威商品分析组合成
完整 `CreativeDraft`。
"""

from app.application.creative_plan import CreativePlanContent


class GeneratedCreativeDraft(CreativePlanContent):
    """定义外部模型可以生成的创意字段。"""
