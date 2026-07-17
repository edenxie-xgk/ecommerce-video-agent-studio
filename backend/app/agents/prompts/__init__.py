"""通过 typed registry 加载版本化 Prompt。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


# creative_script 节点使用的 Prompt 引用，格式固定为 `调用点/版本`。
ANALYZE_PRODUCT_PROMPT_REF = "analyze_product/v1"
GENERATE_CREATIVE_DRAFT_PROMPT_REF = "generate_creative_draft/v1"
REVIEW_CREATIVE_CLAIMS_PROMPT_REF = "review_creative_claims/v1"


@dataclass(frozen=True)
class PromptDefinition:
    """声明一次 LLM 调用使用的 Prompt 版本和资源文件。"""

    key: str  # Prompt 对应的 LLM 调用点。
    version: str  # Prompt 的显式版本号。
    description: str  # 该版本 Prompt 的业务用途说明。
    owner: str  # 负责维护该 Prompt 的模块或团队。
    file_name: str  # Prompt 正文所在的 Markdown 文件名。


@dataclass(frozen=True)
class PromptTemplate:
    """运行时可直接发送给模型的 Prompt 模板。"""

    key: str  # Prompt 对应的 LLM 调用点。
    version: str  # Prompt 的显式版本号。
    description: str  # 该版本 Prompt 的业务用途说明。
    owner: str  # 负责维护该 Prompt 的模块或团队。
    system_prompt: str  # 发送给模型的系统 Prompt 正文。


PROMPT_REGISTRY: dict[str, PromptDefinition] = {
    # 商品理解节点：把用户资料整理成后续节点可引用的商品事实。
    ANALYZE_PRODUCT_PROMPT_REF: PromptDefinition(
        key="analyze_product",
        version="v1",
        description="product_understanding 节点调用 LLM 时使用，输出可追溯的商品理解。",
        owner="agents",
        file_name="analyze_product.v1.md",
    ),
    # 创意脚本节点：根据已确认商品事实生成三套创意方案。
    GENERATE_CREATIVE_DRAFT_PROMPT_REF: PromptDefinition(
        key="generate_creative_draft",
        version="v1",
        description="creative_script 节点调用 LLM 时使用，输出三个可审核的 15 秒创意方案。",
        owner="agents",
        file_name="generate_creative_draft.v1.md",
    ),
    REVIEW_CREATIVE_CLAIMS_PROMPT_REF: PromptDefinition(
        key="review_creative_claims",
        version="v1",
        description="审核创意草案中的商品声明是否有已确认事实证据。",
        owner="agents",
        file_name="review_creative_claims.v1.md",
    ),
}


@lru_cache
def load_prompt_template(prompt_ref: str) -> PromptTemplate:
    """按 `调用点/版本` 读取 Prompt 定义和 Markdown 正文。"""

    definition = PROMPT_REGISTRY.get(prompt_ref)
    if definition is None:
        raise KeyError(f"Prompt 未注册：{prompt_ref}")

    system_prompt_path = Path(__file__).parent / definition.file_name
    if not system_prompt_path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在：{definition.file_name}")
    system_prompt = system_prompt_path.read_text(encoding="utf-8").strip()

    if not system_prompt:
        raise ValueError(f"Prompt 正文不能为空：{prompt_ref}")

    return PromptTemplate(
        key=definition.key,
        version=definition.version,
        description=definition.description,
        owner=definition.owner,
        system_prompt=system_prompt,
    )
