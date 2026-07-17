from __future__ import annotations

import json

import pytest

from app.agents.modeling.provider import (
    ModelImageInput,
    OpenAICompatibleProvider,
    ProviderRequestError,
    ProviderResponseError,
    parse_model_json_object,
)


def _provider(base_url: str) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url=base_url,
        api_key="test-key",
        model_key="test-model",
        timeout_seconds=45,
    )


def _generate(provider: OpenAICompatibleProvider) -> None:
    provider.generate_json(
        system_prompt="Return JSON.",
        input_payload={},
        json_schema={"type": "object"},
    )


def test_provider_classifies_malformed_base_url_as_non_retryable_request_error() -> None:
    with pytest.raises(ProviderRequestError, match="request is invalid"):
        _generate(_provider("not a url"))


class InvalidUtf8Response:
    def __enter__(self) -> InvalidUtf8Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return b"\xff"


def test_provider_classifies_invalid_response_encoding_as_response_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agents.modeling.provider.request.urlopen",
        lambda *_args, **_kwargs: InvalidUtf8Response(),
    )

    with pytest.raises(ProviderResponseError, match="not valid JSON"):
        _generate(_provider("https://example.test/v1"))


class JsonResponse:
    def __enter__(self) -> JsonResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "model": "vision-model",
                "choices": [{"message": {"content": "{\"ok\": true}"}}],
            }
        ).encode("utf-8")


def test_provider_sends_multimodal_user_message_when_images_are_present(monkeypatch) -> None:
    captured_body: dict[str, object] = {}

    def fake_urlopen(http_request, **_kwargs):
        captured_body.update(json.loads(http_request.data.decode("utf-8")))
        return JsonResponse()

    monkeypatch.setattr("app.agents.modeling.provider.request.urlopen", fake_urlopen)

    response = _provider("https://example.test/v1").generate_json(
        system_prompt="Return JSON.",
        input_payload={"product_name": "Cup"},
        json_schema={"type": "object"},
        image_inputs=[
            ModelImageInput(
                label="asset_id=1; storage_key=product.jpg",
                mime_type="image/jpeg",
                base64_data="aW1hZ2U=",
            )
        ],
    )

    message = captured_body["messages"][1]
    assert response.payload == {"ok": True}
    assert isinstance(message, dict)
    assert message["content"][0]["type"] == "text"
    assert message["content"][1] == {
        "type": "text",
        "text": "product image: asset_id=1; storage_key=product.jpg",
    }
    assert message["content"][2] == {
        "type": "image_url",
        "image_url": {
            "url": "data:image/jpeg;base64,aW1hZ2U=",
            "detail": "auto",
        },
    }


def test_provider_accepts_json_with_trailing_markdown_fence() -> None:
    assert parse_model_json_object('{"ok": true}\n```') == {"ok": True}
