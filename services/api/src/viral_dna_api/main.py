from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError

from . import __version__
from .ai.billing import cny_to_micros, summarize_model_runs
from .ai.catalog import ModelCatalogError, default_analysis_profile, load_model_plan
from .asset_library import AssetLibraryService
from .asset_routes import create_asset_router
from .chinese import to_simplified
from .exports import ExportService
from .image_generation import (
    ImageGenerationGateway,
    ImageGenerationSettingsService,
    ImageGenerationSettingsServiceError,
)
from .link_ingestion import LinkIngestionError, identify_platform
from .media import get_analysis_artifact_root
from .model_settings import ModelSettingsService, ModelSettingsServiceError
from .models import (
    AnalysisCostSummary,
    AnalysisCreate,
    AnalysisJob,
    AnalysisMode,
    AnalysisRecord,
    AnalysisRecordDetail,
    AnalysisRecordList,
    AnalysisRecordSummary,
    AnalysisRecordUpdate,
    AnalysisReport,
    AnalysisStage,
    CandidateActionResponse,
    CandidateApprovalRequest,
    CandidateSelectRequest,
    ChangeImpactRequest,
    ChangeImpactResponse,
    EditingHandoffManifest,
    ExportArtifact,
    ExportCreate,
    ExportKind,
    FolderCreate,
    FolderUpdate,
    GenerationRunResponse,
    HealthResponse,
    ImageGenerationCreate,
    ImageGenerationSettingsResponse,
    ImageGenerationSettingsUpdate,
    LinkVideoCreate,
    LocalCodexAutoConfigureRequest,
    LocalCodexDiscoveryResponse,
    LocalCodexNetworkTestRequest,
    LocalCodexNetworkTestResponse,
    LocalCodexSandboxTestRequest,
    LocalCodexSandboxTestResponse,
    LocalImageToolDetectRequest,
    LocalImageToolDetectResponse,
    ModelRun,
    ModelSettingsResponse,
    ModelSettingsUpdate,
    ProductionAdvanceRequest,
    ProductionBranchCreate,
    ProductionGateStatus,
    ProductionProject,
    ProductionProjectCreate,
    ProductionProjectDetail,
    ProductionProjectUpdate,
    ProductionRevisionDetail,
    ProductionRevisionResponse,
    ProjectAssetLinkCreate,
    RecordFolder,
    ReferenceAssetCreate,
    ReferenceAssetResponse,
    ReferenceAssetType,
    ReferenceAssetUpdate,
    ReplacementCreate,
    ReplacementVersion,
    ShotImageApprovalRevokeRequest,
    ShotKeyframeSelectRequest,
    ShotLifecycleUpdate,
    ShotPlanBulkUpdate,
    ShotPlanCreate,
    ShotPlanDetailResponse,
    ShotPlanReorder,
    ShotPlanResponse,
    ShotPlanUpdate,
    ShotSourceFrameApprovalRequest,
    ShotVideoApprovalRevokeRequest,
    SourceType,
    Video,
    VideoClipPreparationResponse,
    VideoClipPreparationUpdate,
    VideoCostEstimateRequest,
    VideoCostEstimateResponse,
    VideoGenerationCreate,
    VideoGenerationSettingsResponse,
    VideoGenerationSettingsUpdate,
    VideoProviderValidationRequest,
    VideoProviderValidationResponse,
    VideoStatus,
    WorkspaceInfo,
    WorkspacePathRequest,
    WorkspaceValidationResponse,
)
from .notifications import (
    AccountNotification,
    NotificationListResponse,
    NotificationReadAllResponse,
    NotificationServiceError,
    NotificationStatus,
    create_notification_service,
)
from .pipeline import create_replacement_version
from .production import (
    MAX_REFERENCE_IMAGE_BYTES,
    ProductionService,
    ProductionServiceError,
)
from .project_assets import ProjectAssetService
from .real_pipeline import HybridAnalysisPipeline
from .records import RecordService, resolve_video_path, write_source_metadata
from .storage_objects import StorageManager
from .store import store
from .thumbnails import thumbnail_etag, thumbnail_service
from .video_generation import VideoGenerationGateway
from .video_generation.settings import (
    VideoGenerationSettingsService,
    VideoGenerationSettingsServiceError,
)
from .workspace import WORKSPACE_SCHEMA_VERSION, WorkspaceError, workspace_manager
from .workspace_catalog import (
    Account,
    AccountCatalogError,
    AccountContextResponse,
    ActiveWorkspaceRequest,
    StorageLocation,
    WorkspaceListItem,
    WorkspaceLocalRegisterRequest,
    create_account_context_service,
)

