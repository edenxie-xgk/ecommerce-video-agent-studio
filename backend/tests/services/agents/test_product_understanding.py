from __future__ import annotations

from collections.abc import Callable

from app.agents.modeling.provider import ModelJsonResponse
from app.agents.models import config_model
from app.agents.nodes import CREATIVE_SCRIPT
from app.agents.nodes import product_understanding as product_understanding_module
from app.agents.nodes.product_understanding import product_understanding_node
from app.application.creative_agent import CreativeAssetInput, CreativeRunInput
from app.core.config import Settings


class RecordingProductUnderstandingProvider:
    configured = True

    def __init__(self) -> None:
        self.input_payload: dict[str, object] | None = None
        self.image_count = 0

    def generate_json(self, **kwargs) -> ModelJsonResponse:
        self.input_payload = kwargs["input_payload"]
        self.image_count = len(kwargs["image_inputs"])
        return ModelJsonResponse(
            payload={
                "inferred_category": "通勤保温杯",
                "selected_selling_points": ["Lightweight", "sealed lid"],
                "selected_audience": ["Commuters"],
                "readiness_score": 96,
                "visual_observations": ["图片中可见杯身和杯盖结构。"],
                "visual_uncertainties": ["图片无法确认实际保温时长。"],
            },
            model_key="vision-product-understanding",
        )


def test_product_understanding_node_sends_uploaded_image_bytes(
    tmp_path,
    monkeypatch,
    run_input_factory: Callable[..., CreativeRunInput],
) -> None:
    image_path = tmp_path / "projects" / "1" / "uploads" / "product.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake-image-bytes")
    provider = RecordingProductUnderstandingProvider()
    run_input = run_input_factory(
        assets=[
            CreativeAssetInput(
                id=1,
                project_id=1,
                storage_key="projects/1/uploads/product.jpg",
                mime_type="image/jpeg",
                size_bytes=len(b"fake-image-bytes"),
                asset_metadata={"verified": True},
            )
        ]
    )
    monkeypatch.setattr(config_model, "product_understanding_model", lambda: provider)
    monkeypatch.setattr(
        product_understanding_module,
        "get_settings",
        lambda: Settings(
            database_url="sqlite://",
            asset_storage_path=str(tmp_path),
        ),
    )

    command = product_understanding_node({"run_input": run_input})
    analysis = command.update["analysis"]

    assert command.goto == CREATIVE_SCRIPT
    assert provider.image_count == 1
    assert provider.input_payload is not None
    assert provider.input_payload["visual_input_count"] == 1
    assert provider.input_payload["product_assets"][0]["visual_input_included"] is True
    assert command.update["product_understanding_provider_key"] == "openai_compatible"
    assert command.update["product_understanding_model_key"] == "vision-product-understanding"
    assert analysis.visual_observations == ["图片中可见杯身和杯盖结构。"]
    assert analysis.visual_uncertainties == ["图片无法确认实际保温时长。"]
