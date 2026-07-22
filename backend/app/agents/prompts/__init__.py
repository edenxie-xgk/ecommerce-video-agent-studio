"""通过 typed registry 加载版本化 Prompt。

Prompt 正文存放在相邻 Markdown 文件，代码只依赖稳定的 ``调用点/版本`` 引用。这样可
以在不修改节点调用方式的前提下并行维护不同版本，并让每次模型调用可追溯到具体模板。
"""

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
    """声明一次 LLM 调用使用的 Prompt 版本和资源文件。

    该对象是注册表中的静态元数据，``file_name`` 仅是当前 prompts 包中的文件名，不接受
    来自 API 或模型输出的任意路径。
    """

    key: str  # Prompt 对应的 LLM 调用点。
    version: str  # Prompt 的显式版本号。
    description: str  # 该版本 Prompt 的业务用途说明。
    owner: str  # 负责维护该 Prompt 的模块或团队。
    file_name: str  # Prompt 正文所在的 Markdown 文件名。


@dataclass(frozen=True)
class PromptTemplate:
    """运行时可直接发送给模型的 Prompt 模板。

    它保留与 ``PromptDefinition`` 相同的审计元数据，并将已读取、已去首尾空白的 Markdown
    正文放入 ``system_prompt``，供 Provider 直接发送。
    """

    key: str  # Prompt 对应的 LLM 调用点。
    version: str  # Prompt 的显式版本号。
    description: str  # 该版本 Prompt 的业务用途说明。
    owner: str  # 负责维护该 Prompt 的模块或团队。
    system_prompt: str  # 发送给模型的系统 Prompt 正文。


# 所有节点可用模板的显式白名单。调用方只能使用这些键，避免根据动态输入读取任意文件。
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
    # 语义审核节点：将脚本和可选分镜 Prompt 与服务端证据注册表逐项比对。
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
    """按 `调用点/版本` 读取 Prompt 定义和 Markdown 正文。

    缓存键为完整 prompt_ref，同版本模板在单个进程中只读取一次。模板修改后需要重启进程
    或显式清除缓存，避免执行中的请求看见不一致的系统提示词。
    """

    # 先查白名单，再根据注册表生成路径，防止 prompt_ref 被解释为文件系统路径。
    definition = PROMPT_REGISTRY.get(prompt_ref)
    if definition is None:
        raise KeyError(f"Prompt 未注册：{prompt_ref}")

    # Path(__file__).parent 固定为本包目录，definition.file_name 来自受控常量。
    system_prompt_path = Path(__file__).parent / definition.file_name
    if not system_prompt_path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在：{definition.file_name}")
    # UTF-8 保证中文提示词原样读取；strip 清除 Markdown 文件的无意义首尾空白。
    system_prompt = system_prompt_path.read_text(encoding="utf-8").strip()

    if not system_prompt:
        raise ValueError(f"Prompt 正文不能为空：{prompt_ref}")

    # 返回不可变运行时对象，调用节点无法意外改写全局注册表定义。
    return PromptTemplate(
        key=definition.key,
        version=definition.version,
        description=definition.description,
        owner=definition.owner,
        system_prompt=system_prompt,
    )
