"""封装 OpenAI-compatible 结构化 JSON 模型调用。

Provider 是唯一了解 HTTP endpoint、鉴权头和 OpenAI chat-completions 格式的边界。它只
保证网络响应可解析成 JSON 对象，不解释字段的业务正确性，也不决定失败后的业务降级。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.client import IncompleteRead
from typing import Literal, Protocol
from urllib import error, request


@dataclass(frozen=True)
class ModelJsonResponse:
    """Provider 返回并完成 JSON 解析的结构化响应。"""

    # 仍未验证 Pydantic schema，调用节点必须把它交给生成/审核层进一步验证。
    payload: dict[str, object]  # 等待业务 Pydantic schema 校验的原始对象。
    # 优先保存服务端实际响应的模型名，方便运行审计和排障。
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

        # Provider 接口要求将 MIME 类型和 base64 内容合成为标准 data URL。
        return f"data:{self.mime_type};base64,{self.base64_data}"


class ModelGenerationError(RuntimeError):
    """模型生成失败；节点会按自身业务边界选择重试、失败或本地方案。"""


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
        """返回等待业务 Schema 校验的 JSON 对象。

        ``input_payload`` 只能包含调用节点已筛选的业务事实；``json_schema`` 作为模型
        输出约束提示，并不取代服务端 Pydantic 校验。
        """

        ...


class OpenAICompatibleProvider:
    """最小 OpenAI-compatible JSON 调用边界。

    该适配器兼容实现 chat/completions 的服务。它故意使用标准库 HTTP 客户端，避免将
    一个很小的协议边界扩展为 SDK 依赖和不同 SDK 行为的耦合。
    """

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model_key: str | None,
        timeout_seconds: int,
    ) -> None:
        """注入一组明确的 OpenAI-compatible Provider 配置。"""

        # 原始配置保留为私有字段；``configured`` 决定节点能否安全发起调用。
        self._base_url = base_url
        self._api_key = api_key
        self._model_key = model_key
        self._timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        """判断外部模型调用所需的三个配置是否同时存在。"""

        # 任何一项缺失都不发请求，让节点选择本地策略或明确报错。
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

        # 防止缺失配置时构造空鉴权请求，并给调用节点一个可分类的业务错误。
        if not self.configured:
            raise ProviderRequestError("LLM provider is not configured.")

        # Provider 边界负责组装 OpenAI-compatible 请求。
        # 清除配置末尾斜杠，避免 endpoint 出现 ``//chat/completions``。
        base_url = (self._base_url or "").rstrip("/")
        endpoint = f"{base_url}/chat/completions"
        # response_format 要求模型返回 JSON；实际输出仍需在下方严格解析。
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
            # Request 同时编码 Unicode 文案与 Pydantic JSON Schema，使用 UTF-8 保持中文不丢失。
            http_request = request.Request(
                endpoint,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            # ``with`` 保证响应连接在读取完成或抛错后被关闭。
            with request.urlopen(
                http_request,
                timeout=self._timeout_seconds,
            ) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            # 限流和 5xx 多为服务端暂时状态，交给 LangGraph RetryPolicy 重试。
            if exc.code == 429 or exc.code >= 500:
                raise ProviderTransientError(f"Model request failed: {exc}") from exc
            # 4xx 通常表示密钥、参数或模型配置有问题，重试没有价值。
            raise ProviderRequestError(f"Model request was rejected: {exc}") from exc
        except (error.URLError, TimeoutError) as exc:
            # 网络不可达和超时也可能在短时间内恢复。
            raise ProviderTransientError(f"Model request failed: {exc}") from exc
        except IncompleteRead as exc:
            # 截断响应不能安全解析，也按临时传输问题处理。
            raise ProviderTransientError("Model response ended before completion.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            # HTTP body 非 JSON 表示 Provider 协议响应不符合预期，可由节点的降级逻辑处理。
            raise ProviderResponseError("Model HTTP response is not valid JSON.") from exc
        except ValueError as exc:
            # urllib 对无效 URL 等本地请求参数抛 ValueError，不应无意义重试。
            raise ProviderRequestError(f"Model request is invalid: {exc}") from exc

        # API 响应字段校验统一转成 ProviderResponseError。
        try:
            content = response_payload["choices"][0]["message"]["content"]
            model_key = response_payload.get("model") or self._model_key
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderResponseError("Model response is missing message content.") from exc

        # OpenAI-compatible API 的 content 必须是承载业务 JSON 的字符串。
        if not isinstance(content, str):
            raise ProviderResponseError("Model response content must be a JSON string.")

        # 此处验证 JSON 对象形状；模型输出的业务 Schema 由生成节点完成。
        parsed = parse_model_json_object(content)
        if not isinstance(parsed, dict):
            raise ProviderResponseError("Model response must be a JSON object.")

        # 到这里仅证明为 JSON 对象；具体字段是否合法由调用方对应的 Pydantic 模型决定。
        return ModelJsonResponse(payload=parsed, model_key=str(model_key))

    @staticmethod
    def _user_message_content(
        *,
        input_payload: dict[str, object],
        json_schema: dict[str, object],
        image_inputs: list[ModelImageInput],
    ) -> str | list[dict[str, object]]:
        """按是否带图片选择纯文本或多模态 user message 结构。"""

        # 文本输入与 schema 放在同一 JSON 文本中，使纯文本和多模态请求拥有相同语义。
        text_payload = json.dumps(
            {
                "input": input_payload,
                "required_output_schema": json_schema,
            },
            ensure_ascii=False,
        )
        # 无图片时遵循 chat-completions 的简单字符串 content 格式。
        if not image_inputs:
            return text_payload

        # 有图时转换为 content parts；先发字段描述，再按素材顺序附上图片和可追溯标签。
        content: list[dict[str, object]] = [{"type": "text", "text": text_payload}]
        for image in image_inputs:
            # 标签让模型能把一张像素图与 input_payload 中的 asset_id 对应。
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
    """解析模型返回的 JSON 对象，并兼容常见 Markdown 代码块残留。

    不使用宽松的字符串截取：``raw_decode`` 会返回结束位置，因此可拒绝 JSON 后夹带的
    解释性自然语言，避免节点意外忽略模型输出中的额外内容。
    """

    normalized = content.strip()
    # 即便请求了 json_object，部分兼容服务仍可能包一层 Markdown 代码块。
    if normalized.startswith("```"):
        normalized = normalized.split("\n", 1)[-1]
        normalized = normalized.rsplit("```", 1)[0].strip()

    decoder = json.JSONDecoder()
    try:
        parsed, end_index = decoder.raw_decode(normalized)
    except json.JSONDecodeError as exc:
        raise ProviderResponseError("Model response is not valid JSON.") from exc

    # 仅允许代码围栏残留；任意实质尾随文本都视为 Provider 协议错误。
    trailing = normalized[end_index:].strip()
    if trailing and trailing.strip("`").strip():
        raise ProviderResponseError("Model response is not valid JSON.")
    return parsed
