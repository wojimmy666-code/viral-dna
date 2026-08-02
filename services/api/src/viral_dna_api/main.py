from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from . import __version__
from .link_ingestion import LinkIngestionError, identify_platform
from .media import get_analysis_artifact_root
from .models import (
    AnalysisCreate,
    AnalysisJob,
    AnalysisMode,
    AnalysisReport,
    AnalysisStage,
    HealthResponse,
    LinkVideoCreate,
    ReplacementCreate,
    ReplacementVersion,
    SourceType,
    Video,
)
from .pipeline import create_replacement_version
from .real_pipeline import HybridAnalysisPipeline
from .store import store

API_PREFIX = "/api/v1"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm"}
ALLOWED_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "application/octet-stream",
}


def parse_cors_origins() -> list[str]:
    value = os.getenv(
        "VIRAL_DNA_CORS_ORIGINS",
        "http://127.0.0.1:4174,http://localhost:4174,http://localhost:5173",
    )
    return [origin.strip() for origin in value.split(",") if origin.strip()]


app = FastAPI(
    title="ViralDNA API",
    version=__version__,
    description="Phase 1 single-video analysis orchestration API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = HybridAnalysisPipeline(store)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(analyzer_mode=os.getenv("VIRAL_DNA_ANALYZER_MODE", "hybrid"))


def resolve_platform(url: str) -> SourceType:
    try:
        return identify_platform(url)
    except LinkIngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def safe_filename(filename: str) -> str:
    stem = Path(filename).stem[:80]
    suffix = Path(filename).suffix.lower()
    normalized = re.sub(r"[^0-9A-Za-z._-]+", "-", stem).strip("-.") or "video"
    return f"{normalized}{suffix}"


def prepare_upload_target(video_id: UUID, filename: str) -> tuple[Path, Path]:
    storage_root = Path(os.getenv("VIRAL_DNA_STORAGE_ROOT", "storage")).resolve()
    target_dir = storage_root / "uploads" / str(video_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir, target_dir / safe_filename(filename)


@app.post(f"{API_PREFIX}/videos/link", response_model=Video, status_code=status.HTTP_201_CREATED)
async def create_link_video(payload: LinkVideoCreate) -> Video:
    if not payload.rights_confirmed:
        raise HTTPException(status_code=422, detail="请先确认拥有分析和使用该视频的权利")

    source_type = resolve_platform(str(payload.url))
    platform_name = "抖音" if source_type == SourceType.DOUYIN else "小红书"
    video = Video(
        source_type=source_type,
        source_url=str(payload.url),
        title=payload.title or f"{platform_name}链接视频",
        target_model=payload.target_model,
    )
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

    video_id = uuid4()
    target_dir, target_path = prepare_upload_target(video_id, file.filename)
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

    video = Video(
        id=video_id,
        source_type=SourceType.UPLOAD,
        original_filename=file.filename,
        stored_path=str(target_path),
        title=title or Path(file.filename).stem,
        target_model=target_model,
    )
    return await store.add_video(video)


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

    analyzer_mode = os.getenv("VIRAL_DNA_ANALYZER_MODE", "hybrid").strip().lower()
    mode = AnalysisMode.SIMULATED if analyzer_mode == "simulated" else AnalysisMode.MEDIA_EVIDENCE
    if mode == AnalysisMode.SIMULATED:
        analysis_version = "phase1-simulated-v1"
    elif video.source_type == SourceType.UPLOAD:
        analysis_version = "phase1-media-v1"
    else:
        analysis_version = "phase1-link-media-v1"
    analysis = AnalysisJob(
        video_id=video.id,
        analysis_version=analysis_version,
        analysis_mode=mode,
        granularity=payload.granularity,
        include_audio=payload.include_audio,
        include_ocr=payload.include_ocr,
        simulated=mode == AnalysisMode.SIMULATED,
    )
    await store.add_analysis(analysis)
    pipeline.start(analysis.id)
    return analysis


@app.get(f"{API_PREFIX}/analyses/{{analysis_id}}", response_model=AnalysisJob)
async def get_analysis(analysis_id: UUID) -> AnalysisJob:
    analysis = await store.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return analysis


@app.get(f"{API_PREFIX}/analyses/{{analysis_id}}/artifacts/{{artifact_path:path}}")
async def get_analysis_artifact(analysis_id: UUID, artifact_path: str) -> FileResponse:
    if await store.get_analysis(analysis_id) is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")

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
