from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from ..chinese import to_simplified
from ..media import MediaProcessingError, MediaProcessor
from ..media_staging import MediaStagingError, MediaStagingService
from ..models import (
    GenerationCandidate,
    GenerationCostSource,
    GenerationKind,
    GenerationRun,
    ImageExecutionMode,
    ProductionProject,
    ProductionRunStatus,
    ShotPlan,
    VideoGenerationCapability,
    VideoGenerationInputMode,
    VideoGenerationInputPlan,
    VideoGenerationInputSource,
)
from ..public_media import PublicMediaStager, PublicMediaStagingError
from ..video_references.planner import (
    VideoReferencePolicyError,
    resolve_video_reference_plan,
)
from ..workspace import WorkspaceManager
from .contracts import (
    MAX_GENERATED_VIDEO_BYTES,
    VIDEO_ADAPTER_PROTOCOL_VERSION,
    VIDEO_PROMPT_VERSION,
    VIDEO_REQUEST_SCHEMA_VERSION,
    DepthControlVideo,
    GeneratedVideo,
    OrderedReferenceFrame,
    ProviderManagedAssetReference,
    VideoAdapterIdentity,
    VideoAdapterRequest,
    VideoAdapterResult,
    VideoGenerationAdapter,
    VideoGenerationError,
    VideoGenerationRequest,
)
from .orchestrator import RemoteVideoOrchestrator, ResolvedVideoExecution
from .settings import VideoGenerationSettingsService

SIMULATED_VIDEO_ADAPTER_VERSION = "batch4.5.1"


class VideoGenerationGatewayError(VideoGenerationError):
    """Public gateway error translated by the production service."""


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


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


def _write_atomic(path: Path, payload: bytes) -> None:
    destination = _filesystem_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".tmp-{uuid4().hex[:8]}"
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _filesystem_path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compiled_dimensions(
    project: ProductionProject,
    capability: VideoGenerationCapability,
    resolution: str | None = None,
) -> tuple[int, int]:
    resolution_long_edge = {
        "512P": 960,
        "720P": 1280,
        "768P": 1366,
        "1080P": 1920,
        "2K": 2560,
    }.get((resolution or "").upper(), max(project.output_width, project.output_height))
    scale = min(
        1.0,
        capability.maximum_width / project.output_width,
        capability.maximum_height / project.output_height,
        resolution_long_edge / max(project.output_width, project.output_height),
    )
    width = max(256, math.floor(project.output_width * scale / 2) * 2)
    height = max(256, math.floor(project.output_height * scale / 2) * 2)
    return width, height


def _effective_input_mode(request: VideoGenerationRequest) -> VideoGenerationInputMode:
    """Derive the legacy coarse mode from the references actually submitted."""
    image_count = len(request.reference_frames) + len(request.managed_asset_references)
    video_count = len(request.depth_control_videos)
    if image_count == 0 and video_count == 0:
        return VideoGenerationInputMode.TEXT_TO_VIDEO
    if image_count and video_count:
        return VideoGenerationInputMode.HYBRID_REFERENCE_TO_VIDEO
    if video_count:
        return VideoGenerationInputMode.VIDEO_TO_VIDEO
    if image_count == 1:
        return VideoGenerationInputMode.IMAGE_TO_VIDEO
    return VideoGenerationInputMode.MULTI_IMAGE_TO_VIDEO


def _positive_prompt(
    shot: ShotPlan,
    reference_frames: tuple[OrderedReferenceFrame, ...],
    managed_asset_references: tuple[ProviderManagedAssetReference, ...] = (),
) -> str:
    lines = [f"动作与运镜要求：{shot.video_prompt.strip()}"]
    if shot.video_prompt_mentions:
        role_labels = {
            "actor_identity": "人物身份",
            "composition": "构图",
            "scene": "场景",
            "product": "产品外观",
            "wardrobe": "服装",
            "motion": "人物动作",
            "camera": "运镜",
            "depth": "动作与空间深度",
        }
        lines.append("提示词中的 @引用 与本次上传素材一一对应，必须按各自用途使用：")
        for mention in sorted(shot.video_prompt_mentions, key=lambda item: item.order):
            lines.append(
                f"- @{mention.label}：{role_labels[mention.role.value]}；"
                "不得与其他引用交换身份、外观、动作或空间职责。"
            )
    if managed_asset_references:
        names = "、".join(item.name for item in managed_asset_references)
        lines.append(
            f"人物身份只使用已绑定的 Provider 托管演员（{names}）；"
            "不要从本地动作、构图或场景参考中继承年龄、五官或可识别身份。"
        )
    if reference_frames:
        lines.extend(
            [
                "使用下列有序安全参考画面生成连续视频；图号顺序就是画面出现顺序。",
                "保持服装、产品结构、动作承接、空间位置、画幅和光影连续。",
            ]
        )
    for frame in reference_frames:
        lines.append(
            f"图{frame.ordinal}（{frame.title}）位于视频进度 "
            f"{frame.start_ratio:.0%}～{frame.end_ratio:.0%}。"
        )
        if frame.ordinal < len(reference_frames):
            transition = frame.transition_to_next_prompt.strip()
            lines.append(
                f"图{frame.ordinal}到图{frame.ordinal + 1}采用 "
                f"{frame.transition_to_next_type} 转场，约 "
                f"{frame.transition_to_next_duration_seconds:g} 秒"
                f"{f'；{transition}' if transition else '。'}"
            )
    lines.append("不添加配音、字幕、片头、片尾、额外文字或水印。")
    locked = "、".join(item.value for item in shot.locks)
    if locked:
        lines.append(f"必须保持的约束：{locked}。")
    text = "\n".join(lines)
    return (to_simplified(text) or text).strip()


