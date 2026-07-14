"""验证模型 Prompt 以资源文件形式进行版本管理。"""

from __future__ import annotations

from pathlib import Path

from app.agents.prompts import (
    GENERATE_CREATIVE_DRAFT_PROMPT_REF,
    PROMPT_REGISTRY,
    REVIEW_CREATIVE_CLAIMS_PROMPT_REF,
    load_prompt_template,
)


PROMPT_ROOT = Path(__file__).parents[1] / "app" / "agents" / "prompts"


def test_generate_creative_draft_prompt_loads_from_versioned_resource() -> None:
    """一次 LLM 调用只能通过自己的显式版本引用读取 Prompt。"""

    template = load_prompt_template(GENERATE_CREATIVE_DRAFT_PROMPT_REF)

    assert template.key == "generate_creative_draft"
    assert template.version == "v1"
    assert template.owner == "agents"
    assert "15 秒" in template.system_prompt
    assert "JSON schema" in template.system_prompt


def test_review_creative_claims_prompt_loads_from_versioned_resource() -> None:
    template = load_prompt_template(REVIEW_CREATIVE_CLAIMS_PROMPT_REF)

    assert template.key == "review_creative_claims"
    assert template.version == "v1"
    assert "confirmed_facts" in template.system_prompt
    assert "evidence_key" in template.system_prompt


def test_prompt_registry_points_to_existing_markdown_files() -> None:
    """每个 Prompt 注册项都必须指向唯一 Markdown 正文文件。"""

    assert PROMPT_REGISTRY, "至少需要一个已注册的 Prompt 版本"
    for prompt_ref, definition in PROMPT_REGISTRY.items():
        assert prompt_ref == f"{definition.key}/{definition.version}"
        assert definition.description
        assert definition.owner
        assert definition.file_name == f"{definition.key}.{definition.version}.md"

        system_prompt_path = PROMPT_ROOT / definition.file_name
        assert system_prompt_path.exists(), f"{definition.file_name} 不存在"
        system_prompt = system_prompt_path.read_text(encoding="utf-8").strip()
        assert system_prompt, f"{definition.file_name} 不能为空"
        assert "必须遵守" in system_prompt


def test_prompt_files_are_registered() -> None:
    """避免新增 Prompt 文件但忘记在 registry 中声明版本。"""

    registered_files = {definition.file_name for definition in PROMPT_REGISTRY.values()}
    prompt_files = {path.name for path in PROMPT_ROOT.glob("*.md")}

    assert prompt_files == registered_files
