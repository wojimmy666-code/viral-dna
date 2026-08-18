from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from ..models import ProductionProject, ShotPlan
from ..notifications import NotificationPublisher
from ..workspace import WorkspaceError, WorkspaceManager
from .domain import (
    DepthControlAsset,
    DepthControlStatus,
    DepthControlValidationStatus,
)
from .engines import (
    AsyncVideoDepthAnythingEngine,
    DepthAnythingOnnxCpuEngine,
    DepthEngineCapability,
    DepthEngineRegistry,
    DepthEngineRegistryError,
    DepthEngineSelectionError,
    DepthEngineSelector,
    DepthGenerationProfile,
    VideoDepthAnythingEngine,
)
from .jobs.domain import (
    DepthControlJob,
    DepthControlJobStage,
    DepthControlPreset,
    DepthExecutionPreference,
)
from .jobs.progress import DepthProgressEvent
from .settings import DepthGenerationSettingsService


def _filesystem_path(path: Path) -> Path:
    if os.name != "nt":
        return path
    separator = chr(92)
    raw = str(path)
    prefix = f"{separator}{separator}?{separator}"
    if raw.startswith(prefix):
        return path
    if raw.startswith(separator * 2):
        return Path(f"{prefix}UNC{separator}{raw[2:]}")
    return Path(f"{prefix}{raw}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _filesystem_path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    destination = _filesystem_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".tmp-{uuid4().hex}{destination.suffix}")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    _write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


class DepthControlServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True, slots=True)
class DepthContentDeletion:
    original_root: Path
    staged_root: Path | None = None


@dataclass(slots=True)
class DepthEngineInstallation:
    id: UUID
    engine: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress_percent: int
    message: str
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    capability: DepthEngineCapability | None = None