def _negative_prompt(shot: ShotPlan) -> str:
    values = [
        *shot.video_negative_constraints,
        "人物身份漂移",
        "产品结构变形",
        "服装突变",
        "场景跳变",
        "闪烁",
        "镜头抖动",
        "动作不连贯",
        "额外文字",
        "水印",
    ]
    normalized: list[str] = []
    for value in values:
        item = (to_simplified(value) or value).strip()
        if item and item not in normalized:
            normalized.append(item)
    return "，".join(normalized)[:1000]


class SimulatedVideoAdapter:
    """Creates a silent still-frame MP4 for workflow verification only."""

    def __init__(self, media_processor: MediaProcessor | None = None) -> None:
        self.media_processor = media_processor or MediaProcessor()
        self.identity = VideoAdapterIdentity(
            execution_mode=ImageExecutionMode.SIMULATED,
            provider="simulated",
            model="approved-frame-hold",
            model_snapshot="batch4.5.1-simulated-video-v1",
            adapter_id="viral_dna_simulated_video",
            adapter_version=SIMULATED_VIDEO_ADAPTER_VERSION,
            protocol_version=VIDEO_ADAPTER_PROTOCOL_VERSION,
            capability=VideoGenerationCapability(
                image_to_video=True,
                multi_image_reference=True,
                ordered_reference_images=True,
                minimum_reference_images=1,
                maximum_reference_images=20,
                start_frame=True,
                end_frame=False,
                max_candidates=4,
                minimum_duration_seconds=0.1,
                maximum_duration_seconds=60,
                maximum_width=1920,
                maximum_height=1920,
                native_audio=False,
            ),
            estimated_cost_micros=0,
            cost_estimate_known=True,
            cost_source=GenerationCostSource.UNMETERED,
            pricing_version="simulated-zero-cost-v1",
            execution_summary={
                "simulated": True,
                "purpose": "workflow_validation",
                "native_audio": False,
            },
        )

    async def generate(self, request: VideoAdapterRequest) -> VideoAdapterResult:
        videos: list[GeneratedVideo] = []
        for ordinal in range(1, request.candidate_count + 1):
            if request.cancel_event is not None and request.cancel_event.is_set():
                raise VideoGenerationError(
                    409,
                    "generation_cancelled",
                    "视频生成任务已取消",
                )
            destination = request.run_root / f"candidate_{ordinal:03d}.mp4"
            temporary = request.run_root / f".candidate_{ordinal:03d}.mp4"
            try:
                await self.media_processor.create_still_video(
                    request.reference_frames[0].path,
                    _filesystem_path(temporary),
                    duration_seconds=request.duration_seconds,
                    width=request.width,
                    height=request.height,
                )
                os.replace(_filesystem_path(temporary), _filesystem_path(destination))
            except MediaProcessingError as exc:
                raise VideoGenerationError(
                    503 if exc.code == "media_dependency_missing" else 502,
                    exc.code,
                    str(exc),
                    retryable=exc.retryable,
                ) from exc
            finally:
                _filesystem_path(temporary).unlink(missing_ok=True)
            videos.append(
                GeneratedVideo(
                    path=destination,
                    width=request.width,
                    height=request.height,
                    duration_seconds=request.duration_seconds,
                    metadata={
                        "simulated": True,
                        "ordinal": ordinal,
                        "source": "approved_image_hold",
                    },
                )
            )
        return VideoAdapterResult(
            videos=tuple(videos),
            usage={
                "candidate_count": len(videos),
                "duration_seconds": request.duration_seconds,
                "native_audio": False,
            },
            actual_cost_micros=0,
            cost_source=GenerationCostSource.UNMETERED,
        )


