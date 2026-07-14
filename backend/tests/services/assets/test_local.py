from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import Settings
from app.models.project import ProjectAsset, VideoProject
from app.services.assets.local import (
    AssetCountLimitError,
    AssetTooLargeError,
    InvalidImageError,
    LocalAssetService,
    UnsupportedImageTypeError,
    UploadedAssetDraft,
)


def _image_bytes(
    *,
    image_format: str = "PNG",
    size: tuple[int, int] = (16, 12),
) -> bytes:
    image = Image.new("RGB", size, color=(42, 115, 99))
    content = BytesIO()
    image.save(content, format=image_format)
    return content.getvalue()


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as database_session:
        database_session.add(VideoProject(id=1, title="Asset test"))
        database_session.commit()
        yield database_session


def _settings(storage_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "sqlite://",
        "asset_storage_path": str(storage_path),
        "asset_max_bytes": 10 * 1024 * 1024,
        "asset_max_files_per_project": 5,
        "asset_max_image_pixels": 25_000_000,
    }
    values.update(overrides)
    return Settings(**values)


def _draft(*, mime_type: str = "image/png") -> UploadedAssetDraft:
    return UploadedAssetDraft(
        project_id=1,
        asset_type="product_image",
        filename="../catalog/product.png",
        mime_type=mime_type,
    )


def test_valid_image_is_persisted_with_verified_metadata(
    session: Session,
    tmp_path: Path,
) -> None:
    content = _image_bytes()
    service = LocalAssetService(session, _settings(tmp_path))

    asset = service.create_uploaded_asset(_draft(), BytesIO(content))

    stored_path = tmp_path / asset.storage_key
    assert stored_path.read_bytes() == content
    assert stored_path.suffix == ".png"
    assert stored_path.name != "product.png"
    assert asset.mime_type == "image/png"
    assert asset.size_bytes == len(content)
    assert asset.asset_metadata["original_filename"] == "product.png"
    assert asset.asset_metadata["verified"] is True
    assert asset.asset_metadata["width"] == 16
    assert asset.asset_metadata["height"] == 12
    assert len(str(asset.asset_metadata["sha256"])) == 64


@pytest.mark.parametrize(
    ("content", "error_type"),
    ((b"", InvalidImageError), (b"not an image", InvalidImageError)),
)
def test_invalid_image_is_rejected_without_leaving_files(
    session: Session,
    tmp_path: Path,
    content: bytes,
    error_type: type[Exception],
) -> None:
    service = LocalAssetService(session, _settings(tmp_path))

    with pytest.raises(error_type):
        service.create_uploaded_asset(_draft(), BytesIO(content))

    assert list(session.exec(select(ProjectAsset)).all()) == []
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


def test_declared_mime_must_match_detected_image(
    session: Session,
    tmp_path: Path,
) -> None:
    service = LocalAssetService(session, _settings(tmp_path))

    with pytest.raises(UnsupportedImageTypeError):
        service.create_uploaded_asset(
            _draft(mime_type="image/jpeg"),
            BytesIO(_image_bytes(image_format="PNG")),
        )


def test_byte_and_pixel_limits_are_enforced(
    session: Session,
    tmp_path: Path,
) -> None:
    content = _image_bytes(size=(64, 64))
    byte_limited = LocalAssetService(
        session,
        _settings(tmp_path / "bytes", asset_max_bytes=1024),
    )
    pixel_limited = LocalAssetService(
        session,
        _settings(tmp_path / "pixels", asset_max_image_pixels=1000),
    )

    with pytest.raises(AssetTooLargeError):
        byte_limited.create_uploaded_asset(_draft(), BytesIO(content + b"x" * 1024))
    with pytest.raises(AssetTooLargeError):
        pixel_limited.create_uploaded_asset(_draft(), BytesIO(content))


def test_project_image_count_limit_is_enforced(
    session: Session,
    tmp_path: Path,
) -> None:
    service = LocalAssetService(
        session,
        _settings(tmp_path, asset_max_files_per_project=1),
    )
    content = _image_bytes()
    service.create_uploaded_asset(_draft(), BytesIO(content))

    with pytest.raises(AssetCountLimitError):
        service.create_uploaded_asset(_draft(), BytesIO(content))

    assets = list(session.exec(select(ProjectAsset)).all())
    assert len(assets) == 1


def test_database_failure_removes_persisted_file(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = LocalAssetService(session, _settings(tmp_path))

    def fail_commit() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="database unavailable"):
        service.create_uploaded_asset(_draft(), BytesIO(_image_bytes()))

    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []
