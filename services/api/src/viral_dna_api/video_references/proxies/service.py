from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from ...models import GenerationCandidate, GenerationKind, ProductionProject, ShotPlan
from ...notifications import NotificationPublisher
from ...workspace import WorkspaceError, WorkspaceManager
from ..domain import (
    ReferenceProxyAsset,
    ReferenceProxyKind,
    ReferenceProxyPrivacyMode,
    ReferenceProxyRenderProfile,
    ReferenceProxyStatus,
)
from .browser_video import BrowserVideoEncodingError, FfmpegBrowserVideoEncoder
from .contracts import (
    ProxyEngineCapability,
    ProxyEnhancementError,
    ProxyEnhancementRequest,
    ProxyGenerationOutput,
    ReferenceProxyEngine,
    ReferenceProxyEnhancer,
)
from .dwpose import DWPoseWholeBodyEngine
from .opencv_silhouette import OpenCvSilhouetteEngine

if TYPE_CHECKING:
    from ...image_generation.gateway import ImageGenerationGateway
    from ...video_generation.settings import VideoGenerationSettingsService


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


@dataclass(frozen=True, slots=True)
class ProxyContentDeletion:
    original_root: Path
    staged_root: Path | None = None


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


def _workspace_path(path: Path) -> Path:
    """Remove a Windows device prefix before workspace-boundary validation.

    Generators use Windows device paths for long-path-safe I/O, while ``Path.relative_to``
    treats a device-prefixed path as a different drive from the canonical workspace
    root.  Persisted metadata must always use the canonical workspace path.
    """

    if os.name != "nt":
        return path
    separator = chr(92)
    raw = str(path)
    prefix = f"{separator}{separator}?{separator}"
    unc_prefix = f"{prefix}UNC{separator}"
    if raw.startswith(unc_prefix):
        return Path(f"{separator}{separator}{raw[len(unc_prefix):]}")
    if raw.startswith(prefix):
        return Path(raw[len(prefix):])
    return path


