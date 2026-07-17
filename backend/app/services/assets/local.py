from __future__ import annotations

import hashlib
import os
import warnings
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import BinaryIO
from uuid import uuid4

from PIL import Image
from sqlmodel import Session, select

from app.core.config import BACKEND_ROOT, Settings, get_settings
from app.models.project import ProjectAsset


# 上传文件按 1MB 分块读取，避免一次性把大文件放进内存。
READ_CHUNK_BYTES = 1024 * 1024

# Pillow 识别到的格式名 -> 对外 MIME 类型和最终落盘扩展名。
SUPPORTED_IMAGE_FORMATS: dict[str, tuple[str, str]] = {
    "JPEG": ("image/jpeg", ".jpg"),  # 常见照片和商品主图格式。
    "PNG": ("image/png", ".png"),  # 支持透明背景的商品图格式。
    "WEBP": ("image/webp", ".webp"),  # 体积更小的现代网页图片格式。
}

# 浏览器或客户端可能上报 image/jpg，服务端统一归一为标准 image/jpeg。
MIME_TYPE_ALIASES = {"image/jpg": "image/jpeg"}

# 本地文件写入和数据库记录创建需要串行，避免同一项目并发突破数量上限。
_UPLOAD_LOCK = Lock()


class AssetUploadError(ValueError):
    """所有可安全返回给 API 调用方的素材上传错误基类。"""


class UnsupportedAssetTypeError(AssetUploadError):
    """素材业务类型不在服务端白名单中。"""


class UnsupportedImageTypeError(AssetUploadError):
    """声明或检测到的图片格式不在服务端白名单中。"""


class InvalidImageError(AssetUploadError):
    """文件无法通过完整图片识别和解码校验。"""


class AssetTooLargeError(AssetUploadError):
    """上传内容超过单文件字节或解码像素上限。"""


class AssetCountLimitError(AssetUploadError):
    """项目已经达到有效商品图片数量上限。"""


@dataclass(frozen=True)
class UploadedAssetDraft:
    """API 上传文件转入素材服务的轻量输入。"""

    project_id: int
    asset_type: str
    filename: str | None
    mime_type: str | None


@dataclass(frozen=True)
class ValidatedImage:
    """完成格式、尺寸和像素解码校验后的图片事实。"""

    format_name: str
    mime_type: str
    extension: str
    width: int
    height: int


