from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# 后端项目根目录；相对路径配置都以这里为基准解析。
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """应用配置；未配置模型时使用内置决策器。"""

    database_url: str = Field(
        default=f"sqlite:///{(BACKEND_ROOT / 'var' / 'app.sqlite3').as_posix()}",
        description="业务数据库连接地址；生产环境应配置为 PostgreSQL。",
    )
    llm_base_url: str | None = Field(
        default=None,
        description="OpenAI-compatible API 根地址，例如 https://api.openai.com/v1。",
    )
    llm_api_key: str | None = Field(default=None, description="模型 Provider API 密钥。")
    llm_model: str | None = Field(default=None, description="用于结构化创意生成的模型名称。")
    llm_timeout_seconds: int = Field(
        default=45,
        ge=5,
        le=180,
        description="单次模型请求超时时间，单位秒。",
    )
    langgraph_checkpoint_path: str = Field(
        default=(BACKEND_ROOT / "var" / "creative_agent_checkpoints.sqlite3").as_posix(),
        description="LangGraph SQLite checkpoint 文件路径。",
    )
    asset_storage_path: str = Field(
        default=(BACKEND_ROOT / "var" / "assets").as_posix(),
        description="本地商品素材文件的持久化根目录。",
    )
    asset_max_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1024,
        le=100 * 1024 * 1024,
        description="单个商品图片允许上传的最大字节数。",
    )
    asset_max_files_per_project: int = Field(
        default=5,
        ge=1,
        le=50,
        description="单个项目允许保存的有效商品图片数量上限。",
    )
    asset_max_image_pixels: int = Field(
        default=25_000_000,
        ge=1,
        le=200_000_000,
        description="单个商品图片解码后允许包含的最大像素数。",
    )

    model_config = SettingsConfigDict(
        env_prefix="EVAS_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """读取并缓存后端配置。"""

    return Settings()


def ensure_local_var_dir() -> None:
    """确保本地持久化文件目录存在。"""

    (BACKEND_ROOT / "var").mkdir(parents=True, exist_ok=True)
