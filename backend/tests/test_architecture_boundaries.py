"""验证 API、应用用例和 Agent 实现之间的单向依赖。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.api.schemas import CreativeRunResponse


APP_ROOT = Path(__file__).parents[1] / "app"


def _imported_modules(path: Path) -> set[str]:
    """提取 Python 文件中的绝对导入模块，供边界规则检查。"""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize(
    ("package", "forbidden_prefixes"),
    (
        ("api", ("app.agents", "langgraph")),
        ("application", ("app.agents", "app.api", "langgraph")),
        ("agents", ("app.api", "app.models")),
    ),
)
def test_packages_follow_dependency_direction(
    package: str,
    forbidden_prefixes: tuple[str, ...],
) -> None:
    """禁止上层访问 Agent 基础设施，也禁止 Agent 反向读取 API 或 ORM。"""

    violations: list[str] = []
    for path in (APP_ROOT / package).rglob("*.py"):
        for module in _imported_modules(path):
            if module.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(APP_ROOT)} -> {module}")

    assert not violations, "发现跨层反向依赖：\n" + "\n".join(violations)


def test_api_does_not_expose_checkpoint_identifier() -> None:
    """LangGraph 的线程标识必须保持为应用内部实现细节。"""

    assert "thread_id" not in CreativeRunResponse.model_fields