API_PREFIX = "/api/v1"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm"}
ALLOWED_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "application/octet-stream",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_cors_origins() -> list[str]:
    value = os.getenv(
        "VIRAL_DNA_CORS_ORIGINS",
        "http://127.0.0.1:4174,http://localhost:4174,http://localhost:5173",
    )
    return [origin.strip() for origin in value.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await account_context_service.ensure_current()
    await notification_service.initialize()
    await project_asset_service.bootstrap_legacy_references()
    await record_service.bootstrap(recover_interrupted=True)
    await production_service.recover_generation_runs()
    try:
        yield
    finally:
        await production_service.shutdown_generation_runs()


app = FastAPI(
    title="ViralDNA API",
    version=__version__,
    description="Phase 1 single-video analysis orchestration API",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = HybridAnalysisPipeline(store)
model_settings_service = ModelSettingsService()
image_generation_settings_service = ImageGenerationSettingsService()
video_generation_settings_service = VideoGenerationSettingsService()
record_service = RecordService(store)
export_service = ExportService(store)
image_generation_gateway = ImageGenerationGateway(
    workspace_manager,
    image_generation_settings_service,
    repository=store,
)
video_generation_gateway = VideoGenerationGateway(
    workspace_manager,
    settings_service=video_generation_settings_service,
    repository=store,
)
account_context_service = create_account_context_service(workspace_manager)
notification_service = create_notification_service(account_context_service)
storage_manager = StorageManager(store, workspace_manager)
asset_library_service = AssetLibraryService(store, storage_manager, account_context_service)
project_asset_service = ProjectAssetService(
    store, workspace_manager, storage_manager, account_context_service
)
production_service = ProductionService(
    store,
    workspace_manager,
    image_generation_gateway,
    project_assets=project_asset_service,
    video_gateway=video_generation_gateway,
    notification_publisher=notification_service,
)
app.include_router(create_asset_router(asset_library_service), prefix=API_PREFIX)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(analyzer_mode=os.getenv("VIRAL_DNA_ANALYZER_MODE", "hybrid"))


@app.get(f"{API_PREFIX}/settings/model", response_model=ModelSettingsResponse)
async def get_model_settings() -> ModelSettingsResponse:
    try:
        return model_settings_service.get()
    except ModelSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.put(f"{API_PREFIX}/settings/model", response_model=ModelSettingsResponse)
async def update_model_settings(payload: ModelSettingsUpdate) -> ModelSettingsResponse:
    try:
        return await model_settings_service.update(payload)
    except ModelSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(
    f"{API_PREFIX}/settings/image-generation",
    response_model=ImageGenerationSettingsResponse,
)
async def get_image_generation_settings() -> ImageGenerationSettingsResponse:
    try:
        return image_generation_settings_service.get()
    except ImageGenerationSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.put(
    f"{API_PREFIX}/settings/image-generation",
    response_model=ImageGenerationSettingsResponse,
)
async def update_image_generation_settings(
    payload: ImageGenerationSettingsUpdate,
) -> ImageGenerationSettingsResponse:
    try:
        return await image_generation_settings_service.update(payload)
    except ImageGenerationSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/settings/image-generation/detect-local",
    response_model=LocalImageToolDetectResponse,
)
async def detect_local_image_tool(
    payload: LocalImageToolDetectRequest,
) -> LocalImageToolDetectResponse:
    try:
        return await image_generation_settings_service.detect_local(payload)
    except ImageGenerationSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/settings/image-generation/discover-local-codex",
    response_model=LocalCodexDiscoveryResponse,
)
async def discover_local_codex() -> LocalCodexDiscoveryResponse:
    try:
        return await image_generation_settings_service.discover_codex()
    except ImageGenerationSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/settings/image-generation/test-local-network",
    response_model=LocalCodexNetworkTestResponse,
)
async def test_local_codex_network(
    payload: LocalCodexNetworkTestRequest,
) -> LocalCodexNetworkTestResponse:
    try:
        return await image_generation_settings_service.test_codex_network(payload)
    except ImageGenerationSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/settings/image-generation/auto-configure-codex",
    response_model=ImageGenerationSettingsResponse,
)
async def auto_configure_local_codex(
    payload: LocalCodexAutoConfigureRequest,
) -> ImageGenerationSettingsResponse:
    try:
        return await image_generation_settings_service.auto_configure_codex(payload)
    except ImageGenerationSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(f"{API_PREFIX}/context", response_model=AccountContextResponse)
async def get_account_context() -> AccountContextResponse:
    try:
        return await account_context_service.ensure_current()
    except AccountCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(f"{API_PREFIX}/accounts/current", response_model=Account)
async def get_current_account() -> Account:
    try:
        return await account_context_service.current_account()
    except AccountCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(f"{API_PREFIX}/workspaces", response_model=list[WorkspaceListItem])
async def list_registered_workspaces() -> list[WorkspaceListItem]:
    try:
        return await account_context_service.list_workspaces()
    except AccountCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/workspaces/validate-local",
    response_model=WorkspaceValidationResponse,
)
async def validate_local_workspace(
    payload: WorkspacePathRequest,
) -> WorkspaceValidationResponse:
    return workspace_manager.validate(payload.path)


@app.post(
    f"{API_PREFIX}/workspaces/register-local",
    response_model=WorkspaceListItem,
    status_code=status.HTTP_201_CREATED,
)
async def register_local_workspace(
    payload: WorkspaceLocalRegisterRequest,
) -> WorkspaceListItem:
    try:
        return await account_context_service.register_local(payload.path, name=payload.name)
    except AccountCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.put(
    f"{API_PREFIX}/context/active-workspace",
    response_model=AccountContextResponse,
)
async def activate_registered_workspace(
    payload: ActiveWorkspaceRequest,
) -> AccountContextResponse:
    try:
        context = await account_context_service.activate_workspace(payload.workspace_id, store)
        await record_service.bootstrap(recover_interrupted=True)
        return context
    except AccountCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(
    f"{API_PREFIX}/workspaces/{{workspace_id}}/storage-locations",
    response_model=list[StorageLocation],
)
async def list_workspace_storage_locations(
    workspace_id: UUID,
) -> list[StorageLocation]:
    try:
        return await account_context_service.list_storage_locations(workspace_id)
    except AccountCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


async def workspace_info() -> WorkspaceInfo:
    records = await store.list_records()
    folders = await store.list_folders()
    return WorkspaceInfo(
        root_path=str(workspace_manager.root),
        database_path=str(workspace_manager.database_path),
        schema_version=WORKSPACE_SCHEMA_VERSION,
        record_count=len(records),
        folder_count=len(folders),
    )


@app.get(f"{API_PREFIX}/workspace", response_model=WorkspaceInfo)
async def get_workspace() -> WorkspaceInfo:
    return await workspace_info()


@app.post(f"{API_PREFIX}/workspace/validate", response_model=WorkspaceValidationResponse)
async def validate_workspace(payload: WorkspacePathRequest) -> WorkspaceValidationResponse:
    return workspace_manager.validate(payload.path)


@app.put(f"{API_PREFIX}/workspace", response_model=WorkspaceInfo)
async def update_workspace(payload: WorkspacePathRequest) -> WorkspaceInfo:
    validation = workspace_manager.validate(payload.path)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.error or "工作区不可用")
    try:
        await account_context_service.activate_local_path(validation.normalized_path, store)
        await record_service.bootstrap(recover_interrupted=True)
    except AccountCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return await workspace_info()


