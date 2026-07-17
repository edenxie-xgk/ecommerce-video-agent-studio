"""定义应用用例调用创意 Agent 所需的输入 DTO、结果和依赖端口。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from pydantic import BaseModel, Field

from app.application.creative_decision import CreativeDecisionBundle


PHRASE_SEPARATOR_PATTERN = re.compile(r"[\n,，、;；]+")
PHRASE_TRIM_CHARS = " -。.!！?？"


def split_phrase_text(value: str) -> list[str]:
    """把用户在 textarea 中输入的中英文逗号、顿号、分号和换行统一拆成业务短语。"""

    return [
        part.strip(PHRASE_TRIM_CHARS)
        for part in PHRASE_SEPARATOR_PATTERN.split(value)
        if part.strip(PHRASE_TRIM_CHARS)
    ]


class CreativeProjectInput(BaseModel):
    """保存 Agent 使用的项目事实字段白名单。"""

    id: int | None = Field(default=None, description="项目 ID。")
    title: str = Field(description="项目标题。")
    target_platform: str = Field(description="目标内容平台。")
    language: str = Field(description="内容语言。")
    aspect_ratio: str = Field(description="目标视频画面比例。")
    duration_seconds: int = Field(description="目标视频时长，单位秒。")
    status: str = Field(description="项目当前业务状态。")


class CreativeBriefInput(BaseModel):
    """保存 Agent 可以使用的已确认商品资料。"""

    id: int | None = Field(default=None, description="商品资料 ID。")
    project_id: int = Field(description="所属项目 ID。")
    product_name: str = Field(description="用户确认的准确商品名称。")
    selling_points_text: str = Field(description="用户确认的商品卖点文本。")
    target_audience_text: str = Field(description="用户确认的目标人群文本。")
    brand_tone: str = Field(description="品牌语气或表达风格。")
    forbidden_words_text: str = Field(description="需要规避的风险表达。")

    def selling_points(self) -> list[str]:
        """返回可被 Agent 直接引用的已确认商品卖点列表。"""

        return split_phrase_text(self.selling_points_text)

    def target_audiences(self) -> list[str]:
        """返回可被 Agent 直接引用的已确认目标人群列表。"""

        return split_phrase_text(self.target_audience_text)

    def forbidden_words(self) -> list[str]:
        """返回质量门禁和模型 Prompt 都必须避开的风险表达。"""

        return split_phrase_text(self.forbidden_words_text)


class CreativeAssetInput(BaseModel):
    """保存 Agent 使用的素材证据引用。"""

    id: int | None = Field(default=None, description="素材 ID。")
    project_id: int = Field(description="所属项目 ID。")
    asset_type: str = Field(default="product_image", description="素材业务类型。")
    storage_key: str = Field(description="素材在后端存储中的稳定引用。")
    mime_type: str = Field(description="素材 MIME 类型。")
    size_bytes: int | None = Field(default=None, description="素材大小，单位字节。")
    asset_metadata: dict[str, object] = Field(
        default_factory=dict,
        description="素材附带的可序列化元数据。",
    )


class CreativeRunInput(BaseModel):
    """定义启动一次新 Agent 决策所需的完整应用输入。"""

    project: CreativeProjectInput = Field(description="本次运行所属的项目事实。")
    brief: CreativeBriefInput | None = Field(
        default=None,
        description="用户当前确认的商品资料。",
    )
    assets: list[CreativeAssetInput] = Field(
        default_factory=list,
        description="已验证且可用于镜头规划的商品图片引用。",
    )
    campaign_goal: str = Field(description="本次创意决策需要达成的营销目标。")

    def missing_required_agent_inputs(self) -> list[str]:
        """列出启动当前自动创意段前必须补齐的资料字段。"""

        missing: list[str] = []
        if self.brief is None:
            missing.extend(["product_name", "selling_points", "target_audience"])
        else:
            if not self.brief.product_name.strip():
                missing.append("product_name")
            if not self.brief.selling_points():
                missing.append("selling_points")
            if not self.brief.target_audiences():
                missing.append("target_audience")
        if not any(asset.asset_type == "product_image" for asset in self.assets):
            missing.append("product_images")
        return missing


@dataclass(frozen=True)
class CreativeAgentResult:
    """定义 Agent 实现返回给应用服务的最小运行结果。"""

    bundle: CreativeDecisionBundle
    provider_key: str
    model_key: str | None
    product_understanding_provider_key: str = "local"
    product_understanding_model_key: str | None = None
    execution_id: str | None = None


class CreativeAgentPort(Protocol):
    """隔离应用用例与 LangGraph、checkpoint 和模型 Provider。"""

    def run(
        self,
        run_input: CreativeRunInput,
        *,
        execution_id: str | None = None,
    ) -> CreativeAgentResult:
        """启动一次新决策；显式 execution_id 必须从未用于其他运行。"""

        ...
