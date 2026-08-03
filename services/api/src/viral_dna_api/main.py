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

from . import __version__
from .ai.billing import cny_to_micros, summarize_model_runs
from .ai.catalog import ModelCatalogError, default_analysis_profile, load_model_plan
from .chinese import to_simplified
from .exports import ExportService
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
    AnalysisRecordUpdate,
    AnalysisReport,
    AnalysisStage,
    ExportArtifact,
    ExportCreate,
    ExportKind,
    FolderCreate,
    FolderUpdate,
    HealthResponse,
    LinkVideoCreate,
    ModelRun,
    ModelSettingsResponse,
    ModelSettingsUpdate,
    RecordFolder,
    ReplacementCreate,
    ReplacementVersion,
    SourceType,
    Video,
    VideoStatus,
    WorkspaceInfo,
    WorkspacePathRequest,
    WorkspaceValidationResponse,
)
from .pipeline import create_replacement_version
from .real_pipeline import HybridAnalysisPipeline
from .records import RecordService, resolve_video_path, write_source_metadata
from .store import store
from .workspace import WORKSPACE_SCHEMA_VERSION, WorkspaceError, workspace_manager

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
    await record_service.bootstrap(recover_interrupted=True)
    yield


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
record_service = RecordService(store)
export_service = ExportService(store)


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
        await store.switch_workspace(validation.normalized_path)
        await record_service.bootstrap(recover_interrupted=True)
    except WorkspaceError as exc:
        status_code = 409 if "正在运行" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return await workspace_info()


def normalize_name(value: str, *, fallback: str | None = None) -> str:
    cleaned = " ".join((to_simplified(value) or "").split()).strip()
    if not cleaned and fallback is not None:
        return fallback
    if not cleaned:
        raise HTTPException(status_code=422, detail="名称不能为空")
    return cleaned


async def ensure_unique_folder_name(name: str, *, exclude_id: UUID | None = None) -> None:
    folders = await store.list_folders()
    if any(
        folder.id != exclude_id and folder.name.casefold() == name.casefold()
        for folder in folders
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
            "phase1-link-vlm-shot-facts-v1"
            if video.source_type != SourceType.UPLOAD
            else "phase1-vlm-shot-facts-v1"
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
    return AnalysisRecordList(items=records, total=len(records))


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
        report = report.model_copy(
            update={"prompt_package": replacement.prompt_package}
        )
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
