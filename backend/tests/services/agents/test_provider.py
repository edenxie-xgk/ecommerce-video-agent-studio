from __future__ import annotations

import pytest

from app.agents.modeling.provider import (
    OpenAICompatibleProvider,
    ProviderRequestError,
    ProviderResponseError,
)
from app.core.config import Settings


def _provider(base_url: str) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        Settings(
            database_url="sqlite://",
            llm_base_url=base_url,
            llm_api_key="test-key",
            llm_model="test-model",
        )
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