class VideoGenerationGateway:
    """Provider-neutral video generation boundary.

    Only the simulated adapter is registered in Batch 4.5.1. The registry is
    the extension seam for Batch 4.5.2's domestic remote adapter and for a
    possible future local implementation; no local executable is accepted or
    launched by this batch.
    """

    def __init__(
        self,
        workspace: WorkspaceManager,
        *,
        media_processor: MediaProcessor | None = None,
        adapters: Mapping[ImageExecutionMode, VideoGenerationAdapter] | None = None,
        settings_service: VideoGenerationSettingsService | None = None,
        repository: object | None = None,
        remote_orchestrator: RemoteVideoOrchestrator | None = None,
        public_media_stager: PublicMediaStager | None = None,
        media_staging_service: MediaStagingService | None = None,
    ) -> None:
        self.workspace = workspace
        self.public_media_stager = public_media_stager or PublicMediaStager(workspace)
        self.media_staging_service = media_staging_service
        if adapters is None:
            simulated = SimulatedVideoAdapter(media_processor)
            self.adapters: dict[ImageExecutionMode, VideoGenerationAdapter] = {
                ImageExecutionMode.SIMULATED: simulated,
            }
        else:
            self.adapters = dict(adapters)
        self.settings_service = settings_service
        self.remote_orchestrator = remote_orchestrator
        if (
            self.remote_orchestrator is None
            and settings_service is not None
            and repository is not None
        ):
            self.remote_orchestrator = RemoteVideoOrchestrator(settings_service, repository)

    def validate_execution_mode(self, mode: ImageExecutionMode) -> None:
        if mode == ImageExecutionMode.LOCAL_TOOL:
            raise VideoGenerationGatewayError(
                409,
                "video_local_tool_not_supported",
                "当前版本不支持本机视频生成工具",
            )
        if mode == ImageExecutionMode.REMOTE_API and self.remote_orchestrator is not None:
            return
        if mode not in self.adapters:
            code = (
                "video_remote_provider_not_configured"
                if mode == ImageExecutionMode.REMOTE_API
                else "video_adapter_not_configured"
            )
            message = (
                "国内视频生成 API 将在 Batch 4.5.2 接入"
                if mode == ImageExecutionMode.REMOTE_API
                else "当前视频生成执行器尚未配置"
            )
            raise VideoGenerationGatewayError(409, code, message)

    def resolve_identity(
        self,
        *,
        execution_mode: str,
        model_alias: str | None,
        duration_seconds: float,
        resolution: str | None,
        candidate_count: int,
        allow_unknown_cost: bool,
    ) -> tuple[VideoAdapterIdentity, ResolvedVideoExecution | None]:
        try:
            mode = ImageExecutionMode(execution_mode)
        except ValueError as exc:
            raise VideoGenerationGatewayError(
                422,
                "video_execution_mode_invalid",
                "视频生成执行模式无效",
            ) from exc
        self.validate_execution_mode(mode)
        if mode == ImageExecutionMode.REMOTE_API:
            if self.remote_orchestrator is None:
                raise VideoGenerationGatewayError(
                    409,
                    "video_remote_provider_not_configured",
                    "远程视频 Provider 尚未配置",
                )
            try:
                resolved = self.remote_orchestrator.resolve(
                    model_alias=model_alias,
                    duration_seconds=duration_seconds,
                    resolution=resolution,
                    candidate_count=candidate_count,
                    allow_unknown_cost=allow_unknown_cost,
                )
            except VideoGenerationError as exc:
                raise VideoGenerationGatewayError(
                    exc.status_code,
                    exc.code,
                    str(exc),
                    retryable=exc.retryable,
                ) from exc
            if not resolved.identity.capability.reference_route.enabled:
                raise VideoGenerationGatewayError(
                    409,
                    "video_reference_route_disabled",
                    resolved.identity.capability.reference_route.availability_note
                    or "当前模型的参考素材路由尚未开放",
                )
            return resolved.identity, resolved
        adapter = self.adapters.get(mode)
        if adapter is None:
            raise VideoGenerationGatewayError(
                409,
                "video_adapter_not_configured",
                "当前视频生成执行器尚未配置",
            )
        if not adapter.identity.capability.reference_route.enabled:
            raise VideoGenerationGatewayError(
                409,
                "video_reference_route_disabled",
                adapter.identity.capability.reference_route.availability_note
                or "当前模型的参考素材路由尚未开放",
            )
        return adapter.identity, None

    async def cancel(self, run_id: UUID) -> None:
        if self.remote_orchestrator is not None:
            await self.remote_orchestrator.cancel_run(run_id)

    def _depth_control_videos(self, shot: ShotPlan) -> tuple[DepthControlVideo, ...]:
        selected = [item for item in shot.depth_control_assets if item.enabled]
        if len(selected) > 1:
            raise VideoGenerationGatewayError(
                422,
                "depth_control_count_invalid",
                "一个分镜只能启用一个全场景深度控制视频",
            )
        if not selected:
            return ()
        asset = selected[0]
        if not asset.usable_for_generation or not asset.relative_path or not asset.sha256:
            raise VideoGenerationGatewayError(
                422,
                "depth_control_not_ready",
                "已启用的深度控制视频尚未通过质检，请重新生成",
            )
        try:
            path = self.workspace.resolve(asset.relative_path)
        except (OSError, ValueError) as exc:
            raise VideoGenerationGatewayError(
                409,
                "depth_control_path_invalid",
                "深度控制视频路径无效，请重新生成",
            ) from exc
        if not path.is_file():
            raise VideoGenerationGatewayError(
                404,
                "depth_control_file_missing",
                "深度控制视频文件不存在，请重新生成",
            )
        return (
            DepthControlVideo(
                control_asset_id=asset.id,
                source_video_id=asset.source_video_id,
                ordinal=1,
                title="全场景深度控制",
                path=path,
                relative_path=asset.relative_path,
                sha256=asset.sha256,
                kind=asset.kind.value,
                depth_convention=asset.depth_convention.value,
            ),
        )

    async def generate(
        self,
        project: ProductionProject,
        shot: ShotPlan,
        revision_id: UUID,
        reference_frames: tuple[OrderedReferenceFrame, ...],
        *,
        candidate_count: int,
        duration_seconds: float,
        execution_mode: str = "simulated",
        model_alias: str | None = None,
        resolution: str | None = None,
        allow_unknown_cost: bool = False,
        seed: int | None = None,
        run_id: UUID | None = None,
        cancel_event: Event | None = None,
        input_plan: VideoGenerationInputPlan | None = None,
    ) -> tuple[GenerationRun, list[GenerationCandidate]]:
        input_plan = input_plan or VideoGenerationInputPlan(
            sources=[VideoGenerationInputSource.APPROVED_IMAGES]
        )
        try:
            mode = ImageExecutionMode(execution_mode)
        except ValueError as exc:
            raise VideoGenerationGatewayError(
                422,
                "video_execution_mode_invalid",
                "视频生成执行模式无效",
            ) from exc
        identity, resolved_remote = self.resolve_identity(
            execution_mode=mode.value,
            model_alias=model_alias,
            duration_seconds=duration_seconds,
            resolution=resolution,
            candidate_count=candidate_count,
            allow_unknown_cost=allow_unknown_cost,
        )
        adapter = self.adapters.get(mode)
        capability = identity.capability
        if input_plan.sources and not capability.reference_route.enabled:
            raise VideoGenerationGatewayError(
                409,
                "video_reference_route_disabled",
                capability.reference_route.availability_note
                or "当前模型的参考素材路由尚未开放",
            )
        source_ordered_frames = tuple(sorted(reference_frames, key=lambda item: item.ordinal))
        if [item.ordinal for item in source_ordered_frames] != list(
            range(1, len(source_ordered_frames) + 1)
        ):
            raise VideoGenerationGatewayError(
                422,
                "video_reference_order_invalid",
                "参考图序号必须连续",
            )
        all_managed_references = tuple(
            ProviderManagedAssetReference(
                binding_id=binding.id,
                provider=binding.provider,
                asset_id=binding.asset_id,
                group_id=binding.group_id,
                kind=binding.kind.value,
                role=binding.role.value,
                name=binding.name,
                media_type=binding.media_type.value,
                project_name=binding.project_name,
                uri=f"asset://{binding.asset_id}",
            )
            for binding in shot.managed_asset_bindings
        )
        mentioned_managed_ids = {
            item.reference_id
            for item in shot.video_prompt_mentions
            if item.reference_kind.value == "provider_managed_asset"
        }
        managed_references = (
            tuple(
                item
                for item in all_managed_references
                if not mentioned_managed_ids or item.binding_id in mentioned_managed_ids
            )
            if input_plan.includes(VideoGenerationInputSource.PROVIDER_MANAGED_ASSETS)
            else ()
        )
        managed_capability = capability.managed_assets
        if managed_references and not managed_capability.supported:
            raise VideoGenerationGatewayError(
                422,
                "video_managed_assets_unsupported",
                "当前视频模型不支持供应商托管人物资产，请切换到支持该能力的 Seedance 模型",
            )
        if len(managed_references) > managed_capability.maximum_bindings:
            raise VideoGenerationGatewayError(
                422,
                "video_managed_asset_count_unsupported",
                f"当前视频模型最多绑定 {managed_capability.maximum_bindings} 个托管资产",
            )
        managed_bindings_by_id = {item.id: item for item in shot.managed_asset_bindings}
        for reference in managed_references:
            binding = managed_bindings_by_id[reference.binding_id]
            if binding.provider != managed_capability.provider:
                raise VideoGenerationGatewayError(
                    422,
                    "video_managed_asset_provider_mismatch",
                    "所选托管资产与当前视频模型不属于同一个 Provider",
                )
            if binding.kind not in managed_capability.asset_kinds:
                raise VideoGenerationGatewayError(
                    422,
                    "video_managed_asset_kind_unsupported",
                    "当前视频模型不支持所选托管资产类型",
                )
            if binding.role not in managed_capability.roles:
                raise VideoGenerationGatewayError(
                    422,
                    "video_managed_asset_role_unsupported",
                    "当前视频模型不支持所选托管资产角色",
                )
            transport_supported = managed_capability.reference_transport == "asset_uri"
            uri_supported = reference.uri.startswith("asset://")
            if not transport_supported or not uri_supported:
                raise VideoGenerationGatewayError(
                    422,
                    "video_managed_asset_transport_unsupported",
                    "当前视频模型无法使用该托管资产引用协议",
                )
        depth_control_videos = (
            self._depth_control_videos(shot)
            if input_plan.includes(VideoGenerationInputSource.DEPTH_CONTROL)
            else ()
        )
        try:
            reference_plan = resolve_video_reference_plan(
                capability=capability,
                shot=shot,
                reference_frames=source_ordered_frames,
                managed_asset_references=managed_references,
                depth_control_videos=depth_control_videos,
                public_media_transport_ready=(
                    await self.media_staging_service.ready()
                    if self.media_staging_service is not None
                    else self.public_media_stager.ready
                ),
                depth_optional=True,
            )
        except VideoReferencePolicyError as exc:
            raise VideoGenerationGatewayError(422, exc.code, str(exc)) from exc
        ordered_frames = reference_plan.reference_frames
        depth_control_videos = reference_plan.depth_control_videos
        if depth_control_videos:
            try:
                staged_depth_videos: list[DepthControlVideo] = []
                for item in depth_control_videos:
                    if self.media_staging_service is not None:
                        staged = await self.media_staging_service.stage_path(
                            item.path,
                            expected_sha256=item.sha256,
                            purpose=f"video_generation:{run_id or 'pending'}",
                        )
                        staged_depth_videos.append(
                            replace(
                                item,
                                public_url=staged.url,
                                storage_object_id=staged.storage_object_id,
                                access_lease_id=staged.lease_id,
                            )
                        )
                    else:
                        staged_depth_videos.append(
                            replace(
                                item,
                                public_url=self.public_media_stager.stage(item.path).url,
                            )
                        )
                depth_control_videos = tuple(staged_depth_videos)
            except MediaStagingError as exc:
                raise VideoGenerationGatewayError(
                    exc.status_code,
                    exc.code,
                    str(exc),
                ) from exc
            except PublicMediaStagingError as exc:
                raise VideoGenerationGatewayError(
                    exc.status_code,
                    exc.code,
                    str(exc),
                ) from exc
        managed_references = reference_plan.managed_asset_references
        reference_manifest = {
            **reference_plan.manifest(),
            "input_plan": input_plan.model_dump(mode="json"),
            "prompt_mentions": [
                item.model_dump(mode="json")
                for item in sorted(shot.video_prompt_mentions, key=lambda value: value.order)
            ],
        }
        total_reference_count = (
            len(ordered_frames) + len(depth_control_videos) + len(managed_references)
        )
        if total_reference_count == 0 and not capability.text_to_video:
            raise VideoGenerationGatewayError(
                422,
                "video_text_to_video_unsupported",
                "当前模型不支持纯文生视频，请选择图片或资产输入",
            )
        if total_reference_count > 0 and not (
            capability.minimum_reference_images
            <= total_reference_count
            <= capability.maximum_reference_images
        ):
            raise VideoGenerationGatewayError(
                422,
                "video_reference_count_unsupported",
                (
                    f"当前模型支持 {capability.minimum_reference_images}～"
                    f"{capability.maximum_reference_images} 个参考输入；"
                    f"当前包含 {len(managed_references)} 个托管资产和 "
                    f"{len(ordered_frames)} 张外观参考图、"
                    f"{len(depth_control_videos)} 个深度控制视频"
                ),
            )
        if candidate_count < 1 or candidate_count > capability.max_candidates:
            raise VideoGenerationGatewayError(
                422,
                "video_candidate_count_unsupported",
                f"当前执行器最多生成 {capability.max_candidates} 个视频候选",
            )
        if not (
            capability.minimum_duration_seconds
            <= duration_seconds
            <= capability.maximum_duration_seconds
        ):
            raise VideoGenerationGatewayError(
                422,
                "video_duration_unsupported",
                (
                    "当前执行器支持的时长范围为 "
                    f"{capability.minimum_duration_seconds:g}～"
                    f"{capability.maximum_duration_seconds:g} 秒"
                ),
            )
        if not identity.cost_estimate_known and not allow_unknown_cost:
            raise VideoGenerationGatewayError(
                409,
                "video_unknown_cost_confirmation_required",
                "当前视频模型无法预估成本，请确认未知成本后重试",
            )

        run_id = run_id or uuid4()
        run_root = (
            self.workspace.production_shot_root(project.record_id, project.id, shot.id)
            / "videos"
            / str(run_id)
        )
        _filesystem_path(run_root).mkdir(parents=True, exist_ok=True)
        selected_resolution = resolved_remote.resolution if resolved_remote else resolution
        width, height = _compiled_dimensions(project, capability, selected_resolution)
        prompt = _positive_prompt(shot, ordered_frames, managed_references)
        negative_prompt = _negative_prompt(shot)
        request = VideoGenerationRequest(
            project=project,
            shot=shot,
            revision_id=revision_id,
            reference_frames=ordered_frames,
            candidate_count=candidate_count,
            duration_seconds=duration_seconds,
            execution_mode=mode,
            model_alias=identity.model_alias,
            resolution=selected_resolution,
            allow_unknown_cost=allow_unknown_cost,
            seed=seed,
            managed_asset_references=managed_references,
            depth_control_videos=depth_control_videos,
            reference_manifest=reference_manifest,
            input_plan=input_plan,
        )
        effective_input_mode = _effective_input_mode(request)
        input_payload = self._input_payload(
            request,
            identity,
            width=width,
            height=height,
            prompt=prompt,
            negative_prompt=negative_prompt,
        )
        fingerprint = hashlib.sha256(_canonical_json(input_payload)).hexdigest()
        input_path = run_root / "input.json"
        _write_atomic(input_path, _canonical_json(input_payload) + b"\n")
        started = time.perf_counter()
        try:
            adapter_request = VideoAdapterRequest(
                request_id=run_id,
                run_root=run_root,
                project=project,
                shot=shot,
                reference_frames=ordered_frames,
                candidate_count=candidate_count,
                duration_seconds=duration_seconds,
                width=width,
                height=height,
                positive_prompt=prompt,
                negative_prompt=negative_prompt,
                seed=seed,
                capability=capability,
                managed_asset_references=managed_references,
                depth_control_videos=depth_control_videos,
                reference_manifest=reference_manifest,
                input_plan=input_plan,
                cancel_event=cancel_event,
            )
            if resolved_remote is not None:
                if self.remote_orchestrator is None:  # pragma: no cover
                    raise VideoGenerationGatewayError(
                        409,
                        "video_remote_provider_not_configured",
                        "远程视频 Provider 尚未配置",
                    )
                result = await self.remote_orchestrator.generate(
                    resolved_remote,
                    run_id=run_id,
                    project_id=project.id,
                    shot_plan_id=shot.id,
                    run_root=run_root,
                    reference_frames=ordered_frames,
                    depth_control_videos=depth_control_videos,
                    managed_asset_references=managed_references,
                    candidate_count=candidate_count,
                    duration_seconds=duration_seconds,
                    aspect_ratio=project.output_aspect_ratio,
                    width=width,
                    height=height,
                    positive_prompt=prompt,
                    negative_prompt=negative_prompt,
                    seed=seed,
                    cancel_event=cancel_event,
                    reference_manifest=reference_manifest,
                )
            else:
                if adapter is None:  # pragma: no cover
                    raise VideoGenerationGatewayError(
                        409,
                        "video_adapter_not_configured",
                        "当前视频生成执行器尚未配置",
                    )
                result = await adapter.generate(adapter_request)
        except VideoGenerationError as exc:
            raise VideoGenerationGatewayError(
                exc.status_code,
                exc.code,
                str(exc),
                retryable=exc.retryable,
                provider_code=exc.provider_code,
                error_category=exc.error_category,
                user_title=exc.user_title,
                suggested_action=exc.suggested_action,
                technical_message=exc.technical_message,
            ) from exc
        if cancel_event is not None and cancel_event.is_set():
            raise VideoGenerationGatewayError(
                409,
                "generation_cancelled",
                "视频生成任务已取消",
            )
        if resolved_remote is None and len(result.videos) != candidate_count:
            raise VideoGenerationGatewayError(
                502,
                "video_candidate_count_mismatch",
                "视频执行器返回的候选数量与请求不一致",
            )

        candidates = [
            self._save_candidate(
                run_root,
                run_id,
                int(generated.metadata.get("provider_ordinal") or ordinal),
                generated,
                request=request,
                identity=identity,
                request_fingerprint=fingerprint,
                target_width=width,
                target_height=height,
            )
            for ordinal, generated in enumerate(result.videos, start=1)
        ]
        actual_cost_known = result.actual_cost_micros is not None
        actual_cost = result.actual_cost_micros or 0
        cost_source = result.cost_source or identity.cost_source
        manifest_path = run_root / "manifest.json"
        manifest = {
            "schema_version": "viral-dna-video-generation-result/v1",
            "status": "completed",
            "request_id": str(run_id),
            "request_fingerprint": fingerprint,
            "provider_request_id": result.provider_request_id,
            "candidate_ids": [str(item.id) for item in candidates],
            "candidate_sha256": [item.sha256 for item in candidates],
            "estimated_cost_micros": identity.estimated_cost_micros,
            "actual_cost_micros": actual_cost,
            "cost_source": cost_source.value,
        }
        _write_atomic(manifest_path, _canonical_json(manifest) + b"\n")
        completed_at = datetime.now(UTC)
        run = GenerationRun(
            id=run_id,
            project_id=project.id,
            shot_plan_id=shot.id,
            revision_id=revision_id,
            kind=GenerationKind.VIDEO,
            input_mode=effective_input_mode,
            provider=identity.provider,
            model=identity.model,
            model_snapshot=identity.model_snapshot,
            model_alias=identity.model_alias,
            model_display_name=identity.model_display_name,
            prompt_version=VIDEO_PROMPT_VERSION,
            schema_version=VIDEO_REQUEST_SCHEMA_VERSION,
            pricing_version=identity.pricing_version,
            request_fingerprint=fingerprint,
            input_snapshot_relative_path=self.workspace.relative(input_path),
            execution_mode=identity.execution_mode,
            adapter_id=identity.adapter_id,
            adapter_version=identity.adapter_version,
            protocol_version=identity.protocol_version,
            provider_request_id=result.provider_request_id,
            capability_snapshot=capability.model_dump(mode="json"),
            execution_summary=identity.execution_summary,
            cost_source=cost_source,
            cost_estimate_known=identity.cost_estimate_known,
            actual_cost_known=actual_cost_known,
            cost_currency="CNY",
            pricing_snapshot=identity.pricing_snapshot,
            usage=result.usage,
            output_manifest_relative_path=self.workspace.relative(manifest_path),
            status=ProductionRunStatus.COMPLETED,
            estimated_cost_micros=identity.estimated_cost_micros,
            actual_cost_micros=max(0, actual_cost),
            latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
            completed_at=completed_at,
        )
        return run, candidates

    def _input_payload(
        self,
        request: VideoGenerationRequest,
        identity: VideoAdapterIdentity,
        *,
        width: int,
        height: int,
        prompt: str,
        negative_prompt: str,
    ) -> dict[str, object]:
        return {
            "schema_version": VIDEO_REQUEST_SCHEMA_VERSION,
            "input_mode": _effective_input_mode(request).value,
            "input_plan": request.input_plan.model_dump(mode="json"),
            "project_id": str(request.project.id),
            "shot_plan_id": str(request.shot.id),
            "revision_id": str(request.revision_id),
            "execution": {
                "mode": identity.execution_mode.value,
                "provider": identity.provider,
                "model": identity.model,
                "model_alias": identity.model_alias,
                "model_display_name": identity.model_display_name,
                "model_snapshot": identity.model_snapshot,
                "adapter_id": identity.adapter_id,
                "adapter_version": identity.adapter_version,
                "protocol_version": identity.protocol_version,
                "capabilities": identity.capability.model_dump(mode="json"),
                "summary": identity.execution_summary,
            },
            "output": {
                "aspect_ratio": request.project.output_aspect_ratio,
                "requested_width": request.project.output_width,
                "requested_height": request.project.output_height,
                "compiled_width": width,
                "compiled_height": height,
                "duration_seconds": request.duration_seconds,
                "candidate_count": request.candidate_count,
                "resolution": request.resolution,
                "native_audio": identity.capability.native_audio,
            },
            "prompt": {
                "positive": prompt,
                "negative": negative_prompt,
                "version": VIDEO_PROMPT_VERSION,
            },
            "seed": request.seed,
            "reference_images": [
                {
                    "visual_beat_id": str(frame.visual_beat_id),
                    "ordinal": frame.ordinal,
                    "title": frame.title,
                    "role": frame.role,
                    "source_kind": frame.source_kind,
                    "candidate_id": str(frame.candidate_id),
                    "relative_path": frame.relative_path,
                    "sha256": frame.sha256,
                    "start_ratio": frame.start_ratio,
                    "end_ratio": frame.end_ratio,
                    "transition_to_next_type": frame.transition_to_next_type,
                    "transition_to_next_duration_seconds": (
                        frame.transition_to_next_duration_seconds
                    ),
                    "transition_to_next_prompt": frame.transition_to_next_prompt,
                }
                for frame in request.reference_frames
            ],
            "depth_control_videos": [
                {
                    "control_asset_id": str(video.control_asset_id),
                    "source_video_id": str(video.source_video_id),
                    "ordinal": video.ordinal,
                    "title": video.title,
                    "relative_path": video.relative_path,
                    "sha256": video.sha256,
                    "kind": video.kind,
                    "depth_convention": video.depth_convention,
                }
                for video in request.depth_control_videos
            ],
            "managed_asset_references": [
                {
                    "binding_id": str(reference.binding_id),
                    "provider": reference.provider,
                    "asset_id": reference.asset_id,
                    "group_id": reference.group_id,
                    "kind": reference.kind,
                    "role": reference.role,
                    "name": reference.name,
                    "media_type": reference.media_type,
                    "project_name": reference.project_name,
                    "uri": reference.uri,
                }
                for reference in request.managed_asset_references
            ],
            "reference_policy": request.reference_manifest,
            "locks": [item.value for item in request.shot.locks],
            "cost": {
                "estimated_cost_micros": identity.estimated_cost_micros,
                "estimate_known": identity.cost_estimate_known,
                "source": identity.cost_source.value,
            },
        }

    def _save_candidate(
        self,
        run_root: Path,
        run_id: UUID,
        ordinal: int,
        generated: GeneratedVideo,
        *,
        request: VideoGenerationRequest,
        identity: VideoAdapterIdentity,
        request_fingerprint: str,
        target_width: int,
        target_height: int,
    ) -> GenerationCandidate:
        try:
            resolved = generated.path.resolve()
            resolved.relative_to(run_root.resolve())
        except (OSError, ValueError) as exc:
            raise VideoGenerationGatewayError(
                502,
                "generated_video_path_invalid",
                "视频执行器返回了工作目录之外的文件",
            ) from exc
        filesystem_path = _filesystem_path(resolved)
        if generated.media_type != "video/mp4":
            raise VideoGenerationGatewayError(
                502,
                "generated_video_format_unsupported",
                "当前基础架构只接受 MP4 视频候选",
            )
        try:
            size_bytes = filesystem_path.stat().st_size
        except OSError as exc:
            raise VideoGenerationGatewayError(
                502,
                "generated_video_missing",
                "视频执行器没有输出候选文件",
            ) from exc
        if size_bytes <= 0 or size_bytes > MAX_GENERATED_VIDEO_BYTES:
            raise VideoGenerationGatewayError(
                502,
                "generated_video_size_invalid",
                "视频候选为空或超过工作区安全限制",
            )

        width = generated.width or target_width
        height = generated.height or target_height
        duration = generated.duration_seconds or request.duration_seconds
        sha256 = _sha256_file(resolved)
        thumbnail_path = run_root / f"candidate_{ordinal:03d}.webp"
        if request.reference_frames:
            self._write_thumbnail(request.reference_frames[0].path, thumbnail_path)
        else:
            self._write_placeholder_thumbnail(
                thumbnail_path,
                width=width,
                height=height,
            )
        quality_report = {
            "schema_version": "viral-dna-video-quality/v1",
            "status": "manual_review_required",
            "summary": (
                "基础文件检查通过；需人工检查动作、稳定性、主体一致性与时长。"
                if identity.execution_mode == ImageExecutionMode.REMOTE_API
                else "基础文件检查通过；模拟候选仅用于验证流程，需人工检查动作、稳定性与时长。"
            ),
            "automated_checks": {
                "file_integrity": {
                    "status": "passed",
                    "size_bytes": size_bytes,
                    "media_type": generated.media_type,
                },
                "duration": {
                    "status": "passed",
                    "requested_seconds": request.duration_seconds,
                    "actual_seconds": duration,
                },
                "dimensions": {
                    "status": "passed",
                    "width": width,
                    "height": height,
                },
                "native_audio": {
                    "status": "not_requested",
                    "present": False,
                },
            },
            "manual_checks": [
                {"id": "motion", "label": "动作与运镜", "status": "required"},
                {"id": "identity", "label": "人物与产品稳定性", "status": "required"},
                {"id": "continuity", "label": "画面连续性", "status": "required"},
            ],
            "simulated": identity.execution_mode == ImageExecutionMode.SIMULATED,
        }
        metadata_path = run_root / f"candidate_{ordinal:03d}.json"
        metadata = {
            "schema_version": "viral-dna-video-candidate/v1",
            "ordinal": ordinal,
            "provider": identity.provider,
            "model": identity.model,
            "request_fingerprint": request_fingerprint,
            "sha256": sha256,
            "width": width,
            "height": height,
            "duration_seconds": duration,
            "quality_report": quality_report,
            "adapter_metadata": generated.metadata,
        }
        _write_atomic(metadata_path, _canonical_json(metadata) + b"\n")
        return GenerationCandidate(
            generation_run_id=run_id,
            ordinal=ordinal,
            kind=GenerationKind.VIDEO,
            relative_path=self.workspace.relative(resolved),
            thumbnail_relative_path=self.workspace.relative(thumbnail_path),
            width=width,
            height=height,
            duration_seconds=round(duration, 3),
            sha256=sha256,
            metadata_relative_path=self.workspace.relative(metadata_path),
            quality_report=quality_report,
        )

    @staticmethod
    def _write_thumbnail(source_path: Path, destination: Path) -> None:
        try:
            with Image.open(_filesystem_path(source_path)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
        except (OSError, UnidentifiedImageError) as exc:
            raise VideoGenerationGatewayError(
                409,
                "approved_image_invalid",
                "已确认图片文件无法作为视频起始帧",
            ) from exc
        image.thumbnail((640, 640), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="WEBP", quality=84, method=4)
        _write_atomic(destination, output.getvalue())

    @staticmethod
    def _write_placeholder_thumbnail(
        destination: Path,
        *,
        width: int,
        height: int,
    ) -> None:
        ratio = max(width, 1) / max(height, 1)
        if ratio >= 1:
            canvas_width = 640
            canvas_height = max(180, round(canvas_width / ratio))
        else:
            canvas_height = 640
            canvas_width = max(180, round(canvas_height * ratio))
        image = Image.new("RGB", (canvas_width, canvas_height), "#24232c")
        output = BytesIO()
        image.save(output, format="WEBP", quality=82, method=4)
        _write_atomic(destination, output.getvalue())