class DepthControlService:
    def __init__(
        self,
        workspace: WorkspaceManager,
        *,
        engine: VideoDepthAnythingEngine | None = None,
        settings_service: DepthGenerationSettingsService | None = None,
        notification_publisher: NotificationPublisher | None = None,
    ) -> None:
        self.workspace = workspace
        self.engine = engine or VideoDepthAnythingEngine()
        self.async_engine = AsyncVideoDepthAnythingEngine(self.engine)
        self.cpu_engine = DepthAnythingOnnxCpuEngine()
        self._legacy_engine_injected = engine is not None
        registered_engines = (
            [self.async_engine]
            if self._legacy_engine_injected
            else [self.cpu_engine, self.async_engine]
        )
        self.registry = DepthEngineRegistry(registered_engines)
        self.selector = DepthEngineSelector(self.registry)
        self.settings_service = settings_service
        self.notification_publisher = notification_publisher
        self._installation_lock = asyncio.Lock()
        self._installations: dict[UUID, DepthEngineInstallation] = {}
        self._installation_tasks: dict[UUID, asyncio.Task[None]] = {}

    def capability(self, engine_name: str | None = None) -> DepthEngineCapability:
        if self._legacy_engine_injected:
            return self.engine.capability()
        selected = engine_name or self.cpu_engine.engine_id
        try:
            return self.registry.require(selected).capability()
        except DepthEngineRegistryError as exc:
            raise DepthControlServiceError(
                404, "depth_engine_not_found", str(exc)
            ) from exc

    def capabilities(self) -> list[DepthEngineCapability]:
        if self._legacy_engine_injected:
            return [self.engine.capability()]
        return self.registry.capabilities()

    async def start_installation(self, engine_name: str) -> DepthEngineInstallation:
        aliases = {
            "video_depth_anything": self.async_engine.engine_id,
            "video_depth_anything_cuda": self.async_engine.engine_id,
            "depth_anything_v2_onnx": self.cpu_engine.engine_id,
        }
        resolved_name = aliases.get(engine_name, engine_name)
        if self._legacy_engine_injected:
            resolved_name = self.async_engine.engine_id
        if resolved_name not in self.registry.engine_ids():
            raise DepthControlServiceError(
                404,
                "depth_engine_not_found",
                "未找到指定的深度引擎",
            )
        async with self._installation_lock:
            active = next(
                (
                    item
                    for item in self._installations.values()
                    if item.status in {"queued", "running"}
                    and item.engine == resolved_name
                ),
                None,
            )
            if active is not None:
                return active
            now = datetime.now(UTC)
            installation = DepthEngineInstallation(
                id=uuid4(),
                engine=resolved_name,
                status="queued",
                progress_percent=0,
                message="安装任务已创建",
                created_at=now,
                updated_at=now,
            )
            self._installations[installation.id] = installation
            task = asyncio.create_task(self._run_installation(installation))
            self._installation_tasks[installation.id] = task
            return installation

    def installation(self, installation_id: UUID) -> DepthEngineInstallation:
        installation = self._installations.get(installation_id)
        if installation is None:
            raise DepthControlServiceError(
                404,
                "depth_engine_installation_not_found",
                "未找到该深度引擎安装任务",
            )
        return installation

    async def _publish_installation(
        self,
        installation: DepthEngineInstallation,
    ) -> None:
        if self.notification_publisher is None:
            return
        level = {
            "queued": "info",
            "running": "info",
            "succeeded": "success",
            "failed": "error",
        }[installation.status]
        try:
            await self.notification_publisher.publish(
                category="system",
                level=level,
                status=(
                    "in_progress"
                    if installation.status in {"queued", "running"}
                    else installation.status
                ),
                title=(
                    "深度引擎安装完成"
                    if installation.status == "succeeded"
                    else "深度引擎安装失败"
                    if installation.status == "failed"
                    else "正在安装深度引擎"
                ),
                message=installation.error or installation.message,
                event_key=f"depth-engine-installation:{installation.id}",
                action_kind="model_settings",
                action_label="模型与设置",
            )
        except Exception:
            return

    async def _run_installation(self, installation: DepthEngineInstallation) -> None:
        installation.status = "running"
        installation.progress_percent = 1
        installation.message = "正在准备安装"
        installation.updated_at = datetime.now(UTC)
        await self._publish_installation(installation)

        def update_progress(percent: int, message: str) -> None:
            installation.progress_percent = max(0, min(100, int(percent)))
            installation.message = message[:500]
            installation.updated_at = datetime.now(UTC)

        try:
            selected_engine = self.registry.require(installation.engine)
            await asyncio.to_thread(selected_engine.install, update_progress)
            capability = selected_engine.capability()
            installation.status = "succeeded"
            installation.progress_percent = 100
            installation.message = "深度引擎已安装并通过环境检查"
            installation.capability = capability
        except Exception as exc:
            installation.status = "failed"
            installation.error = str(exc)[-2000:] or "深度引擎安装失败"
            installation.message = "安装未完成，请查看错误后重试"
        finally:
            installation.updated_at = datetime.now(UTC)
            self._installation_tasks.pop(installation.id, None)
            await self._publish_installation(installation)

    async def generate(
        self,
        *,
        project: ProductionProject,
        shot: ShotPlan,
        source_path: Path,
        source_video_id: UUID,
    ) -> DepthControlAsset:
        # This legacy synchronous endpoint remains tied to the original
        # engine. Durable jobs honor the account-scoped CPU/GPU setting.
        capability = self.engine.capability()
        if not capability.available:
            raise DepthControlServiceError(
                409,
                "depth_engine_unavailable",
                capability.availability_note,
            )
        physical_source = _filesystem_path(source_path)
        if not await asyncio.to_thread(physical_source.is_file):
            raise DepthControlServiceError(
                404,
                "depth_source_video_missing",
                "原视频文件不存在，无法生成深度控制视频",
            )
        asset_id = uuid4()
        root = (
            self.workspace.production_shot_root(project.record_id, project.id, shot.id)
            / "depth-controls"
            / str(asset_id)
        )
        destination = root / "depth.mp4"
        thumbnail = root / "thumbnail.jpg"
        manifest = root / "manifest.json"
        working = root / "work"
        try:
            output = await asyncio.to_thread(
                self.engine.generate,
                source_path=physical_source,
                destination_path=_filesystem_path(destination),
                thumbnail_path=_filesystem_path(thumbnail),
                working_root=_filesystem_path(working),
                start_seconds=shot.start_seconds,
                end_seconds=shot.end_seconds,
            )
            await asyncio.to_thread(shutil.rmtree, _filesystem_path(working), True)
            file_sha256 = await asyncio.to_thread(_sha256, destination)
            payload: dict[str, object] = {
                "schema_version": "viral-dna-depth-control/v1",
                "asset_id": str(asset_id),
                "kind": "full_scene_depth_video",
                "source_video_id": str(source_video_id),
                "source_relative_path": self.workspace.relative(source_path),
                "source_start_seconds": shot.start_seconds,
                "source_end_seconds": shot.end_seconds,
                "engine": capability.engine,
                "engine_version": capability.version,
                "model_variant": capability.model_variant,
                "depth_convention": "near_white_far_black",
                "width": output.width,
                "height": output.height,
                "fps": output.fps,
                "duration_seconds": output.duration_seconds,
                "frame_count": output.frame_count,
                "sha256": file_sha256,
                "validation": {
                    "status": "passed",
                    "message": output.validation_message,
                    "metrics": output.validation_metrics,
                },
                "created_at": datetime.now(UTC).isoformat(),
            }
            await asyncio.to_thread(_write_json, manifest, payload)
        except DepthControlServiceError:
            await asyncio.to_thread(shutil.rmtree, _filesystem_path(root), True)
            raise
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            await asyncio.to_thread(shutil.rmtree, _filesystem_path(root), True)
            raise DepthControlServiceError(
                422,
                "depth_control_generation_failed",
                str(exc),
            ) from exc
        return DepthControlAsset(
            id=asset_id,
            status=DepthControlStatus.READY,
            enabled=True,
            source_video_id=source_video_id,
            source_relative_path=self.workspace.relative(source_path),
            source_start_seconds=shot.start_seconds,
            source_end_seconds=shot.end_seconds,
            relative_path=self.workspace.relative(destination),
            thumbnail_relative_path=self.workspace.relative(thumbnail),
            manifest_relative_path=self.workspace.relative(manifest),
            sha256=file_sha256,
            engine=capability.engine,
            engine_version=capability.version,
            model_variant=capability.model_variant,
            width=output.width,
            height=output.height,
            fps=output.fps,
            duration_seconds=output.duration_seconds,
            frame_count=output.frame_count,
            validation_status=DepthControlValidationStatus.PASSED,
            validation_message=output.validation_message,
            validation_metrics=output.validation_metrics,
        )

    async def generation_profile(
        self,
        preset: DepthControlPreset,
    ) -> DepthGenerationProfile:
        if self._legacy_engine_injected:
            capability = self.capability()
            if not capability.available:
                raise DepthControlServiceError(
                    409,
                    "depth_engine_unavailable",
                    capability.availability_note,
                )
            try:
                return await self.async_engine.profile(preset)
            except RuntimeError as exc:
                raise DepthControlServiceError(
                    422,
                    "depth_preset_unavailable",
                    str(exc),
                ) from exc

        account_id = None
        preference = DepthExecutionPreference.AUTO
        if self.settings_service is not None:
            account_id, settings = await self.settings_service.get_current()
            preference = settings.execution_preference
        try:
            profile = await self.selector.resolve(
                preference=preference,
                legacy_preset=preset,
            )
            return replace(profile, account_id=account_id)
        except DepthEngineSelectionError as exc:
            raise DepthControlServiceError(
                422,
                exc.code,
                str(exc),
            ) from exc

    def job_root(self, job: DepthControlJob) -> Path:
        return (
            self.workspace.production_shot_root(
                job.record_id,
                job.project_id,
                job.shot_plan_id,
            )
            / "depth-control-jobs"
            / str(job.id)
        )

    async def write_job_diagnostics(
        self,
        job: DepthControlJob,
        *,
        technical_detail: str = "",
    ) -> None:
        root = self.job_root(job)
        payload = job.model_dump(mode="json")
        await asyncio.to_thread(_write_json, root / "job.json", payload)
        if technical_detail:
            tail = technical_detail[-6000:]
            await asyncio.to_thread(_write_text_atomic, root / "stderr-tail.log", tail)

    async def generate_job(
        self,
        job: DepthControlJob,
        *,
        cancellation: asyncio.Event,
        progress: Callable[[DepthProgressEvent], Awaitable[None]],
    ) -> DepthControlAsset:
        engine_name = job.engine
        if engine_name == "video_depth_anything":
            engine_name = self.async_engine.engine_id
        try:
            selected_engine = self.registry.require(engine_name)
        except DepthEngineRegistryError as exc:
            raise DepthControlServiceError(
                409,
                "depth_engine_unavailable",
                f"任务使用的深度引擎不可用：{job.engine}",
            ) from exc
        capability = selected_engine.capability()
        if not capability.available:
            raise DepthControlServiceError(
                409,
                "depth_engine_unavailable",
                capability.availability_note,
            )
        try:
            source_path = _filesystem_path(
                self.workspace.resolve(job.source_relative_path)
            )
        except (OSError, ValueError, WorkspaceError) as exc:
            raise DepthControlServiceError(
                409,
                "depth_source_video_invalid",
                "原视频路径无效，无法继续生成深度视频",
            ) from exc
        if not await asyncio.to_thread(source_path.is_file):
            raise DepthControlServiceError(
                404,
                "depth_source_video_missing",
                "原视频文件不存在，无法生成深度视频",
            )
        profile = DepthGenerationProfile(
            preset=job.effective_preset,
            device=job.execution_device,
            device_name=job.device_name,
            target_fps=job.target_fps,
            input_size=job.input_size,
            max_resolution=job.max_resolution,
            timeout_seconds=job.timeout_seconds,
            runtime_version=job.runtime_version,
            engine_id=engine_name,
            selection_reason=job.selection_reason,
            requested_execution_preference=job.requested_execution_preference,
            account_id=job.account_id,
        )
        asset_id = uuid4()
        asset_root = (
            self.workspace.production_shot_root(
                job.record_id,
                job.project_id,
                job.shot_plan_id,
            )
            / "depth-controls"
            / str(asset_id)
        )
        destination = asset_root / "depth.mp4"
        thumbnail = asset_root / "thumbnail.jpg"
        manifest = asset_root / "manifest.json"
        working = self.job_root(job) / "work"
        generation_completed = False
        try:
            output = await selected_engine.generate(
                source_path=source_path,
                destination_path=_filesystem_path(destination),
                thumbnail_path=_filesystem_path(thumbnail),
                working_root=_filesystem_path(working),
                start_seconds=job.source_start_seconds,
                end_seconds=job.source_end_seconds,
                profile=profile,
                cancellation=cancellation,
                progress=progress,
            )
            generation_completed = True
            await progress(
                DepthProgressEvent(
                    stage=DepthControlJobStage.PERSISTING_ASSET,
                    ratio=0,
                    message="正在保存深度资产",
                    processed_frames=job.total_frames,
                    total_frames=job.total_frames,
                )
            )
            await asyncio.to_thread(shutil.rmtree, _filesystem_path(working), True)
            file_sha256 = await asyncio.to_thread(_sha256, destination)
            payload: dict[str, object] = {
                "schema_version": "viral-dna-depth-control/v1",
                "asset_id": str(asset_id),
                "job_id": str(job.id),
                "kind": "full_scene_depth_video",
                "source_video_id": str(job.source_video_id),
                "source_relative_path": job.source_relative_path,
                "source_start_seconds": job.source_start_seconds,
                "source_end_seconds": job.source_end_seconds,
                "source_fingerprint": job.source_fingerprint,
                "engine": capability.engine,
                "engine_version": capability.version,
                "model_variant": capability.model_variant,
                "depth_convention": "near_white_far_black",
                "generation_profile": {
                    "preset": profile.preset.value,
                    "device": profile.device.value,
                    "device_name": profile.device_name,
                    "target_fps": profile.target_fps,
                    "input_size": profile.input_size,
                    "max_resolution": profile.max_resolution,
                },
                "width": output.width,
                "height": output.height,
                "fps": output.fps,
                "duration_seconds": output.duration_seconds,
                "frame_count": output.frame_count,
                "sha256": file_sha256,
                "validation": {
                    "status": "passed",
                    "message": output.validation_message,
                    "metrics": output.validation_metrics,
                },
                "created_at": datetime.now(UTC).isoformat(),
            }
            await asyncio.to_thread(_write_json, manifest, payload)
            await progress(
                DepthProgressEvent(
                    stage=DepthControlJobStage.PERSISTING_ASSET,
                    ratio=1,
                    message="深度资产已保存",
                    processed_frames=output.frame_count,
                    total_frames=output.frame_count,
                )
            )
        except Exception as exc:
            if not generation_completed:
                await asyncio.to_thread(
                    shutil.rmtree,
                    _filesystem_path(asset_root),
                    True,
                )
                raise
            raise DepthControlServiceError(
                500,
                "depth_asset_persist_failed",
                (
                    "深度推理已经完成，但资产清单保存失败；生成文件已保留，"
                    f"可在修复后恢复：{destination}。原始错误：{exc}"
                ),
            ) from exc
        return DepthControlAsset(
            id=asset_id,
            status=DepthControlStatus.READY,
            enabled=True,
            source_video_id=job.source_video_id,
            source_relative_path=job.source_relative_path,
            source_start_seconds=job.source_start_seconds,
            source_end_seconds=job.source_end_seconds,
            relative_path=self.workspace.relative(destination),
            thumbnail_relative_path=self.workspace.relative(thumbnail),
            manifest_relative_path=self.workspace.relative(manifest),
            sha256=file_sha256,
            engine=capability.engine,
            engine_version=capability.version,
            model_variant=capability.model_variant,
            width=output.width,
            height=output.height,
            fps=output.fps,
            duration_seconds=output.duration_seconds,
            frame_count=output.frame_count,
            validation_status=DepthControlValidationStatus.PASSED,
            validation_message=output.validation_message,
            validation_metrics=output.validation_metrics,
        )

    def _content_root(self, asset: DepthControlAsset) -> Path:
        if not asset.relative_path:
            raise DepthControlServiceError(
                409, "depth_control_path_invalid", "深度控制文件路径无效"
            )
        relative_root = Path(asset.relative_path).parent
        if relative_root.name != str(asset.id) or relative_root.parent.name != "depth-controls":
            raise DepthControlServiceError(
                409,
                "depth_control_path_invalid",
                "深度控制文件目录不符合安全删除规则",
            )
        try:
            return _filesystem_path(self.workspace.resolve(relative_root.as_posix()))
        except (OSError, ValueError, WorkspaceError) as exc:
            raise DepthControlServiceError(
                409, "depth_control_path_invalid", "深度控制文件路径无效"
            ) from exc

    async def resolve_content(
        self,
        asset: DepthControlAsset,
        *,
        thumbnail: bool = False,
    ) -> tuple[Path, str, str]:
        relative = asset.thumbnail_relative_path if thumbnail else asset.relative_path
        if not relative:
            raise DepthControlServiceError(
                409, "depth_control_path_invalid", "深度控制文件路径无效"
            )
        try:
            path = _filesystem_path(self.workspace.resolve(relative))
        except (OSError, ValueError, WorkspaceError) as exc:
            raise DepthControlServiceError(
                409, "depth_control_path_invalid", "深度控制文件路径无效"
            ) from exc
        if not await asyncio.to_thread(path.is_file):
            raise DepthControlServiceError(
                404, "depth_control_content_missing", "深度控制文件不存在"
            )
        if thumbnail:
            return path, "image/jpeg", f"depth-control-{asset.id}.jpg"
        return path, "video/mp4", f"depth-control-{asset.id}.mp4"

    async def stage_content_deletion(
        self, asset: DepthControlAsset
    ) -> DepthContentDeletion:
        original_root = self._content_root(asset)
        if not await asyncio.to_thread(original_root.exists):
            return DepthContentDeletion(original_root=original_root)
        staged_root = original_root.with_name(f".deleting-{asset.id}-{uuid4().hex}")
        try:
            await asyncio.to_thread(os.replace, original_root, staged_root)
        except OSError as exc:
            raise DepthControlServiceError(
                500, "depth_control_delete_failed", f"无法准备删除深度控制文件：{exc}"
            ) from exc
        return DepthContentDeletion(original_root=original_root, staged_root=staged_root)

    async def restore_staged_content(self, deletion: DepthContentDeletion) -> None:
        if deletion.staged_root is None:
            return
        try:
            if await asyncio.to_thread(deletion.staged_root.exists):
                await asyncio.to_thread(
                    os.replace, deletion.staged_root, deletion.original_root
                )
        except OSError as exc:
            raise DepthControlServiceError(
                500,
                "depth_control_delete_restore_failed",
                f"删除事务失败后无法恢复深度控制文件：{exc}",
            ) from exc

    async def finalize_staged_content(self, deletion: DepthContentDeletion) -> bool:
        if deletion.staged_root is None:
            return True
        try:
            await asyncio.to_thread(shutil.rmtree, deletion.staged_root)
        except OSError:
            return False
        return True
