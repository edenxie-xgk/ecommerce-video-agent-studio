"""封装 OpenAI-compatible 结构化 JSON 模型调用。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.client import IncompleteRead
from typing import Literal, Protocol
from urllib import error, request


@dataclass(frozen=True)
class ModelJsonResponse:
    """Provider 返回并完成 JSON 解析的结构化响应。"""

    payload: dict[str, object]  # 等待业务 Pydantic schema 校验的原始对象。
    model_key: str  # Provider 实际返回的模型标识。


@dataclass(frozen=True)
class ModelImageInput:
    """发送给多模态模型的一张图片。"""

    label: str  # 帮模型把图片与 product_assets 中的素材记录对应起来。
    mime_type: str  # 图片 MIME 类型，例如 image/jpeg。
    base64_data: str  # 不带 data URL 前缀的 base64 图片内容。
    detail: Literal["auto", "low", "high"] = "auto"  # 交给兼容 Provider 的视觉细节偏好。

    @property
    def data_url(self) -> str:
        """返回 OpenAI-compatible image_url 可直接使用的 data URL。"""

        return f"data:{self.mime_type};base64,{self.base64_data}"


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
        image_inputs: list[ModelImageInput] | None = None,
    ) -> ModelJsonResponse:
        """返回等待业务 Schema 校验的 JSON 对象。"""

        ...


class OpenAICompatibleProvider:
    """最小 OpenAI-compatible JSON 调用边界。"""

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model_key: str | None,
        timeout_seconds: int,
    ) -> None:
        """注入一组明确的 OpenAI-compatible Provider 配置。"""

        self._base_url = base_url
        self._api_key = api_key
        self._model_key = model_key
        self._timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        """判断外部模型调用所需的三个配置是否同时存在。"""

        return bool(self._base_url and self._api_key and self._model_key)

    def generate_json(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, object],
        json_schema: dict[str, object],
        image_inputs: list[ModelImageInput] | None = None,
    ) -> ModelJsonResponse:
        """调用外部模型并返回可解析的 JSON 对象。

        Provider 负责 HTTP 协议适配和 JSON 解析，业务校验由生成节点完成。
        """

        if not self.configured:
            raise ProviderRequestError("LLM provider is not configured.")

        # Provider 边界负责组装 OpenAI-compatible 请求。
        base_url = (self._base_url or "").rstrip("/")
        endpoint = f"{base_url}/chat/completions"
        body = {
            "model": self._model_key,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": self._user_message_content(
                        input_payload=input_payload,
                        json_schema=json_schema,
                        image_inputs=image_inputs or [],
                    ),
                },
            ],
        }
        try:
            http_request = request.Request(
                endpoint,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with request.urlopen(
                http_request,
                timeout=self._timeout_seconds,
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
            model_key = response_payload.get("model") or self._model_key
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderResponseError("Model response is missing message content.") from exc

        if not isinstance(content, str):
            raise ProviderResponseError("Model response content must be a JSON string.")

        # 此处验证 JSON 对象形状；模型输出的业务 Schema 由生成节点完成。
        parsed = parse_model_json_object(content)
        if not isinstance(parsed, dict):
            raise ProviderResponseError("Model response must be a JSON object.")

        return ModelJsonResponse(payload=parsed, model_key=str(model_key))

    @staticmethod
    def _user_message_content(
        *,
        input_payload: dict[str, object],
        json_schema: dict[str, object],
        image_inputs: list[ModelImageInput],
    ) -> str | list[dict[str, object]]:
        """按是否带图片选择纯文本或多模态 user message 结构。"""

        text_payload = json.dumps(
            {
                "input": input_payload,
                "required_output_schema": json_schema,
            },
            ensure_ascii=False,
        )
        if not image_inputs:
            return text_payload

        content: list[dict[str, object]] = [{"type": "text", "text": text_payload}]
        for image in image_inputs:
            content.append({"type": "text", "text": f"product image: {image.label}"})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image.data_url,
                        "detail": image.detail,
                    },
                }
            )
        return content


def parse_model_json_object(content: str) -> object:
    """解析模型返回的 JSON 对象，并兼容常见 Markdown 代码块残留。"""

    normalized = content.strip()
    if normalized.startswith("```"):
        normalized = normalized.split("\n", 1)[-1]
        normalized = normalized.rsplit("```", 1)[0].strip()

    decoder = json.JSONDecoder()
    try:
        parsed, end_index = decoder.raw_decode(normalized)
    except json.JSONDecodeError as exc:
        raise ProviderResponseError("Model response is not valid JSON.") from exc

    trailing = normalized[end_index:].strip()
    if trailing and trailing.strip("`").strip():
        raise ProviderResponseError("Model response is not valid JSON.")
    return parsed
