from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from ...models import GenerationCandidate, GenerationKind, ProductionProject, ShotPlan
from ...notifications import NotificationPublisher
from ...workspace import WorkspaceError, WorkspaceManager
from ..domain import (
    ReferenceProxyAsset,
    ReferenceProxyKind,
    ReferenceProxyStatus,
)
from .browser_video import BrowserVideoEncodingError, FfmpegBrowserVideoEncoder
from .contracts import ProxyEngineCapability, ReferenceProxyEngine
from .dwpose import DWPoseWholeBodyEngine
from .opencv_silhouette import OpenCvSilhouetteEngine


class ReferenceProxyServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(slots=True)
class ProxyEngineInstallation:
    id: UUID
    engine: str
    status: str = "queued"
    progress_percent: int = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    message: str = "等待开始安装"
    error_code: str | None = None
    capability: ProxyEngineCapability | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


class ReferenceProxyService:
    def __init__(
        self,
        workspace: WorkspaceManager,
        *,
        engines: list[ReferenceProxyEngine] | None = None,
        browser_video_encoder: FfmpegBrowserVideoEncoder | None = None,
        notification_publisher: NotificationPublisher | None = None,
    ) -> None:
        self.workspace = workspace
        self.engines = engines if engines is not None else self._default_engines()
        self.browser_video_encoder = browser_video_encoder or FfmpegBrowserVideoEncoder()
        self.notification_publisher = notification_publisher
        self._install_lock = asyncio.Lock()
        self._installations: dict[UUID, ProxyEngineInstallation] = {}
        self._installation_tasks: dict[UUID, asyncio.Task[None]] = {}

    @staticmethod
    def _default_engines() -> list[ReferenceProxyEngine]:
        engines: list[ReferenceProxyEngine] = [DWPoseWholeBodyEngine()]
        try:
            import cv2  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return engines
        engines.append(OpenCvSilhouetteEngine())
        return engines

    def capabilities(self) -> list[ProxyEngineCapability]:
        if self.engines:
            return [engine.capability for engine in self.engines]
        return [
            ProxyEngineCapability(
                engine="opencv_silhouette",
                version="unavailable",
                kinds=(
                    ReferenceProxyKind.SILHOUETTE_IMAGE,
                    ReferenceProxyKind.SILHOUETTE_VIDEO,
                ),
                available=False,
                availability_note="请安装 API 的 reference-proxy 可选依赖后重启",
            )
        ]

    async def install_engine(self, engine_name: str) -> ProxyEngineCapability:
        """Install a supported local engine and refresh its in-memory capability."""

        return await self._install_engine(engine_name)

    async def start_engine_installation(
        self,
        engine_name: str,
    ) -> ProxyEngineInstallation:
        for current in self._installations.values():
            if current.engine == engine_name and current.status in {"queued", "running"}:
                return current
        self._installable_engine(engine_name)
        installation = ProxyEngineInstallation(id=uuid4(), engine=engine_name)
        self._installations[installation.id] = installation
        task = asyncio.create_task(self._run_engine_installation(installation.id))
        self._installation_tasks[installation.id] = task
        task.add_done_callback(
            lambda _task, job_id=installation.id: self._installation_tasks.pop(job_id, None)
        )
        return installation

    def engine_installation(self, installation_id: UUID) -> ProxyEngineInstallation:
        installation = self._installations.get(installation_id)
        if installation is None:
            raise ReferenceProxyServiceError(
                404,
                "reference_proxy_installation_not_found",
                "未找到该 DWPose 安装任务",
            )
        return installation

    def _installable_engine(self, engine_name: str) -> tuple[int, DWPoseWholeBodyEngine]:
        for index, engine in enumerate(self.engines):
            if engine.capability.engine != engine_name:
                continue
            if not isinstance(engine, DWPoseWholeBodyEngine):
                raise ReferenceProxyServiceError(
                    409,
                    "reference_proxy_engine_not_installable",
                    "该动作代理引擎不支持通过 ViralDNA 安装",
                )
            return index, engine
        raise ReferenceProxyServiceError(
            404,
            "reference_proxy_engine_not_found",
            "未找到指定动作代理引擎",
        )

    async def _install_engine(
        self,
        engine_name: str,
        *,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> ProxyEngineCapability:

        async with self._install_lock:
            index, engine = self._installable_engine(engine_name)
            try:
                await asyncio.to_thread(engine.model_manager.install, progress)
                refreshed = DWPoseWholeBodyEngine(
                    model_manager=engine.model_manager,
                    video_encoder=self.browser_video_encoder,
                )
            except (OSError, RuntimeError) as exc:
                raise ReferenceProxyServiceError(
                    502,
                    "reference_proxy_engine_install_failed",
                    f"DWPose WholeBody 模型安装失败：{exc}",
                ) from exc
            self.engines[index] = refreshed
            return refreshed.capability

    async def _run_engine_installation(self, installation_id: UUID) -> None:
        installation = self._installations[installation_id]
        installation.status = "running"
        installation.message = "正在准备下载 DWPose WholeBody"
        await self._notify_engine_installation(installation)

        def update_progress(downloaded: int, total: int, message: str) -> None:
            installation.downloaded_bytes = max(0, int(downloaded))
            installation.total_bytes = max(0, int(total))
            installation.progress_percent = (
                min(99, round(downloaded * 100 / total)) if total > 0 else 0
            )
            installation.message = message

        try:
            capability = await self._install_engine(
                installation.engine,
                progress=update_progress,
            )
        except ReferenceProxyServiceError as exc:
            installation.status = "failed"
            installation.error_code = exc.code
            installation.message = str(exc)
            await self._notify_engine_installation(installation)
            return
        installation.status = "succeeded"
        installation.progress_percent = 100
        installation.downloaded_bytes = installation.total_bytes
        installation.message = "DWPose WholeBody 安装成功"
        installation.capability = capability
        await self._notify_engine_installation(installation)

    async def _notify_engine_installation(
        self,
        installation: ProxyEngineInstallation,
    ) -> None:
        if self.notification_publisher is None:
            return
        if installation.status == "succeeded":
            level = "success"
            title = "DWPose WholeBody 安装成功"
        elif installation.status == "failed":
            level = "error"
            title = "DWPose WholeBody 安装失败"
        else:
            level = "info"
            title = "正在安装 DWPose WholeBody"
        try:
            await self.notification_publisher.publish(
                category="system",
                level=level,
                status=(
                    "in_progress"
                    if installation.status in {"queued", "running"}
                    else installation.status
                ),
                title=title,
                message=installation.message,
                event_key=f"reference-proxy-engine-install:{installation.engine}",
            )
        except Exception:
            # Notifications are auxiliary and must never change the installation result.
            return

    def _engine(self, kind: ReferenceProxyKind) -> ReferenceProxyEngine:
        for engine in self.engines:
            if (
                engine.capability.available
                and engine.capability.production_ready
                and kind in engine.capability.kinds
            ):
                return engine
        raise ReferenceProxyServiceError(
            409,
            "reference_proxy_engine_unavailable",
            "当前没有可用的动作代理引擎；请安装 local-ai 依赖或配置外部姿态代理引擎",
        )

    async def resolve_content(
        self,
        asset: ReferenceProxyAsset,
        *,
        thumbnail: bool = False,
    ) -> tuple[Path, str, str]:
        """Resolve a persisted proxy through the active workspace boundary."""

        if asset.status != ReferenceProxyStatus.READY:
            raise ReferenceProxyServiceError(
                409,
                "reference_proxy_not_ready",
                "白模尚未生成完成",
            )
        relative_path = (
            asset.thumbnail_relative_path if thumbnail else asset.relative_path
        )
        if not relative_path:
            raise ReferenceProxyServiceError(
                404,
                "reference_proxy_content_missing",
                "白模预览文件不存在",
            )
        try:
            path = self.workspace.resolve(relative_path)
        except (OSError, ValueError, WorkspaceError) as exc:
            raise ReferenceProxyServiceError(
                409,
                "reference_proxy_path_invalid",
                "白模文件路径无效",
            ) from exc
        physical_path = _filesystem_path(path)
        if not await asyncio.to_thread(physical_path.is_file):
            raise ReferenceProxyServiceError(
                404,
                "reference_proxy_content_missing",
                "白模预览文件不存在",
            )
        if (
            not thumbnail
            and asset.media_type.value == "video"
            and asset.engine == "opencv_silhouette"
            and asset.engine_version == "1.0.0"
        ):
            preview_path = physical_path.with_name("browser-preview.mp4")
            try:
                physical_path = await asyncio.to_thread(
                    self.browser_video_encoder.ensure_cached_preview,
                    physical_path,
                    preview_path,
                )
            except BrowserVideoEncodingError as exc:
                raise ReferenceProxyServiceError(
                    409,
                    "reference_proxy_browser_preview_failed",
                    str(exc),
                ) from exc
        is_image = thumbnail or asset.media_type.value == "image"
        suffix = ".png" if is_image else ".mp4"
        media_type = "image/png" if is_image else "video/mp4"
        return physical_path, media_type, f"reference-proxy-{asset.id}{suffix}"

    async def generate(
        self,
        *,
        project: ProductionProject,
        shot: ShotPlan,
        source_candidate: GenerationCandidate | None = None,
        source_path_override: Path | None = None,
        source_video_id: UUID | None = None,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
        kind: ReferenceProxyKind,
        visual_beat_id: UUID,
        order: int = 1,
    ) -> ReferenceProxyAsset:
        expected_kind = (
            GenerationKind.IMAGE
            if kind.value.endswith("_image")
            else GenerationKind.VIDEO
        )
        if source_candidate is None and source_path_override is None:
            raise ReferenceProxyServiceError(
                422,
                "reference_proxy_source_required",
                "动作代理缺少源素材",
            )
        if source_candidate is not None and source_candidate.kind != expected_kind:
            raise ReferenceProxyServiceError(
                422,
                "reference_proxy_source_kind_mismatch",
                "动作代理类型与源候选媒体类型不匹配",
            )
        if source_path_override is not None:
            source_path = source_path_override
            source_relative_path = self.workspace.relative(source_path)
        else:
            try:
                assert source_candidate is not None
                source_path = self.workspace.resolve(source_candidate.relative_path)
                source_relative_path = source_candidate.relative_path
            except (OSError, ValueError) as exc:
                raise ReferenceProxyServiceError(
                    409,
                    "reference_proxy_source_invalid",
                    "动作代理源文件路径无效",
                ) from exc
        physical_source = _filesystem_path(source_path)
        if not physical_source.is_file():
            raise ReferenceProxyServiceError(
                404,
                "reference_proxy_source_missing",
                "动作代理源文件不存在",
            )
        engine = self._engine(kind)
        proxy_id = uuid4()
        root = (
            self.workspace.production_shot_root(project.record_id, project.id, shot.id)
            / "reference-proxies"
            / str(proxy_id)
        )
        is_image = kind.value.endswith("_image")
        destination = root / ("proxy.png" if is_image else "proxy.mp4")
        thumbnail = root / "thumbnail.png"
        try:
            output = await asyncio.to_thread(
                engine.generate,
                source_path=physical_source,
                destination_path=_filesystem_path(destination),
                thumbnail_path=_filesystem_path(thumbnail),
                kind=kind,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
            )
        except RuntimeError as exc:
            raise ReferenceProxyServiceError(
                422,
                "reference_proxy_generation_failed",
                str(exc),
            ) from exc
        if not output.identity_removed or not _filesystem_path(output.path).is_file():
            raise ReferenceProxyServiceError(
                422,
                "reference_proxy_identity_validation_failed",
                "动作代理未通过身份去除校验，已禁止用于视频生成",
            )
        now = datetime.now(UTC)
        return ReferenceProxyAsset(
            id=proxy_id,
            visual_beat_id=visual_beat_id,
            order=order,
            kind=kind,
            media_type=output.media_type,
            status=ReferenceProxyStatus.READY,
            source_image_candidate_id=(
                source_candidate.id
                if source_candidate is not None and expected_kind == GenerationKind.IMAGE
                else None
            ),
            source_video_candidate_id=(
                source_candidate.id
                if source_candidate is not None and expected_kind == GenerationKind.VIDEO
                else None
            ),
            source_video_id=source_video_id,
            source_relative_path=source_relative_path,
            relative_path=self.workspace.relative(destination),
            thumbnail_relative_path=self.workspace.relative(thumbnail),
            sha256=_sha256(_filesystem_path(output.path)),
            engine=engine.capability.engine,
            engine_version=engine.capability.version,
            identity_removed=True,
            validation_status="passed",
            validation_message=output.validation_message,
            semantic_validation_status=output.semantic_validation_status,
            quality_score=output.quality_score,
            quality_metrics=output.quality_metrics or {},
            manifest_relative_path=(
                self.workspace.relative(root / output.manifest_path.name)
                if output.manifest_path is not None
                else None
            ),
            quality_report_relative_path=(
                self.workspace.relative(root / output.quality_report_path.name)
                if output.quality_report_path is not None
                else None
            ),
            model_sha256=output.model_sha256,
            created_at=now,
            updated_at=now,
        )