def normalize_name(value: str, *, fallback: str | None = None) -> str:
    cleaned = " ".join((to_simplified(value) or "").split()).strip()
    if not cleaned and fallback is not None:
        return fallback
    if not cleaned:
        raise HTTPException(status_code=422, detail="名称不能为空")
    return cleaned


def parse_reference_tags(value: str | None) -> list[str]:
    if not value or not value.strip():
        return []
    text = value.strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="参考资产标签 JSON 格式无效") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise HTTPException(status_code=422, detail="参考资产标签必须是字符串数组")
        return parsed
    return [item.strip() for item in re.split(r"[,，\n]", text) if item.strip()]


@app.post(
    f"{API_PREFIX}/records/{{record_id}}/productions",
    response_model=ProductionProjectDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_production(
    record_id: UUID,
    payload: ProductionProjectCreate,
) -> ProductionProjectDetail:
    try:
        return await production_service.create_project(record_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(
    f"{API_PREFIX}/records/{{record_id}}/productions",
    response_model=list[ProductionProject],
)
async def list_productions(record_id: UUID) -> list[ProductionProject]:
    try:
        return await production_service.list_projects(record_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(
    f"{API_PREFIX}/productions/{{project_id}}",
    response_model=ProductionProjectDetail,
)
async def get_production(project_id: UUID) -> ProductionProjectDetail:
    try:
        return await production_service.get_project(project_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.patch(
    f"{API_PREFIX}/productions/{{project_id}}",
    response_model=ProductionProjectDetail,
)
async def update_production(
    project_id: UUID,
    payload: ProductionProjectUpdate,
) -> ProductionProjectDetail:
    try:
        return await production_service.update_project(project_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/productions/{{project_id}}/branches",
    response_model=ProductionProjectDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_production_branch(
    project_id: UUID,
    payload: ProductionBranchCreate,
) -> ProductionProjectDetail:
    try:
        return await production_service.create_branch(project_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(
    f"{API_PREFIX}/productions/{{project_id}}/revisions",
    response_model=list[ProductionRevisionResponse],
)
async def list_production_revisions(
    project_id: UUID,
) -> list[ProductionRevisionResponse]:
    try:
        return await production_service.list_revisions(project_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(
    f"{API_PREFIX}/productions/{{project_id}}/revisions/{{revision_id}}",
    response_model=ProductionRevisionDetail,
)
async def get_production_revision(
    project_id: UUID,
    revision_id: UUID,
) -> ProductionRevisionDetail:
    try:
        return await production_service.get_revision(project_id, revision_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/productions/{{project_id}}/references",
    response_model=ReferenceAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_production_reference(
    project_id: UUID,
    file: Annotated[UploadFile, File()],
    expected_revision_id: Annotated[UUID, Form()],
    asset_type: Annotated[ReferenceAssetType, Form(alias="type")],
    name: Annotated[str | None, Form()] = None,
    description: Annotated[str, Form()] = "",
    tags: Annotated[str | None, Form()] = None,
    rights_confirmed: Annotated[bool, Form()] = False,
    rights_note: Annotated[str | None, Form()] = None,
) -> ReferenceAssetResponse:
    filename = file.filename or ""
    fallback_name = Path(filename).stem.strip() or "参考图片"
    content = bytearray()
    try:
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > MAX_REFERENCE_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="参考图片不能超过 15 MB")
    finally:
        await file.close()
    try:
        payload = ReferenceAssetCreate(
            expected_revision_id=expected_revision_id,
            type=asset_type,
            name=name or fallback_name,
            description=description,
            tags=parse_reference_tags(tags),
            rights_confirmed=rights_confirmed,
            rights_note=rights_note,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="参考资产信息无效") from exc
    try:
        return await production_service.create_reference(
            project_id,
            payload,
            bytes(content),
            file.content_type,
            filename,
        )
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

@app.post(
    f"{API_PREFIX}/productions/{{project_id}}/assets/{{asset_id}}/link",
    response_model=ReferenceAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def link_production_asset(
    project_id: UUID,
    asset_id: UUID,
    payload: ProjectAssetLinkCreate,
) -> ReferenceAssetResponse:
    try:
        return await production_service.link_reference(
            project_id,
            asset_id,
            payload.expected_revision_id,
            payload.type,
        )
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc



@app.get(
    f"{API_PREFIX}/productions/{{project_id}}/references",
    response_model=list[ReferenceAssetResponse],
)
async def list_production_references(
    project_id: UUID,
    include_archived: Annotated[bool, Query()] = False,
) -> list[ReferenceAssetResponse]:
    try:
        return await production_service.list_references(
            project_id,
            include_archived=include_archived,
        )
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.patch(
    f"{API_PREFIX}/references/{{asset_id}}",
    response_model=ReferenceAssetResponse,
)
async def update_production_reference(
    asset_id: UUID,
    payload: ReferenceAssetUpdate,
    project_id: Annotated[UUID | None, Query()] = None,
) -> ReferenceAssetResponse:
    try:
        return await production_service.update_reference(
            asset_id, payload, project_id=project_id
        )
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.delete(
    f"{API_PREFIX}/references/{{asset_id}}",
    response_model=ReferenceAssetResponse,
)
async def archive_production_reference(
    asset_id: UUID,
    expected_revision_id: Annotated[UUID, Query()],
    confirm_stale: Annotated[bool, Query()] = False,
    project_id: Annotated[UUID | None, Query()] = None,
) -> ReferenceAssetResponse:
    try:
        return await production_service.archive_reference(
            asset_id,
            expected_revision_id,
            confirm_stale=confirm_stale,
            project_id=project_id,
        )
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(f"{API_PREFIX}/references/{{asset_id}}/content")
async def get_production_reference_content(asset_id: UUID) -> FileResponse:
    try:
        path, media_type = await production_service.resolve_reference_content(asset_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=media_type,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get(f"{API_PREFIX}/references/{{asset_id}}/thumbnail")
async def get_production_reference_thumbnail(asset_id: UUID) -> FileResponse:
    try:
        path, media_type = await production_service.resolve_reference_content(
            asset_id,
            thumbnail=True,
        )
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=media_type,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get(
    f"{API_PREFIX}/productions/{{project_id}}/shots",
    response_model=list[ShotPlanResponse],
)
async def list_production_shots(project_id: UUID) -> list[ShotPlanResponse]:
    try:
        return await production_service.list_shots(project_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/productions/{{project_id}}/shots",
    response_model=ShotPlanDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_production_shot(
    project_id: UUID,
    payload: ShotPlanCreate,
) -> ShotPlanDetailResponse:
    try:
        return await production_service.create_shot(project_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.put(
    f"{API_PREFIX}/productions/{{project_id}}/shots/order",
    response_model=list[ShotPlanResponse],
)
async def reorder_production_shots(
    project_id: UUID,
    payload: ShotPlanReorder,
) -> list[ShotPlanResponse]:
    try:
        return await production_service.reorder_shots(project_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(f"{API_PREFIX}/productions/{{project_id}}/source-video")
async def get_production_source_video(project_id: UUID) -> FileResponse:
    try:
        path, media_type = await production_service.resolve_source_video(project_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=media_type,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get(
    f"{API_PREFIX}/production-shots/{{shot_plan_id}}",
    response_model=ShotPlanDetailResponse,
)
async def get_production_shot(shot_plan_id: UUID) -> ShotPlanDetailResponse:
    try:
        return await production_service.get_shot(shot_plan_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.put(
    f"{API_PREFIX}/production-shots/{{shot_plan_id}}/video-preparation",
    response_model=VideoClipPreparationResponse,
)
async def prepare_production_video_clip(
    shot_plan_id: UUID,
    payload: VideoClipPreparationUpdate,
) -> VideoClipPreparationResponse:
    try:
        return await production_service.prepare_video_clip(shot_plan_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(f"{API_PREFIX}/production-shots/{{shot_plan_id}}/video-preparation/cover")
async def get_production_video_preparation_cover(shot_plan_id: UUID) -> FileResponse:
    try:
        path, media_type = await production_service.resolve_video_preparation_cover(shot_plan_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=media_type,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.patch(
    f"{API_PREFIX}/production-shots/{{shot_plan_id}}",
    response_model=ShotPlanDetailResponse,
)
async def update_production_shot(
    shot_plan_id: UUID,
    payload: ShotPlanUpdate,
) -> ShotPlanDetailResponse:
    try:
        return await production_service.update_shot(shot_plan_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/production-shots/{{shot_plan_id}}/discard",
    response_model=list[ShotPlanResponse],
)
async def discard_production_shot(
    shot_plan_id: UUID,
    payload: ShotLifecycleUpdate,
) -> list[ShotPlanResponse]:
    try:
        return await production_service.discard_shot(shot_plan_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/production-shots/{{shot_plan_id}}/restore",
    response_model=list[ShotPlanResponse],
)
async def restore_production_shot(
    shot_plan_id: UUID,
    payload: ShotLifecycleUpdate,
) -> list[ShotPlanResponse]:
    try:
        return await production_service.restore_shot(shot_plan_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(f"{API_PREFIX}/production-shots/{{shot_plan_id}}/source-keyframe")
async def get_production_source_keyframe(shot_plan_id: UUID) -> FileResponse:
    try:
        path, media_type = await production_service.resolve_source_keyframe_content(shot_plan_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=media_type,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post(
    f"{API_PREFIX}/production-shots/{{shot_plan_id}}/source-keyframe",
    response_model=ShotPlanDetailResponse,
)
async def select_production_source_keyframe(
    shot_plan_id: UUID,
    payload: ShotKeyframeSelectRequest,
) -> ShotPlanDetailResponse:
    try:
        return await production_service.select_source_keyframe(shot_plan_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/production-shots/{{shot_plan_id}}/source-keyframe/approval",
    response_model=CandidateActionResponse,
)
async def approve_production_source_keyframe(
    shot_plan_id: UUID,
    payload: ShotSourceFrameApprovalRequest,
) -> CandidateActionResponse:
    try:
        return await production_service.approve_source_keyframe(shot_plan_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(
    f"{API_PREFIX}/me/notifications",
    response_model=NotificationListResponse,
)
async def list_current_account_notifications(
    notification_status: Annotated[NotificationStatus | None, Query(alias="status")] = None,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> NotificationListResponse:
    return await notification_service.list_notifications(
        status=notification_status,
        unread_only=unread_only,
        limit=limit,
    )


@app.post(
    f"{API_PREFIX}/me/notifications/read-all",
    response_model=NotificationReadAllResponse,
)
async def mark_all_current_account_notifications_read() -> NotificationReadAllResponse:
    return await notification_service.mark_all_read()


@app.patch(
    f"{API_PREFIX}/me/notifications/{{notification_id}}/read",
    response_model=AccountNotification,
)
async def mark_current_account_notification_read(
    notification_id: UUID,
) -> AccountNotification:
    try:
        return await notification_service.mark_read(notification_id)
    except NotificationServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/settings/image-generation/test-local-sandbox",
    response_model=LocalCodexSandboxTestResponse,
)
async def test_local_codex_sandbox(
    payload: LocalCodexSandboxTestRequest,
) -> LocalCodexSandboxTestResponse:
    try:
        return await image_generation_settings_service.test_codex_sandbox(payload)
    except ImageGenerationSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(
    f"{API_PREFIX}/settings/video-generation",
    response_model=VideoGenerationSettingsResponse,
)
async def get_video_generation_settings() -> VideoGenerationSettingsResponse:
    try:
        return video_generation_settings_service.get()
    except VideoGenerationSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.put(
    f"{API_PREFIX}/settings/video-generation",
    response_model=VideoGenerationSettingsResponse,
)
async def update_video_generation_settings(
    payload: VideoGenerationSettingsUpdate,
) -> VideoGenerationSettingsResponse:
    try:
        return await video_generation_settings_service.update(payload)
    except VideoGenerationSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/settings/video-generation/providers/{{provider}}/validate",
    response_model=VideoProviderValidationResponse,
)
async def validate_video_provider(
    provider: Literal["bailian", "volc_ark", "minimax"],
    payload: VideoProviderValidationRequest,
) -> VideoProviderValidationResponse:
    try:
        return await video_generation_settings_service.validate_provider(provider, payload)
    except VideoGenerationSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/video-generation/estimate",
    response_model=VideoCostEstimateResponse,
)
async def estimate_video_generation_cost(
    payload: VideoCostEstimateRequest,
) -> VideoCostEstimateResponse:
    try:
        return video_generation_settings_service.estimate(payload)
    except VideoGenerationSettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/production-shots/{{shot_plan_id}}/image-approval/revoke",
    response_model=CandidateActionResponse,
)
async def revoke_production_image_approval(
    shot_plan_id: UUID,
    payload: ShotImageApprovalRevokeRequest,
) -> CandidateActionResponse:
    try:
        return await production_service.revoke_image_approval(shot_plan_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/production-shots/{{shot_plan_id}}/video-approval/revoke",
    response_model=CandidateActionResponse,
)
async def revoke_production_video_approval(
    shot_plan_id: UUID,
    payload: ShotVideoApprovalRevokeRequest,
) -> CandidateActionResponse:
    try:
        return await production_service.revoke_video_approval(shot_plan_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/production-shots/bulk-update",
    response_model=list[ShotPlanResponse],
)
async def bulk_update_production_shots(
    project_id: Annotated[UUID, Query()],
    payload: ShotPlanBulkUpdate,
) -> list[ShotPlanResponse]:
    try:
        return await production_service.bulk_update_shots(project_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/productions/{{project_id}}/change-impact",
    response_model=ChangeImpactResponse,
)
async def get_production_change_impact(
    project_id: UUID,
    payload: ChangeImpactRequest,
) -> ChangeImpactResponse:
    try:
        return await production_service.change_impact(project_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/production-shots/{{shot_plan_id}}/image-runs",
    response_model=GenerationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_production_image_run(
    shot_plan_id: UUID,
    payload: ImageGenerationCreate,
) -> GenerationRunResponse:
    try:
        return await production_service.create_image_run(shot_plan_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/production-shots/{{shot_plan_id}}/video-runs",
    response_model=GenerationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_production_video_run(
    shot_plan_id: UUID,
    payload: VideoGenerationCreate,
) -> GenerationRunResponse:
    try:
        return await production_service.create_video_run(shot_plan_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(
    f"{API_PREFIX}/generation-runs/{{run_id}}",
    response_model=GenerationRunResponse,
)
async def get_production_generation_run(run_id: UUID) -> GenerationRunResponse:
    try:
        return await production_service.get_generation_run(run_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/generation-runs/{{run_id}}/cancel",
    response_model=GenerationRunResponse,
)
async def cancel_production_generation_run(run_id: UUID) -> GenerationRunResponse:
    try:
        return await production_service.cancel_generation_run(run_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/generation-runs/{{run_id}}/retry",
    response_model=GenerationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_production_generation_run(run_id: UUID) -> GenerationRunResponse:
    try:
        return await production_service.retry_generation_run(run_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/generation-candidates/{{candidate_id}}/select",
    response_model=CandidateActionResponse,
)
async def select_production_candidate(
    candidate_id: UUID,
    payload: CandidateSelectRequest,
) -> CandidateActionResponse:
    try:
        return await production_service.select_candidate(candidate_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/generation-candidates/{{candidate_id}}/approvals",
    response_model=CandidateActionResponse,
)
async def approve_production_candidate(
    candidate_id: UUID,
    payload: CandidateApprovalRequest,
) -> CandidateActionResponse:
    try:
        return await production_service.approve_candidate(candidate_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(f"{API_PREFIX}/generation-candidates/{{candidate_id}}/content")
async def get_production_candidate_content(candidate_id: UUID) -> FileResponse:
    try:
        path, media_type = await production_service.resolve_candidate_content(candidate_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=media_type,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get(f"{API_PREFIX}/generation-candidates/{{candidate_id}}/thumbnail")
async def get_production_candidate_thumbnail(candidate_id: UUID) -> FileResponse:
    try:
        path, media_type = await production_service.resolve_candidate_content(
            candidate_id,
            thumbnail=True,
        )
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=media_type,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get(
    f"{API_PREFIX}/productions/{{project_id}}/gate-status",
    response_model=ProductionGateStatus,
)
async def get_production_gate_status(project_id: UUID) -> ProductionGateStatus:
    try:
        return await production_service.gate_status(project_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get(
    f"{API_PREFIX}/productions/{{project_id}}/editing-handoff",
    response_model=EditingHandoffManifest,
)
async def get_production_editing_handoff(project_id: UUID) -> EditingHandoffManifest:
    try:
        return await production_service.get_editing_handoff(project_id)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    f"{API_PREFIX}/productions/{{project_id}}/advance",
    response_model=ProductionProjectDetail,
)
async def advance_production(
    project_id: UUID,
    payload: ProductionAdvanceRequest,
) -> ProductionProjectDetail:
    try:
        return await production_service.advance(project_id, payload)
    except ProductionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


async def ensure_unique_folder_name(name: str, *, exclude_id: UUID | None = None) -> None:
    folders = await store.list_folders()
    if any(
        folder.id != exclude_id and folder.name.casefold() == name.casefold() for folder in folders
    ):
        raise HTTPException(status_code=409, detail="已存在同名目录")


@app.get(f"{API_PREFIX}/folders", response_model=list[RecordFolder])
async def list_folders() -> list[RecordFolder]:
    folders = await store.list_folders()
    return sorted(folders, key=lambda item: (item.name.casefold(), item.created_at))


@app.post(
    f"{API_PREFIX}/folders",
    response_model=RecordFolder,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(payload: FolderCreate) -> RecordFolder:
    name = normalize_name(payload.name)
    await ensure_unique_folder_name(name)
    return await store.save_folder(RecordFolder(name=name))


@app.patch(f"{API_PREFIX}/folders/{{folder_id}}", response_model=RecordFolder)
async def update_folder(folder_id: UUID, payload: FolderUpdate) -> RecordFolder:
    folder = await store.get_folder(folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="目录不存在")
    name = normalize_name(payload.name)
    await ensure_unique_folder_name(name, exclude_id=folder.id)
    folder.name = name
    folder.updated_at = utc_now()
    return await store.save_folder(folder)


def resolve_platform(url: str) -> SourceType:
    try:
        return identify_platform(url)
    except LinkIngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def prepare_upload_target(record_id: UUID, filename: str) -> tuple[Path, Path]:
    suffix = Path(filename).suffix.lower()
    target_dir = workspace_manager.source_root(record_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir, target_dir / f"original{suffix}"


def resolve_video_media_path(video: Video) -> Path:
    try:
        return resolve_video_path(video)
    except WorkspaceError as exc:
        status_code = 409 if "尚未准备" in str(exc) else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def video_download_filename(video: Video, media_path: Path) -> str:
    if video.source_type == SourceType.UPLOAD and video.original_filename:
        stem = Path(video.original_filename).stem
    else:
        stem = video.title or "video"
    normalized = re.sub(r"[<>\x22:/\\|?*\x00-\x1f]+", "-", stem).strip(" .-")[:120] or "video"
    return f"{normalized}{media_path.suffix.lower()}"


def video_file_response(video: Video, *, disposition: str) -> FileResponse:
    media_path = resolve_video_media_path(video)
    return FileResponse(
        media_path,
        media_type=mimetypes.guess_type(media_path.name)[0] or "application/octet-stream",
        filename=video_download_filename(video, media_path),
        content_disposition_type=disposition,
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post(f"{API_PREFIX}/videos/link", response_model=Video, status_code=status.HTTP_201_CREATED)
async def create_link_video(payload: LinkVideoCreate) -> Video:
    if not payload.rights_confirmed:
        raise HTTPException(status_code=422, detail="请先确认拥有分析和使用该视频的权利")

    source_type = resolve_platform(str(payload.url))
    platform_name = "抖音" if source_type == SourceType.DOUYIN else "小红书"
    title = normalize_name(payload.title or f"{platform_name}链接视频")
    record_id = uuid4()
    video = Video(
        record_id=record_id,
        source_type=source_type,
        source_url=str(payload.url),
        title=title,
        target_model=payload.target_model,
    )
    record = AnalysisRecord(
        id=record_id,
        name=title,
        video_id=video.id,
        source_type=source_type,
        source_url=str(payload.url),
    )
    await store.save_record(record)
    return await store.add_video(video)


@app.post(f"{API_PREFIX}/videos/upload", response_model=Video, status_code=status.HTTP_201_CREATED)
async def upload_video(
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    target_model: Annotated[str, Form()] = "seedance",
    rights_confirmed: Annotated[bool, Form()] = False,
) -> Video:
    if not rights_confirmed:
        raise HTTPException(status_code=422, detail="请先确认拥有分析和使用该视频的权利")
    if not file.filename:
        raise HTTPException(status_code=422, detail="缺少文件名")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="仅支持 MP4、MOV 和 WebM")
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="文件媒体类型不受支持")

    record_id = uuid4()
    target_dir, target_path = prepare_upload_target(record_id, file.filename)
    written = 0
    try:
        with target_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="视频文件不能超过 500 MB")
                output.write(chunk)
    except Exception:
        target_path.unlink(missing_ok=True)
        try:
            target_dir.rmdir()
        except OSError:
            pass
        raise
    finally:
        await file.close()

    record_name = normalize_name(title or Path(file.filename).stem, fallback="未命名视频")
    video = Video(
        record_id=record_id,
        source_type=SourceType.UPLOAD,
        original_filename=file.filename,
        stored_path=str(target_path),
        stored_relative_path=workspace_manager.relative(target_path),
        title=record_name,
        target_model=target_model,
    )
    record = AnalysisRecord(
        id=record_id,
        name=record_name,
        video_id=video.id,
        source_type=SourceType.UPLOAD,
    )
    await store.save_record(record)
    saved = await store.add_video(video)
    await write_source_metadata(saved)
    return saved


@app.get(f"{API_PREFIX}/videos/{{video_id}}", response_model=Video)
async def get_video(video_id: UUID) -> Video:
    video = await store.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    return video


@app.post(
    f"{API_PREFIX}/videos/{{video_id}}/analyses",
    response_model=AnalysisJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_analysis(video_id: UUID, payload: AnalysisCreate) -> AnalysisJob:
    video = await store.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")

    if video.record_id is None:
        await record_service.bootstrap()
        video = await store.get_video(video_id)
        if video is None or video.record_id is None:
            raise HTTPException(status_code=409, detail="无法为视频建立分析记录")

    analyzer_mode = os.getenv("VIRAL_DNA_ANALYZER_MODE", "hybrid").strip().lower()
    try:
        analysis_profile = (
            payload.analysis_profile
            if "analysis_profile" in payload.model_fields_set
            else default_analysis_profile()
        )
        model_plan = None if analyzer_mode == "simulated" else load_model_plan(analysis_profile)
    except ModelCatalogError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    mode = (
        AnalysisMode.SIMULATED
        if analyzer_mode == "simulated"
        else AnalysisMode.MODEL
        if model_plan is not None
        else AnalysisMode.MEDIA_EVIDENCE
    )
    if mode == AnalysisMode.SIMULATED:
        analysis_version = "phase1-simulated-v1"
    elif mode == AnalysisMode.MODEL:
        analysis_version = (
            "phase1-link-hybrid-segmentation-v5"
            if video.source_type != SourceType.UPLOAD
            else "phase1-hybrid-segmentation-v5"
        )
    elif video.source_type == SourceType.UPLOAD:
        analysis_version = "phase1-evidence-timeline-v2"
    else:
        analysis_version = "phase1-link-evidence-timeline-v2"
    analysis = AnalysisJob(
        record_id=video.record_id,
        video_id=video.id,
        analysis_version=analysis_version,
        analysis_mode=mode,
        granularity=payload.granularity,
        include_audio=payload.include_audio,
        include_ocr=payload.include_ocr,
        analysis_profile=analysis_profile,
        max_cost_micros=(
            cny_to_micros(payload.max_cost_cny) if payload.max_cost_cny is not None else None
        ),
        model_plan=model_plan,
        simulated=mode == AnalysisMode.SIMULATED,
    )
    await store.add_analysis(analysis)
    pipeline.start(analysis.id)
    return analysis


@app.get(f"{API_PREFIX}/records", response_model=AnalysisRecordList)
async def list_records(
    q: Annotated[str | None, Query(max_length=120)] = None,
    folder_id: Annotated[str | None, Query(max_length=40)] = None,
    record_status: Annotated[VideoStatus | None, Query(alias="status")] = None,
    sort: Annotated[
        Literal["updated_desc", "created_desc", "name_asc"],
        Query(),
    ] = "updated_desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AnalysisRecordList:
    records = await store.list_records()
    videos = {video.id: video for video in await store.list_videos()}
    if q:
        needle = q.strip().casefold()
        records = [
            record
            for record in records
            if needle
            in " ".join(
                filter(
                    None,
                    [
                        record.name,
                        record.source_url,
                        videos.get(record.video_id).source_author
                        if videos.get(record.video_id)
                        else None,
                    ],
                )
            ).casefold()
        ]
    if folder_id:
        if folder_id == "unfiled":
            records = [record for record in records if record.folder_id is None]
        else:
            try:
                selected_folder_id = UUID(folder_id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="目录参数无效") from exc
            records = [record for record in records if record.folder_id == selected_folder_id]
    if record_status is not None:
        records = [record for record in records if record.status == record_status]
    if sort == "created_desc":
        records.sort(key=lambda item: item.created_at, reverse=True)
    elif sort == "name_asc":
        records.sort(key=lambda item: item.name.casefold())
    else:
        records.sort(key=lambda item: item.updated_at, reverse=True)

    total = len(records)
    total_pages = (total + page_size - 1) // page_size
    effective_page = min(page, total_pages or 1)
    page_start = (effective_page - 1) * page_size
    records = records[page_start : page_start + page_size]

    summaries = []
    for record in records:
        video = videos.get(record.video_id)
        cache_version = round(record.updated_at.timestamp())
        summaries.append(
            AnalysisRecordSummary.model_validate(
                {
                    **record.model_dump(mode="python"),
                    "thumbnail_url": (
                        f"{API_PREFIX}/records/{record.id}/thumbnail?v={cache_version}"
                    ),
                    "duration_seconds": video.duration_seconds if video else None,
                }
            )
        )
    return AnalysisRecordList(
        items=summaries,
        total=total,
        page=effective_page,
        page_size=page_size,
        total_pages=total_pages,
    )


@app.get(f"{API_PREFIX}/records/{{record_id}}/thumbnail")
async def get_record_thumbnail(record_id: UUID) -> FileResponse:
    record = await store.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    video = await store.get_video(record.video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    thumbnail = await thumbnail_service.ensure(video)
    if thumbnail is None:
        raise HTTPException(status_code=404, detail="缩略图尚不可用")
    return FileResponse(
        thumbnail,
        media_type="image/jpeg",
        filename=f"{record.id}.jpg",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=86400",
            "ETag": thumbnail_etag(thumbnail),
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get(f"{API_PREFIX}/records/{{record_id}}", response_model=AnalysisRecordDetail)
async def get_record(record_id: UUID) -> AnalysisRecordDetail:
    record = await store.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    video = await store.get_video(record.video_id)
    if video is None:
        raise HTTPException(status_code=409, detail="分析记录缺少视频信息")
    analyses = [
        analysis
        for analysis in await store.list_analyses()
        if analysis.record_id == record.id or analysis.video_id == record.video_id
    ]
    analyses.sort(key=lambda item: item.created_at, reverse=True)
    latest_report = None
    if record.latest_analysis_id is not None:
        latest_report = await store.get_report_by_analysis(record.latest_analysis_id)
    if latest_report is None:
        latest_report = await store.get_report(record.video_id)
    record.last_opened_at = utc_now()
    await store.save_record(record)
    return AnalysisRecordDetail(
        record=record,
        video=video,
        analyses=analyses,
        latest_report=latest_report,
    )


@app.patch(f"{API_PREFIX}/records/{{record_id}}", response_model=AnalysisRecord)
async def update_record(record_id: UUID, payload: AnalysisRecordUpdate) -> AnalysisRecord:
    record = await store.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    if "name" in payload.model_fields_set:
        if payload.name is None:
            raise HTTPException(status_code=422, detail="记录名称不能为空")
        record.name = normalize_name(payload.name)
        video = await store.get_video(record.video_id)
        if video is not None:
            video.title = record.name
            await store.save_video(video)
    if "folder_id" in payload.model_fields_set:
        if payload.folder_id is not None and await store.get_folder(payload.folder_id) is None:
            raise HTTPException(status_code=404, detail="目标目录不存在")
        record.folder_id = payload.folder_id
    record.updated_at = utc_now()
    return await store.save_record(record)


@app.post(
    f"{API_PREFIX}/records/{{record_id}}/analyses",
    response_model=AnalysisJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reanalyze_record(record_id: UUID, payload: AnalysisCreate) -> AnalysisJob:
    record = await store.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    return await create_analysis(record.video_id, payload)


@app.post(
    f"{API_PREFIX}/records/{{record_id}}/exports",
    response_model=list[ExportArtifact],
    status_code=status.HTTP_201_CREATED,
)
async def create_exports(record_id: UUID, payload: ExportCreate) -> list[ExportArtifact]:
    record = await store.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    analysis_id = payload.analysis_id or record.latest_analysis_id
    if analysis_id is None:
        raise HTTPException(status_code=409, detail="该记录尚无可导出的分析报告")
    analysis = await store.get_analysis(analysis_id)
    if analysis is None or (analysis.record_id not in {None, record.id}):
        raise HTTPException(status_code=404, detail="分析版本不存在")
    report = await store.get_report_by_analysis(analysis_id)
    if report is None:
        raise HTTPException(status_code=409, detail="分析报告尚未生成")
    filename_suffix = ""
    if payload.replacement_version_id is not None:
        if payload.kinds != [ExportKind.PROMPT_PACKAGE]:
            raise HTTPException(status_code=422, detail="替换版本仅支持导出提示词包")
        replacement = await store.get_replacement(payload.replacement_version_id)
        if replacement is None or replacement.video_id != record.video_id:
            raise HTTPException(status_code=404, detail="替换版本不存在")
        report = report.model_copy(update={"prompt_package": replacement.prompt_package})
        filename_suffix = f"-replacement-{str(replacement.id)[:8]}"
    return await export_service.create(
        record,
        report,
        payload.kinds,
        filename_suffix=filename_suffix,
    )


@app.get(f"{API_PREFIX}/records/{{record_id}}/exports", response_model=list[ExportArtifact])
async def list_exports(record_id: UUID) -> list[ExportArtifact]:
    if await store.get_record(record_id) is None:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    artifacts = await store.list_exports(record_id)
    return sorted(artifacts, key=lambda item: item.created_at, reverse=True)


@app.get(f"{API_PREFIX}/exports/{{export_id}}/download")
async def download_export(export_id: UUID) -> FileResponse:
    artifact = await store.get_export(export_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="导出记录不存在")
    try:
        path = export_service.resolve(artifact)
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=artifact.media_type,
        filename=artifact.filename,
        content_disposition_type="attachment",
    )


@app.get(f"{API_PREFIX}/analyses/{{analysis_id}}", response_model=AnalysisJob)
async def get_analysis(analysis_id: UUID) -> AnalysisJob:
    analysis = await store.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return analysis


@app.get(f"{API_PREFIX}/analyses/{{analysis_id}}/report", response_model=AnalysisReport)
async def get_analysis_report(analysis_id: UUID) -> AnalysisReport:
    analysis = await store.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    report = await store.get_report_by_analysis(analysis_id)
    if report is None:
        raise HTTPException(status_code=409, detail="报告尚未生成")
    return report


@app.get(f"{API_PREFIX}/analyses/{{analysis_id}}/model-runs", response_model=list[ModelRun])
async def get_model_runs(analysis_id: UUID) -> list[ModelRun]:
    analysis = await store.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return await store.list_model_runs(analysis_id)


@app.get(f"{API_PREFIX}/analyses/{{analysis_id}}/cost", response_model=AnalysisCostSummary)
async def get_analysis_cost(analysis_id: UUID) -> AnalysisCostSummary:
    analysis = await store.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    runs = await store.list_model_runs(analysis_id)
    return summarize_model_runs(
        analysis_id,
        runs,
        estimated_cost_micros=analysis.estimated_cost_micros,
    )


@app.get(f"{API_PREFIX}/analyses/{{analysis_id}}/artifacts/{{artifact_path:path}}")
async def get_analysis_artifact(analysis_id: UUID, artifact_path: str) -> FileResponse:
    analysis = await store.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")

    artifact_root = get_analysis_artifact_root(analysis_id, analysis.record_id).resolve()
    if not artifact_root.exists() and analysis.record_id is not None:
        artifact_root = get_analysis_artifact_root(analysis_id).resolve()
    candidate = (artifact_root / artifact_path).resolve()
    try:
        candidate.relative_to(artifact_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="分析产物不存在") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="分析产物不存在")
    return FileResponse(candidate)


@app.get(f"{API_PREFIX}/analyses/{{analysis_id}}/events")
async def analysis_events(analysis_id: UUID) -> StreamingResponse:
    if await store.get_analysis(analysis_id) is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")

    async def event_stream():
        last_payload = ""
        while True:
            analysis = await store.get_analysis(analysis_id)
            if analysis is None:
                break
            payload = json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False)
            if payload != last_payload:
                yield f"event: progress\ndata: {payload}\n\n"
                last_payload = payload
            if analysis.stage in {AnalysisStage.COMPLETED, AnalysisStage.FAILED}:
                break
            await asyncio.sleep(0.35)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get(f"{API_PREFIX}/videos/{{video_id}}/report", response_model=AnalysisReport)
async def get_report(video_id: UUID) -> AnalysisReport:
    video = await store.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    report = await store.get_report(video_id)
    if report is None:
        raise HTTPException(status_code=409, detail="报告尚未生成")
    return report


@app.post(
    f"{API_PREFIX}/videos/{{video_id}}/replacement-versions",
    response_model=ReplacementVersion,
    status_code=status.HTTP_201_CREATED,
)
async def create_replacement(video_id: UUID, payload: ReplacementCreate) -> ReplacementVersion:
    report = await store.get_report(video_id)
    if report is None:
        raise HTTPException(status_code=409, detail="请先完成视频分析")
    try:
        version = create_replacement_version(video_id, report, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await store.save_replacement(version)


@app.get(f"{API_PREFIX}/videos/{{video_id}}/media")
async def play_video(video_id: UUID) -> FileResponse:
    video = await store.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    return video_file_response(video, disposition="inline")


@app.get(f"{API_PREFIX}/videos/{{video_id}}/download")
async def download_video(video_id: UUID) -> FileResponse:
    video = await store.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    return video_file_response(video, disposition="attachment")
