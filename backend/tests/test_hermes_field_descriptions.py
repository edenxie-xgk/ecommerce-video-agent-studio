import ast
import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.api.schemas import (
    CreativeRunResponse,
    ProductBriefPayload,
    ProductBriefResponse,
    ProjectAssetResponse,
    ProjectCreatePayload,
    ProjectResponse,
)
from app.agents.modeling.contracts import GeneratedCreativeDraft
from app.application.creative_agent import (
    CreativeAssetInput,
    CreativeBriefInput,
    CreativeConcept,
    CreativeDecisionBundle,
    CreativeDraft,
    CreativeProjectInput,
    CreativeRunInput,
    ProductAnalysis,
    QualityEvaluation,
    QualityIssue,
    ShotPlan,
    StoryboardConceptPrompt,
    StoryboardPromptBundle,
    StoryboardShotPrompt,
)
from app.application.creative_plan import CreativePlanContent
from app.core.config import Settings
from app.models.creative import AgentRun, CreativeRun, WorkflowNodeRun, WorkflowRun
from app.models.project import ProductBrief, ProjectAsset, VideoProject


SCHEMAS: tuple[type[BaseModel], ...] = (
    Settings,
    VideoProject,
    ProductBrief,
    ProjectAsset,
    WorkflowRun,
    WorkflowNodeRun,
    AgentRun,
    CreativeRun,
    ProductBriefPayload,
    ProductBriefResponse,
    ProjectCreatePayload,
    ProjectResponse,
    ProjectAssetResponse,
    CreativeRunResponse,
    ProductAnalysis,
    ShotPlan,
    CreativeConcept,
    CreativePlanContent,
    CreativeDraft,
    StoryboardShotPrompt,
    StoryboardConceptPrompt,
    StoryboardPromptBundle,
    GeneratedCreativeDraft,
    QualityIssue,
    QualityEvaluation,
    CreativeDecisionBundle,
    CreativeProjectInput,
    CreativeBriefInput,
    CreativeAssetInput,
    CreativeRunInput,
)


@pytest.mark.parametrize("schema", SCHEMAS)
def test_hermes_fields_have_chinese_descriptions(schema: type[BaseModel]) -> None:
    """Hermes 要求持久化、配置和接口字段包含可读的中文业务说明。"""

    for field_name, field in schema.model_fields.items():
        assert field.description, f"{schema.__name__}.{field_name} 缺少字段说明"
        assert re.search(r"[\u4e00-\u9fff]", field.description), (
            f"{schema.__name__}.{field_name} 缺少中文业务说明"
        )


def test_agent_modules_have_chinese_docstrings() -> None:
    """Agent 模块、类和函数必须解释业务职责，避免只有实现没有上下文。"""

    agent_dir = Path(__file__).parents[1] / "app" / "agents"
    for path in agent_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        documented_nodes = [tree]
        documented_nodes.extend(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        )
        for node in documented_nodes:
            docstring = ast.get_docstring(node)
            name = getattr(node, "name", "module")
            assert docstring, f"{path.name}:{name} 缺少 docstring"
            assert re.search(r"[\u4e00-\u9fff]", docstring), f"{path.name}:{name} 缺少中文业务说明"