class ReferenceProxyService:
    def __init__(
        self,
        workspace: WorkspaceManager,
        *,
        engines: list[ReferenceProxyEngine] | None = None,
        enhancers: list[ReferenceProxyEnhancer] | None = None,
        image_gateway: ImageGenerationGateway | None = None,
        video_settings: VideoGenerationSettingsService | None = None,
        browser_video_encoder: FfmpegBrowserVideoEncoder | None = None,
        notification_publisher: NotificationPublisher | None = None,
    ) -> None:
        self.workspace = workspace
        self.engines = engines if engines is not None else self._default_engines()
        self.browser_video_encoder = browser_video_encoder or FfmpegBrowserVideoEncoder()
        self.image_gateway = image_gateway
        self.video_settings = video_settings
        self._owns_default_enhancers = enhancers is None
        self.enhancers = (
            enhancers
            if enhancers is not None
            else self._default_enhancers(image_gateway, video_settings)
        )
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

    def _default_enhancers(
        self,
        image_gateway: ImageGenerationGateway | None,
        video_settings: VideoGenerationSettingsService | None,
    ) -> list[ReferenceProxyEnhancer]:
        from .ai import QwenMannequinImageEnhancer, SeedanceMannequinVideoEnhancer

        verifier = next(
            (engine for engine in self.engines if isinstance(engine, DWPoseWholeBodyEngine)),
            None,
        )
        if verifier is None:
            return []
        enhancers: list[ReferenceProxyEnhancer] = []
        if image_gateway is not None:
            enhancers.append(QwenMannequinImageEnhancer(image_gateway, verifier))
        if video_settings is not None:
            enhancers.append(
                SeedanceMannequinVideoEnhancer(
                    video_settings,
                    verifier,
                    video_encoder=self.browser_video_encoder,
                )
            )
        return enhancers

    def capabilities(self) -> list[ProxyEngineCapability]:
        if self.engines or self.enhancers:
            return [
                *[engine.capability for engine in self.engines],
                *[enhancer.capability for enhancer in self.enhancers],
            ]
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
            if self._owns_default_enhancers:
                self.enhancers = self._default_enhancers(
                    self.image_gateway,
                    self.video_settings,
                )
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

    def _enhancer(
        self,
        kind: ReferenceProxyKind,
        engine_name: str | None,
    ) -> ReferenceProxyEnhancer:
        matching = [
            enhancer
            for enhancer in self.enhancers
            if kind in enhancer.capability.kinds
            and (engine_name is None or enhancer.capability.engine == engine_name)
        ]
        if engine_name and not matching:
            raise ReferenceProxyServiceError(
                404,
                "reference_proxy_enhancer_not_found",
                "未找到指定的 AI 白模增强引擎",
            )
        for enhancer in matching:
            if enhancer.capability.available and enhancer.capability.production_ready:
                return enhancer
        note = next(
            (
                enhancer.capability.availability_note
                for enhancer in matching
                if enhancer.capability.availability_note
            ),
            "当前没有可用的 AI 白模增强引擎",
        )
        raise ReferenceProxyServiceError(
            409,
            "reference_proxy_enhancer_unavailable",
            note,
        )

    @staticmethod
    def _fallback_output(
        *,
        base_output: ProxyGenerationOutput,
        destination: Path,
        thumbnail: Path,
        privacy_mode: ReferenceProxyPrivacyMode,
        enhancer: ReferenceProxyEnhancer | None,
        error: Exception,
    ) -> ProxyGenerationOutput:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_output.path, destination)
        shutil.copy2(base_output.thumbnail_path, thumbnail)
        manifest_path = destination.with_name("pose-manifest.json")
        quality_path = destination.with_name("quality-report.json")
        if base_output.manifest_path is not None:
            shutil.copy2(base_output.manifest_path, manifest_path)
        else:
            manifest_path = None
        if base_output.quality_report_path is not None:
            shutil.copy2(base_output.quality_report_path, quality_path)
        else:
            quality_path = None
        return replace(
            base_output,
            path=destination,
            thumbnail_path=thumbnail,
            manifest_path=manifest_path,
            quality_report_path=quality_path,
            requested_render_profile=ReferenceProxyRenderProfile.AI_ENHANCED,
            effective_render_profile=ReferenceProxyRenderProfile.STRUCTURAL,
            privacy_mode=privacy_mode,
            base_engine=base_output.base_engine or "dwpose_wholebody_mannequin",
            base_engine_version=base_output.base_engine_version or "1.0.0",
            provider=(
                error.provider
                if isinstance(error, ProxyEnhancementError)
                else enhancer.capability.provider if enhancer else None
            ),
            provider_model=(
                error.provider_model
                if isinstance(error, ProxyEnhancementError)
                else enhancer.capability.model if enhancer else None
            ),
            provider_request_id=(
                error.provider_request_id
                if isinstance(error, ProxyEnhancementError)
                else None
            ),
            raw_source_uploaded=False,
            fallback_applied=True,
            fallback_reason=str(error)[:1000],
            estimated_cost_micros=(
                error.estimated_cost_micros
                if isinstance(error, ProxyEnhancementError)
                else None
            ),
            actual_cost_micros=(
                error.actual_cost_micros
                if isinstance(error, ProxyEnhancementError)
                else None
            ),
            cost_estimate_known=(
                error.cost_estimate_known
                if isinstance(error, ProxyEnhancementError)
                else False
            ),
            actual_cost_known=(
                error.actual_cost_known
                if isinstance(error, ProxyEnhancementError)
                else False
            ),
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

    def _proxy_content_root(self, asset: ReferenceProxyAsset) -> Path:
        if not asset.relative_path:
            raise ReferenceProxyServiceError(
                409,
                "reference_proxy_path_invalid",
                "白模文件路径无效",
            )
        relative_root = Path(asset.relative_path).parent
        if (
            relative_root.name != str(asset.id)
            or relative_root.parent.name != "reference-proxies"
        ):
            raise ReferenceProxyServiceError(
                409,
                "reference_proxy_path_invalid",
                "白模文件目录不符合安全删除规则",
            )
        try:
            return _filesystem_path(self.workspace.resolve(relative_root.as_posix()))
        except (OSError, ValueError, WorkspaceError) as exc:
            raise ReferenceProxyServiceError(
                409,
                "reference_proxy_path_invalid",
                "白模文件路径无效",
            ) from exc

    async def stage_content_deletion(
        self,
        asset: ReferenceProxyAsset,
    ) -> ProxyContentDeletion:
        """Atomically hide a proxy directory before its metadata is removed."""

        original_root = self._proxy_content_root(asset)
        if not await asyncio.to_thread(original_root.exists):
            return ProxyContentDeletion(original_root=original_root)
        if not await asyncio.to_thread(original_root.is_dir):
            raise ReferenceProxyServiceError(
                409,
                "reference_proxy_path_invalid",
                "白模文件目录无效，无法安全删除",
            )
        staged_root = original_root.with_name(
            f".deleting-{asset.id}-{uuid4().hex}"
        )
        try:
            await asyncio.to_thread(os.replace, original_root, staged_root)
        except OSError as exc:
            raise ReferenceProxyServiceError(
                500,
                "reference_proxy_delete_failed",
                f"无法准备删除白模文件：{exc}",
            ) from exc
        return ProxyContentDeletion(
            original_root=original_root,
            staged_root=staged_root,
        )

    async def restore_staged_content(
        self,
        deletion: ProxyContentDeletion,
    ) -> None:
        if deletion.staged_root is None:
            return
        try:
            if await asyncio.to_thread(deletion.staged_root.exists):
                await asyncio.to_thread(
                    os.replace,
                    deletion.staged_root,
                    deletion.original_root,
                )
        except OSError as exc:
            raise ReferenceProxyServiceError(
                500,
                "reference_proxy_delete_restore_failed",
                f"删除事务失败后无法恢复白模文件：{exc}",
            ) from exc

    async def finalize_staged_content(
        self,
        deletion: ProxyContentDeletion,
    ) -> bool:
        if deletion.staged_root is None:
            return True
        try:
            await asyncio.to_thread(shutil.rmtree, deletion.staged_root)
        except OSError:
            return False
        return True

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
        render_profile: ReferenceProxyRenderProfile = (
            ReferenceProxyRenderProfile.STRUCTURAL
        ),
        privacy_mode: ReferenceProxyPrivacyMode | None = None,
        enhancer_engine: str | None = None,
        fallback_to_structural: bool = True,
        allow_unknown_cost: bool = False,
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
        effective_privacy = privacy_mode or (
            ReferenceProxyPrivacyMode.LOCAL_ONLY
            if render_profile == ReferenceProxyRenderProfile.STRUCTURAL
            else ReferenceProxyPrivacyMode.ANONYMOUS_STRUCTURE_ONLY
        )
        if (
            render_profile == ReferenceProxyRenderProfile.STRUCTURAL
            and effective_privacy != ReferenceProxyPrivacyMode.LOCAL_ONLY
        ):
            raise ReferenceProxyServiceError(
                422,
                "reference_proxy_privacy_mode_invalid",
                "本机结构白模只能使用仅本机处理模式",
            )
        if (
            render_profile == ReferenceProxyRenderProfile.AI_ENHANCED
            and effective_privacy != ReferenceProxyPrivacyMode.ANONYMOUS_STRUCTURE_ONLY
        ):
            raise ReferenceProxyServiceError(
                422,
                "reference_proxy_privacy_mode_invalid",
                "AI 增强白模只允许上传匿名结构稿，不允许上传原始人物素材",
            )
        proxy_id = uuid4()
        root = (
            self.workspace.production_shot_root(project.record_id, project.id, shot.id)
            / "reference-proxies"
            / str(proxy_id)
        )
        is_image = kind.value.endswith("_image")
        destination = root / ("proxy.png" if is_image else "proxy.mp4")
        thumbnail = root / "thumbnail.png"
        base_root = (
            root
            if render_profile == ReferenceProxyRenderProfile.STRUCTURAL
            else root / "base"
        )
        base_destination = base_root / ("proxy.png" if is_image else "proxy.mp4")
        base_thumbnail = base_root / "thumbnail.png"
        try:
            base_output = await asyncio.to_thread(
                engine.generate,
                source_path=physical_source,
                destination_path=_filesystem_path(base_destination),
                thumbnail_path=_filesystem_path(base_thumbnail),
                kind=kind,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
            )
            base_output = replace(
                base_output,
                requested_render_profile=render_profile,
                effective_render_profile=ReferenceProxyRenderProfile.STRUCTURAL,
                privacy_mode=ReferenceProxyPrivacyMode.LOCAL_ONLY,
                base_engine=engine.capability.engine,
                base_engine_version=engine.capability.version,
                raw_source_uploaded=False,
            )
            selected_enhancer: ReferenceProxyEnhancer | None = None
            if render_profile == ReferenceProxyRenderProfile.AI_ENHANCED:
                try:
                    selected_enhancer = self._enhancer(kind, enhancer_engine)
                    duration_seconds = (
                        max(0.1, end_seconds - start_seconds)
                        if start_seconds is not None and end_seconds is not None
                        else None
                    )
                    output = await selected_enhancer.enhance(
                        ProxyEnhancementRequest(
                            request_id=proxy_id,
                            project=project,
                            shot=shot,
                            kind=kind,
                            base_output=base_output,
                            destination_path=_filesystem_path(destination),
                            thumbnail_path=_filesystem_path(thumbnail),
                            run_root=_filesystem_path(root / "ai-enhancement"),
                            duration_seconds=duration_seconds,
                            privacy_mode=effective_privacy,
                            allow_unknown_cost=allow_unknown_cost,
                        )
                    )
                except (ReferenceProxyServiceError, RuntimeError) as exc:
                    if not fallback_to_structural:
                        raise
                    output = await asyncio.to_thread(
                        self._fallback_output,
                        base_output=base_output,
                        destination=_filesystem_path(destination),
                        thumbnail=_filesystem_path(thumbnail),
                        privacy_mode=effective_privacy,
                        enhancer=selected_enhancer,
                        error=exc,
                    )
            else:
                output = base_output
        except ReferenceProxyServiceError:
            await asyncio.to_thread(shutil.rmtree, _filesystem_path(root), True)
            raise
        except RuntimeError as exc:
            await asyncio.to_thread(shutil.rmtree, _filesystem_path(root), True)
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
            engine=(
                output.base_engine or engine.capability.engine
                if output.effective_render_profile
                == ReferenceProxyRenderProfile.STRUCTURAL
                else enhancer_engine
                or next(
                    (
                        item.capability.engine
                        for item in self.enhancers
                        if item.capability.provider == output.provider
                        and item.capability.model == output.provider_model
                    ),
                    "ai_mannequin",
                )
            ),
            engine_version=(
                output.base_engine_version or engine.capability.version
                if output.effective_render_profile
                == ReferenceProxyRenderProfile.STRUCTURAL
                else "1.0.0"
            ),
            requested_render_profile=output.requested_render_profile,
            effective_render_profile=output.effective_render_profile,
            privacy_mode=output.privacy_mode,
            base_engine=output.base_engine,
            base_engine_version=output.base_engine_version,
            provider=output.provider,
            provider_model=output.provider_model,
            provider_request_id=output.provider_request_id,
            raw_source_uploaded=output.raw_source_uploaded,
            fallback_applied=output.fallback_applied,
            fallback_reason=output.fallback_reason,
            estimated_cost_micros=output.estimated_cost_micros,
            actual_cost_micros=output.actual_cost_micros,
            cost_estimate_known=output.cost_estimate_known,
            actual_cost_known=output.actual_cost_known,
            identity_removed=True,
            validation_status="passed",
            validation_message=output.validation_message,
            semantic_validation_status=output.semantic_validation_status,
            quality_score=output.quality_score,
            quality_metrics=output.quality_metrics or {},
            manifest_relative_path=(
                self.workspace.relative(_workspace_path(output.manifest_path))
                if output.manifest_path is not None
                else None
            ),
            quality_report_relative_path=(
                self.workspace.relative(_workspace_path(output.quality_report_path))
                if output.quality_report_path is not None
                else None
            ),
            model_sha256=output.model_sha256,
            created_at=now,
            updated_at=now,
        )
