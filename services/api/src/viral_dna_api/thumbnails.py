from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote
from uuid import UUID, uuid4

from .models import AnalysisReport, Video
from .records import resolve_video_path
from .workspace import WorkspaceError, workspace_manager

THUMBNAIL_FILENAME = "thumbnail.jpg"
THUMBNAIL_METADATA_FILENAME = "thumbnail.json"
THUMBNAIL_WIDTH = 480
THUMBNAIL_HEIGHT = 320
THUMBNAIL_TIMEOUT_SECONDS = 25

_THUMBNAIL_FILTER = (
    f"[0:v:0]split=2[bg][fg];"
    f"[bg]scale={THUMBNAIL_WIDTH}:{THUMBNAIL_HEIGHT}:"
    "force_original_aspect_ratio=increase,"
    f"crop={THUMBNAIL_WIDTH}:{THUMBNAIL_HEIGHT},gblur=sigma=18[bg2];"
    f"[fg]scale={THUMBNAIL_WIDTH}:{THUMBNAIL_HEIGHT}:"
    "force_original_aspect_ratio=decrease[fg2];"
    "[bg2][fg2]overlay=(W-w)/2:(H-h)/2,format=yuvj420p[out]"
)

_generation_slots = threading.BoundedSemaphore(2)
_record_locks_guard = threading.Lock()
_record_locks: dict[UUID, threading.Lock] = {}


def thumbnail_path(record_id: UUID) -> Path:
    return workspace_manager.source_root(record_id) / THUMBNAIL_FILENAME


def thumbnail_etag(path: Path) -> str:
    stat = path.stat()
    return f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'


def _lock_for(record_id: UUID) -> threading.Lock:
    with _record_locks_guard:
        return _record_locks.setdefault(record_id, threading.Lock())


def _resolve_ffmpeg() -> str | None:
    configured = os.getenv("VIRAL_DNA_FFMPEG_PATH", "ffmpeg").strip() or "ffmpeg"
    resolved = shutil.which(configured)
    if resolved:
        return resolved
    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    return None


def _capture_seconds(duration_seconds: float | None) -> float:
    if duration_seconds is None or duration_seconds <= 0:
        return 1.0
    upper_bound = max(0.05, duration_seconds - 0.05)
    return min(max(duration_seconds * 0.1, 0.2), 2.0, upper_bound)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_path(record_id: UUID) -> Path:
    return workspace_manager.source_root(record_id) / THUMBNAIL_METADATA_FILENAME


def _read_metadata(record_id: UUID) -> dict[str, object]:
    path = _metadata_path(record_id)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text("utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_metadata(
    record_id: UUID,
    *,
    source_kind: str,
    analysis_id: UUID | None,
    source_path: Path,
    destination: Path,
) -> None:
    metadata = {
        "source_kind": source_kind,
        "analysis_id": str(analysis_id) if analysis_id else None,
        "source_filename": source_path.name,
        "width": THUMBNAIL_WIDTH,
        "height": THUMBNAIL_HEIGHT,
        "sha256": _sha256(destination),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    path = _metadata_path(record_id)
    temporary = path.with_name(f".thumb-meta-{uuid4().hex[:8]}.tmp")
    try:
        temporary.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _render_thumbnail(
    record_id: UUID,
    source_path: Path,
    *,
    capture_seconds: float | None,
    source_kind: str,
    analysis_id: UUID | None,
    overwrite: bool,
) -> Path | None:
    destination = thumbnail_path(record_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _resolve_ffmpeg()
    if ffmpeg is None or not source_path.is_file():
        return destination if destination.is_file() else None

    with _lock_for(record_id), _generation_slots:
        if destination.is_file() and not overwrite:
            return destination
        temporary = destination.with_name(f".thumb-{uuid4().hex[:8]}.jpg")
        try:
            attempts = [capture_seconds]
            if capture_seconds is not None and capture_seconds > 0.05:
                attempts.append(0.05)
            for timestamp in attempts:
                args = [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-y",
                ]
                if timestamp is not None:
                    args.extend(["-ss", f"{timestamp:.3f}"])
                args.extend(
                    [
                        "-i",
                        str(source_path),
                        "-filter_complex",
                        _THUMBNAIL_FILTER,
                        "-map",
                        "[out]",
                        "-frames:v",
                        "1",
                        "-q:v",
                        "3",
                        str(temporary),
                    ]
                )
                completed = subprocess.run(
                    args,
                    capture_output=True,
                    check=False,
                    timeout=THUMBNAIL_TIMEOUT_SECONDS,
                )
                if completed.returncode == 0 and temporary.is_file() and temporary.stat().st_size:
                    os.replace(temporary, destination)
                    _write_metadata(
                        record_id,
                        source_kind=source_kind,
                        analysis_id=analysis_id,
                        source_path=source_path,
                        destination=destination,
                    )
                    return destination
                temporary.unlink(missing_ok=True)
        except (OSError, subprocess.SubprocessError):
            return destination if destination.is_file() else None
        finally:
            temporary.unlink(missing_ok=True)
    return destination if destination.is_file() else None


def _keyframe_path(record_id: UUID, report: AnalysisReport) -> Path | None:
    prefix = f"/api/v1/analyses/{report.analysis_id}/artifacts/"
    keyframe_url = next(
        (shot.keyframe_url for shot in report.shots if shot.keyframe_url),
        None,
    )
    if not keyframe_url or not keyframe_url.startswith(prefix):
        return None
    relative = unquote(keyframe_url.removeprefix(prefix)).lstrip("/")
    root = workspace_manager.analysis_root(record_id, report.analysis_id).resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


class ThumbnailService:
    async def ensure(self, video: Video) -> Path | None:
        if video.record_id is None:
            return None
        existing = thumbnail_path(video.record_id)
        if existing.is_file():
            return existing
        try:
            source_path = resolve_video_path(video)
        except WorkspaceError:
            return None
        return await asyncio.to_thread(
            _render_thumbnail,
            video.record_id,
            source_path,
            capture_seconds=_capture_seconds(video.duration_seconds),
            source_kind="video_frame",
            analysis_id=None,
            overwrite=False,
        )

    async def promote_from_report(
        self,
        record_id: UUID,
        report: AnalysisReport,
    ) -> Path | None:
        destination = thumbnail_path(record_id)
        metadata = await asyncio.to_thread(_read_metadata, record_id)
        if (
            destination.is_file()
            and metadata.get("source_kind") == "analysis_keyframe"
            and metadata.get("analysis_id") == str(report.analysis_id)
        ):
            return destination
        keyframe = await asyncio.to_thread(_keyframe_path, record_id, report)
        if keyframe is None:
            return destination if destination.is_file() else None
        return await asyncio.to_thread(
            _render_thumbnail,
            record_id,
            keyframe,
            capture_seconds=None,
            source_kind="analysis_keyframe",
            analysis_id=report.analysis_id,
            overwrite=True,
        )


thumbnail_service = ThumbnailService()