class LocalAssetService:
    """校验并持久化本地商品图片，保持文件与数据库记录一致。"""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        storage_path = Path(self._settings.asset_storage_path).expanduser()
        if not storage_path.is_absolute():
            storage_path = BACKEND_ROOT / storage_path
        self._storage_root = storage_path.resolve()

    def create_uploaded_asset(
        self,
        draft: UploadedAssetDraft,
        source: BinaryIO,
    ) -> ProjectAsset:
        """流式保存并验证图片，成功后才创建可供 Agent 使用的素材记录。"""

        self._validate_declared_type(draft)
        with _UPLOAD_LOCK:
            self._enforce_project_limit(draft.project_id)
            return self._persist_validated_image(draft, source)

    def delete_uploaded_assets(self, assets: list[ProjectAsset]) -> None:
        """删除本次请求已经保存的商品图片，保留用户重新提交的干净入口。"""

        if not assets:
            return
        for asset in assets:
            with suppress(FileNotFoundError):
                (self._storage_root / asset.storage_key).unlink()
            self._session.delete(asset)
        self._session.commit()

    def _validate_declared_type(self, draft: UploadedAssetDraft) -> None:
        """在读取文件前拒绝未知业务类型和非图片 MIME。"""

        if draft.asset_type != "product_image":
            raise UnsupportedAssetTypeError("只允许上传 product_image 类型的商品图片。")

        declared_mime = self._normalize_mime_type(draft.mime_type)
        allowed_mime_types = {item[0] for item in SUPPORTED_IMAGE_FORMATS.values()}
        if declared_mime is not None and declared_mime not in allowed_mime_types:
            raise UnsupportedImageTypeError("只支持 JPEG、PNG 或 WebP 商品图片。")

    def _enforce_project_limit(self, project_id: int) -> None:
        """只统计已经通过验证并可作为 Agent 证据的商品图片。"""

        existing_ids = self._session.exec(
            select(ProjectAsset.id)
            .where(ProjectAsset.project_id == project_id)
            .where(ProjectAsset.asset_type == "product_image")
        ).all()
        if len(existing_ids) >= self._settings.asset_max_files_per_project:
            raise AssetCountLimitError(
                f"每个项目最多保存 {self._settings.asset_max_files_per_project} 张商品图片。"
            )

    def _persist_validated_image(
        self,
        draft: UploadedAssetDraft,
        source: BinaryIO,
    ) -> ProjectAsset:
        """先写临时文件并完整解码，再原子落盘和提交数据库。"""

        temporary_dir = self._storage_root / ".tmp"
        temporary_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = temporary_dir / f"{uuid4().hex}.upload"
        final_path: Path | None = None

        try:
            size_bytes, sha256 = self._stream_to_temporary_file(source, temporary_path)
            image = self._validate_image_file(temporary_path, draft.mime_type)
            storage_key = self._storage_key(draft.project_id, image.extension)
            final_path = self._storage_root / storage_key
            final_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary_path, final_path)

            asset = ProjectAsset(
                project_id=draft.project_id,
                asset_type="product_image",
                storage_key=storage_key.as_posix(),
                mime_type=image.mime_type,
                size_bytes=size_bytes,
                asset_metadata={
                    "original_filename": self._safe_original_filename(draft.filename),
                    "verified": True,
                    "image_format": image.format_name,
                    "width": image.width,
                    "height": image.height,
                    "sha256": sha256,
                },
            )
            try:
                self._session.add(asset)
                self._session.commit()
            except Exception:
                self._session.rollback()
                with suppress(FileNotFoundError):
                    final_path.unlink()
                raise

            self._session.refresh(asset)
            return asset
        finally:
            with suppress(FileNotFoundError):
                temporary_path.unlink()

    def _stream_to_temporary_file(
        self,
        source: BinaryIO,
        destination: Path,
    ) -> tuple[int, str]:
        """分块写入并在越过配置上限时立即停止。"""

        size_bytes = 0
        digest = hashlib.sha256()
        with destination.open("xb") as output:
            while chunk := source.read(READ_CHUNK_BYTES):
                size_bytes += len(chunk)
                if size_bytes > self._settings.asset_max_bytes:
                    raise AssetTooLargeError(
                        f"商品图片不能超过 {self._settings.asset_max_bytes} 字节。"
                    )
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())

        if size_bytes == 0:
            raise InvalidImageError("上传文件不能为空。")
        return size_bytes, digest.hexdigest()

    def _validate_image_file(
        self,
        path: Path,
        declared_mime_type: str | None,
    ) -> ValidatedImage:
        """用 Pillow 识别格式、限制像素并完整解码图片数据。"""

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    format_name = image.format or ""
                    width, height = image.size
                    format_details = SUPPORTED_IMAGE_FORMATS.get(format_name)
                    if format_details is None:
                        raise UnsupportedImageTypeError("只支持 JPEG、PNG 或 WebP 商品图片。")
                    if width <= 0 or height <= 0:
                        raise InvalidImageError("图片尺寸无效。")
                    if width * height > self._settings.asset_max_image_pixels:
                        raise AssetTooLargeError(
                            f"商品图片不能超过 {self._settings.asset_max_image_pixels} 像素。"
                        )
                    image.verify()

                # verify 检查容器结构；重新打开并 load，确保像素流也可以完整解码。
                with Image.open(path) as decoded_image:
                    decoded_image.load()
                    if decoded_image.format != format_name or decoded_image.size != (width, height):
                        raise InvalidImageError("图片解码结果不一致。")
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise AssetTooLargeError(
                f"商品图片不能超过 {self._settings.asset_max_image_pixels} 像素。"
            ) from exc
        except AssetUploadError:
            raise
        except (OSError, SyntaxError, ValueError) as exc:
            raise InvalidImageError("文件不是完整、可解码的商品图片。") from exc

        detected_mime, extension = format_details
        declared_mime = self._normalize_mime_type(declared_mime_type)
        if declared_mime is not None and declared_mime != detected_mime:
            raise UnsupportedImageTypeError("声明的 MIME 类型与图片实际格式不一致。")

        return ValidatedImage(
            format_name=format_name,
            mime_type=detected_mime,
            extension=extension,
            width=width,
            height=height,
        )

    @staticmethod
    def _storage_key(project_id: int, extension: str) -> Path:
        """使用不可预测 UUID 文件名，避免信任客户端路径和扩展名。"""

        return Path("projects") / str(project_id) / "uploads" / f"{uuid4().hex}{extension}"

    @staticmethod
    def _normalize_mime_type(value: str | None) -> str | None:
        """规范浏览器可能发送的 MIME 别名并移除参数。"""

        if value is None:
            return None
        normalized = value.split(";", 1)[0].strip().lower()
        return MIME_TYPE_ALIASES.get(normalized, normalized) or None

    @staticmethod
    def _safe_original_filename(value: str | None) -> str | None:
        """原始名称只作展示元数据，移除路径和控制字符并限制长度。"""

        if value is None:
            return None
        basename = Path(value.replace("\\", "/")).name
        cleaned = "".join(character for character in basename if ord(character) >= 32).strip()
        return cleaned[:255] or None
