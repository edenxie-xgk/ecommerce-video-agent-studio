"""封装 OpenAI-compatible 结构化 JSON 模型调用。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.client import IncompleteRead
from typing import Protocol
from urllib import error, request

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class ModelJsonResponse:
    """Provider 返回并完成 JSON 解析的结构化响应。"""

    payload: dict[str, object]  # 等待业务 Pydantic schema 校验的原始对象。
    model_key: str  # Provider 实际返回的模型标识。


class ModelGenerationError(RuntimeError):
    """模型生成失败，但 Agent 可以安全降级到本地策略。"""


class RetryableModelGenerationError(ModelGenerationError):
    """重试可能得到有效结果的模型生成错误。"""


class ProviderTransientError(RetryableModelGenerationError):
    """超时、限流或服务端故障等临时 Provider 错误。"""


class ProviderResponseError(RetryableModelGenerationError):
    """Provider 返回了无法解析或不符合业务契约的模型结果。"""


class ProviderRequestError(ModelGenerationError):
    """当前请求或 Provider 配置导致的模型调用错误。"""


class CreativeModelProvider(Protocol):
    """创意图依赖的最小模型 Provider 契约。"""

    @property
    def configured(self) -> bool:
        """返回当前运行时是否具备调用模型的完整配置。"""

        ...

    def generate_json(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, object],
        json_schema: dict[str, object],
    ) -> ModelJsonResponse:
        """返回等待业务 Schema 校验的 JSON 对象。"""

        ...


class OpenAICompatibleProvider:
    """最小 OpenAI-compatible JSON 调用边界。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """注入可测试的配置对象，默认读取应用配置。"""

        self._settings = settings or get_settings()

    @property
    def configured(self) -> bool:
        """判断外部模型调用所需的三个配置是否同时存在。"""

        return bool(
            self._settings.llm_base_url and self._settings.llm_api_key and self._settings.llm_model
        )

    def generate_json(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, object],
        json_schema: dict[str, object],
    ) -> ModelJsonResponse:
        """调用外部模型并返回可解析的 JSON 对象。

        Provider 负责 HTTP 协议适配和 JSON 解析，业务校验由生成节点完成。
        """

        if not self.configured:
            raise ProviderRequestError("LLM provider is not configured.")

        # Provider 边界负责组装 OpenAI-compatible 请求。
        base_url = (self._settings.llm_base_url or "").rstrip("/")
        endpoint = f"{base_url}/chat/completions"
        body = {
            "model": self._settings.llm_model,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "input": input_payload,
                            "required_output_schema": json_schema,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        try:
            http_request = request.Request(
                endpoint,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self._settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with request.urlopen(
                http_request,
                timeout=self._settings.llm_timeout_seconds,
            ) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                raise ProviderTransientError(f"Model request failed: {exc}") from exc
            raise ProviderRequestError(f"Model request was rejected: {exc}") from exc
        except (error.URLError, TimeoutError) as exc:
            raise ProviderTransientError(f"Model request failed: {exc}") from exc
        except IncompleteRead as exc:
            raise ProviderTransientError("Model response ended before completion.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderResponseError("Model HTTP response is not valid JSON.") from exc
        except ValueError as exc:
            raise ProviderRequestError(f"Model request is invalid: {exc}") from exc

        # API 响应字段校验统一转成 ProviderResponseError。
        try:
            content = response_payload["choices"][0]["message"]["content"]
            model_key = response_payload.get("model") or self._settings.llm_model
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderResponseError("Model response is missing message content.") from exc

        if not isinstance(content, str):
            raise ProviderResponseError("Model response content must be a JSON string.")

        normalized = content.strip()
        # 部分兼容服务仍会用 Markdown 代码块包裹 JSON，需要先去除包装。
        if normalized.startswith("```"):
            normalized = normalized.split("\n", 1)[-1]
            normalized = normalized.rsplit("```", 1)[0]

        # 此处验证 JSON 对象形状；模型输出的业务 Schema 由生成节点完成。
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError("Model response is not valid JSON.") from exc

        if not isinstance(parsed, dict):
            raise ProviderResponseError("Model response must be a JSON object.")

        return ModelJsonResponse(payload=parsed, model_key=str(model_key))
