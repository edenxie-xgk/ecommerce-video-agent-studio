from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import CreativeRunServiceDep, SessionDep
from app.api.schemas import (
    CreativeRunResponse,
    ProductBriefPayload,
    ProductBriefResponse,
    ProjectAssetResponse,
    ProjectCreatePayload,
    ProjectResponse,
)
from app.models.creative import WorkflowRun
from app.models.project import ProductBrief, ProjectAsset, VideoProject
from app.services.assets.local import (
    AssetCountLimitError,
    AssetTooLargeError,
    InvalidImageError,
    LocalAssetService,
    UnsupportedAssetTypeError,
    UnsupportedImageTypeError,
    UploadedAssetDraft,
)
from app.application.creative_runs import CreativeRunService
from app.services.projects import ProductBriefInput, ProjectCreateInput, ProjectService


router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/projects")
def list_projects(session: SessionDep) -> list[ProjectResponse]:
    service = ProjectService(session)
    return [_project_to_response(service, project) for project in service.list_projects()]


@router.post("/projects")
def create_project(
    payload: ProjectCreatePayload,
    session: SessionDep,
) -> ProjectResponse:
    service = ProjectService(session)
    project = service.create_project(
        ProjectCreateInput(
            title=payload.title,
            target_platform=payload.target_platform,
            product_brief=(
                _to_product_brief_input(payload.product_brief) if payload.product_brief else None
            ),
        )
    )
    return _project_to_response(service, project)


@router.get("/projects/{project_id}/assets")
def list_assets(
    project_id: int,
    session: SessionDep,
) -> list[ProjectAssetResponse]:
    service = ProjectService(session)
    _get_project_or_404(service, project_id)
    return [_asset_to_response(asset) for asset in service.list_assets(project_id)]


@router.post("/projects/{project_id}/creative-runs")
def create_creative_run(
    project_id: int,
    session: SessionDep,
    service: CreativeRunServiceDep,
    campaign_goal: str = Form(
        default="让目标用户快速理解商品价值，并愿意进一步查看商品详情",
        max_length=500,
    ),
    product_name: str | None = Form(default=None),
    selling_points_text: str = Form(default=""),
    target_audience_text: str = Form(default=""),
    brand_tone: str = Form(default=""),
    forbidden_words_text: str = Form(default=""),
    product_images: list[UploadFile] = File(...),
) -> CreativeRunResponse:
    project_service = ProjectService(session)
    _get_project_or_404(project_service, project_id)

    if not product_images:
        raise HTTPException(status_code=400, detail="请至少上传一张商品图片。")

    asset_service = LocalAssetService(session)
    created_assets: list[ProjectAsset] = []
    try:
        project_service.upsert_product_brief(
            project_id,
            ProductBriefInput(
                product_name=product_name,
                selling_points_text=selling_points_text,
                target_audience_text=target_audience_text,
                brand_tone=brand_tone,
                forbidden_words_text=forbidden_words_text,
            ),
        )
        for file in product_images:
            created_assets.append(
                asset_service.create_uploaded_asset(
                    UploadedAssetDraft(
                        project_id=project_id,
                        asset_type="product_image",
                        filename=file.filename,
                        mime_type=file.content_type,
                    ),
                    file.file,
                )
            )
        run = service.generate(
            project_id=project_id,
            campaign_goal=campaign_goal,
        )
    except UnsupportedAssetTypeError as exc:
        asset_service.delete_uploaded_assets(created_assets)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnsupportedImageTypeError as exc:
        asset_service.delete_uploaded_assets(created_assets)
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except AssetTooLargeError as exc:
        asset_service.delete_uploaded_assets(created_assets)
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except AssetCountLimitError as exc:
        asset_service.delete_uploaded_assets(created_assets)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidImageError as exc:
        asset_service.delete_uploaded_assets(created_assets)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        asset_service.delete_uploaded_assets(created_assets)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        asset_service.delete_uploaded_assets(created_assets)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        asset_service.delete_uploaded_assets(created_assets)
        raise
    finally:
        for file in product_images:
            file.file.close()
    return _creative_run_to_response(run)


@router.get("/projects/{project_id}/creative-runs")
def list_creative_runs(
    project_id: int,
    session: SessionDep,
    service: CreativeRunServiceDep,
) -> list[CreativeRunResponse]:
    _get_project_or_404(ProjectService(session), project_id)
    return [_creative_run_to_response(run) for run in service.list_for_project(project_id)]


def _to_product_brief_input(payload: ProductBriefPayload) -> ProductBriefInput:
    return ProductBriefInput(
        product_name=payload.product_name,
        selling_points_text=payload.selling_points_text,
        target_audience_text=payload.target_audience_text,
        brand_tone=payload.brand_tone,
        forbidden_words_text=payload.forbidden_words_text,
    )


def _get_project_or_404(
    service: ProjectService,
    project_id: int,
) -> VideoProject:
    project = service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"找不到项目：{project_id}")
    return project


def _project_to_response(
    service: ProjectService,
    project: VideoProject,
) -> ProjectResponse:
    brief = service.get_product_brief(project.id or 0)
    return ProjectResponse(
        id=project.id or 0,
        title=project.title,
        target_platform=project.target_platform,
        language=project.language,
        aspect_ratio=project.aspect_ratio,
        duration_seconds=project.duration_seconds,
        status=project.status,
        product_brief=_brief_to_response(brief) if brief else None,
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
    )


def _brief_to_response(brief: ProductBrief) -> ProductBriefResponse:
    return ProductBriefResponse(
        id=brief.id or 0,
        project_id=brief.project_id,
        product_name=brief.product_name,
        selling_points_text=brief.selling_points_text,
        target_audience_text=brief.target_audience_text,
        brand_tone=brief.brand_tone,
        forbidden_words_text=brief.forbidden_words_text,
    )


def _asset_to_response(asset: ProjectAsset) -> ProjectAssetResponse:
    metadata = asset.asset_metadata or {}
    original_filename = metadata.get("original_filename")
    return ProjectAssetResponse(
        id=asset.id or 0,
        project_id=asset.project_id,
        type=asset.asset_type,
        file_path=asset.storage_key,
        original_filename=(original_filename if isinstance(original_filename, str) else None),
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        created_at=asset.created_at.isoformat(),
    )


def _creative_run_to_response(run: WorkflowRun) -> CreativeRunResponse:
    campaign_goal = CreativeRunService.campaign_goal(run)
    result = CreativeRunService.parse_result(run)
    error_message = run.error_message
    if (run.run_metadata or {}).get("decision_payload") is not None and result is None:
        error_message = "历史创意结果与当前契约不兼容，请重新生成。"
    return CreativeRunResponse(
        id=run.id or 0,
        project_id=run.project_id,
        campaign_goal=campaign_goal,
        status=CreativeRunService.public_status(run),
        action=CreativeRunService.action(run),
        confidence=CreativeRunService.confidence(run),
        provider=CreativeRunService.provider_key(run),
        model=CreativeRunService.model_key(run),
        revision_count=CreativeRunService.revision_count(run),
        result=result,
        started_at=run.started_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        error_message=error_message,
    )
