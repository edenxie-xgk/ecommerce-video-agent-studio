from collections.abc import Callable

import pytest

from app.agents.modeling.provider import OpenAICompatibleProvider
from app.agents.models import config_model
from app.agents.planner import CreativePlanner
from app.application.creative_agent import (
    CreativeAssetInput,
    CreativeBriefInput,
    CreativeProjectInput,
    CreativeRunInput,
)


@pytest.fixture
def recording_session():
    """提供只记录写入调用、不会访问数据库的应用服务测试会话。"""

    class RecordingSession:
        def add(self, _record: object) -> None:
            pass

        def commit(self) -> None:
            pass

        def refresh(self, _record: object) -> None:
            pass

    return RecordingSession()


@pytest.fixture(autouse=True)
def use_local_agent_models(monkeypatch):
    provider = OpenAICompatibleProvider(
        base_url=None,
        api_key=None,
        model_key=None,
        timeout_seconds=45,
    )
    monkeypatch.setattr(config_model, "product_understanding_model", lambda: provider)
    monkeypatch.setattr(config_model, "creative_script_model", lambda: provider)
    monkeypatch.setattr(config_model, "prompt_check_model", lambda: provider)
    return provider


@pytest.fixture
def use_agent_provider(monkeypatch):
    def apply(
        provider,
        *,
        product_understanding: bool = True,
        creative_script: bool = True,
        prompt_check: bool = True,
    ):
        if product_understanding:
            monkeypatch.setattr(config_model, "product_understanding_model", lambda: provider)
        if creative_script:
            monkeypatch.setattr(config_model, "creative_script_model", lambda: provider)
        if prompt_check:
            monkeypatch.setattr(config_model, "prompt_check_model", lambda: provider)
        return provider

    return apply


@pytest.fixture
def local_planner() -> CreativePlanner:
    return CreativePlanner()


@pytest.fixture
def complete_brief() -> CreativeBriefInput:
    return CreativeBriefInput(
        project_id=1,
        product_name="Portable thermal cup",
        selling_points_text="Lightweight, sealed lid",
        target_audience_text="Commuters",
        brand_tone="Clean and practical",
        forbidden_words_text="permanent",
    )


@pytest.fixture
def product_asset() -> CreativeAssetInput:
    return CreativeAssetInput(
        id=1,
        project_id=1,
        storage_key="product.jpg",
        mime_type="image/jpeg",
    )


@pytest.fixture
def project_factory() -> Callable[..., CreativeProjectInput]:
    def make_project(
        *,
        project_id: int | None = None,
        title: str = "Portable cup",
        target_platform: str = "douyin",
    ) -> CreativeProjectInput:
        return CreativeProjectInput(
            id=project_id,
            title=title,
            target_platform=target_platform,
            language="zh-CN",
            aspect_ratio="9:16",
            duration_seconds=15,
            status="draft",
        )

    return make_project


@pytest.fixture
def run_input_factory(
    project_factory: Callable[..., CreativeProjectInput],
    complete_brief: CreativeBriefInput,
    product_asset: CreativeAssetInput,
) -> Callable[..., CreativeRunInput]:
    def make_run_input(
        *,
        project: CreativeProjectInput | None = None,
        brief: CreativeBriefInput | None = complete_brief,
        assets: list[CreativeAssetInput] | None = None,
        campaign_goal: str = "Increase product detail views",
    ) -> CreativeRunInput:
        return CreativeRunInput(
            project=project or project_factory(),
            brief=brief,
            assets=[product_asset] if assets is None else assets,
            campaign_goal=campaign_goal,
        )

    return make_run_input
