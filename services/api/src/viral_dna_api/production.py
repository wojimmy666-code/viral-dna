from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import secrets
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import Event
from typing import Protocol
from urllib.parse import unquote
from uuid import UUID, uuid4

from PIL import Image, ImageOps
from pydantic import ValidationError

from .chinese import to_simplified
from .image_generation import ImageGenerationGateway, ImageGenerationGatewayError
from .media import MediaProcessingError, MediaProcessor
from .models import (
    AnalysisJob,
    AnalysisRecord,
    AnalysisReport,
    AnalysisStage,
    ApprovalDecision,
    ApprovalEvent,
    CandidateActionResponse,
    CandidateApprovalRequest,
    CandidateSelectRequest,
    ChangeImpactRequest,
    ChangeImpactResponse,
    GenerationCandidate,
    GenerationCandidateResponse,
    GenerationCandidateStatus,
    GenerationCostSource,
    GenerationKind,
    GenerationRun,
    GenerationRunResponse,
    ImageExecutionMode,
    ImageGenerationCreate,
    ImageGenerationInputMode,
    ProductionAdvanceRequest,
    ProductionBranchCreate,
    ProductionChangeKind,
    ProductionGateStatus,
    ProductionProject,
    ProductionProjectCreate,
    ProductionProjectDetail,
    ProductionProjectStatus,
    ProductionProjectUpdate,
    ProductionRevision,
    ProductionRevisionDetail,
    ProductionRevisionResponse,
    ProductionRunStatus,
    ProductionStep,
    PromptAssetMention,
    ReferenceAsset,
    ReferenceAssetCreate,
    ReferenceAssetResponse,
    ReferenceAssetType,
    ReferenceAssetUpdate,
    ReferenceBinding,
    ReferenceBindingInput,
    ReferenceRole,
    ShotImageApprovalRevokeRequest,
    ShotKeyframeSelectRequest,
    ShotLifecycleStatus,
    ShotLifecycleUpdate,
    ShotMediaPreview,
    ShotPlan,
    ShotPlanBulkUpdate,
    ShotPlanCreate,
    ShotPlanDetailResponse,
    ShotPlanFieldsUpdate,
    ShotPlanReorder,
    ShotPlanResponse,
    ShotPlanUpdate,
    ShotSourceFrameApprovalRequest,
    ShotSourceKind,
    ShotVideoApprovalRevokeRequest,
    Video,
    VideoGenerationCreate,
    VideoGenerationInputMode,
    VideoProviderTask,
    VideoProviderTaskResponse,
    VideoProviderTaskStatus,
    WorkflowItemStatus,
)
from .notifications import NotificationPublisher
from .video_generation import VideoGenerationGateway, VideoGenerationGatewayError
from .workspace import WorkspaceError, WorkspaceManager

MAX_REFERENCE_IMAGE_BYTES = 15 * 1024 * 1024
MAX_REFERENCE_IMAGE_DIMENSION = 16_384
MAX_REFERENCE_IMAGE_PIXELS = 64_000_000
MAX_REFERENCE_ASSETS_PER_PROJECT = 50
REFERENCE_THUMBNAIL_SIZE = 480
PRODUCTION_SNAPSHOT_SCHEMA = "production-revision-v2"
SUPPORTED_PRODUCTION_SNAPSHOT_SCHEMAS = {"production-revision-v1", PRODUCTION_SNAPSHOT_SCHEMA}

_IMAGE_FORMATS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}

_DEFAULT_ROLE_BY_REFERENCE_TYPE = {
    ReferenceAssetType.PERSON: ReferenceRole.IDENTITY,
    ReferenceAssetType.PRODUCT: ReferenceRole.PRODUCT,
    ReferenceAssetType.WARDROBE: ReferenceRole.WARDROBE,
    ReferenceAssetType.SCENE: ReferenceRole.SCENE,
    ReferenceAssetType.STYLE: ReferenceRole.STYLE,
    ReferenceAssetType.PROP: ReferenceRole.LAYOUT,
}


def _is_simulated_image_run(run: GenerationRun) -> bool:
    return (
        run.kind == GenerationKind.IMAGE
        and (
            run.execution_mode == ImageExecutionMode.SIMULATED
            or run.provider.strip().casefold() == "simulated"
        )
    )


def utc_now() -> datetime:
    return datetime.now(UTC)


def _filesystem_path(path: Path) -> Path:
    """Use Windows extended-length paths without persisting the OS-specific prefix."""
    if os.name != "nt":
        return path
    separator = chr(92)
    raw = str(path)
    extended_prefix = f"{separator}{separator}?{separator}"
    if raw.startswith(extended_prefix):
        return path
    if raw.startswith(separator * 2):
        return Path(f"{extended_prefix}UNC{separator}{raw[2:]}")
    return Path(f"{extended_prefix}{raw}")


class ProductionRepository(Protocol):
    async def get_record(self, record_id: UUID) -> AnalysisRecord | None: ...

    async def get_video(self, video_id: UUID) -> Video | None: ...

    async def get_analysis(self, analysis_id: UUID) -> AnalysisJob | None: ...

    async def get_report_by_analysis(
        self,
        analysis_id: UUID,
    ) -> AnalysisReport | None: ...

    async def save_production_bundle(
        self,
        project: ProductionProject,
        revision: ProductionRevision,
        *,
        reference_assets: list[ReferenceAsset] | None = None,
        shot_plans: list[ShotPlan] | None = None,
        reference_bindings: list[ReferenceBinding] | None = None,
        remove_reference_binding_ids: list[UUID] | None = None,
        generation_runs: list[GenerationRun] | None = None,
        generation_candidates: list[GenerationCandidate] | None = None,
        approval_events: list[ApprovalEvent] | None = None,
    ) -> tuple[ProductionProject, ProductionRevision]: ...

    async def get_production_project(
        self,
        project_id: UUID,
    ) -> ProductionProject | None: ...

    async def list_production_projects(
        self,
        record_id: UUID | None = None,
    ) -> list[ProductionProject]: ...

    async def get_production_revision(
        self,
        revision_id: UUID,
    ) -> ProductionRevision | None: ...

    async def list_production_revisions(
        self,
        project_id: UUID,
    ) -> list[ProductionRevision]: ...

    async def get_reference_asset(self, asset_id: UUID) -> ReferenceAsset | None: ...

    async def list_reference_assets(self, project_id: UUID) -> list[ReferenceAsset]: ...

    async def list_shot_plans(self, project_id: UUID) -> list[ShotPlan]: ...

    async def list_reference_bindings(
        self,
        shot_plan_id: UUID,
    ) -> list[ReferenceBinding]: ...

    async def get_shot_plan(self, shot_plan_id: UUID) -> ShotPlan | None: ...

    async def save_generation_run(self, run: GenerationRun) -> GenerationRun: ...

    async def claim_generation_run(
        self,
        run_id: UUID,
        claimed_at: datetime,
    ) -> GenerationRun | None: ...

    async def get_generation_run(self, run_id: UUID) -> GenerationRun | None: ...

    async def list_generation_runs(
        self,
        project_id: UUID,
        shot_plan_id: UUID | None = None,
    ) -> list[GenerationRun]: ...

    async def get_generation_candidate(
        self,
        candidate_id: UUID,
    ) -> GenerationCandidate | None: ...

    async def list_generation_candidates(
        self,
        generation_run_id: UUID,
    ) -> list[GenerationCandidate]: ...

    async def list_generation_candidates_by_run_ids(
        self,
        generation_run_ids: set[UUID],
    ) -> list[GenerationCandidate]: ...

    async def save_video_provider_task(
        self,
        task: VideoProviderTask,
    ) -> VideoProviderTask: ...

    async def get_video_provider_task(
        self,
        task_id: UUID,
    ) -> VideoProviderTask | None: ...

    async def list_video_provider_tasks(
        self,
        generation_run_id: UUID,
    ) -> list[VideoProviderTask]: ...

    async def list_approval_events(
        self,
        project_id: UUID,
        shot_plan_id: UUID | None = None,
    ) -> list[ApprovalEvent]: ...


class ProjectAssetBridge(Protocol):
    async def create_reference(
        self,
        project: ProductionProject,
        payload: ReferenceAssetCreate,
        file_payload: bytes,
        filename: str,
        declared_mime_type: str | None,
    ) -> ReferenceAsset: ...

    async def link_asset(
        self,
        project: ProductionProject,
        asset_id: UUID,
        reference_type: ReferenceAssetType | None = None,
    ) -> ReferenceAsset: ...

    async def list_references(
        self,
        project_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[ReferenceAsset]: ...

    async def get_reference(
        self,
        asset_id: UUID,
        project_id: UUID | None = None,
        *,
        include_archived: bool = True,
    ) -> ReferenceAsset | None: ...

    async def update_reference(
        self,
        project_id: UUID,
        asset_id: UUID,
        payload: ReferenceAssetUpdate,
    ) -> ReferenceAsset: ...

    async def unlink_reference(self, project_id: UUID, asset_id: UUID) -> ReferenceAsset: ...

    async def resolve_content(
        self,
        asset_id: UUID,
        *,
        thumbnail: bool,
    ) -> tuple[Path, str]: ...

    async def snapshot_reference(
        self,
        project_id: UUID,
        reference: ReferenceAsset,
    ) -> dict[str, object]: ...

    async def link_snapshot_reference(
        self,
        project: ProductionProject,
        payload: dict[str, object],
    ) -> ReferenceAsset: ...


class ProductionServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True, slots=True)
class ReferenceImageInfo:
    extension: str
    mime_type: str
    width: int
    height: int
    sha256: str
    thumbnail: bytes


def _fail(status_code: int, code: str, message: str) -> ProductionServiceError:
    return ProductionServiceError(status_code, code, message)


def _simplified_text(
    value: str,
    *,
    field_name: str,
    allow_empty: bool = False,
    max_length: int,
) -> str:
    normalized = (to_simplified(value) or "").strip()
    if not normalized and not allow_empty:
        raise _fail(422, "invalid_text", f"{field_name}不能为空")
    if len(normalized) > max_length:
        raise _fail(422, "invalid_text", f"{field_name}不能超过 {max_length} 个字符")
    return normalized


def _simplified_tags(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        tag = _simplified_text(
            value,
            field_name="标签",
            allow_empty=True,
            max_length=80,
        )
        if tag and tag not in normalized:
            normalized.append(tag)
    if len(normalized) > 20:
        raise _fail(422, "too_many_tags", "参考资产标签不能超过 20 个")
    return normalized


def _canonical_ratio(value: str) -> tuple[str, int, int]:
    try:
        width, height = (int(part) for part in value.split(":"))
    except (TypeError, ValueError) as exc:
        raise _fail(422, "invalid_aspect_ratio", "输出画面比例格式无效") from exc
    if width <= 0 or height <= 0:
        raise _fail(422, "invalid_aspect_ratio", "输出画面比例必须大于零")
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}", width, height


def _output_settings(
    ratio_value: str,
    width: int | None,
    height: int | None,
) -> tuple[str, int, int]:
    ratio, ratio_width, ratio_height = _canonical_ratio(ratio_value)
    if width is None or height is None:
        if ratio_width >= ratio_height:
            height = 1080
            width = round(height * ratio_width / ratio_height)
        else:
            width = 1080
            height = round(width * ratio_height / ratio_width)
        width += width % 2
        height += height % 2
    if not 256 <= width <= 8192 or not 256 <= height <= 8192:
        raise _fail(422, "invalid_output_size", "输出尺寸必须在 256 到 8192 像素之间")
    expected = ratio_width / ratio_height
    actual = width / height
    if abs(actual - expected) / expected > 0.02:
        raise _fail(422, "output_ratio_mismatch", "输出尺寸与画面比例不匹配")
    return ratio, width, height


_SUPPORTED_OUTPUT_RATIOS = ("9:16", "16:9", "1:1", "4:5")


def _default_output_ratio(
    width: int | None,
    height: int | None,
    fallback: str,
) -> str:
    if not width or not height or width <= 0 or height <= 0:
        return fallback
    source_ratio = width / height

    def orientation(value: float) -> str:
        if abs(1 - value) <= 0.06:
            return "square"
        return "landscape" if value > 1 else "portrait"

    source_orientation = orientation(source_ratio)
    ranked: list[tuple[int, int, int, str]] = []
    for index, candidate in enumerate(_SUPPORTED_OUTPUT_RATIOS):
        candidate_width, candidate_height = (
            int(part) for part in candidate.split(":")
        )
        candidate_ratio = candidate_width / candidate_height
        ranked.append(
            (
                round(abs(math.log(source_ratio / candidate_ratio)) * 1_000_000_000_000),
                0 if orientation(candidate_ratio) == source_orientation else 1,
                index,
                candidate,
            )
        )
    return min(ranked)[3]


def inspect_reference_image(payload: bytes, declared_mime_type: str | None) -> ReferenceImageInfo:
    if not payload:
        raise _fail(422, "empty_reference_image", "参考图片不能为空")
    if len(payload) > MAX_REFERENCE_IMAGE_BYTES:
        raise _fail(413, "reference_image_too_large", "参考图片不能超过 15 MB")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as opened:
                image_format = (opened.format or "").upper()
                if image_format not in _IMAGE_FORMATS:
                    raise _fail(415, "unsupported_reference_image", "仅支持 JPG、PNG 和 WebP")
                if getattr(opened, "n_frames", 1) != 1:
                    raise _fail(415, "animated_reference_image", "参考图片必须是静态图片")
                raw_width, raw_height = opened.size
                opened.verify()

            if (
                raw_width <= 0
                or raw_height <= 0
                or raw_width > MAX_REFERENCE_IMAGE_DIMENSION
                or raw_height > MAX_REFERENCE_IMAGE_DIMENSION
                or raw_width * raw_height > MAX_REFERENCE_IMAGE_PIXELS
            ):
                raise _fail(
                    413,
                    "reference_image_dimensions_too_large",
                    "参考图片尺寸不能超过 16384 像素或 6400 万像素",
                )

            extension, mime_type = _IMAGE_FORMATS[image_format]
            declared = (declared_mime_type or "").split(";", 1)[0].strip().lower()
            if declared and declared not in {mime_type, "application/octet-stream"}:
                raise _fail(415, "reference_image_mime_mismatch", "图片媒体类型与文件内容不一致")

            with Image.open(BytesIO(payload)) as source:
                thumbnail = ImageOps.exif_transpose(source)
                width, height = thumbnail.size
                thumbnail.thumbnail(
                    (REFERENCE_THUMBNAIL_SIZE, REFERENCE_THUMBNAIL_SIZE),
                    Image.Resampling.LANCZOS,
                )
                has_alpha = thumbnail.mode in {"RGBA", "LA"} or "transparency" in thumbnail.info
                thumbnail = thumbnail.convert("RGBA" if has_alpha else "RGB")
                output = BytesIO()
                thumbnail.save(output, format="WEBP", quality=84, method=4)
    except ProductionServiceError:
        raise
    except (
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise _fail(415, "invalid_reference_image", "参考图片文件已损坏或格式无效") from exc

    return ReferenceImageInfo(
        extension=extension,
        mime_type=mime_type,
        width=width,
        height=height,
        sha256=hashlib.sha256(payload).hexdigest(),
        thumbnail=output.getvalue(),
    )


def _revision_response(revision: ProductionRevision) -> ProductionRevisionResponse:
    return ProductionRevisionResponse.model_validate(
        revision.model_dump(exclude={"snapshot_relative_path"})
    )


class ProductionService:
    def __init__(
        self,
        repository: ProductionRepository,
        workspace: WorkspaceManager,
        image_gateway: ImageGenerationGateway | None = None,
        media_processor: MediaProcessor | None = None,
        project_assets: ProjectAssetBridge | None = None,
        video_gateway: VideoGenerationGateway | None = None,
        notification_publisher: NotificationPublisher | None = None,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.project_assets = project_assets
        self.media_processor = media_processor or MediaProcessor()
        self.image_gateway = image_gateway or ImageGenerationGateway(
            workspace,
            repository=repository,
        )
        self.video_gateway = video_gateway or VideoGenerationGateway(
            workspace,
            media_processor=self.media_processor,
        )
        self.notification_publisher = notification_publisher
        self._lock_guard = asyncio.Lock()
        self._project_locks: dict[UUID, asyncio.Lock] = {}
        self._generation_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._generation_cancellations: dict[UUID, Event] = {}

    async def _project_lock(self, project_id: UUID) -> asyncio.Lock:
        async with self._lock_guard:
            return self._project_locks.setdefault(project_id, asyncio.Lock())

    async def _notify_generation_run(self, run: GenerationRun) -> None:
        """Publish a safe account notification without affecting generation results."""
        if self.notification_publisher is None:
            return
        if run.status not in {
            ProductionRunStatus.QUEUED,
            ProductionRunStatus.RUNNING,
            ProductionRunStatus.COMPLETED,
            ProductionRunStatus.CACHED,
            ProductionRunStatus.FAILED,
            ProductionRunStatus.BLOCKED,
            ProductionRunStatus.CANCELLED,
        }:
            return
        try:
            project = await self._require_project(run.project_id)
            plan = await self._require_shot(run.shot_plan_id)
            candidates = await self.repository.list_generation_candidates(run.id)
            candidate = next(
                (
                    item
                    for item in candidates
                    if item.status
                    in {
                        GenerationCandidateStatus.READY,
                        GenerationCandidateStatus.SELECTED,
                    }
                ),
                candidates[0] if candidates else None,
            )
            kind_label = "视频" if run.kind == GenerationKind.VIDEO else "图片"
            category = (
                "video_generation"
                if run.kind == GenerationKind.VIDEO
                else "image_generation"
            )
            model_label = run.model_display_name or run.model_alias or run.model
            action_payload = {
                "record_id": str(project.record_id),
                "project_id": str(project.id),
                "shot_plan_id": str(plan.id),
                "step": "shot_videos" if run.kind == GenerationKind.VIDEO else "shot_images",
                "run_id": str(run.id),
            }
            if candidate is not None:
                action_payload["candidate_id"] = str(candidate.id)

            if run.status in {ProductionRunStatus.QUEUED, ProductionRunStatus.RUNNING}:
                notification_status = "in_progress"
                level = "info"
                title = f"分镜 {plan.index} 的{kind_label}生成已开始"
                message = f"{model_label} 正在处理，完成后会在这里通知你。"
                action_label = "查看进度"
            elif run.status in {ProductionRunStatus.COMPLETED, ProductionRunStatus.CACHED}:
                notification_status = "succeeded"
                level = "success"
                title = f"分镜 {plan.index} 的{kind_label}候选已生成"
                if run.actual_cost_known:
                    cost_text = f"实际 ¥{run.actual_cost_micros / 1_000_000:.2f}"
                elif run.cost_estimate_known:
                    cost_text = f"预计 ¥{run.estimated_cost_micros / 1_000_000:.2f}"
                else:
                    cost_text = "费用待 Provider 回传"
                message = f"{model_label} · {len(candidates)} 个候选 · {cost_text}"
                action_label = "查看候选"
            elif run.status in {ProductionRunStatus.FAILED, ProductionRunStatus.BLOCKED}:
                notification_status = "failed"
                level = "error"
                if run.error_code == "video_provider_balance_insufficient":
                    title = "视频生成失败：API 余额不足"
                    message = "请充值对应 Provider 账户，或切换到其他已配置的视频模型。"
                    action_label = "检查模型设置"
                    await self.notification_publisher.publish(
                        category=category,
                        level=level,
                        status=notification_status,
                        title=title,
                        message=message,
                        event_key=f"generation:{run.id}",
                        action_kind="model_settings",
                        action_label=action_label,
                        action_payload=action_payload,
                    )
                    return
                title = f"分镜 {plan.index} 的{kind_label}生成失败"
                message = "请打开对应分镜查看错误详情，调整设置后重试。"
                action_label = "查看分镜"
            else:
                notification_status = "cancelled"
                level = "warning"
                title = f"分镜 {plan.index} 的{kind_label}生成已取消"
                message = "本次任务未产生可审核候选。"
                action_label = "返回分镜"

            await self.notification_publisher.publish(
                category=category,
                level=level,
                status=notification_status,
                title=title,
                message=message,
                event_key=f"generation:{run.id}",
                action_kind="production_shot",
                action_label=action_label,
                action_payload=action_payload,
            )
        except Exception:
            # Notification delivery is secondary and must never change generation state.
            return

    async def create_project(
        self,
        record_id: UUID,
        payload: ProductionProjectCreate,
    ) -> ProductionProjectDetail:
        record = await self.repository.get_record(record_id)
        if record is None:
            raise _fail(404, "record_not_found", "分析记录不存在")
        analysis_id = payload.base_analysis_id or record.latest_analysis_id
        if analysis_id is None:
            raise _fail(409, "analysis_required", "请先完成视频分析")
        analysis, report = await self._completed_analysis(record, analysis_id)
        video = await self.repository.get_video(record.video_id)
        if video is None:
            raise _fail(409, "video_missing", "分析记录缺少视频信息")

        ratio_value = payload.output_aspect_ratio or _default_output_ratio(
            video.width,
            video.height,
            report.prompt_package.aspect_ratio,
        )
        ratio, width, height = _output_settings(
            ratio_value,
            payload.output_width,
            payload.output_height,
        )
        default_name = f"{record.name} 复刻方案"
        project = ProductionProject(
            record_id=record.id,
            video_id=video.id,
            base_analysis_id=analysis.id,
            source_prompt_package_id=report.prompt_package.id,
            name=_simplified_text(
                payload.name or default_name,
                field_name="创作方案名称",
                max_length=120,
            ),
            output_aspect_ratio=ratio,
            output_width=width,
            output_height=height,
            budget_limit_micros=payload.budget_limit_micros,
        )
        self.workspace.initialize_production(record.id, project.id)
        revision_id = uuid4()
        shot_plans = self._initial_shot_plans(
            project,
            report,
            revision_id,
        )
        project, revision = await self._prepare_revision(
            project,
            ProductionChangeKind.PROJECT_CREATED,
            "创建创作方案并冻结基础分析",
            revision_id=revision_id,
            report=report,
            reference_assets=[],
            shot_plans=shot_plans,
            reference_bindings=[],
        )
        await self.repository.save_production_bundle(
            project,
            revision,
            shot_plans=shot_plans,
        )
        return ProductionProjectDetail(
            project=project,
            current_revision=_revision_response(revision),
            revision_count=1,
            reference_count=0,
            shot_count=len(shot_plans),
        )

    async def list_projects(self, record_id: UUID) -> list[ProductionProject]:
        if await self.repository.get_record(record_id) is None:
            raise _fail(404, "record_not_found", "分析记录不存在")
        projects = await self.repository.list_production_projects(record_id)
        return sorted(projects, key=lambda item: item.updated_at, reverse=True)

    async def get_project(self, project_id: UUID) -> ProductionProjectDetail:
        project = await self._require_project(project_id)
        project, shots = await self._ensure_project_shots(project)
        revisions = await self.repository.list_production_revisions(project.id)
        references = await self._list_reference_assets(project.id)
        current = next(
            (item for item in revisions if item.id == project.current_revision_id),
            None,
        )
        active_shots = [
            item for item in shots
            if item.lifecycle_status == ShotLifecycleStatus.ACTIVE
        ]
        return ProductionProjectDetail(
            project=project,
            current_revision=_revision_response(current) if current else None,
            revision_count=len(revisions),
            reference_count=sum(item.archived_at is None for item in references),
            shot_count=len(active_shots),
            discarded_shot_count=len(shots) - len(active_shots),
            approved_image_count=sum(
                item.image_status == WorkflowItemStatus.APPROVED
                for item in active_shots
            ),
            stale_image_count=sum(
                item.image_status == WorkflowItemStatus.STALE
                for item in active_shots
            ),
        )

    async def update_project(
        self,
        project_id: UUID,
        payload: ProductionProjectUpdate,
    ) -> ProductionProjectDetail:
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            fields = payload.model_fields_set - {
                "expected_revision_id",
                "confirm_stale",
            }
            updates: dict[str, object] = {}
            if "name" in fields:
                if payload.name is None:
                    raise _fail(422, "invalid_name", "创作方案名称不能为空")
                updates["name"] = _simplified_text(
                    payload.name,
                    field_name="创作方案名称",
                    max_length=120,
                )
            ratio_value = (
                payload.output_aspect_ratio
                if "output_aspect_ratio" in fields and payload.output_aspect_ratio is not None
                else project.output_aspect_ratio
            )
            if "output_aspect_ratio" in fields and payload.output_aspect_ratio is None:
                raise _fail(422, "invalid_aspect_ratio", "输出画面比例不能为空")
            dimensions_changed = "output_width" in fields or "output_height" in fields
            ratio_changed = "output_aspect_ratio" in fields
            output_fields_provided = dimensions_changed or ratio_changed
            output_changed = False
            if output_fields_provided:
                selected_width = payload.output_width if dimensions_changed else None
                selected_height = payload.output_height if dimensions_changed else None
                ratio, width, height = _output_settings(
                    ratio_value,
                    selected_width,
                    selected_height,
                )
                output_changed = (
                    ratio != project.output_aspect_ratio
                    or width != project.output_width
                    or height != project.output_height
                )
                updates.update(
                    output_aspect_ratio=ratio,
                    output_width=width,
                    output_height=height,
                )
            plans = await self.repository.list_shot_plans(project.id)
            if (
                output_changed
                and any(
                    item.image_status == WorkflowItemStatus.APPROVED
                    or item.video_status == WorkflowItemStatus.APPROVED
                    for item in plans
                )
                and not payload.confirm_stale
            ):
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "输出规格修改会使全部已审批分镜过期，请确认影响范围后重试",
                )
            if "budget_limit_micros" in fields:
                updates["budget_limit_micros"] = payload.budget_limit_micros
            updates["updated_at"] = utc_now()
            updated = ProductionProject.model_validate(
                {**project.model_dump(mode="python"), **updates}
            )
            revision_id = uuid4()
            next_plans = plans
            changed_plans: list[ShotPlan] = []
            if output_changed:
                next_plans, changed_plans = self._mark_plans_stale(
                    plans,
                    {item.id for item in plans},
                    revision_id,
                )
            updated, revision = await self._prepare_revision(
                updated,
                ProductionChangeKind.PROJECT_SETTINGS_CHANGED,
                "更新创作方案设置",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                updated,
                revision,
                shot_plans=changed_plans,
            )
        return await self.get_project(project_id)

    async def create_branch(
        self,
        project_id: UUID,
        payload: ProductionBranchCreate,
    ) -> ProductionProjectDetail:
        source_project = await self._require_project(project_id)
        source_revision_id = payload.source_revision_id or source_project.current_revision_id
        if source_revision_id is None:
            raise _fail(409, "revision_required", "创作方案尚无可分支的版本")
        source_revision = await self._require_revision(source_project, source_revision_id)
        source_snapshot = await self._read_revision_snapshot(source_project, source_revision)
        try:
            frozen_project = ProductionProject.model_validate(source_snapshot["project"])
        except (KeyError, TypeError, ValidationError) as exc:
            raise _fail(409, "invalid_revision_snapshot", "源版本快照无法用于创建分支") from exc

        now = utc_now()
        branch_id = uuid4()
        branch_revision_id = uuid4()
        branch = ProductionProject(
            id=branch_id,
            record_id=source_project.record_id,
            video_id=frozen_project.video_id,
            base_analysis_id=frozen_project.base_analysis_id,
            source_prompt_package_id=frozen_project.source_prompt_package_id,
            source_project_id=source_project.id,
            source_revision_id=source_revision.id,
            name=_simplified_text(
                payload.name or f"{source_project.name} 分支",
                field_name="创作方案名称",
                max_length=120,
            ),
            status=ProductionProjectStatus.DRAFT,
            active_step=frozen_project.active_step,
            output_aspect_ratio=frozen_project.output_aspect_ratio,
            output_width=frozen_project.output_width,
            output_height=frozen_project.output_height,
            budget_limit_micros=frozen_project.budget_limit_micros,
            created_at=now,
            updated_at=now,
        )
        self.workspace.initialize_production(branch.record_id, branch.id)
        cloned_assets, asset_ids = await self._clone_snapshot_assets(
            source_project,
            branch,
            source_snapshot,
        )
        cloned_shots, cloned_bindings = await self._clone_snapshot_shots(
            source_project,
            branch,
            branch_revision_id,
            source_snapshot,
            asset_ids,
        )
        branch, revision = await self._prepare_revision(
            branch,
            ProductionChangeKind.BRANCH_CREATED,
            f"从版本 {source_revision.revision_number} 创建分支",
            revision_id=branch_revision_id,
            reference_assets=cloned_assets,
            shot_plans=cloned_shots,
            reference_bindings=cloned_bindings,
        )
        await self.repository.save_production_bundle(
            branch,
            revision,
            reference_assets=cloned_assets if self.project_assets is None else None,
            shot_plans=cloned_shots,
            reference_bindings=cloned_bindings,
        )
        active_cloned_shots = [
            item for item in cloned_shots
            if item.lifecycle_status == ShotLifecycleStatus.ACTIVE
        ]
        return ProductionProjectDetail(
            project=branch,
            current_revision=_revision_response(revision),
            revision_count=1,
            reference_count=len(cloned_assets),
            shot_count=len(active_cloned_shots),
            discarded_shot_count=len(cloned_shots) - len(active_cloned_shots),
            approved_image_count=sum(
                item.image_status == WorkflowItemStatus.APPROVED
                for item in active_cloned_shots
            ),
            stale_image_count=sum(
                item.image_status == WorkflowItemStatus.STALE
                for item in active_cloned_shots
            ),
        )

    async def list_revisions(self, project_id: UUID) -> list[ProductionRevisionResponse]:
        await self._require_project(project_id)
        revisions = await self.repository.list_production_revisions(project_id)
        return [_revision_response(item) for item in reversed(revisions)]

    async def get_revision(
        self,
        project_id: UUID,
        revision_id: UUID,
    ) -> ProductionRevisionDetail:
        project = await self._require_project(project_id)
        revision = await self._require_revision(project, revision_id)
        snapshot = await self._read_revision_snapshot(project, revision)
        return ProductionRevisionDetail(
            **_revision_response(revision).model_dump(),
            snapshot=snapshot,
        )

    async def create_reference(
        self,
        project_id: UUID,
        payload: ReferenceAssetCreate,
        file_payload: bytes,
        declared_mime_type: str | None,
        filename: str = "",
    ) -> ReferenceAssetResponse:
        project = await self._require_project(project_id)
        if self.project_assets is not None:
            return await self._create_workspace_reference(
                project, payload, file_payload, filename, declared_mime_type
            )
        image = await asyncio.to_thread(
            inspect_reference_image,
            file_payload,
            declared_mime_type,
        )
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            existing = await self._list_reference_assets(project.id)
            active_count = sum(item.archived_at is None for item in existing)
            if active_count >= MAX_REFERENCE_ASSETS_PER_PROJECT:
                raise _fail(409, "reference_asset_limit", "每个创作方案最多保存 50 个参考资产")
            if not payload.rights_confirmed:
                raise _fail(422, "rights_confirmation_required", "请先确认拥有该参考图片的使用权")

            asset_id = uuid4()
            asset_root = self.workspace.reference_asset_root(
                project.record_id,
                project.id,
                asset_id,
            )
            original = asset_root / f"original{image.extension}"
            thumbnail = asset_root / "thumbnail.webp"
            asset = ReferenceAsset(
                id=asset_id,
                project_id=project.id,
                type=payload.type,
                name=_simplified_text(
                    payload.name,
                    field_name="参考资产名称",
                    max_length=120,
                ),
                description=_simplified_text(
                    payload.description,
                    field_name="参考资产说明",
                    allow_empty=True,
                    max_length=2000,
                ),
                relative_path=self.workspace.relative(original),
                thumbnail_relative_path=self.workspace.relative(thumbnail),
                mime_type=image.mime_type,
                width=image.width,
                height=image.height,
                sha256=image.sha256,
                tags=_simplified_tags(payload.tags),
                rights_confirmed=True,
                rights_note=(
                    _simplified_text(
                        payload.rights_note,
                        field_name="权利说明",
                        allow_empty=True,
                        max_length=1000,
                    )
                    if payload.rights_note is not None
                    else None
                ),
            )
            await asyncio.to_thread(
                self._write_reference_files,
                project,
                asset,
                file_payload,
                image.thumbnail,
            )
            next_project = ProductionProject.model_validate(
                {
                    **project.model_dump(mode="python"),
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.REFERENCE_ASSETS,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"新增参考资产：{asset.name}",
                reference_assets=[*existing, asset],
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                reference_assets=[asset],
            )
        return self._reference_response(asset, next_project.current_revision_id)

    async def _create_workspace_reference(
        self,
        project: ProductionProject,
        payload: ReferenceAssetCreate,
        file_payload: bytes,
        filename: str,
        declared_mime_type: str | None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is None:
            raise _fail(500, "project_asset_bridge_missing", "项目资产服务未初始化")
        lock = await self._project_lock(project.id)
        async with lock:
            project = await self._require_project(project.id)
            self._require_expected_revision(project, payload.expected_revision_id)
            existing = await self._list_reference_assets(project.id)
            if len(existing) >= MAX_REFERENCE_ASSETS_PER_PROJECT:
                raise _fail(409, "reference_asset_limit", "每个创作方案最多保存 50 个参考资产")
            asset = await self.project_assets.create_reference(
                project,
                payload,
                file_payload,
                filename,
                declared_mime_type,
            )
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.REFERENCE_ASSETS,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"新增参考资产：{asset.name}",
                reference_assets=[*existing, asset],
            )
            await self.repository.save_production_bundle(next_project, revision)
        return self._reference_response(asset, next_project.current_revision_id)

    async def link_reference(
        self,
        project_id: UUID,
        asset_id: UUID,
        expected_revision_id: UUID,
        reference_type: ReferenceAssetType | None = None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is None:
            raise _fail(409, "asset_library_not_enabled", "资产库尚未启用")
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, expected_revision_id)
            existing = await self._list_reference_assets(project.id)
            if any(item.id == asset_id for item in existing):
                raise _fail(409, "asset_already_linked", "该资产已添加到当前创作方案")
            if len(existing) >= MAX_REFERENCE_ASSETS_PER_PROJECT:
                raise _fail(409, "reference_asset_limit", "每个创作方案最多保存 50 个参考资产")
            asset = await self.project_assets.link_asset(project, asset_id, reference_type)
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.REFERENCE_ASSETS,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"从资产库添加：{asset.name}",
                reference_assets=[*existing, asset],
            )
            await self.repository.save_production_bundle(next_project, revision)
        return self._reference_response(asset, next_project.current_revision_id)

    async def _update_workspace_reference(
        self,
        asset_id: UUID,
        payload: ReferenceAssetUpdate,
        project_id: UUID | None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is None:
            raise _fail(500, "project_asset_bridge_missing", "项目资产服务未初始化")
        asset = await self.project_assets.get_reference(asset_id, project_id)
        if asset is None:
            raise _fail(404, "reference_asset_not_found", "项目参考资产不存在")
        lock = await self._project_lock(asset.project_id)
        async with lock:
            asset = await self.project_assets.get_reference(asset_id, asset.project_id)
            if asset is None or asset.archived_at is not None:
                raise _fail(409, "reference_asset_archived", "已移出项目的参考资产不能修改")
            project = await self._require_project(asset.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            all_bindings = await self._all_bindings(plans)
            impacted_ids = {
                item.shot_plan_id
                for item in all_bindings
                if item.reference_asset_id == asset.id
            }
            if (
                any(
                    item.id in impacted_ids
                    and item.image_status == WorkflowItemStatus.APPROVED
                    for item in plans
                )
                and not payload.confirm_stale
            ):
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "参考资产修改会使已绑定分镜过期，请确认影响范围后重试",
                )
            updated_asset = await self.project_assets.update_reference(
                project.id,
                asset.id,
                payload,
            )
            snapshot_assets = await self._list_reference_assets(
                project.id,
                include_archived=True,
            )
            revision_id = uuid4()
            next_plans, changed_plans = self._mark_plans_stale(
                plans,
                impacted_ids,
                revision_id,
            )
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"更新资产库参考：{updated_asset.name}",
                revision_id=revision_id,
                reference_assets=snapshot_assets,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
            )
        return self._reference_response(updated_asset, next_project.current_revision_id)

    async def _archive_workspace_reference(
        self,
        asset_id: UUID,
        expected_revision_id: UUID,
        confirm_stale: bool,
        project_id: UUID | None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is None:
            raise _fail(500, "project_asset_bridge_missing", "项目资产服务未初始化")
        asset = await self.project_assets.get_reference(asset_id, project_id)
        if asset is None:
            raise _fail(404, "reference_asset_not_found", "项目参考资产不存在")
        lock = await self._project_lock(asset.project_id)
        async with lock:
            asset = await self.project_assets.get_reference(asset_id, asset.project_id)
            if asset is None:
                raise _fail(404, "reference_asset_not_found", "项目参考资产不存在")
            project = await self._require_project(asset.project_id)
            self._require_expected_revision(project, expected_revision_id)
            if asset.archived_at is not None:
                return self._reference_response(asset, project.current_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            all_bindings = await self._all_bindings(plans)
            impacted_ids = {
                item.shot_plan_id
                for item in all_bindings
                if item.reference_asset_id == asset.id
            }
            if (
                any(
                    item.id in impacted_ids
                    and item.image_status == WorkflowItemStatus.APPROVED
                    for item in plans
                )
                and not confirm_stale
            ):
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "移出参考资产会使已绑定分镜过期，请确认影响范围后重试",
                )
            archived = await self.project_assets.unlink_reference(project.id, asset.id)
            snapshot_assets = await self._list_reference_assets(
                project.id,
                include_archived=True,
            )
            revision_id = uuid4()
            next_plans, changed_plans = self._mark_plans_stale(
                plans,
                impacted_ids,
                revision_id,
            )
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"从项目移出参考资产：{archived.name}",
                revision_id=revision_id,
                reference_assets=snapshot_assets,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
            )
        return self._reference_response(archived, next_project.current_revision_id)


    async def list_references(
        self,
        project_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[ReferenceAssetResponse]:
        project = await self._require_project(project_id)
        if project.current_revision_id is None:
            raise _fail(409, "revision_required", "创作方案尚无当前版本")
        assets = await self._list_reference_assets(
            project.id, include_archived=include_archived
        )
        if not include_archived and self.project_assets is None:
            assets = [item for item in assets if item.archived_at is None]
        return [self._reference_response(item, project.current_revision_id) for item in assets]

    async def update_reference(
        self,
        asset_id: UUID,
        payload: ReferenceAssetUpdate,
        *,
        project_id: UUID | None = None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is not None:
            return await self._update_workspace_reference(asset_id, payload, project_id)
        asset = await self._require_asset(asset_id)
        lock = await self._project_lock(asset.project_id)
        async with lock:
            asset = await self._require_asset(asset_id)
            if asset.archived_at is not None:
                raise _fail(409, "reference_asset_archived", "已归档的参考资产不能继续修改")
            project = await self._require_project(asset.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            fields = payload.model_fields_set - {
                "expected_revision_id",
                "confirm_stale",
            }
            updates: dict[str, object] = {}
            if "name" in fields:
                if payload.name is None:
                    raise _fail(422, "invalid_name", "参考资产名称不能为空")
                updates["name"] = _simplified_text(
                    payload.name,
                    field_name="参考资产名称",
                    max_length=120,
                )
            if "description" in fields:
                updates["description"] = _simplified_text(
                    payload.description or "",
                    field_name="参考资产说明",
                    allow_empty=True,
                    max_length=2000,
                )
            if "tags" in fields:
                updates["tags"] = _simplified_tags(payload.tags or [])
            if "rights_confirmed" in fields:
                updates["rights_confirmed"] = bool(payload.rights_confirmed)
            if "rights_note" in fields:
                updates["rights_note"] = (
                    _simplified_text(
                        payload.rights_note,
                        field_name="权利说明",
                        allow_empty=True,
                        max_length=1000,
                    )
                    if payload.rights_note is not None
                    else None
                )
            updated_asset = ReferenceAsset.model_validate(
                {**asset.model_dump(mode="python"), **updates}
            )
            existing = await self._list_reference_assets(project.id, include_archived=True)
            snapshot_assets = [updated_asset if item.id == asset.id else item for item in existing]
            plans = await self.repository.list_shot_plans(project.id)
            all_bindings = await self._all_bindings(plans)
            impacted_ids = {
                item.shot_plan_id for item in all_bindings if item.reference_asset_id == asset.id
            }
            if (
                any(
                    item.id in impacted_ids and item.image_status == WorkflowItemStatus.APPROVED
                    for item in plans
                )
                and not payload.confirm_stale
            ):
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "参考资产修改会使已绑定分镜过期，请确认影响范围后重试",
                )
            await asyncio.to_thread(
                self._write_asset_metadata,
                project,
                updated_asset,
            )
            revision_id = uuid4()
            next_plans, changed_plans = self._mark_plans_stale(
                plans,
                impacted_ids,
                revision_id,
            )
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"更新参考资产：{updated_asset.name}",
                revision_id=revision_id,
                reference_assets=snapshot_assets,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                reference_assets=[updated_asset],
                shot_plans=changed_plans,
            )
        return self._reference_response(updated_asset, next_project.current_revision_id)

    async def archive_reference(
        self,
        asset_id: UUID,
        expected_revision_id: UUID,
        *,
        confirm_stale: bool = False,
        project_id: UUID | None = None,
    ) -> ReferenceAssetResponse:
        if self.project_assets is not None:
            return await self._archive_workspace_reference(
                asset_id, expected_revision_id, confirm_stale, project_id
            )
        asset = await self._require_asset(asset_id)
        lock = await self._project_lock(asset.project_id)
        async with lock:
            asset = await self._require_asset(asset_id)
            project = await self._require_project(asset.project_id)
            self._require_expected_revision(project, expected_revision_id)
            if asset.archived_at is not None:
                return self._reference_response(asset, project.current_revision_id)
            archived = ReferenceAsset.model_validate(
                {**asset.model_dump(mode="python"), "archived_at": utc_now()}
            )
            existing = await self._list_reference_assets(project.id, include_archived=True)
            snapshot_assets = [archived if item.id == asset.id else item for item in existing]
            plans = await self.repository.list_shot_plans(project.id)
            all_bindings = await self._all_bindings(plans)
            impacted_ids = {
                item.shot_plan_id for item in all_bindings if item.reference_asset_id == asset.id
            }
            if (
                any(
                    item.id in impacted_ids and item.image_status == WorkflowItemStatus.APPROVED
                    for item in plans
                )
                and not confirm_stale
            ):
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "归档参考资产会使已绑定分镜过期，请确认影响范围后重试",
                )
            await asyncio.to_thread(
                self._write_asset_metadata,
                project,
                archived,
            )
            revision_id = uuid4()
            next_plans, changed_plans = self._mark_plans_stale(
                plans,
                impacted_ids,
                revision_id,
            )
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.REFERENCE_CHANGED,
                f"归档参考资产：{archived.name}",
                revision_id=revision_id,
                reference_assets=snapshot_assets,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                reference_assets=[archived],
                shot_plans=changed_plans,
            )
        return self._reference_response(archived, next_project.current_revision_id)

    async def resolve_reference_content(
        self,
        asset_id: UUID,
        *,
        thumbnail: bool = False,
    ) -> tuple[Path, str]:
        if self.project_assets is not None:
            return await self.project_assets.resolve_content(asset_id, thumbnail=thumbnail)
        asset = await self._require_asset(asset_id)
        project = await self._require_project(asset.project_id)
        relative_path = asset.thumbnail_relative_path if thumbnail else asset.relative_path
        if relative_path is None:
            raise _fail(404, "reference_thumbnail_missing", "参考资产缩略图不存在")
        candidate = self._resolve_reference_path(project, relative_path)
        filesystem_candidate = _filesystem_path(candidate)
        if not filesystem_candidate.is_file():
            raise _fail(404, "reference_file_missing", "参考资产文件不存在")
        return filesystem_candidate, "image/webp" if thumbnail else asset.mime_type

    @staticmethod
    def _shot_media_preview(
        plan: ShotPlan,
        kind: GenerationKind,
        candidates: list[GenerationCandidate],
    ) -> ShotMediaPreview | None:
        approved_id = (
            plan.approved_image_candidate_id
            if kind == GenerationKind.IMAGE
            else plan.approved_video_candidate_id
        )
        available = [
            candidate
            for candidate in candidates
            if candidate.kind == kind
            and candidate.thumbnail_relative_path is not None
            and candidate.status
            not in {GenerationCandidateStatus.REJECTED, GenerationCandidateStatus.ARCHIVED}
        ]
        if not available:
            return None

        approved = next(
            (candidate for candidate in available if candidate.id == approved_id),
            None,
        )
        selected = [
            candidate
            for candidate in available
            if candidate.status == GenerationCandidateStatus.SELECTED
        ]
        candidate = approved or max(
            selected or available,
            key=lambda item: (item.created_at, item.ordinal),
        )
        stage = kind.value
        preview_kind = (
            f"approved_{stage}"
            if approved is not None
            else f"selected_{stage}"
            if candidate.status == GenerationCandidateStatus.SELECTED
            else f"candidate_{stage}"
        )
        return ShotMediaPreview(
            thumbnail_url=f"/api/v1/generation-candidates/{candidate.id}/thumbnail",
            kind=preview_kind,
            candidate_id=candidate.id,
            updated_at=candidate.created_at,
        )

    async def _shot_media_previews(
        self,
        project_id: UUID,
        plans: list[ShotPlan],
    ) -> dict[UUID, tuple[ShotMediaPreview | None, ShotMediaPreview | None]]:
        runs = await self.repository.list_generation_runs(project_id)
        run_by_id = {run.id: run for run in runs}
        candidates = await self.repository.list_generation_candidates_by_run_ids(
            set(run_by_id)
        )
        candidates_by_shot: dict[UUID, list[GenerationCandidate]] = {
            plan.id: [] for plan in plans
        }
        for candidate in candidates:
            run = run_by_id.get(candidate.generation_run_id)
            if run is not None and run.shot_plan_id in candidates_by_shot:
                candidates_by_shot[run.shot_plan_id].append(candidate)

        return {
            plan.id: (
                self._shot_media_preview(
                    plan,
                    GenerationKind.IMAGE,
                    candidates_by_shot[plan.id],
                ),
                self._shot_media_preview(
                    plan,
                    GenerationKind.VIDEO,
                    candidates_by_shot[plan.id],
                ),
            )
            for plan in plans
        }

    async def list_shots(self, project_id: UUID) -> list[ShotPlanResponse]:
        project = await self._require_project(project_id)
        project, plans = await self._ensure_project_shots(project)
        if project.current_revision_id is None:
            raise _fail(409, "revision_required", "创作方案尚无当前版本")
        previews = await self._shot_media_previews(project.id, plans)
        return [
            ShotPlanResponse(
                plan=plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=project.current_revision_id,
                image_preview=previews[plan.id][0],
                video_preview=previews[plan.id][1],
            )
            for plan in plans
        ]

    async def create_shot(
        self,
        project_id: UUID,
        payload: ShotPlanCreate,
    ) -> ShotPlanDetailResponse:
        initial_project = await self._require_project(project_id)
        await self._ensure_project_shots(initial_project)
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            active = [
                item for item in plans
                if item.lifecycle_status == ShotLifecycleStatus.ACTIVE
            ]
            discarded = [
                item for item in plans
                if item.lifecycle_status == ShotLifecycleStatus.DISCARDED
            ]
            active.sort(key=lambda item: item.index)
            discarded.sort(key=lambda item: item.index)
            insert_index = len(active)
            if payload.insert_after_shot_plan_id is not None:
                after_index = next(
                    (
                        index
                        for index, item in enumerate(active)
                        if item.id == payload.insert_after_shot_plan_id
                    ),
                    None,
                )
                if after_index is None:
                    raise _fail(
                        422,
                        "insert_position_invalid",
                        "新增分镜的插入位置不存在或已舍弃",
                    )
                insert_index = after_index + 1

            revision_id = uuid4()
            now = utc_now()
            new_plan_id = uuid4()
            new_bindings: list[ReferenceBinding] = []
            source_keyframe_url: str | None = None
            source_keyframe_relative_path: str | None = None
            source_keyframe_timestamp: float | None = None

            if payload.mode == "duplicate":
                source_plan = next(
                    (
                        item
                        for item in plans
                        if item.id == payload.source_shot_plan_id
                    ),
                    None,
                )
                if source_plan is None:
                    raise _fail(404, "source_shot_not_found", "要复制的源分镜不存在")
                source_keyframe_url = source_plan.source_keyframe_url
                source_keyframe_timestamp = source_plan.source_keyframe_timestamp_seconds
                if source_plan.source_keyframe_relative_path is not None:
                    source_path = self._resolve_source_keyframe(project, source_plan)
                    if source_path is None:
                        raise _fail(409, "source_keyframe_missing", "源分镜关键帧文件不存在")
                    destination = (
                        self.workspace.production_shot_root(
                            project.record_id,
                            project.id,
                            new_plan_id,
                        )
                        / "source-keyframes"
                        / f"{revision_id}.jpg"
                    )
                    source_bytes = await asyncio.to_thread(source_path.read_bytes)
                    await asyncio.to_thread(self._write_atomic, destination, source_bytes)
                    source_keyframe_relative_path = self.workspace.relative(destination)
                    source_keyframe_url = (
                        f"/api/v1/production-shots/{new_plan_id}/source-keyframe"
                        f"?v={revision_id}"
                    )
                new_plan = ShotPlan(
                    id=new_plan_id,
                    project_id=project.id,
                    revision_id=revision_id,
                    source_shot_id=f"duplicate-{new_plan_id.hex}",
                    index=1,
                    lifecycle_status=ShotLifecycleStatus.ACTIVE,
                    source_kind=ShotSourceKind.DUPLICATE,
                    source_keyframe_url=source_keyframe_url,
                    source_keyframe_relative_path=source_keyframe_relative_path,
                    source_keyframe_timestamp_seconds=source_keyframe_timestamp,
                    source_keyframe_origin="duplicate",
                    start_seconds=source_plan.start_seconds,
                    end_seconds=source_plan.end_seconds,
                    duration_seconds=source_plan.duration_seconds,
                    image_prompt=source_plan.image_prompt,
                    image_prompt_mentions=source_plan.image_prompt_mentions,
                    image_negative_constraints=source_plan.image_negative_constraints,
                    video_prompt=source_plan.video_prompt,
                    video_negative_constraints=source_plan.video_negative_constraints,
                    locks=source_plan.locks,
                    required=source_plan.required,
                    image_status=(
                        WorkflowItemStatus.READY
                        if source_plan.image_prompt.strip()
                        else WorkflowItemStatus.DRAFT
                    ),
                    created_at=now,
                    updated_at=now,
                )
                for binding in await self.repository.list_reference_bindings(source_plan.id):
                    new_bindings.append(
                        binding.model_copy(
                            update={
                                "id": uuid4(),
                                "shot_plan_id": new_plan_id,
                                "created_at": now,
                            }
                        )
                    )
            elif payload.mode == "video_range":
                start = float(payload.start_seconds or 0)
                end = float(payload.end_seconds or 0)
                timestamp = float(
                    payload.source_keyframe_timestamp_seconds
                    if payload.source_keyframe_timestamp_seconds is not None
                    else start + (end - start) / 2
                )
                video = await self.repository.get_video(project.video_id)
                if video is None:
                    raise _fail(404, "source_video_not_found", "创作方案的源视频不存在")
                source_video = self._resolve_video_file(video)
                destination = (
                    self.workspace.production_shot_root(
                        project.record_id,
                        project.id,
                        new_plan_id,
                    )
                    / "source-keyframes"
                    / f"{revision_id}.jpg"
                )
                temporary = destination.parent / f".tmp-{revision_id}.jpg"
                filesystem_temporary = _filesystem_path(temporary)
                filesystem_destination = _filesystem_path(destination)
                try:
                    await self.media_processor.extract_frame(
                        source_video,
                        timestamp,
                        filesystem_temporary,
                    )
                    await asyncio.to_thread(
                        self._validate_keyframe_file,
                        filesystem_temporary,
                    )
                    filesystem_destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(filesystem_temporary, filesystem_destination)
                except MediaProcessingError as exc:
                    raise _fail(422, exc.code, str(exc)) from exc
                except OSError as exc:
                    raise _fail(507, "keyframe_write_failed", "无法保存新增分镜关键帧") from exc
                finally:
                    filesystem_temporary.unlink(missing_ok=True)
                duration = max(0.01, end - start)
                prompt = _simplified_text(
                    payload.image_prompt,
                    field_name="图片提示词",
                    allow_empty=True,
                    max_length=8000,
                )
                new_plan = ShotPlan(
                    id=new_plan_id,
                    project_id=project.id,
                    revision_id=revision_id,
                    source_shot_id=f"video-range-{new_plan_id.hex}",
                    index=1,
                    lifecycle_status=ShotLifecycleStatus.ACTIVE,
                    source_kind=ShotSourceKind.VIDEO_RANGE,
                    source_keyframe_url=(
                        f"/api/v1/production-shots/{new_plan_id}/source-keyframe"
                        f"?v={revision_id}"
                    ),
                    source_keyframe_relative_path=self.workspace.relative(destination),
                    source_keyframe_timestamp_seconds=round(timestamp, 3),
                    source_keyframe_origin="video_selection",
                    start_seconds=start,
                    end_seconds=end,
                    duration_seconds=duration,
                    image_prompt=prompt,
                    video_prompt=f"持续 {duration:.2f} 秒。",
                    image_status=(
                        WorkflowItemStatus.READY
                        if prompt.strip()
                        else WorkflowItemStatus.DRAFT
                    ),
                    created_at=now,
                    updated_at=now,
                )
            else:
                previous = active[insert_index - 1] if insert_index else None
                start = float(
                    payload.start_seconds
                    if payload.start_seconds is not None
                    else previous.end_seconds if previous is not None else 0
                )
                end = float(
                    payload.end_seconds
                    if payload.end_seconds is not None and payload.end_seconds > start
                    else start + 3
                )
                duration = max(0.01, end - start)
                prompt = _simplified_text(
                    payload.image_prompt,
                    field_name="图片提示词",
                    allow_empty=True,
                    max_length=8000,
                )
                new_plan = ShotPlan(
                    id=new_plan_id,
                    project_id=project.id,
                    revision_id=revision_id,
                    source_shot_id=f"blank-{new_plan_id.hex}",
                    index=1,
                    lifecycle_status=ShotLifecycleStatus.ACTIVE,
                    source_kind=ShotSourceKind.BLANK,
                    source_keyframe_url=None,
                    source_keyframe_origin="blank",
                    start_seconds=start,
                    end_seconds=end,
                    duration_seconds=duration,
                    image_prompt=prompt,
                    video_prompt=f"持续 {duration:.2f} 秒。",
                    image_status=(
                        WorkflowItemStatus.READY
                        if prompt.strip()
                        else WorkflowItemStatus.DRAFT
                    ),
                    created_at=now,
                    updated_at=now,
                )

            active.insert(insert_index, new_plan)
            next_plans, changed_plans = self._resequence_plans(
                active,
                discarded,
                revision_id,
                force_ids={new_plan_id},
            )
            all_bindings = await self._all_bindings(plans)
            all_bindings.extend(new_bindings)
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_IMAGES,
                    "updated_at": now,
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_STRUCTURE_CHANGED,
                f"新增分镜并插入到第 {insert_index + 1} 位",
                revision_id=revision_id,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
                reference_bindings=new_bindings,
            )
        return await self.get_shot(new_plan_id)

    async def discard_shot(
        self,
        shot_plan_id: UUID,
        payload: ShotLifecycleUpdate,
    ) -> list[ShotPlanResponse]:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            if plan.lifecycle_status == ShotLifecycleStatus.DISCARDED:
                return await self.list_shots(project.id)
            active = [
                item for item in plans
                if item.lifecycle_status == ShotLifecycleStatus.ACTIVE
            ]
            if len(active) <= 1:
                raise _fail(409, "last_active_shot", "创作方案至少需要保留一个有效分镜")
            revision_id = uuid4()
            discarded_plan = plan.model_copy(
                update={
                    "lifecycle_status": ShotLifecycleStatus.DISCARDED,
                    "revision_id": revision_id,
                    "updated_at": utc_now(),
                }
            )
            next_active = [item for item in active if item.id != plan.id]
            discarded = [
                item for item in plans
                if item.lifecycle_status == ShotLifecycleStatus.DISCARDED
            ] + [discarded_plan]
            next_plans, changed_plans = self._resequence_plans(
                next_active,
                discarded,
                revision_id,
                force_ids={plan.id},
            )
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_STRUCTURE_CHANGED,
                f"舍弃分镜 {plan.index}",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
            )
        return await self.list_shots(plan.project_id)

    async def restore_shot(
        self,
        shot_plan_id: UUID,
        payload: ShotLifecycleUpdate,
    ) -> list[ShotPlanResponse]:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            if plan.lifecycle_status == ShotLifecycleStatus.ACTIVE:
                return await self.list_shots(project.id)
            active = sorted(
                (
                    item for item in plans
                    if item.lifecycle_status == ShotLifecycleStatus.ACTIVE
                ),
                key=lambda item: item.index,
            )
            insert_index = len(active)
            if payload.insert_after_shot_plan_id is not None:
                after_index = next(
                    (
                        index
                        for index, item in enumerate(active)
                        if item.id == payload.insert_after_shot_plan_id
                    ),
                    None,
                )
                if after_index is None:
                    raise _fail(422, "insert_position_invalid", "恢复分镜的插入位置无效")
                insert_index = after_index + 1
            revision_id = uuid4()
            restored = plan.model_copy(
                update={
                    "lifecycle_status": ShotLifecycleStatus.ACTIVE,
                    "revision_id": revision_id,
                    "updated_at": utc_now(),
                }
            )
            active.insert(insert_index, restored)
            discarded = [
                item for item in plans
                if item.lifecycle_status == ShotLifecycleStatus.DISCARDED
                and item.id != plan.id
            ]
            next_plans, changed_plans = self._resequence_plans(
                active,
                discarded,
                revision_id,
                force_ids={plan.id},
            )
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_STRUCTURE_CHANGED,
                f"恢复分镜并插入到第 {insert_index + 1} 位",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
            )
        return await self.list_shots(plan.project_id)

    async def reorder_shots(
        self,
        project_id: UUID,
        payload: ShotPlanReorder,
    ) -> list[ShotPlanResponse]:
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            active_by_id = {
                item.id: item
                for item in plans
                if item.lifecycle_status == ShotLifecycleStatus.ACTIVE
            }
            requested_ids = payload.ordered_shot_plan_ids
            if set(requested_ids) != set(active_by_id):
                raise _fail(
                    422,
                    "shot_order_incomplete",
                    "排序必须包含当前全部有效分镜，且不能包含已舍弃分镜",
                )
            current_ids = [
                item.id
                for item in sorted(active_by_id.values(), key=lambda item: item.index)
            ]
            if requested_ids == current_ids:
                return await self.list_shots(project.id)
            revision_id = uuid4()
            active = [active_by_id[item_id] for item_id in requested_ids]
            discarded = [
                item for item in plans
                if item.lifecycle_status == ShotLifecycleStatus.DISCARDED
            ]
            next_plans, changed_plans = self._resequence_plans(
                active,
                discarded,
                revision_id,
            )
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_STRUCTURE_CHANGED,
                "调整有效分镜顺序",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
            )
        return await self.list_shots(project_id)

    async def get_shot(self, shot_plan_id: UUID) -> ShotPlanDetailResponse:
        plan = await self._require_shot(shot_plan_id)
        project = await self._require_project(plan.project_id)
        project, _ = await self._ensure_project_shots(project)
        plan = await self._require_shot(shot_plan_id)
        if project.current_revision_id is None:
            raise _fail(409, "revision_required", "创作方案尚无当前版本")
        runs = await self.repository.list_generation_runs(project.id, plan.id)
        return ShotPlanDetailResponse(
            plan=plan,
            reference_bindings=await self.repository.list_reference_bindings(plan.id),
            current_revision_id=project.current_revision_id,
            generation_runs=[await self._run_response(run) for run in reversed(runs)],
            approval_events=await self.repository.list_approval_events(
                project.id,
                plan.id,
            ),
        )

    async def update_shot(
        self,
        shot_plan_id: UUID,
        payload: ShotPlanUpdate,
    ) -> ShotPlanDetailResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            fields = payload.model_fields_set - {
                "expected_revision_id",
                "confirm_stale",
            }
            image_changed = bool(
                fields
                & {
                    "image_prompt",
                    "image_prompt_mentions",
                    "image_negative_constraints",
                    "locks",
                    "reference_bindings",
                }
            )
            video_changed = bool(
                fields
                & {
                    "video_prompt",
                    "video_negative_constraints",
                    "locks",
                }
            )
            requires_confirmation = (
                image_changed and plan.image_status == WorkflowItemStatus.APPROVED
            ) or (video_changed and plan.video_status == WorkflowItemStatus.APPROVED)
            if requires_confirmation and not payload.confirm_stale:
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "该修改会使已审批结果过期，请确认影响范围后重试",
                )

            plans = await self.repository.list_shot_plans(project.id)
            all_bindings = await self._all_bindings(plans)
            current_bindings = [item for item in all_bindings if item.shot_plan_id == plan.id]
            next_bindings = current_bindings
            removed_binding_ids: list[UUID] = []
            normalized_payload = payload
            if "image_prompt_mentions" in fields:
                normalized_mentions = await self._validate_prompt_mentions(
                    project,
                    payload.image_prompt_mentions or [],
                )
                normalized_payload = payload.model_copy(
                    update={"image_prompt_mentions": normalized_mentions}
                )
            if "reference_bindings" in fields or "image_prompt_mentions" in fields:
                binding_inputs = (
                    payload.reference_bindings or []
                    if "reference_bindings" in fields
                    else [
                        ReferenceBindingInput(
                            reference_asset_id=item.reference_asset_id,
                            role=item.role,
                            weight=item.weight,
                            crop_hint=item.crop_hint,
                            notes=item.notes,
                        )
                        for item in current_bindings
                    ]
                )
                binding_inputs = await self._append_mention_bindings(
                    project,
                    binding_inputs,
                    normalized_payload.image_prompt_mentions
                    if "image_prompt_mentions" in fields
                    else plan.image_prompt_mentions,
                )
                next_bindings = await self._build_bindings(
                    project,
                    plan,
                    binding_inputs,
                )
                removed_binding_ids = [item.id for item in current_bindings]
                all_bindings = [
                    item for item in all_bindings if item.shot_plan_id != plan.id
                ] + next_bindings

            revision_id = uuid4()
            updated = self._apply_shot_fields(
                plan,
                normalized_payload,
                fields,
                revision_id,
                image_changed=image_changed,
                video_changed=video_changed,
            )
            next_plans = [updated if item.id == updated.id else item for item in plans]
            next_active_step = project.active_step
            if image_changed:
                next_active_step = ProductionStep.SHOT_IMAGES
            elif video_changed:
                next_active_step = ProductionStep.SHOT_VIDEOS
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": next_active_step,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_PLAN_CHANGED,
                f"更新分镜 {updated.index} 创作计划",
                revision_id=revision_id,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated],
                reference_bindings=(
                    next_bindings
                    if "reference_bindings" in fields or "image_prompt_mentions" in fields
                    else None
                ),
                remove_reference_binding_ids=removed_binding_ids,
            )
        return await self.get_shot(shot_plan_id)

    async def bulk_update_shots(
        self,
        project_id: UUID,
        payload: ShotPlanBulkUpdate,
    ) -> list[ShotPlanResponse]:
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            plans = await self.repository.list_shot_plans(project.id)
            plans_by_id = {item.id: item for item in plans}
            missing = [
                item.shot_plan_id
                for item in payload.updates
                if item.shot_plan_id not in plans_by_id
            ]
            if missing:
                raise _fail(404, "shot_plan_not_found", "批量更新包含不存在的分镜")
            if any(
                plans_by_id[item.shot_plan_id].lifecycle_status
                != ShotLifecycleStatus.ACTIVE
                for item in payload.updates
            ):
                raise _fail(409, "shot_discarded", "已舍弃分镜需要先恢复后才能修改")

            impacted_approved = any(
                plans_by_id[item.shot_plan_id].image_status == WorkflowItemStatus.APPROVED
                and self._image_fields_changed(item)
                for item in payload.updates
            )
            if impacted_approved and not payload.confirm_stale:
                raise _fail(
                    409,
                    "stale_confirmation_required",
                    "批量修改会使已审批结果过期，请确认影响范围后重试",
                )

            revision_id = uuid4()
            all_bindings = await self._all_bindings(plans)
            changed_plans: list[ShotPlan] = []
            new_bindings: list[ReferenceBinding] = []
            removed_binding_ids: list[UUID] = []
            for item in payload.updates:
                current = plans_by_id[item.shot_plan_id]
                fields = item.model_fields_set - {"shot_plan_id"}
                normalized_item = item
                if "image_prompt_mentions" in fields:
                    normalized_mentions = await self._validate_prompt_mentions(
                        project,
                        item.image_prompt_mentions or [],
                    )
                    normalized_item = item.model_copy(
                        update={"image_prompt_mentions": normalized_mentions}
                    )
                if "reference_bindings" in fields or "image_prompt_mentions" in fields:
                    previous = [
                        binding for binding in all_bindings if binding.shot_plan_id == current.id
                    ]
                    binding_inputs = (
                        item.reference_bindings or []
                        if "reference_bindings" in fields
                        else [
                            ReferenceBindingInput(
                                reference_asset_id=binding.reference_asset_id,
                                role=binding.role,
                                weight=binding.weight,
                                crop_hint=binding.crop_hint,
                                notes=binding.notes,
                            )
                            for binding in previous
                        ]
                    )
                    binding_inputs = await self._append_mention_bindings(
                        project,
                        binding_inputs,
                        normalized_item.image_prompt_mentions
                        if "image_prompt_mentions" in fields
                        else current.image_prompt_mentions,
                    )
                    replacements = await self._build_bindings(
                        project,
                        current,
                        binding_inputs,
                    )
                    removed_binding_ids.extend(binding.id for binding in previous)
                    all_bindings = [
                        binding for binding in all_bindings if binding.shot_plan_id != current.id
                    ] + replacements
                    new_bindings.extend(replacements)
                updated = self._apply_shot_fields(
                    current,
                    normalized_item,
                    fields,
                    revision_id,
                    image_changed=self._image_fields_changed(item),
                    video_changed=self._video_fields_changed(item),
                )
                plans_by_id[updated.id] = updated
                changed_plans.append(updated)

            next_plans = [plans_by_id[item.id] for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_IMAGES,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_PLAN_CHANGED,
                f"批量更新 {len(changed_plans)} 个分镜创作计划",
                revision_id=revision_id,
                shot_plans=next_plans,
                reference_bindings=all_bindings,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
                reference_bindings=new_bindings,
                remove_reference_binding_ids=removed_binding_ids,
            )
        return await self.list_shots(project_id)

    async def change_impact(
        self,
        project_id: UUID,
        payload: ChangeImpactRequest,
    ) -> ChangeImpactResponse:
        project = await self._require_project(project_id)
        self._require_expected_revision(project, payload.expected_revision_id)
        plans = await self.repository.list_shot_plans(project.id)
        impacted: list[ShotPlan]
        if payload.change_type == "project_settings":
            impacted = plans
        elif payload.change_type == "reference_asset":
            asset_ids = set(payload.reference_asset_ids)
            impacted_ids: set[UUID] = set()
            for plan in plans:
                bindings = await self.repository.list_reference_bindings(plan.id)
                if any(item.reference_asset_id in asset_ids for item in bindings):
                    impacted_ids.add(plan.id)
            impacted = [item for item in plans if item.id in impacted_ids]
        else:
            requested = set(payload.shot_plan_ids)
            impacted = [item for item in plans if item.id in requested]

        downstream_only = payload.change_type in {
            "candidate_selection",
            "image_approval_revoke",
        }
        stale_stages = (
            [
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            ]
            if downstream_only
            else [
                ProductionStep.SHOT_IMAGES,
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            ]
        )
        stale_candidates = (
            []
            if payload.change_type == "image_approval_revoke"
            else [
                item.approved_image_candidate_id
                for item in impacted
                if item.approved_image_candidate_id is not None
            ]
        )
        downstream_result_statuses = {
            WorkflowItemStatus.GENERATING,
            WorkflowItemStatus.REVIEW_REQUIRED,
            WorkflowItemStatus.APPROVED,
            WorkflowItemStatus.STALE,
        }
        downstream_stage_active = project.active_step in {
            ProductionStep.SHOT_VIDEOS,
            ProductionStep.EDITING,
            ProductionStep.EXPORT,
        }
        requires_confirmation = (
            (
                any(item.video_status in downstream_result_statuses for item in impacted)
                or (bool(impacted) and downstream_stage_active)
            )
            if downstream_only
            else any(
                item.image_status == WorkflowItemStatus.APPROVED
                or item.video_status == WorkflowItemStatus.APPROVED
                for item in impacted
            )
        )
        count = len(impacted)
        return ChangeImpactResponse(
            impacted_shot_plan_ids=[item.id for item in impacted],
            impacted_shot_ids=[item.source_shot_id for item in impacted],
            stale_candidate_ids=stale_candidates,
            stale_stage_ids=stale_stages if count else [],
            requires_confirmation=requires_confirmation,
            summary=(
                f"将重新打开 {count} 个分镜的图片审核，并使其后续结果过期"
                if count and payload.change_type == "image_approval_revoke"
                else (
                    f"将影响 {count} 个分镜，并使其后续结果过期"
                    if count
                    else "当前修改不会使已生成结果过期"
                )
            ),
        )

    async def resolve_source_video(
        self,
        project_id: UUID,
    ) -> tuple[Path, str]:
        project = await self._require_project(project_id)
        video = await self.repository.get_video(project.video_id)
        if video is None:
            raise _fail(404, "source_video_not_found", "创作方案的源视频不存在")
        path = self._resolve_video_file(video)
        media_type = {
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".webm": "video/webm",
        }.get(path.suffix.lower(), "application/octet-stream")
        return path, media_type

    async def resolve_source_keyframe_content(
        self,
        shot_plan_id: UUID,
    ) -> tuple[Path, str]:
        plan = await self._require_shot(shot_plan_id)
        project = await self._require_project(plan.project_id)
        path = self._resolve_source_keyframe(project, plan)
        if path is None:
            raise _fail(404, "source_keyframe_missing", "当前分镜关键帧不存在")
        return path, "image/jpeg"

    async def select_source_keyframe(
        self,
        shot_plan_id: UUID,
        payload: ShotKeyframeSelectRequest,
    ) -> ShotPlanDetailResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            timestamp = float(payload.timestamp_seconds)
            if timestamp < plan.start_seconds - 0.001 or timestamp > plan.end_seconds + 0.001:
                raise _fail(
                    422,
                    "keyframe_timestamp_out_of_range",
                    (
                        f"关键帧时间必须位于分镜 {plan.start_seconds:.3f}s "
                        f"到 {plan.end_seconds:.3f}s 之间"
                    ),
                )
            has_reviewed_output = (
                plan.approved_image_candidate_id is not None
                or plan.image_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                    WorkflowItemStatus.STALE,
                }
            )
            if has_reviewed_output and not payload.confirm_stale:
                raise _fail(
                    409,
                    "keyframe_change_confirmation_required",
                    "替换关键帧会归档旧图片候选并使后续结果过期，请确认后重试",
                )
            timestamp = min(
                max(timestamp, plan.start_seconds),
                max(plan.start_seconds, plan.end_seconds - 0.001),
            )
            video = await self.repository.get_video(project.video_id)
            if video is None:
                raise _fail(404, "source_video_not_found", "创作方案的源视频不存在")
            source_video = self._resolve_video_file(video)
            revision_id = uuid4()
            keyframe_root = (
                self.workspace.production_shot_root(
                    project.record_id,
                    project.id,
                    plan.id,
                )
                / "source-keyframes"
            )
            destination = keyframe_root / f"{revision_id}.jpg"
            temporary = keyframe_root / f".tmp-{revision_id}.jpg"
            filesystem_temporary = _filesystem_path(temporary)
            filesystem_destination = _filesystem_path(destination)
            try:
                await self.media_processor.extract_frame(
                    source_video,
                    timestamp,
                    filesystem_temporary,
                )
                await asyncio.to_thread(
                    self._validate_keyframe_file,
                    filesystem_temporary,
                )
                filesystem_destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(filesystem_temporary, filesystem_destination)
            except MediaProcessingError as exc:
                raise _fail(422, exc.code, str(exc)) from exc
            except OSError as exc:
                raise _fail(507, "keyframe_write_failed", "无法保存所选关键帧") from exc
            finally:
                filesystem_temporary.unlink(missing_ok=True)

            archived_candidates = await self._archive_active_candidates(project, plan)
            video_status = (
                WorkflowItemStatus.STALE
                if plan.video_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                    WorkflowItemStatus.STALE,
                }
                else plan.video_status
            )
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "source_keyframe_url": (
                        f"/api/v1/production-shots/{plan.id}/source-keyframe"
                        f"?v={revision_id}"
                    ),
                    "source_keyframe_relative_path": self.workspace.relative(destination),
                    "source_keyframe_timestamp_seconds": round(timestamp, 3),
                    "source_keyframe_origin": "video_selection",
                    "image_status": (
                        WorkflowItemStatus.READY
                        if plan.image_prompt.strip()
                        else WorkflowItemStatus.DRAFT
                    ),
                    "video_status": video_status,
                    "approved_image_candidate_id": None,
                    "updated_at": utc_now(),
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_IMAGES,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SOURCE_KEYFRAME_CHANGED,
                f"将分镜 {plan.index} 的关键帧切换到 {timestamp:.3f}s",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=archived_candidates,
            )
        return await self.get_shot(shot_plan_id)

    async def approve_source_keyframe(
        self,
        shot_plan_id: UUID,
        payload: ShotSourceFrameApprovalRequest,
    ) -> CandidateActionResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if plan.image_status == WorkflowItemStatus.APPROVED:
                raise _fail(
                    409,
                    "image_already_approved",
                    "该分镜图片已经确认；如需更换，请先重新选择关键帧或修改生成输入",
                )
            source_path = self._resolve_source_keyframe(project, plan)
            if source_path is None:
                raise _fail(409, "source_keyframe_required", "当前分镜没有可读取的关键帧")
            revision_id = uuid4()
            run, candidate = await asyncio.to_thread(
                self._create_source_frame_candidate,
                project,
                plan,
                revision_id,
                source_path,
            )
            archived_candidates = await self._archive_active_candidates(project, plan)
            event = ApprovalEvent(
                project_id=project.id,
                revision_id=revision_id,
                shot_plan_id=plan.id,
                candidate_id=candidate.id,
                target_kind=GenerationKind.IMAGE,
                decision=ApprovalDecision.APPROVED,
                reason=(
                    _simplified_text(
                        payload.reason,
                        field_name="确认说明",
                        allow_empty=True,
                        max_length=1000,
                    )
                    if payload.reason is not None
                    else "直接使用源视频关键帧，未调用图片生成模型"
                ),
            )
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "image_status": WorkflowItemStatus.APPROVED,
                    "approved_image_candidate_id": candidate.id,
                    "updated_at": utc_now(),
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_IMAGES,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.IMAGE_APPROVED,
                f"直接确认分镜 {plan.index} 的源视频关键帧",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_runs=[run],
                generation_candidates=[*archived_candidates, candidate],
                approval_events=[event],
            )
        return CandidateActionResponse(
            shot=ShotPlanResponse(
                plan=updated_plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=next_project.current_revision_id,
            ),
            candidate=self._candidate_response(candidate),
            approval_event=event,
        )

    async def create_image_run(
        self,
        shot_plan_id: UUID,
        payload: ImageGenerationCreate,
    ) -> GenerationRunResponse:
        run = await self._enqueue_image_run(shot_plan_id, payload)
        self._schedule_image_run(run.id)
        return await self._run_response(run)

    async def create_video_run(
        self,
        shot_plan_id: UUID,
        payload: VideoGenerationCreate,
    ) -> GenerationRunResponse:
        run = await self._enqueue_video_run(shot_plan_id, payload)
        self._schedule_video_run(run.id)
        return await self._run_response(run)

    async def _enqueue_video_run(
        self,
        shot_plan_id: UUID,
        payload: VideoGenerationCreate,
        *,
        retry_of_run_id: UUID | None = None,
        retry_count: int = 0,
    ) -> GenerationRun:
        plan = await self._require_shot(shot_plan_id)
        self._ensure_shot_active(plan)
        project = await self._require_project(plan.project_id)
        self._require_expected_revision(project, payload.expected_revision_id)
        if project.active_step != ProductionStep.SHOT_VIDEOS:
            raise _fail(
                409,
                "video_stage_not_active",
                "请先完成全部必需分镜图片并进入分段视频阶段",
            )
        if not plan.video_prompt.strip():
            raise _fail(409, "video_prompt_required", "请先填写视频提示词")
        if not await self._has_valid_approved_image_output(project, plan):
            raise _fail(
                409,
                "approved_image_required",
                "当前分镜缺少有效的已确认图片",
            )
        if plan.video_status == WorkflowItemStatus.APPROVED:
            raise _fail(
                409,
                "video_already_approved",
                "已确认视频需要先取消采用再生成新候选",
            )
        if payload.generation_intent == "new_variation" and payload.seed is None:
            payload = payload.model_copy(
                update={"seed": secrets.randbelow(2_147_483_648)}
            )
        try:
            execution_mode = ImageExecutionMode(payload.execution_mode)
        except ValueError as exc:
            raise _fail(422, "video_execution_mode_invalid", "视频生成执行模式无效") from exc
        validate_mode = getattr(self.video_gateway, "validate_execution_mode", None)
        if callable(validate_mode):
            try:
                validate_mode(execution_mode)
            except VideoGenerationGatewayError as exc:
                raise _fail(exc.status_code, exc.code, str(exc)) from exc

        duration_seconds = round(payload.duration_seconds or plan.duration_seconds, 3)
        try:
            identity, resolved = self.video_gateway.resolve_identity(
                execution_mode=execution_mode.value,
                model_alias=payload.model_alias,
                duration_seconds=duration_seconds,
                resolution=payload.resolution,
                candidate_count=payload.candidate_count,
                allow_unknown_cost=payload.allow_unknown_cost,
            )
        except VideoGenerationGatewayError as exc:
            raise _fail(exc.status_code, exc.code, str(exc)) from exc
        payload = payload.model_copy(
            update={
                "duration_seconds": duration_seconds,
                "model_alias": identity.model_alias,
                "resolution": resolved.resolution if resolved is not None else payload.resolution,
            }
        )

        active_statuses = {
            ProductionRunStatus.QUEUED,
            ProductionRunStatus.RUNNING,
            ProductionRunStatus.CANCELLATION_REQUESTED,
        }
        existing_runs = await self.repository.list_generation_runs(project.id, plan.id)
        if any(
            item.kind == GenerationKind.VIDEO and item.status in active_statuses
            for item in existing_runs
        ):
            raise _fail(409, "generation_already_running", "该分镜已有视频生成任务在执行")

        run_id = uuid4()
        request_payload = payload.model_dump(mode="json")
        queue_root = (
            self.workspace.production_shot_root(project.record_id, project.id, plan.id)
            / "videos"
            / str(run_id)
        )
        queue_path = queue_root / "queue.json"
        fingerprint = hashlib.sha256(
            json.dumps(
                request_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        await asyncio.to_thread(
            self._write_json_atomic,
            queue_path,
            {
                "schema_version": "viral-dna-video-job/v1",
                "run_id": str(run_id),
                "shot_plan_id": str(plan.id),
                "request": request_payload,
                "retry_of_run_id": str(retry_of_run_id) if retry_of_run_id else None,
                "retry_count": retry_count,
            },
        )
        now = utc_now()
        run = GenerationRun(
            id=run_id,
            project_id=project.id,
            shot_plan_id=plan.id,
            revision_id=payload.expected_revision_id,
            kind=GenerationKind.VIDEO,
            input_mode=VideoGenerationInputMode.IMAGE_TO_VIDEO,
            provider=identity.provider,
            model=identity.model,
            model_snapshot=identity.model_snapshot,
            model_alias=identity.model_alias,
            model_display_name=identity.model_display_name,
            prompt_version="shot-video-v1",
            schema_version="viral-dna-video-job/v1",
            pricing_version=identity.pricing_version,
            request_fingerprint=fingerprint,
            input_snapshot_relative_path=self.workspace.relative(queue_path),
            execution_mode=execution_mode,
            adapter_id=identity.adapter_id,
            adapter_version=identity.adapter_version,
            protocol_version=identity.protocol_version,
            capability_snapshot=identity.capability.model_dump(mode="json"),
            execution_summary=identity.execution_summary,
            cost_source=identity.cost_source,
            cost_estimate_known=identity.cost_estimate_known,
            actual_cost_known=False,
            cost_currency="CNY",
            pricing_snapshot=identity.pricing_snapshot,
            request_payload=request_payload,
            retry_of_run_id=retry_of_run_id,
            retry_count=retry_count,
            status=ProductionRunStatus.QUEUED,
            estimated_cost_micros=identity.estimated_cost_micros,
            created_at=now,
            updated_at=now,
        )
        await self.repository.save_generation_run(run)
        await self._notify_generation_run(run)
        if retry_of_run_id is not None:
            source_tasks = await self.repository.list_video_provider_tasks(retry_of_run_id)
            for source_task in source_tasks:
                if not source_task.provider_task_id or source_task.status in {
                    VideoProviderTaskStatus.FAILED,
                    VideoProviderTaskStatus.CANCELLED,
                }:
                    continue
                await self.repository.save_video_provider_task(
                    source_task.model_copy(
                        update={
                            "id": uuid4(),
                            "generation_run_id": run.id,
                            "project_id": run.project_id,
                            "shot_plan_id": run.shot_plan_id,
                            "created_at": now,
                            "updated_at": now,
                        }
                    )
                )
        return run

    def _schedule_video_run(self, run_id: UUID) -> None:
        current = self._generation_tasks.get(run_id)
        if current is not None and not current.done():
            return
        cancellation = Event()
        self._generation_cancellations[run_id] = cancellation
        task = asyncio.create_task(
            self._run_queued_video(run_id, cancellation),
            name=f"viral-dna-video-{run_id}",
        )
        self._generation_tasks[run_id] = task

    async def _run_queued_video(self, run_id: UUID, cancellation: Event) -> None:
        try:
            running = await self.repository.claim_generation_run(run_id, utc_now())
            if running is None:
                return
            payload = VideoGenerationCreate.model_validate(running.request_payload)
            await self._execute_video_run_request(
                running.shot_plan_id,
                payload,
                run_id=running.id,
                cancellation=cancellation,
                queued_run=running,
            )
        except asyncio.CancelledError:
            await self._mark_generation_terminal(
                run_id,
                ProductionRunStatus.CANCELLED,
                "generation_cancelled",
                "视频生成任务已取消",
            )
        except ProductionServiceError as exc:
            if cancellation.is_set() or exc.code == "generation_cancelled":
                await self._mark_generation_terminal(
                    run_id,
                    ProductionRunStatus.CANCELLED,
                    "generation_cancelled",
                    "视频生成任务已取消",
                )
            else:
                await self._mark_generation_terminal(
                    run_id,
                    ProductionRunStatus.FAILED,
                    exc.code,
                    str(exc),
                )
        except Exception as exc:
            await self._mark_generation_terminal(
                run_id,
                ProductionRunStatus.FAILED,
                "generation_worker_failed",
                str(exc)[:2000],
            )
        finally:
            self._generation_cancellations.pop(run_id, None)
            current = self._generation_tasks.get(run_id)
            if current is asyncio.current_task():
                self._generation_tasks.pop(run_id, None)

    async def _enqueue_image_run(
        self,
        shot_plan_id: UUID,
        payload: ImageGenerationCreate,
        *,
        retry_of_run_id: UUID | None = None,
        retry_count: int = 0,
    ) -> GenerationRun:
        plan = await self._require_shot(shot_plan_id)
        self._ensure_shot_active(plan)
        project = await self._require_project(plan.project_id)
        self._require_expected_revision(project, payload.expected_revision_id)
        if payload.generation_intent == "new_variation" and payload.seed is None:
            payload = payload.model_copy(
                update={"seed": secrets.randbelow(2_147_483_648)}
            )
        if not plan.image_prompt.strip():
            raise _fail(409, "image_prompt_required", "请先填写图片提示词")
        if plan.image_status == WorkflowItemStatus.APPROVED:
            raise _fail(409, "image_already_approved", "已审批分镜需要先修改输入再重新生成")
        active_statuses = {
            ProductionRunStatus.QUEUED,
            ProductionRunStatus.RUNNING,
            ProductionRunStatus.CANCELLATION_REQUESTED,
        }
        existing_runs = await self.repository.list_generation_runs(project.id, plan.id)
        if any(item.status in active_statuses for item in existing_runs):
            raise _fail(409, "generation_already_running", "该分镜已有图片生成任务在执行")
        settings_service = getattr(self.image_gateway, "settings_service", None)
        settings = settings_service.get() if settings_service is not None else None
        if settings is not None and not settings.enabled:
            raise _fail(409, "image_generation_not_configured", "请先配置并启用真实图片生成引擎")
        try:
            execution_mode = ImageExecutionMode(
                payload.execution_mode
                or (
                    settings.execution_mode
                    if settings is not None
                    else ImageExecutionMode.REMOTE_API
                )
            )
        except ValueError as exc:
            raise _fail(422, "image_execution_mode_invalid", "图片生成执行模式无效") from exc
        run_id = uuid4()
        request_payload = payload.model_dump(mode="json")
        queue_root = (
            self.workspace.production_shot_root(project.record_id, project.id, plan.id)
            / "images"
            / str(run_id)
        )
        queue_path = queue_root / "queue.json"
        fingerprint = hashlib.sha256(
            json.dumps(
                request_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        await asyncio.to_thread(
            self._write_json_atomic,
            queue_path,
            {
                "schema_version": "viral-dna-image-job/v1",
                "run_id": str(run_id),
                "shot_plan_id": str(plan.id),
                "request": request_payload,
                "retry_of_run_id": str(retry_of_run_id) if retry_of_run_id else None,
                "retry_count": retry_count,
            },
        )
        now = utc_now()
        run = GenerationRun(
            id=run_id,
            project_id=project.id,
            shot_plan_id=plan.id,
            revision_id=payload.expected_revision_id,
            kind=GenerationKind.IMAGE,
            input_mode=payload.input_mode,
            provider="pending",
            model="pending",
            model_snapshot="pending",
            prompt_version="shot-image-v2",
            schema_version="viral-dna-image-job/v1",
            pricing_version="pending",
            request_fingerprint=fingerprint,
            input_snapshot_relative_path=self.workspace.relative(queue_path),
            execution_mode=execution_mode,
            adapter_id="pending",
            adapter_version="batch4.2.4",
            cost_source=GenerationCostSource.UNKNOWN,
            cost_estimate_known=False,
            request_payload=request_payload,
            retry_of_run_id=retry_of_run_id,
            retry_count=retry_count,
            status=ProductionRunStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        await self.repository.save_generation_run(run)
        await self._notify_generation_run(run)
        return run

    def _schedule_image_run(self, run_id: UUID) -> None:
        current = self._generation_tasks.get(run_id)
        if current is not None and not current.done():
            return
        cancellation = Event()
        self._generation_cancellations[run_id] = cancellation
        task = asyncio.create_task(
            self._run_queued_image(run_id, cancellation),
            name=f"viral-dna-image-{run_id}",
        )
        self._generation_tasks[run_id] = task

    async def _run_queued_image(self, run_id: UUID, cancellation: Event) -> None:
        try:
            running = await self.repository.claim_generation_run(run_id, utc_now())
            if running is None:
                return
            payload = ImageGenerationCreate.model_validate(running.request_payload)
            await self._execute_image_run_request(
                running.shot_plan_id,
                payload,
                run_id=running.id,
                cancellation=cancellation,
                queued_run=running,
            )
        except asyncio.CancelledError:
            await self._mark_generation_terminal(
                run_id,
                ProductionRunStatus.CANCELLED,
                "generation_cancelled",
                "图片生成任务已取消",
            )
        except ProductionServiceError as exc:
            if cancellation.is_set() or exc.code == "generation_cancelled":
                await self._mark_generation_terminal(
                    run_id,
                    ProductionRunStatus.CANCELLED,
                    "generation_cancelled",
                    "生成任务已取消",
                )
            else:
                await self._mark_generation_terminal(
                    run_id,
                    ProductionRunStatus.FAILED,
                    exc.code,
                    str(exc),
                )
        except Exception as exc:
            await self._mark_generation_terminal(
                run_id,
                ProductionRunStatus.FAILED,
                "generation_worker_failed",
                str(exc)[:2000],
            )
        finally:
            self._generation_cancellations.pop(run_id, None)
            current = self._generation_tasks.get(run_id)
            if current is asyncio.current_task():
                self._generation_tasks.pop(run_id, None)

    async def _mark_generation_terminal(
        self,
        run_id: UUID,
        status: ProductionRunStatus,
        error_code: str,
        error_message: str,
    ) -> GenerationRun:
        run = await self._require_run(run_id)
        if run.status in {
            ProductionRunStatus.COMPLETED,
            ProductionRunStatus.CACHED,
            ProductionRunStatus.FAILED,
            ProductionRunStatus.BLOCKED,
            ProductionRunStatus.CANCELLED,
        }:
            return run
        now = utc_now()
        updated = run.model_copy(
            update={
                "status": status,
                "cancellation_requested": status == ProductionRunStatus.CANCELLED,
                "error_code": error_code,
                "error_message": error_message,
                "updated_at": now,
                "last_heartbeat_at": now,
                "completed_at": now,
            }
        )
        await self.repository.save_generation_run(updated)
        await self._notify_generation_run(updated)
        return updated

    async def cancel_generation_run(self, run_id: UUID) -> GenerationRunResponse:
        run = await self._require_run(run_id)
        if run.status in {
            ProductionRunStatus.COMPLETED,
            ProductionRunStatus.CACHED,
            ProductionRunStatus.FAILED,
            ProductionRunStatus.CANCELLED,
            ProductionRunStatus.BLOCKED,
        }:
            return await self._run_response(run)
        now = utc_now()
        requested = run.model_copy(
            update={
                "status": ProductionRunStatus.CANCELLATION_REQUESTED,
                "cancellation_requested": True,
                "updated_at": now,
            }
        )
        await self.repository.save_generation_run(requested)
        if run.kind == GenerationKind.VIDEO:
            try:
                await self.video_gateway.cancel(run_id)
            except Exception:
                # Local cancellation must still complete even when an upstream Provider
                # does not expose cancellation or is temporarily unreachable.
                pass
        cancellation = self._generation_cancellations.get(run_id)
        if cancellation is not None:
            cancellation.set()
        task = self._generation_tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            latest = await self._require_run(run_id)
            if latest.status not in {
                ProductionRunStatus.COMPLETED,
                ProductionRunStatus.CACHED,
                ProductionRunStatus.CANCELLED,
            }:
                await self._mark_generation_terminal(
                    run_id,
                    ProductionRunStatus.CANCELLED,
                    "generation_cancelled",
                    "图片生成任务已取消",
                )
        else:
            await self._mark_generation_terminal(
                run_id,
                ProductionRunStatus.CANCELLED,
                "generation_cancelled",
                "生成任务已取消",
            )
        return await self.get_generation_run(run_id)

    async def retry_generation_run(self, run_id: UUID) -> GenerationRunResponse:
        source = await self._require_run(run_id)
        if source.status not in {
            ProductionRunStatus.FAILED,
            ProductionRunStatus.CANCELLED,
            ProductionRunStatus.BLOCKED,
        }:
            raise _fail(409, "generation_retry_unavailable", "只有失败或已取消的任务可以重试")
        project = await self._require_project(source.project_id)
        payload_data = dict(source.request_payload)
        payload_data["expected_revision_id"] = str(project.current_revision_id)
        if source.kind == GenerationKind.VIDEO:
            provider_tasks = await self.repository.list_video_provider_tasks(source.id)
            if any(
                not item.provider_task_id
                and item.status
                in {
                    VideoProviderTaskStatus.PENDING_SUBMISSION,
                    VideoProviderTaskStatus.UNKNOWN,
                }
                for item in provider_tasks
            ):
                raise _fail(
                    409,
                    "video_provider_submission_ambiguous",
                    "上游提交结果不明确；为避免重复扣费，请先在 Provider 控制台核对任务",
                )
            video_payload = VideoGenerationCreate.model_validate(payload_data)
            run = await self._enqueue_video_run(
                source.shot_plan_id,
                video_payload,
                retry_of_run_id=source.id,
                retry_count=source.retry_count + 1,
            )
            self._schedule_video_run(run.id)
        else:
            image_payload = ImageGenerationCreate.model_validate(payload_data)
            run = await self._enqueue_image_run(
                source.shot_plan_id,
                image_payload,
                retry_of_run_id=source.id,
                retry_count=source.retry_count + 1,
            )
            self._schedule_image_run(run.id)
        return await self._run_response(run)

    async def recover_generation_runs(self) -> dict[str, int]:
        recovered = 0
        interrupted = 0
        cancelled = 0
        for project in await self.repository.list_production_projects():
            for run in await self.repository.list_generation_runs(project.id):
                if run.status == ProductionRunStatus.QUEUED and run.request_payload:
                    if run.kind == GenerationKind.VIDEO:
                        self._schedule_video_run(run.id)
                    else:
                        self._schedule_image_run(run.id)
                    recovered += 1
                elif run.status == ProductionRunStatus.CANCELLATION_REQUESTED:
                    await self._mark_generation_terminal(
                        run.id,
                        ProductionRunStatus.CANCELLED,
                        "generation_cancelled",
                        "服务重启前已请求取消任务",
                    )
                    cancelled += 1
                elif run.status == ProductionRunStatus.RUNNING:
                    provider_tasks = (
                        await self.repository.list_video_provider_tasks(run.id)
                        if run.kind == GenerationKind.VIDEO
                        and run.execution_mode == ImageExecutionMode.REMOTE_API
                        else []
                    )
                    if provider_tasks and all(
                        item.provider_task_id
                        or item.status
                        in {
                            VideoProviderTaskStatus.FAILED,
                            VideoProviderTaskStatus.CANCELLED,
                        }
                        for item in provider_tasks
                    ):
                        resumed = run.model_copy(
                            update={
                                "status": ProductionRunStatus.QUEUED,
                                "updated_at": utc_now(),
                                "error_code": None,
                                "error_message": None,
                            }
                        )
                        await self.repository.save_generation_run(resumed)
                        self._schedule_video_run(run.id)
                        recovered += 1
                    else:
                        await self._mark_generation_terminal(
                            run.id,
                            ProductionRunStatus.FAILED,
                            "generation_interrupted",
                            "服务重启导致任务中断，请人工重试以避免重复计费",
                        )
                        interrupted += 1
        return {
            "recovered": recovered,
            "interrupted": interrupted,
            "cancelled": cancelled,
        }

    async def shutdown_generation_runs(self) -> None:
        tasks = [task for task in self._generation_tasks.values() if not task.done()]
        for cancellation in self._generation_cancellations.values():
            cancellation.set()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_image_run_request(
        self,
        shot_plan_id: UUID,
        payload: ImageGenerationCreate,
        *,
        run_id: UUID,
        cancellation: Event,
        queued_run: GenerationRun,
    ) -> GenerationRunResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if not plan.image_prompt.strip():
                raise _fail(409, "image_prompt_required", "请先填写图片提示词")
            if plan.image_status == WorkflowItemStatus.APPROVED:
                raise _fail(409, "image_already_approved", "已审批分镜需要先修改输入再重新生成")

            uses_images = payload.input_mode == ImageGenerationInputMode.KEYFRAME_EDIT
            bindings = (
                await self.repository.list_reference_bindings(plan.id)
                if uses_images
                else []
            )
            assets = (
                await self._list_reference_assets(project.id)
                if uses_images
                else []
            )
            assets_by_id = {item.id: item for item in assets}
            for binding in bindings:
                asset = assets_by_id.get(binding.reference_asset_id)
                if asset is None or asset.archived_at is not None:
                    raise _fail(
                        409,
                        "reference_binding_invalid",
                        "分镜绑定了不存在或已归档的参考资产",
                    )
                if not asset.rights_confirmed:
                    raise _fail(409, "reference_rights_required", "分镜参考资产尚未完成权利确认")
            source_path = (
                self._resolve_source_keyframe(project, plan)
                if uses_images
                else None
            )
            try:
                run, candidates = await self.image_gateway.generate(
                    project,
                    plan,
                    payload.expected_revision_id,
                    bindings,
                    assets,
                    candidate_count=payload.candidate_count,
                    source_path=source_path,
                    input_mode=payload.input_mode,
                    execution_mode=payload.execution_mode,
                    allow_unknown_cost=payload.allow_unknown_cost,
                    seed=payload.seed,
                    reuse_cache=payload.generation_intent != "new_variation",
                    run_id=run_id,
                    cancel_event=cancellation,
                )
            except ImageGenerationGatewayError as exc:
                raise _fail(exc.status_code, exc.code, str(exc)) from exc
            now = utc_now()
            run = run.model_copy(
                update={
                    "request_payload": queued_run.request_payload,
                    "retry_of_run_id": queued_run.retry_of_run_id,
                    "retry_count": queued_run.retry_count,
                    "created_at": queued_run.created_at,
                    "started_at": queued_run.started_at,
                    "updated_at": now,
                    "last_heartbeat_at": now,
                }
            )
            if cancellation.is_set() or run.error_code == "generation_cancelled":
                cancelled = run.model_copy(
                    update={
                        "status": ProductionRunStatus.CANCELLED,
                        "cancellation_requested": True,
                        "error_code": "generation_cancelled",
                        "error_message": "图片生成任务已取消",
                        "completed_at": now,
                    }
                )
                await self.repository.save_generation_run(cancelled)
                return await self._run_response(cancelled)
            if _is_simulated_image_run(run):
                raise _fail(
                    409,
                    "simulated_generation_forbidden",
                    "模拟占位图不能作为图片生成结果，请先配置真实生图引擎",
                )
            prior_candidate_updates: list[GenerationCandidate] = []
            for prior_run in await self.repository.list_generation_runs(
                project.id,
                plan.id,
            ):
                for prior_candidate in await self.repository.list_generation_candidates(
                    prior_run.id
                ):
                    if prior_candidate.status in {
                        GenerationCandidateStatus.READY,
                        GenerationCandidateStatus.SELECTED,
                    }:
                        prior_candidate_updates.append(
                            prior_candidate.model_copy(
                                update={
                                    "status": GenerationCandidateStatus.ARCHIVED,
                                }
                            )
                        )
            revision_id = uuid4()
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "image_status": (
                        WorkflowItemStatus.REVIEW_REQUIRED
                        if candidates
                        else WorkflowItemStatus.FAILED
                    ),
                    "approved_image_candidate_id": None,
                    "updated_at": utc_now(),
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_IMAGES,
                    "estimated_cost_micros": (
                        project.estimated_cost_micros + run.estimated_cost_micros
                    ),
                    "actual_cost_micros": project.actual_cost_micros + run.actual_cost_micros,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_PLAN_CHANGED,
                (
                    f"为分镜 {plan.index} 创建 {len(candidates)} 个图片候选"
                    if candidates
                    else f"分镜 {plan.index} 图片生成失败：{run.error_code or 'unknown'}"
                ),
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_runs=[run],
                generation_candidates=[*prior_candidate_updates, *candidates],
            )
        await self._notify_generation_run(run)
        return await self.get_generation_run(run.id)

    async def _execute_video_run_request(
        self,
        shot_plan_id: UUID,
        payload: VideoGenerationCreate,
        *,
        run_id: UUID,
        cancellation: Event,
        queued_run: GenerationRun,
    ) -> GenerationRunResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if project.active_step != ProductionStep.SHOT_VIDEOS:
                raise _fail(
                    409,
                    "video_stage_not_active",
                    "当前方案不在分段视频阶段",
                )
            if not plan.video_prompt.strip():
                raise _fail(409, "video_prompt_required", "请先填写视频提示词")
            if not await self._has_valid_approved_image_output(project, plan):
                raise _fail(
                    409,
                    "approved_image_required",
                    "当前分镜缺少有效的已确认图片",
                )
            approved_image_id = plan.approved_image_candidate_id
            if approved_image_id is None:
                raise _fail(409, "approved_image_required", "当前分镜缺少已确认图片")
            approved_image = await self._require_candidate(approved_image_id)
            approved_image_path, _ = await self.resolve_candidate_content(
                approved_image.id
            )
            duration_seconds = round(
                payload.duration_seconds or plan.duration_seconds,
                3,
            )
            try:
                run, candidates = await self.video_gateway.generate(
                    project,
                    plan,
                    payload.expected_revision_id,
                    approved_image.id,
                    approved_image_path,
                    approved_image.sha256,
                    approved_image_relative_path=approved_image.relative_path,
                    candidate_count=payload.candidate_count,
                    duration_seconds=duration_seconds,
                    execution_mode=payload.execution_mode,
                    model_alias=payload.model_alias,
                    resolution=payload.resolution,
                    allow_unknown_cost=payload.allow_unknown_cost,
                    seed=payload.seed,
                    run_id=run_id,
                    cancel_event=cancellation,
                )
            except VideoGenerationGatewayError as exc:
                raise _fail(exc.status_code, exc.code, str(exc)) from exc

            now = utc_now()
            run = run.model_copy(
                update={
                    "request_payload": queued_run.request_payload,
                    "retry_of_run_id": queued_run.retry_of_run_id,
                    "retry_count": queued_run.retry_count,
                    "created_at": queued_run.created_at,
                    "started_at": queued_run.started_at,
                    "updated_at": now,
                    "last_heartbeat_at": now,
                }
            )
            if cancellation.is_set() or run.error_code == "generation_cancelled":
                cancelled = run.model_copy(
                    update={
                        "status": ProductionRunStatus.CANCELLED,
                        "cancellation_requested": True,
                        "error_code": "generation_cancelled",
                        "error_message": "视频生成任务已取消",
                        "completed_at": now,
                    }
                )
                await self.repository.save_generation_run(cancelled)
                return await self._run_response(cancelled)

            prior_candidate_updates: list[GenerationCandidate] = []
            for prior_run in await self.repository.list_generation_runs(
                project.id,
                plan.id,
            ):
                if prior_run.kind != GenerationKind.VIDEO or prior_run.id == run.id:
                    continue
                for prior_candidate in await self.repository.list_generation_candidates(
                    prior_run.id
                ):
                    if prior_candidate.status in {
                        GenerationCandidateStatus.READY,
                        GenerationCandidateStatus.SELECTED,
                    }:
                        prior_candidate_updates.append(
                            prior_candidate.model_copy(
                                update={"status": GenerationCandidateStatus.ARCHIVED}
                            )
                        )
            revision_id = uuid4()
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "video_status": (
                        WorkflowItemStatus.REVIEW_REQUIRED
                        if candidates
                        else WorkflowItemStatus.FAILED
                    ),
                    "approved_video_candidate_id": None,
                    "updated_at": utc_now(),
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_VIDEOS,
                    "estimated_cost_micros": (
                        project.estimated_cost_micros + run.estimated_cost_micros
                    ),
                    "actual_cost_micros": project.actual_cost_micros + run.actual_cost_micros,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.VIDEO_CANDIDATES_CREATED,
                f"为分镜 {plan.index} 创建 {len(candidates)} 个视频候选",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_runs=[run],
                generation_candidates=[*prior_candidate_updates, *candidates],
            )
        await self._notify_generation_run(run)
        return await self.get_generation_run(run.id)

    async def get_generation_run(self, run_id: UUID) -> GenerationRunResponse:
        run = await self._require_run(run_id)
        await self._require_project(run.project_id)
        return await self._run_response(run)

    async def select_candidate(
        self,
        candidate_id: UUID,
        payload: CandidateSelectRequest,
    ) -> CandidateActionResponse:
        candidate = await self._require_candidate(candidate_id)
        run = await self._require_run(candidate.generation_run_id)
        lock = await self._project_lock(run.project_id)
        async with lock:
            candidate = await self._require_candidate(candidate_id)
            run = await self._require_run(candidate.generation_run_id)
            plan = await self._require_shot(run.shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(run.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if candidate.kind != run.kind:
                raise _fail(409, "candidate_kind_mismatch", "候选类型与生成任务不匹配")
            if run.kind == GenerationKind.IMAGE and _is_simulated_image_run(run):
                raise _fail(
                    409,
                    "simulated_candidate_forbidden",
                    "模拟占位候选不能选择，请使用真实模型生成或直接采用源关键帧",
                )
            if candidate.status in {
                GenerationCandidateStatus.REJECTED,
                GenerationCandidateStatus.ARCHIVED,
            }:
                raise _fail(409, "candidate_unavailable", "该候选已退回或归档")
            target_status = (
                plan.image_status
                if run.kind == GenerationKind.IMAGE
                else plan.video_status
            )
            if target_status == WorkflowItemStatus.STALE:
                raise _fail(409, "candidate_stale", "分镜输入已修改，请重新生成候选")
            shot_runs = [
                item
                for item in await self.repository.list_generation_runs(
                    project.id,
                    plan.id,
                )
                if item.kind == run.kind
            ]
            if not shot_runs or shot_runs[-1].id != run.id:
                raise _fail(409, "candidate_superseded", "该候选已被较新的生成任务替代")

            run_candidates: list[GenerationCandidate] = []
            for shot_run in shot_runs:
                run_candidates.extend(await self.repository.list_generation_candidates(shot_run.id))
            updated_candidates = [
                item.model_copy(
                    update={
                        "status": (
                            GenerationCandidateStatus.SELECTED
                            if item.id == candidate.id
                            else (
                                GenerationCandidateStatus.READY
                                if item.status == GenerationCandidateStatus.SELECTED
                                else item.status
                            )
                        )
                    }
                )
                for item in run_candidates
            ]
            selected = next(item for item in updated_candidates if item.id == candidate.id)
            revision_id = uuid4()
            if run.kind == GenerationKind.IMAGE:
                plan_updates = {
                    "image_status": WorkflowItemStatus.REVIEW_REQUIRED,
                    "approved_image_candidate_id": None,
                }
                change_kind = ProductionChangeKind.IMAGE_CANDIDATE_SELECTED
                summary = f"选择分镜 {plan.index} 的图片候选 {candidate.ordinal}"
            else:
                if project.active_step != ProductionStep.SHOT_VIDEOS:
                    raise _fail(409, "video_stage_not_active", "当前方案不在分段视频阶段")
                plan_updates = {
                    "video_status": WorkflowItemStatus.REVIEW_REQUIRED,
                    "approved_video_candidate_id": None,
                }
                change_kind = ProductionChangeKind.VIDEO_CANDIDATE_SELECTED
                summary = f"选择分镜 {plan.index} 的视频候选 {candidate.ordinal}"
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    **plan_updates,
                    "updated_at": utc_now(),
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(update={"updated_at": utc_now()})
            next_project, revision = await self._prepare_revision(
                next_project,
                change_kind,
                summary,
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=updated_candidates,
            )
        return CandidateActionResponse(
            shot=ShotPlanResponse(
                plan=updated_plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=next_project.current_revision_id,
            ),
            candidate=self._candidate_response(selected),
        )

    async def approve_candidate(
        self,
        candidate_id: UUID,
        payload: CandidateApprovalRequest,
    ) -> CandidateActionResponse:
        candidate = await self._require_candidate(candidate_id)
        run = await self._require_run(candidate.generation_run_id)
        lock = await self._project_lock(run.project_id)
        async with lock:
            candidate = await self._require_candidate(candidate_id)
            run = await self._require_run(candidate.generation_run_id)
            plan = await self._require_shot(run.shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(run.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if candidate.kind != run.kind:
                raise _fail(409, "candidate_kind_mismatch", "候选类型与生成任务不匹配")
            if run.kind == GenerationKind.IMAGE and _is_simulated_image_run(run):
                raise _fail(
                    409,
                    "simulated_candidate_forbidden",
                    "模拟占位候选不能确认，请使用真实模型生成或直接采用源关键帧",
                )
            target_status = (
                plan.image_status
                if run.kind == GenerationKind.IMAGE
                else plan.video_status
            )
            if target_status == WorkflowItemStatus.APPROVED:
                raise _fail(
                    409,
                    (
                        "image_already_approved"
                        if run.kind == GenerationKind.IMAGE
                        else "video_already_approved"
                    ),
                    (
                        "该分镜图片已审批，如需修改请先调整分镜输入"
                        if run.kind == GenerationKind.IMAGE
                        else "该分镜视频已审批，如需修改请先取消采用"
                    ),
                )
            if (
                payload.decision == ApprovalDecision.APPROVED
                and candidate.status != GenerationCandidateStatus.SELECTED
            ):
                raise _fail(409, "candidate_selection_required", "请先选择候选，再执行审批")
            if candidate.status == GenerationCandidateStatus.ARCHIVED:
                raise _fail(409, "candidate_unavailable", "已归档候选不能审批")
            if target_status == WorkflowItemStatus.STALE:
                raise _fail(409, "candidate_stale", "分镜输入已修改，请重新生成候选")
            shot_runs = [
                item
                for item in await self.repository.list_generation_runs(
                    project.id,
                    plan.id,
                )
                if item.kind == run.kind
            ]
            if not shot_runs or shot_runs[-1].id != run.id:
                raise _fail(409, "candidate_superseded", "该候选已被较新的生成任务替代")

            revision_id = uuid4()
            event = ApprovalEvent(
                project_id=project.id,
                revision_id=revision_id,
                shot_plan_id=plan.id,
                candidate_id=candidate.id,
                target_kind=run.kind,
                decision=payload.decision,
                reason=(
                    _simplified_text(
                        payload.reason or "",
                        field_name="退回原因",
                        max_length=1000,
                    )
                    if payload.decision == ApprovalDecision.REJECTED
                    else (
                        _simplified_text(
                            payload.reason,
                            field_name="审批说明",
                            allow_empty=True,
                            max_length=1000,
                        )
                        if payload.reason is not None
                        else None
                    )
                ),
            )
            if payload.decision == ApprovalDecision.APPROVED:
                updated_candidate = candidate
                next_status = WorkflowItemStatus.APPROVED
                approved_candidate_id: UUID | None = candidate.id
                change_kind = (
                    ProductionChangeKind.IMAGE_APPROVED
                    if run.kind == GenerationKind.IMAGE
                    else ProductionChangeKind.VIDEO_APPROVED
                )
                summary = (
                    f"审批通过分镜 {plan.index} 图片"
                    if run.kind == GenerationKind.IMAGE
                    else f"审批通过分镜 {plan.index} 视频"
                )
            else:
                updated_candidate = candidate.model_copy(
                    update={"status": GenerationCandidateStatus.REJECTED}
                )
                other_candidates = [
                    item
                    for item in await self.repository.list_generation_candidates(run.id)
                    if item.id != candidate.id
                    and item.status
                    in {
                        GenerationCandidateStatus.READY,
                        GenerationCandidateStatus.SELECTED,
                    }
                ]
                next_status = (
                    WorkflowItemStatus.REVIEW_REQUIRED
                    if other_candidates
                    else WorkflowItemStatus.READY
                )
                approved_candidate_id = None
                change_kind = (
                    ProductionChangeKind.IMAGE_REJECTED
                    if run.kind == GenerationKind.IMAGE
                    else ProductionChangeKind.VIDEO_REJECTED
                )
                summary = (
                    f"退回分镜 {plan.index} 图片候选"
                    if run.kind == GenerationKind.IMAGE
                    else f"退回分镜 {plan.index} 视频候选"
                )
            if run.kind == GenerationKind.IMAGE:
                plan_updates = {
                    "image_status": next_status,
                    "approved_image_candidate_id": approved_candidate_id,
                }
                active_step = ProductionStep.SHOT_IMAGES
            else:
                if project.active_step != ProductionStep.SHOT_VIDEOS:
                    raise _fail(409, "video_stage_not_active", "当前方案不在分段视频阶段")
                plan_updates = {
                    "video_status": next_status,
                    "approved_video_candidate_id": approved_candidate_id,
                }
                active_step = ProductionStep.SHOT_VIDEOS
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    **plan_updates,
                    "updated_at": utc_now(),
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": active_step,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                change_kind,
                summary,
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=[updated_candidate],
                approval_events=[event],
            )
        return CandidateActionResponse(
            shot=ShotPlanResponse(
                plan=updated_plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=next_project.current_revision_id,
            ),
            candidate=self._candidate_response(updated_candidate),
            approval_event=event,
        )

    async def revoke_image_approval(
        self,
        shot_plan_id: UUID,
        payload: ShotImageApprovalRevokeRequest,
    ) -> CandidateActionResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if plan.image_status != WorkflowItemStatus.APPROVED:
                raise _fail(409, "image_not_approved", "当前分镜图片尚未采用，无需取消")
            if plan.approved_image_candidate_id is None:
                raise _fail(
                    409,
                    "approved_candidate_missing",
                    "当前分镜的已采用图片记录不完整，请重新打开方案后重试",
                )

            candidate = await self._require_candidate(plan.approved_image_candidate_id)
            run = await self._require_run(candidate.generation_run_id)
            if (
                candidate.kind != GenerationKind.IMAGE
                or run.project_id != project.id
                or run.shot_plan_id != plan.id
            ):
                raise _fail(
                    409,
                    "approved_candidate_mismatch",
                    "当前分镜的已采用图片与候选记录不匹配",
                )
            if candidate.status in {
                GenerationCandidateStatus.REJECTED,
                GenerationCandidateStatus.ARCHIVED,
            }:
                raise _fail(
                    409,
                    "approved_candidate_unavailable",
                    "当前已采用图片已归档或退回，无法重新打开审核",
                )

            downstream_result_statuses = {
                WorkflowItemStatus.GENERATING,
                WorkflowItemStatus.REVIEW_REQUIRED,
                WorkflowItemStatus.APPROVED,
                WorkflowItemStatus.STALE,
            }
            downstream_stage_active = project.active_step in {
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            }
            has_downstream_impact = (
                plan.video_status in downstream_result_statuses
                or downstream_stage_active
            )
            if has_downstream_impact and not payload.confirm_downstream_stale:
                raise _fail(
                    409,
                    "downstream_stale_confirmation_required",
                    "取消采用会使该分镜的后续视频或合成结果过期，请确认影响后重试",
                )

            revision_id = uuid4()
            event = ApprovalEvent(
                project_id=project.id,
                revision_id=revision_id,
                shot_plan_id=plan.id,
                candidate_id=candidate.id,
                target_kind=run.kind,
                decision=ApprovalDecision.REVOKED,
                reason=(
                    _simplified_text(
                        payload.reason,
                        field_name="取消采用说明",
                        allow_empty=True,
                        max_length=1000,
                    )
                    if payload.reason is not None
                    else "重新打开图片审核"
                ),
            )
            updated_candidate = (
                candidate
                if candidate.status == GenerationCandidateStatus.SELECTED
                else candidate.model_copy(
                    update={"status": GenerationCandidateStatus.SELECTED}
                )
            )
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "image_status": WorkflowItemStatus.REVIEW_REQUIRED,
                    "video_status": (
                        WorkflowItemStatus.STALE
                        if plan.video_status in downstream_result_statuses
                        else plan.video_status
                    ),
                    "approved_image_candidate_id": None,
                    "updated_at": utc_now(),
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_IMAGES,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.IMAGE_APPROVAL_REVOKED,
                f"取消采用分镜 {plan.index} 图片，重新打开图片审核",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=[updated_candidate],
                approval_events=[event],
            )
        return CandidateActionResponse(
            shot=ShotPlanResponse(
                plan=updated_plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=next_project.current_revision_id,
            ),
            candidate=self._candidate_response(updated_candidate),
            approval_event=event,
        )

    async def revoke_video_approval(
        self,
        shot_plan_id: UUID,
        payload: ShotVideoApprovalRevokeRequest,
    ) -> CandidateActionResponse:
        plan = await self._require_shot(shot_plan_id)
        lock = await self._project_lock(plan.project_id)
        async with lock:
            plan = await self._require_shot(shot_plan_id)
            self._ensure_shot_active(plan)
            project = await self._require_project(plan.project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if plan.video_status != WorkflowItemStatus.APPROVED:
                raise _fail(409, "video_not_approved", "当前分镜视频尚未采用，无需取消")
            if plan.approved_video_candidate_id is None:
                raise _fail(
                    409,
                    "approved_video_candidate_missing",
                    "当前分镜的已采用视频记录不完整，请重新打开方案后重试",
                )
            candidate = await self._require_candidate(plan.approved_video_candidate_id)
            run = await self._require_run(candidate.generation_run_id)
            if (
                candidate.kind != GenerationKind.VIDEO
                or run.kind != GenerationKind.VIDEO
                or run.project_id != project.id
                or run.shot_plan_id != plan.id
            ):
                raise _fail(
                    409,
                    "approved_video_candidate_mismatch",
                    "当前分镜的已采用视频与候选记录不匹配",
                )
            if candidate.status in {
                GenerationCandidateStatus.REJECTED,
                GenerationCandidateStatus.ARCHIVED,
            }:
                raise _fail(
                    409,
                    "approved_video_candidate_unavailable",
                    "当前已采用视频已归档或退回，无法重新打开审核",
                )
            has_downstream_impact = project.active_step in {
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            }
            if has_downstream_impact and not payload.confirm_downstream_stale:
                raise _fail(
                    409,
                    "downstream_stale_confirmation_required",
                    "取消采用会使剪辑或导出结果过期，请确认影响后重试",
                )

            revision_id = uuid4()
            event = ApprovalEvent(
                project_id=project.id,
                revision_id=revision_id,
                shot_plan_id=plan.id,
                candidate_id=candidate.id,
                target_kind=GenerationKind.VIDEO,
                decision=ApprovalDecision.REVOKED,
                reason=(
                    _simplified_text(
                        payload.reason,
                        field_name="取消采用说明",
                        allow_empty=True,
                        max_length=1000,
                    )
                    if payload.reason is not None
                    else "重新打开视频审核"
                ),
            )
            updated_candidate = (
                candidate
                if candidate.status == GenerationCandidateStatus.SELECTED
                else candidate.model_copy(
                    update={"status": GenerationCandidateStatus.SELECTED}
                )
            )
            updated_plan = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "video_status": WorkflowItemStatus.REVIEW_REQUIRED,
                    "approved_video_candidate_id": None,
                    "updated_at": utc_now(),
                }
            )
            plans = await self.repository.list_shot_plans(project.id)
            next_plans = [updated_plan if item.id == plan.id else item for item in plans]
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": ProductionStep.SHOT_VIDEOS,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.VIDEO_APPROVAL_REVOKED,
                f"取消采用分镜 {plan.index} 视频，重新打开视频审核",
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=[updated_plan],
                generation_candidates=[updated_candidate],
                approval_events=[event],
            )
        return CandidateActionResponse(
            shot=ShotPlanResponse(
                plan=updated_plan,
                reference_bindings=await self.repository.list_reference_bindings(plan.id),
                current_revision_id=next_project.current_revision_id,
            ),
            candidate=self._candidate_response(updated_candidate),
            approval_event=event,
        )

    async def resolve_candidate_content(
        self,
        candidate_id: UUID,
        *,
        thumbnail: bool = False,
    ) -> tuple[Path, str]:
        candidate = await self._require_candidate(candidate_id)
        run = await self._require_run(candidate.generation_run_id)
        plan = await self._require_shot(run.shot_plan_id)
        project = await self._require_project(run.project_id)
        relative_path = candidate.thumbnail_relative_path if thumbnail else candidate.relative_path
        if relative_path is None:
            raise _fail(404, "candidate_thumbnail_missing", "候选缩略图不存在")
        try:
            resolved = self.workspace.resolve(relative_path).resolve()
        except WorkspaceError as exc:
            raise _fail(409, "invalid_candidate_path", "候选文件路径无效") from exc
        root = (
            self.workspace.production_shot_root(
                project.record_id,
                project.id,
                plan.id,
            )
            / ("images" if candidate.kind == GenerationKind.IMAGE else "videos")
            / str(run.id)
        ).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise _fail(409, "invalid_candidate_path", "候选文件路径无效") from exc
        filesystem_path = _filesystem_path(resolved)
        if not filesystem_path.is_file():
            raise _fail(404, "candidate_file_missing", "候选文件不存在")
        if thumbnail:
            return filesystem_path, "image/webp"
        return filesystem_path, (
            "image/jpeg"
            if candidate.kind == GenerationKind.IMAGE
            else "video/mp4"
        )

    async def _has_valid_approved_image_output(
        self,
        project: ProductionProject,
        plan: ShotPlan,
    ) -> bool:
        candidate_id = plan.approved_image_candidate_id
        if plan.image_status != WorkflowItemStatus.APPROVED or candidate_id is None:
            return False
        candidate = await self.repository.get_generation_candidate(candidate_id)
        if (
            candidate is None
            or candidate.kind != GenerationKind.IMAGE
            or candidate.status != GenerationCandidateStatus.SELECTED
        ):
            return False
        run = await self.repository.get_generation_run(candidate.generation_run_id)
        return bool(
            run is not None
            and run.project_id == project.id
            and run.shot_plan_id == plan.id
            and run.kind == GenerationKind.IMAGE
            and run.status in {ProductionRunStatus.COMPLETED, ProductionRunStatus.CACHED}
            and not _is_simulated_image_run(run)
        )

    async def _has_valid_approved_video_output(
        self,
        project: ProductionProject,
        plan: ShotPlan,
    ) -> bool:
        candidate_id = plan.approved_video_candidate_id
        if plan.video_status != WorkflowItemStatus.APPROVED or candidate_id is None:
            return False
        candidate = await self.repository.get_generation_candidate(candidate_id)
        if (
            candidate is None
            or candidate.kind != GenerationKind.VIDEO
            or candidate.status != GenerationCandidateStatus.SELECTED
        ):
            return False
        run = await self.repository.get_generation_run(candidate.generation_run_id)
        if not (
            run is not None
            and run.project_id == project.id
            and run.shot_plan_id == plan.id
            and run.kind == GenerationKind.VIDEO
            and run.status in {ProductionRunStatus.COMPLETED, ProductionRunStatus.CACHED}
        ):
            return False
        try:
            await self.resolve_candidate_content(candidate.id)
        except ProductionServiceError:
            return False
        return True

    async def gate_status(self, project_id: UUID) -> ProductionGateStatus:
        project = await self._require_project(project_id)
        project, plans = await self._ensure_project_shots(project)
        required = [
            item for item in plans
            if item.lifecycle_status == ShotLifecycleStatus.ACTIVE and item.required
        ]
        video_stage = project.active_step in {
            ProductionStep.SHOT_VIDEOS,
            ProductionStep.EDITING,
            ProductionStep.EXPORT,
        }
        if video_stage:
            approved = [
                item
                for item in required
                if await self._has_valid_approved_video_output(project, item)
            ]
            stale = [
                item for item in required
                if item.video_status == WorkflowItemStatus.STALE
            ]
            next_step = (
                ProductionStep.EDITING
                if project.active_step == ProductionStep.SHOT_VIDEOS
                else None
            )
            pending_label = "必需分镜视频"
        else:
            approved = [
                item
                for item in required
                if await self._has_valid_approved_image_output(project, item)
            ]
            stale = [
                item for item in required
                if item.image_status == WorkflowItemStatus.STALE
            ]
            next_step = ProductionStep.SHOT_VIDEOS
            pending_label = "必需分镜图片"
        blockers: list[str] = []
        if not required:
            blockers.append("创作方案没有必需分镜")
        pending = len(required) - len(approved)
        if pending:
            blockers.append(f"仍有 {pending} 个{pending_label}未审批")
        if stale:
            blockers.append(f"有 {len(stale)} 个分镜结果已过期")
        return ProductionGateStatus(
            project_id=project.id,
            current_step=project.active_step,
            next_step=next_step,
            allowed=bool(required) and not blockers,
            required_shot_count=len(required),
            approved_shot_count=len(approved),
            stale_shot_count=len(stale),
            blocker_messages=blockers,
        )

    async def advance(
        self,
        project_id: UUID,
        payload: ProductionAdvanceRequest,
    ) -> ProductionProjectDetail:
        initial_project = await self._require_project(project_id)
        await self._ensure_project_shots(initial_project)
        lock = await self._project_lock(project_id)
        async with lock:
            project = await self._require_project(project_id)
            self._require_expected_revision(project, payload.expected_revision_id)
            if project.active_step == payload.target_step:
                label = (
                    "分段视频"
                    if payload.target_step == ProductionStep.SHOT_VIDEOS
                    else "剪辑合成"
                )
                raise _fail(409, "workflow_already_advanced", f"当前方案已进入{label}阶段")
            expected_target = (
                ProductionStep.EDITING
                if project.active_step == ProductionStep.SHOT_VIDEOS
                else ProductionStep.SHOT_VIDEOS
            )
            if payload.target_step != expected_target:
                raise _fail(
                    409,
                    "unsupported_target_step",
                    f"当前阶段只能推进到 {expected_target.value}",
                )
            gate = await self.gate_status(project.id)
            if not gate.allowed:
                raise _fail(
                    409,
                    "workflow_gate_blocked",
                    "；".join(gate.blocker_messages) or "当前步骤尚未满足推进条件",
                )
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": payload.target_step,
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.WORKFLOW_ADVANCED,
                (
                    "所有必需分镜视频已审批，推进到剪辑合成"
                    if payload.target_step == ProductionStep.EDITING
                    else "所有必需分镜图片已审批，推进到分段视频"
                ),
            )
            await self.repository.save_production_bundle(next_project, revision)
        return await self.get_project(project_id)

    def _initial_shot_plans(
        self,
        project: ProductionProject,
        report: AnalysisReport,
        revision_id: UUID,
    ) -> list[ShotPlan]:
        prompt_shots = {item.shot_id: item for item in report.prompt_package.shots}
        plans: list[ShotPlan] = []
        for shot in sorted(report.shots, key=lambda item: item.index):
            prompt_shot = prompt_shots.get(shot.id)
            duration = max(0.01, shot.end_seconds - shot.start_seconds)
            keyframe_url = (
                shot.keyframe_url
                or next(iter(shot.evidence_frame_urls), None)
                or (
                    f"/api/v1/analyses/{report.analysis_id}/artifacts/"
                    f"shots/shot_{shot.index:03d}.jpg"
                )
            )
            image_prompt = prompt_shot.prompt if prompt_shot is not None else shot.prompt
            negative_constraints = (
                prompt_shot.negative_constraints
                if prompt_shot is not None
                else report.prompt_package.negative_constraints
            )
            video_prompt = (
                f"{shot.prompt}；动作过程：{shot.action}；"
                f"运镜：{shot.camera}；持续 {duration:.2f} 秒。"
            )
            plans.append(
                ShotPlan(
                    project_id=project.id,
                    revision_id=revision_id,
                    source_shot_id=shot.id,
                    index=shot.index,
                    source_keyframe_url=keyframe_url,
                    source_keyframe_timestamp_seconds=round(
                        shot.start_seconds + duration / 2,
                        3,
                    ),
                    source_keyframe_origin="analysis",
                    start_seconds=shot.start_seconds,
                    end_seconds=shot.end_seconds,
                    duration_seconds=duration,
                    image_prompt=_simplified_text(
                        image_prompt,
                        field_name="图片提示词",
                        allow_empty=True,
                        max_length=8000,
                    ),
                    image_negative_constraints=[
                        _simplified_text(
                            item,
                            field_name="图片负面约束",
                            max_length=500,
                        )
                        for item in negative_constraints
                    ],
                    video_prompt=_simplified_text(
                        video_prompt,
                        field_name="视频提示词",
                        allow_empty=True,
                        max_length=8000,
                    ),
                    video_negative_constraints=[
                        _simplified_text(
                            item,
                            field_name="视频负面约束",
                            max_length=500,
                        )
                        for item in report.prompt_package.negative_constraints
                    ],
                    image_status=(
                        WorkflowItemStatus.READY
                        if image_prompt.strip()
                        else WorkflowItemStatus.DRAFT
                    ),
                )
            )
        return plans

    async def _ensure_project_shots(
        self,
        project: ProductionProject,
    ) -> tuple[ProductionProject, list[ShotPlan]]:
        plans = await self.repository.list_shot_plans(project.id)
        if plans:
            current_project = await self._require_project(project.id)
            return await self._repair_legacy_simulated_outputs(
                current_project,
                plans,
            )
        lock = await self._project_lock(project.id)
        async with lock:
            project = await self._require_project(project.id)
            plans = await self.repository.list_shot_plans(project.id)
            if plans:
                return project, plans
            report = await self.repository.get_report_by_analysis(project.base_analysis_id)
            if report is None or report.video_id != project.video_id:
                raise _fail(409, "analysis_report_missing", "创作方案的基础分析报告不存在")
            revision_id = uuid4()
            plans = self._initial_shot_plans(project, report, revision_id)
            project, revision = await self._prepare_revision(
                project,
                ProductionChangeKind.SHOT_PLAN_CHANGED,
                "为早期创作方案补充分镜创作计划",
                revision_id=revision_id,
                report=report,
                shot_plans=plans,
            )
            await self.repository.save_production_bundle(
                project,
                revision,
                shot_plans=plans,
            )
        return await self._repair_legacy_simulated_outputs(project, plans)

    async def _legacy_simulation_repair_needed(
        self,
        plans: list[ShotPlan],
    ) -> bool:
        for plan in plans:
            for run in await self.repository.list_generation_runs(
                plan.project_id,
                plan.id,
            ):
                if not _is_simulated_image_run(run):
                    continue
                for candidate in await self.repository.list_generation_candidates(run.id):
                    if (
                        candidate.status != GenerationCandidateStatus.ARCHIVED
                        or candidate.id == plan.approved_image_candidate_id
                    ):
                        return True
        return False

    async def _repair_legacy_simulated_outputs(
        self,
        project: ProductionProject,
        plans: list[ShotPlan],
    ) -> tuple[ProductionProject, list[ShotPlan]]:
        if not await self._legacy_simulation_repair_needed(plans):
            return project, plans

        lock = await self._project_lock(project.id)
        async with lock:
            project = await self._require_project(project.id)
            plans = await self.repository.list_shot_plans(project.id)
            if not await self._legacy_simulation_repair_needed(plans):
                return project, plans

            revision_id = uuid4()
            candidate_updates: list[GenerationCandidate] = []
            simulated_candidate_ids: dict[UUID, set[UUID]] = {}
            had_reviewable_simulated: set[UUID] = set()
            eligible_active_candidates: set[UUID] = set()

            for plan in plans:
                simulated_ids = simulated_candidate_ids.setdefault(plan.id, set())
                for run in await self.repository.list_generation_runs(
                    project.id,
                    plan.id,
                ):
                    candidates = await self.repository.list_generation_candidates(run.id)
                    if _is_simulated_image_run(run):
                        for candidate in candidates:
                            simulated_ids.add(candidate.id)
                            if candidate.status in {
                                GenerationCandidateStatus.READY,
                                GenerationCandidateStatus.SELECTED,
                            }:
                                had_reviewable_simulated.add(plan.id)
                            if candidate.status != GenerationCandidateStatus.ARCHIVED:
                                candidate_updates.append(
                                    candidate.model_copy(
                                        update={
                                            "status": GenerationCandidateStatus.ARCHIVED,
                                        }
                                    )
                                )
                    else:
                        eligible_active_candidates.update(
                            candidate.id
                            for candidate in candidates
                            if candidate.status in {
                                GenerationCandidateStatus.READY,
                                GenerationCandidateStatus.SELECTED,
                            }
                        )

            changed_plans: list[ShotPlan] = []
            next_plans: list[ShotPlan] = []
            for plan in plans:
                invalid_approval = (
                    plan.approved_image_candidate_id
                    in simulated_candidate_ids.get(plan.id, set())
                )
                simulated_review_state = (
                    plan.id in had_reviewable_simulated
                    and plan.image_status
                    in {
                        WorkflowItemStatus.GENERATING,
                        WorkflowItemStatus.REVIEW_REQUIRED,
                        WorkflowItemStatus.APPROVED,
                        WorkflowItemStatus.STALE,
                    }
                    and (
                        plan.approved_image_candidate_id is None
                        or invalid_approval
                    )
                )
                if not invalid_approval and not simulated_review_state:
                    next_plans.append(plan)
                    continue

                has_eligible_candidate = any(
                    candidate_id in eligible_active_candidates
                    for candidate_id in (
                        await self._candidate_ids_for_plan(project.id, plan.id)
                    )
                )
                image_status = (
                    WorkflowItemStatus.REVIEW_REQUIRED
                    if has_eligible_candidate
                    else (
                        WorkflowItemStatus.READY
                        if plan.image_prompt.strip()
                        else WorkflowItemStatus.DRAFT
                    )
                )
                video_status = (
                    WorkflowItemStatus.STALE
                    if plan.video_status
                    in {
                        WorkflowItemStatus.REVIEW_REQUIRED,
                        WorkflowItemStatus.APPROVED,
                        WorkflowItemStatus.STALE,
                    }
                    else plan.video_status
                )
                updated_plan = plan.model_copy(
                    update={
                        "revision_id": revision_id,
                        "image_status": image_status,
                        "video_status": video_status,
                        "approved_image_candidate_id": None,
                        "updated_at": utc_now(),
                    }
                )
                changed_plans.append(updated_plan)
                next_plans.append(updated_plan)

            rollback_steps = {
                ProductionStep.SHOT_VIDEOS,
                ProductionStep.EDITING,
                ProductionStep.EXPORT,
            }
            next_project = project.model_copy(
                update={
                    "status": ProductionProjectStatus.ACTIVE,
                    "active_step": (
                        ProductionStep.SHOT_IMAGES
                        if changed_plans and project.active_step in rollback_steps
                        else project.active_step
                    ),
                    "updated_at": utc_now(),
                }
            )
            next_project, revision = await self._prepare_revision(
                next_project,
                ProductionChangeKind.SHOT_PLAN_CHANGED,
                (
                    f"归档 {len(candidate_updates)} 个历史模拟图片候选，"
                    f"重置 {len(changed_plans)} 个错误确认的分镜"
                ),
                revision_id=revision_id,
                shot_plans=next_plans,
            )
            await self.repository.save_production_bundle(
                next_project,
                revision,
                shot_plans=changed_plans,
                generation_candidates=candidate_updates,
            )
        return next_project, next_plans

    async def _candidate_ids_for_plan(
        self,
        project_id: UUID,
        shot_plan_id: UUID,
    ) -> set[UUID]:
        candidate_ids: set[UUID] = set()
        for run in await self.repository.list_generation_runs(project_id, shot_plan_id):
            if _is_simulated_image_run(run):
                continue
            candidate_ids.update(
                candidate.id
                for candidate in await self.repository.list_generation_candidates(run.id)
                if candidate.status in {
                    GenerationCandidateStatus.READY,
                    GenerationCandidateStatus.SELECTED,
                }
            )
        return candidate_ids

    @staticmethod
    def _resequence_plans(
        active: list[ShotPlan],
        discarded: list[ShotPlan],
        revision_id: UUID,
        *,
        force_ids: set[UUID] | None = None,
    ) -> tuple[list[ShotPlan], list[ShotPlan]]:
        forced = force_ids or set()
        ordered = [*active, *sorted(discarded, key=lambda item: item.index)]
        next_plans: list[ShotPlan] = []
        changed: list[ShotPlan] = []
        now = utc_now()
        for next_index, plan in enumerate(ordered, start=1):
            if plan.index != next_index or plan.id in forced:
                plan = plan.model_copy(
                    update={
                        "index": next_index,
                        "revision_id": revision_id,
                        "updated_at": now,
                    }
                )
                changed.append(plan)
            next_plans.append(plan)
        return next_plans, changed

    @staticmethod
    def _image_fields_changed(payload: ShotPlanFieldsUpdate) -> bool:
        return bool(
            payload.model_fields_set
            & {
                "image_prompt",
                "image_prompt_mentions",
                "image_negative_constraints",
                "locks",
                "reference_bindings",
            }
        )

    @staticmethod
    def _video_fields_changed(payload: ShotPlanFieldsUpdate) -> bool:
        return bool(
            payload.model_fields_set
            & {
                "video_prompt",
                "video_negative_constraints",
                "locks",
            }
        )

    @staticmethod
    def _mark_plans_stale(
        plans: list[ShotPlan],
        impacted_ids: set[UUID],
        revision_id: UUID,
    ) -> tuple[list[ShotPlan], list[ShotPlan]]:
        next_plans: list[ShotPlan] = []
        changed: list[ShotPlan] = []
        for plan in plans:
            if plan.id not in impacted_ids:
                next_plans.append(plan)
                continue
            image_status = (
                WorkflowItemStatus.STALE
                if plan.image_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                    WorkflowItemStatus.STALE,
                }
                or plan.approved_image_candidate_id is not None
                else plan.image_status
            )
            video_status = (
                WorkflowItemStatus.STALE
                if plan.video_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                    WorkflowItemStatus.STALE,
                }
                else plan.video_status
            )
            updated = plan.model_copy(
                update={
                    "revision_id": revision_id,
                    "image_status": image_status,
                    "video_status": video_status,
                    "updated_at": utc_now(),
                }
            )
            next_plans.append(updated)
            changed.append(updated)
        return next_plans, changed

    def _apply_shot_fields(
        self,
        plan: ShotPlan,
        payload: ShotPlanFieldsUpdate,
        fields: set[str],
        revision_id: UUID,
        *,
        image_changed: bool,
        video_changed: bool,
    ) -> ShotPlan:
        updates: dict[str, object] = {
            "revision_id": revision_id,
            "updated_at": utc_now(),
        }
        for field_name, label, max_length in (
            ("image_prompt", "图片提示词", 8000),
            ("video_prompt", "视频提示词", 8000),
        ):
            if field_name in fields:
                value = getattr(payload, field_name)
                if value is None:
                    raise _fail(422, "invalid_shot_plan", f"{label}不能为 null")
                updates[field_name] = _simplified_text(
                    value,
                    field_name=label,
                    allow_empty=True,
                    max_length=max_length,
                )
        if "image_prompt_mentions" in fields:
            if payload.image_prompt_mentions is None:
                raise _fail(422, "invalid_shot_plan", "提示词资产关联不能为 null")
            updates["image_prompt_mentions"] = payload.image_prompt_mentions
        for field_name, label in (
            ("image_negative_constraints", "图片负面约束"),
            ("video_negative_constraints", "视频负面约束"),
        ):
            if field_name in fields:
                values = getattr(payload, field_name)
                if values is None:
                    raise _fail(422, "invalid_shot_plan", f"{label}不能为 null")
                updates[field_name] = [
                    _simplified_text(
                        value,
                        field_name=label,
                        max_length=500,
                    )
                    for value in values
                ]
        if "locks" in fields:
            if payload.locks is None:
                raise _fail(422, "invalid_shot_plan", "锁定项不能为 null")
            updates["locks"] = payload.locks
        if "required" in fields:
            if payload.required is None:
                raise _fail(422, "invalid_shot_plan", "必需分镜不能为 null")
            updates["required"] = payload.required

        next_image_prompt = str(updates.get("image_prompt", plan.image_prompt))
        if image_changed:
            has_prior_result = (
                plan.approved_image_candidate_id is not None
                or plan.image_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.STALE,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                }
            )
            updates["image_status"] = (
                WorkflowItemStatus.STALE
                if has_prior_result
                else (
                    WorkflowItemStatus.READY
                    if next_image_prompt.strip()
                    else WorkflowItemStatus.DRAFT
                )
            )
            if not has_prior_result:
                updates["approved_image_candidate_id"] = None
            updates["video_status"] = (
                WorkflowItemStatus.STALE
                if plan.video_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                    WorkflowItemStatus.STALE,
                }
                else WorkflowItemStatus.DRAFT
            )
        elif video_changed:
            next_video_prompt = str(updates.get("video_prompt", plan.video_prompt))
            has_prior_result = (
                plan.approved_video_candidate_id is not None
                or plan.video_status
                in {
                    WorkflowItemStatus.APPROVED,
                    WorkflowItemStatus.REVIEW_REQUIRED,
                    WorkflowItemStatus.STALE,
                }
            )
            updates["video_status"] = (
                WorkflowItemStatus.STALE
                if has_prior_result
                else (
                    WorkflowItemStatus.READY
                    if next_video_prompt.strip()
                    else WorkflowItemStatus.DRAFT
                )
            )
            if not has_prior_result:
                updates["approved_video_candidate_id"] = None
        return ShotPlan.model_validate({**plan.model_dump(mode="python"), **updates})

    async def _validate_prompt_mentions(
        self,
        project: ProductionProject,
        mentions: list[PromptAssetMention],
    ) -> list[PromptAssetMention]:
        assets = {
            item.id: item
            for item in await self._list_reference_assets(project.id)
        }
        normalized: list[PromptAssetMention] = []
        for mention in mentions:
            asset = assets.get(mention.reference_asset_id)
            if asset is None or asset.archived_at is not None:
                raise _fail(
                    422,
                    "prompt_reference_not_found",
                    "提示词关联的参考资产不存在或已归档",
                )
            if not asset.rights_confirmed:
                raise _fail(
                    422,
                    "reference_rights_required",
                    "提示词关联的参考资产尚未完成权利确认",
                )
            normalized.append(
                PromptAssetMention(
                    reference_asset_id=asset.id,
                    label=_simplified_text(
                        mention.label,
                        field_name="提示词资产名称",
                        max_length=120,
                    ),
                )
            )
        return normalized

    async def _append_mention_bindings(
        self,
        project: ProductionProject,
        inputs: list[ReferenceBindingInput],
        mentions: list[PromptAssetMention],
    ) -> list[ReferenceBindingInput]:
        assets = {
            item.id: item
            for item in await self._list_reference_assets(project.id)
        }
        existing_ids = {item.reference_asset_id for item in inputs}
        merged = list(inputs)
        for mention in mentions:
            if mention.reference_asset_id in existing_ids:
                continue
            asset = assets.get(mention.reference_asset_id)
            if asset is None or asset.archived_at is not None:
                raise _fail(
                    422,
                    "prompt_reference_not_found",
                    "提示词关联的参考资产不存在或已归档",
                )
            merged.append(
                ReferenceBindingInput(
                    reference_asset_id=asset.id,
                    role=_DEFAULT_ROLE_BY_REFERENCE_TYPE[asset.type],
                    weight=1,
                    notes=f"由提示词 @{mention.label} 自动关联",
                )
            )
            existing_ids.add(asset.id)
        return merged

    async def _build_bindings(
        self,
        project: ProductionProject,
        plan: ShotPlan,
        inputs: list[ReferenceBindingInput],
    ) -> list[ReferenceBinding]:
        assets = {item.id: item for item in await self._list_reference_assets(project.id)}
        bindings: list[ReferenceBinding] = []
        for item in inputs:
            asset = assets.get(item.reference_asset_id)
            if asset is None or asset.archived_at is not None:
                raise _fail(422, "reference_asset_not_found", "绑定的参考资产不存在或已归档")
            if not asset.rights_confirmed:
                raise _fail(422, "reference_rights_required", "绑定的参考资产尚未完成权利确认")
            bindings.append(
                ReferenceBinding(
                    shot_plan_id=plan.id,
                    reference_asset_id=asset.id,
                    role=item.role,
                    weight=item.weight,
                    crop_hint=(
                        _simplified_text(
                            item.crop_hint,
                            field_name="裁剪提示",
                            allow_empty=True,
                            max_length=200,
                        )
                        if item.crop_hint is not None
                        else None
                    ),
                    notes=(
                        _simplified_text(
                            item.notes,
                            field_name="绑定说明",
                            allow_empty=True,
                            max_length=500,
                        )
                        if item.notes is not None
                        else None
                    ),
                )
            )
        return bindings

    async def _all_bindings(
        self,
        plans: list[ShotPlan],
    ) -> list[ReferenceBinding]:
        bindings: list[ReferenceBinding] = []
        for plan in plans:
            bindings.extend(await self.repository.list_reference_bindings(plan.id))
        return bindings

    async def _run_response(self, run: GenerationRun) -> GenerationRunResponse:
        candidates = await self.repository.list_generation_candidates(run.id)
        provider_tasks = (
            await self.repository.list_video_provider_tasks(run.id)
            if run.kind == GenerationKind.VIDEO
            else []
        )
        return GenerationRunResponse(
            id=run.id,
            project_id=run.project_id,
            shot_plan_id=run.shot_plan_id,
            revision_id=run.revision_id,
            kind=run.kind,
            input_mode=run.input_mode,
            provider=run.provider,
            model=run.model,
            model_snapshot=run.model_snapshot,
            model_alias=run.model_alias,
            model_display_name=run.model_display_name,
            execution_mode=run.execution_mode,
            adapter_id=run.adapter_id,
            adapter_version=run.adapter_version,
            protocol_version=run.protocol_version,
            provider_request_id=run.provider_request_id,
            capability_snapshot=run.capability_snapshot,
            cost_source=run.cost_source,
            cost_estimate_known=run.cost_estimate_known,
            actual_cost_known=run.actual_cost_known,
            cost_currency=run.cost_currency,
            pricing_snapshot=run.pricing_snapshot,
            usage=run.usage,
            status=run.status,
            estimated_cost_micros=run.estimated_cost_micros,
            actual_cost_micros=run.actual_cost_micros,
            latency_ms=run.latency_ms,
            retry_count=run.retry_count,
            retry_of_run_id=run.retry_of_run_id,
            cancellation_requested=run.cancellation_requested,
            error_code=run.error_code,
            error_message=run.error_message,
            created_at=run.created_at,
            started_at=run.started_at,
            updated_at=run.updated_at,
            last_heartbeat_at=run.last_heartbeat_at,
            completed_at=run.completed_at,
            candidates=[self._candidate_response(item) for item in candidates],
            provider_tasks=[
                VideoProviderTaskResponse.model_validate(
                    item.model_dump(
                        include={
                            "id",
                            "generation_run_id",
                            "ordinal",
                            "provider",
                            "model_alias",
                            "provider_model",
                            "provider_task_id",
                            "status",
                            "estimated_cost_micros",
                            "actual_cost_micros",
                            "cost_known",
                            "error_code",
                            "error_message",
                            "retryable",
                            "submitted_at",
                            "last_polled_at",
                            "completed_at",
                        }
                    )
                )
                for item in provider_tasks
            ],
        )

    @staticmethod
    def _candidate_response(
        candidate: GenerationCandidate,
    ) -> GenerationCandidateResponse:
        return GenerationCandidateResponse(
            id=candidate.id,
            generation_run_id=candidate.generation_run_id,
            ordinal=candidate.ordinal,
            kind=candidate.kind,
            width=candidate.width,
            height=candidate.height,
            duration_seconds=candidate.duration_seconds,
            sha256=candidate.sha256,
            quality_report=candidate.quality_report,
            status=candidate.status,
            content_url=f"/api/v1/generation-candidates/{candidate.id}/content",
            thumbnail_url=f"/api/v1/generation-candidates/{candidate.id}/thumbnail",
            created_at=candidate.created_at,
        )

    def _resolve_video_file(self, video: Video) -> Path:
        if video.stored_relative_path:
            try:
                relative_candidate = self.workspace.resolve(video.stored_relative_path)
            except WorkspaceError:
                relative_candidate = None
            if relative_candidate is not None:
                filesystem_candidate = _filesystem_path(relative_candidate)
                if filesystem_candidate.is_file():
                    return filesystem_candidate
        if video.stored_path:
            filesystem_candidate = _filesystem_path(Path(video.stored_path).resolve())
            if filesystem_candidate.is_file():
                return filesystem_candidate
        raise _fail(404, "source_video_file_missing", "源视频文件不存在，请重新采集或上传")

    @staticmethod
    def _validate_keyframe_file(path: Path) -> None:
        filesystem_path = _filesystem_path(path)
        try:
            with Image.open(filesystem_path) as source:
                source.verify()
            with Image.open(filesystem_path) as source:
                width, height = ImageOps.exif_transpose(source).size
        except OSError as exc:
            raise _fail(422, "keyframe_image_invalid", "提取出的关键帧文件无效") from exc
        if (
            width <= 0
            or height <= 0
            or width > MAX_REFERENCE_IMAGE_DIMENSION
            or height > MAX_REFERENCE_IMAGE_DIMENSION
            or width * height > MAX_REFERENCE_IMAGE_PIXELS
        ):
            raise _fail(422, "keyframe_dimensions_invalid", "提取出的关键帧尺寸无效")

    async def _archive_active_candidates(
        self,
        project: ProductionProject,
        plan: ShotPlan,
    ) -> list[GenerationCandidate]:
        archived: list[GenerationCandidate] = []
        for run in await self.repository.list_generation_runs(project.id, plan.id):
            for candidate in await self.repository.list_generation_candidates(run.id):
                if candidate.status in {
                    GenerationCandidateStatus.READY,
                    GenerationCandidateStatus.SELECTED,
                }:
                    archived.append(
                        candidate.model_copy(
                            update={"status": GenerationCandidateStatus.ARCHIVED}
                        )
                    )
        return archived

    def _create_source_frame_candidate(
        self,
        project: ProductionProject,
        plan: ShotPlan,
        revision_id: UUID,
        source_path: Path,
    ) -> tuple[GenerationRun, GenerationCandidate]:
        started = datetime.now(UTC)
        source_payload = _filesystem_path(source_path).read_bytes()
        source_sha256 = hashlib.sha256(source_payload).hexdigest()
        try:
            with Image.open(BytesIO(source_payload)) as source:
                rendered = ImageOps.exif_transpose(source).convert("RGB")
        except OSError as exc:
            raise _fail(422, "source_keyframe_invalid", "当前分镜关键帧文件无效") from exc

        run_id = uuid4()
        run_root = (
            self.workspace.production_shot_root(
                project.record_id,
                project.id,
                plan.id,
            )
            / "images"
            / str(run_id)
        )
        candidate_output = BytesIO()
        rendered.save(candidate_output, format="JPEG", quality=94, optimize=True)
        candidate_payload = candidate_output.getvalue()
        thumbnail = rendered.copy()
        thumbnail.thumbnail((640, 640), Image.Resampling.LANCZOS)
        thumbnail_output = BytesIO()
        thumbnail.save(thumbnail_output, format="WEBP", quality=84, method=4)

        candidate_path = run_root / "source-frame.jpg"
        thumbnail_path = run_root / "source-frame.webp"
        metadata_path = run_root / "source-frame.json"
        input_path = run_root / "input.json"
        manifest_path = run_root / "manifest.json"
        candidate_sha256 = hashlib.sha256(candidate_payload).hexdigest()
        input_payload = {
            "schema_version": "viral-dna-source-frame/v1",
            "project_id": str(project.id),
            "shot_plan_id": str(plan.id),
            "revision_id": str(revision_id),
            "input_mode": ImageGenerationInputMode.KEYFRAME_EDIT.value,
            "source": {
                "relative_url": plan.source_keyframe_url,
                "relative_path": plan.source_keyframe_relative_path,
                "timestamp_seconds": plan.source_keyframe_timestamp_seconds,
                "sha256": source_sha256,
            },
            "execution": {
                "mode": ImageExecutionMode.SOURCE_FRAME.value,
                "model_call": False,
            },
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                input_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        quality_report = {
            "schema_version": "viral-dna-image-quality/v1",
            "status": "manual_review_required",
            "summary": "已直接使用源视频关键帧，未调用生成模型；请人工核对画面内容。",
            "automated_checks": {
                "file_integrity": {"status": "passed", "decoded": True},
                "dimensions": {
                    "status": "passed",
                    "actual_width": rendered.width,
                    "actual_height": rendered.height,
                },
            },
            "manual_checks": [
                {
                    "id": "source_frame_review",
                    "label": "源视频关键帧画面",
                    "status": "required",
                }
            ],
        }
        candidate = GenerationCandidate(
            generation_run_id=run_id,
            ordinal=1,
            kind=GenerationKind.IMAGE,
            relative_path=self.workspace.relative(candidate_path),
            thumbnail_relative_path=self.workspace.relative(thumbnail_path),
            width=rendered.width,
            height=rendered.height,
            sha256=candidate_sha256,
            metadata_relative_path=self.workspace.relative(metadata_path),
            quality_report=quality_report,
            status=GenerationCandidateStatus.SELECTED,
        )
        metadata = {
            "schema_version": "viral-dna-generation-candidate/v1",
            "source_frame": True,
            "candidate_id": str(candidate.id),
            "request_fingerprint": fingerprint,
            "source_sha256": source_sha256,
            "sha256": candidate_sha256,
            "width": rendered.width,
            "height": rendered.height,
            "quality_report": quality_report,
        }
        manifest = {
            "schema_version": "viral-dna-image-generation-result/v1",
            "status": "completed",
            "request_id": str(run_id),
            "source_frame": True,
            "candidate_ids": [str(candidate.id)],
            "candidate_sha256": [candidate.sha256],
            "estimated_cost_micros": 0,
            "actual_cost_micros": 0,
            "cost_source": GenerationCostSource.UNMETERED.value,
        }
        self._write_atomic(candidate_path, candidate_payload)
        self._write_atomic(thumbnail_path, thumbnail_output.getvalue())
        self._write_json_atomic(metadata_path, metadata)
        self._write_json_atomic(input_path, input_payload)
        self._write_json_atomic(manifest_path, manifest)
        completed_at = datetime.now(UTC)
        run = GenerationRun(
            id=run_id,
            project_id=project.id,
            shot_plan_id=plan.id,
            revision_id=revision_id,
            kind=GenerationKind.IMAGE,
            input_mode=ImageGenerationInputMode.KEYFRAME_EDIT,
            provider="source_video",
            model="selected-keyframe",
            model_snapshot="source-frame-v1",
            prompt_version="source-frame-v1",
            schema_version="viral-dna-source-frame/v1",
            pricing_version="zero-cost-v1",
            request_fingerprint=fingerprint,
            input_snapshot_relative_path=self.workspace.relative(input_path),
            execution_mode=ImageExecutionMode.SOURCE_FRAME,
            adapter_id="source-frame",
            adapter_version="batch4.2",
            capability_snapshot={"source_frame_passthrough": True},
            execution_summary={
                "model_call": False,
                "source_keyframe_timestamp_seconds": (
                    plan.source_keyframe_timestamp_seconds
                ),
            },
            cost_source=GenerationCostSource.UNMETERED,
            cost_estimate_known=True,
            usage={"model_calls": 0, "source_frames": 1},
            output_manifest_relative_path=self.workspace.relative(manifest_path),
            status=ProductionRunStatus.COMPLETED,
            estimated_cost_micros=0,
            actual_cost_micros=0,
            latency_ms=max(0, round((completed_at - started).total_seconds() * 1000)),
            completed_at=completed_at,
        )
        return run, candidate

    def _resolve_source_keyframe(
        self,
        project: ProductionProject,
        plan: ShotPlan,
    ) -> Path | None:
        if plan.source_keyframe_relative_path is not None:
            try:
                candidate = self.workspace.resolve(
                    plan.source_keyframe_relative_path
                ).resolve()
            except WorkspaceError:
                return None
            root = self.workspace.production_shot_root(
                project.record_id,
                project.id,
                plan.id,
            ).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                return None
            filesystem_candidate = _filesystem_path(candidate)
            return filesystem_candidate if filesystem_candidate.is_file() else None

        source_url = plan.source_keyframe_url
        prefix = f"/api/v1/analyses/{project.base_analysis_id}/artifacts/"
        if not source_url or not source_url.startswith(prefix):
            return None
        relative = unquote(source_url[len(prefix) :]).replace(chr(92), "/")
        if not relative or Path(relative).is_absolute():
            return None
        roots = [
            self.workspace.analysis_root(
                project.record_id,
                project.base_analysis_id,
            ),
            self.workspace.root / "analyses" / str(project.base_analysis_id),
        ]
        for root in roots:
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                continue
            filesystem_candidate = _filesystem_path(candidate)
            if filesystem_candidate.is_file():
                return filesystem_candidate
        return None

    async def _require_shot(self, shot_plan_id: UUID) -> ShotPlan:
        plan = await self.repository.get_shot_plan(shot_plan_id)
        if plan is None:
            raise _fail(404, "shot_plan_not_found", "分镜创作计划不存在")
        return plan

    @staticmethod
    def _ensure_shot_active(plan: ShotPlan) -> None:
        if plan.lifecycle_status != ShotLifecycleStatus.ACTIVE:
            raise _fail(409, "shot_discarded", "已舍弃分镜需要先恢复后才能继续操作")

    async def _require_run(self, run_id: UUID) -> GenerationRun:
        run = await self.repository.get_generation_run(run_id)
        if run is None:
            raise _fail(404, "generation_run_not_found", "生成任务不存在")
        return run

    async def _require_candidate(
        self,
        candidate_id: UUID,
    ) -> GenerationCandidate:
        candidate = await self.repository.get_generation_candidate(candidate_id)
        if candidate is None:
            raise _fail(404, "generation_candidate_not_found", "生成候选不存在")
        return candidate

    async def _completed_analysis(
        self,
        record: AnalysisRecord,
        analysis_id: UUID,
    ) -> tuple[AnalysisJob, AnalysisReport]:
        analysis = await self.repository.get_analysis(analysis_id)
        if (
            analysis is None
            or analysis.video_id != record.video_id
            or analysis.record_id not in {None, record.id}
        ):
            raise _fail(404, "analysis_not_found", "指定分析版本不属于当前记录")
        if analysis.stage != AnalysisStage.COMPLETED:
            raise _fail(409, "analysis_incomplete", "指定分析版本尚未完成")
        report = await self.repository.get_report_by_analysis(analysis.id)
        if report is None or report.video_id != record.video_id:
            raise _fail(409, "analysis_report_missing", "指定分析版本缺少分析报告")
        return analysis, report

    async def _require_project(self, project_id: UUID) -> ProductionProject:
        project = await self.repository.get_production_project(project_id)
        if project is None:
            raise _fail(404, "production_not_found", "创作方案不存在")
        return project

    async def _require_revision(
        self,
        project: ProductionProject,
        revision_id: UUID,
    ) -> ProductionRevision:
        revision = await self.repository.get_production_revision(revision_id)
        if revision is None or revision.project_id != project.id:
            raise _fail(404, "revision_not_found", "创作方案版本不存在")
        return revision

    async def _list_reference_assets(
        self,
        project_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[ReferenceAsset]:
        if self.project_assets is not None:
            return await self.project_assets.list_references(
                project_id, include_archived=include_archived
            )
        assets = await self.repository.list_reference_assets(project_id)
        if not include_archived:
            assets = [item for item in assets if item.archived_at is None]
        return assets

    async def _require_asset(
        self,
        asset_id: UUID,
        project_id: UUID | None = None,
    ) -> ReferenceAsset:
        asset = (
            await self.project_assets.get_reference(asset_id, project_id)
            if self.project_assets is not None
            else await self.repository.get_reference_asset(asset_id)
        )
        if asset is None:
            raise _fail(404, "reference_asset_not_found", "参考资产不存在")
        return asset

    @staticmethod
    def _require_expected_revision(
        project: ProductionProject,
        expected_revision_id: UUID,
    ) -> None:
        if project.current_revision_id != expected_revision_id:
            raise _fail(409, "revision_conflict", "创作方案已更新，请刷新后重试")

    async def _prepare_revision(
        self,
        project: ProductionProject,
        change_kind: ProductionChangeKind,
        change_summary: str,
        *,
        revision_id: UUID | None = None,
        report: AnalysisReport | None = None,
        reference_assets: list[ReferenceAsset] | None = None,
        shot_plans: list[ShotPlan] | None = None,
        reference_bindings: list[ReferenceBinding] | None = None,
    ) -> tuple[ProductionProject, ProductionRevision]:
        revisions = await self.repository.list_production_revisions(project.id)
        revision_number = max((item.revision_number for item in revisions), default=0) + 1
        revision_id = revision_id or uuid4()
        paths = self.workspace.initialize_production(project.record_id, project.id)
        revision = ProductionRevision(
            id=revision_id,
            project_id=project.id,
            parent_revision_id=project.current_revision_id,
            revision_number=revision_number,
            change_kind=change_kind,
            change_summary=_simplified_text(
                change_summary,
                field_name="版本说明",
                max_length=500,
            ),
            snapshot_relative_path=self.workspace.relative(paths.revisions / f"{revision_id}.json"),
        )
        updated_project = ProductionProject.model_validate(
            {
                **project.model_dump(mode="python"),
                "current_revision_id": revision.id,
                "updated_at": utc_now(),
            }
        )
        snapshot = await self._build_snapshot(
            updated_project,
            revision,
            report=report,
            reference_assets=reference_assets,
            shot_plans=shot_plans,
            reference_bindings=reference_bindings,
        )
        await asyncio.to_thread(
            self._write_revision_files,
            updated_project,
            revision,
            snapshot,
        )
        return updated_project, revision

    async def _build_snapshot(
        self,
        project: ProductionProject,
        revision: ProductionRevision,
        *,
        report: AnalysisReport | None,
        reference_assets: list[ReferenceAsset] | None,
        shot_plans: list[ShotPlan] | None,
        reference_bindings: list[ReferenceBinding] | None,
    ) -> dict[str, object]:
        if report is None:
            report = await self.repository.get_report_by_analysis(project.base_analysis_id)
        if report is None or report.video_id != project.video_id:
            raise _fail(409, "analysis_report_missing", "创作方案的基础分析报告不存在")
        assets = (
            list(reference_assets)
            if reference_assets is not None
            else await self._list_reference_assets(project.id, include_archived=True)
        )
        plans = (
            list(shot_plans)
            if shot_plans is not None
            else await self.repository.list_shot_plans(project.id)
        )
        if reference_bindings is None:
            bindings: list[ReferenceBinding] = []
            for plan in plans:
                bindings.extend(await self.repository.list_reference_bindings(plan.id))
        else:
            bindings = list(reference_bindings)
        binding_groups = {
            plan.id: [item for item in bindings if item.shot_plan_id == plan.id] for plan in plans
        }
        reference_snapshots = (
            [
                await self.project_assets.snapshot_reference(project.id, item)
                for item in assets
            ]
            if self.project_assets is not None
            else [item.model_dump(mode="json") for item in assets]
        )
        return {
            "schema_version": PRODUCTION_SNAPSHOT_SCHEMA,
            "revision": _revision_response(revision).model_dump(mode="json"),
            "project": project.model_dump(mode="json"),
            "source_analysis": {
                "analysis_id": str(report.analysis_id),
                "generated_at": report.generated_at.isoformat(),
                "overview": report.overview.model_dump(mode="json"),
                "entities": [item.model_dump(mode="json") for item in report.entities],
                "prompt_package": report.prompt_package.model_dump(mode="json"),
                "shots": [item.model_dump(mode="json") for item in report.shots],
            },
            "references": reference_snapshots,
            "shot_plans": [
                {
                    "shot_plan": plan.model_dump(mode="json"),
                    "reference_bindings": [
                        item.model_dump(mode="json") for item in binding_groups[plan.id]
                    ],
                }
                for plan in plans
            ],
        }

    async def _read_revision_snapshot(
        self,
        project: ProductionProject,
        revision: ProductionRevision,
    ) -> dict[str, object]:
        candidate = self.workspace.resolve(revision.snapshot_relative_path)
        revisions_root = self.workspace.production_paths(
            project.record_id,
            project.id,
        ).revisions.resolve()
        try:
            candidate.resolve().relative_to(revisions_root)
        except ValueError as exc:
            raise _fail(409, "invalid_revision_path", "创作方案版本路径无效") from exc
        filesystem_candidate = _filesystem_path(candidate)
        if not filesystem_candidate.is_file():
            raise _fail(409, "revision_snapshot_missing", "创作方案版本快照不存在")
        try:
            payload = await asyncio.to_thread(
                filesystem_candidate.read_text,
                "utf-8-sig",
            )
            snapshot = json.loads(payload)
        except (OSError, json.JSONDecodeError) as exc:
            raise _fail(409, "invalid_revision_snapshot", "创作方案版本快照已损坏") from exc
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("schema_version") not in SUPPORTED_PRODUCTION_SNAPSHOT_SCHEMAS
        ):
            raise _fail(409, "invalid_revision_snapshot", "创作方案版本快照格式不受支持")
        return snapshot

    def _write_revision_files(
        self,
        project: ProductionProject,
        revision: ProductionRevision,
        snapshot: dict[str, object],
    ) -> None:
        paths = self.workspace.production_paths(project.record_id, project.id)
        snapshot_path = self.workspace.resolve(revision.snapshot_relative_path)
        try:
            snapshot_path.resolve().relative_to(paths.revisions.resolve())
        except ValueError as exc:
            raise _fail(409, "invalid_revision_path", "创作方案版本路径无效") from exc
        self._write_json_atomic(snapshot_path, snapshot)
        self._write_json_atomic(
            paths.project_metadata,
            {
                "schema_version": PRODUCTION_SNAPSHOT_SCHEMA,
                "project": project.model_dump(mode="json"),
                "current_revision": _revision_response(revision).model_dump(mode="json"),
            },
        )

    def _write_reference_files(
        self,
        project: ProductionProject,
        asset: ReferenceAsset,
        original: bytes,
        thumbnail: bytes,
    ) -> None:
        original_path = self._resolve_reference_path(project, asset.relative_path)
        if asset.thumbnail_relative_path is None:
            raise _fail(500, "reference_thumbnail_path_missing", "参考资产缩略图路径缺失")
        thumbnail_path = self._resolve_reference_path(
            project,
            asset.thumbnail_relative_path,
        )
        self._write_atomic(original_path, original)
        self._write_atomic(thumbnail_path, thumbnail)
        self._write_asset_metadata(project, asset)

    def _write_asset_metadata(
        self,
        project: ProductionProject,
        asset: ReferenceAsset,
    ) -> None:
        metadata_path = (
            self._resolve_reference_path(project, asset.relative_path).parent / "asset.json"
        )
        self._write_json_atomic(metadata_path, asset.model_dump(mode="json"))

    def _resolve_reference_path(
        self,
        project: ProductionProject,
        relative_path: str,
    ) -> Path:
        try:
            candidate = self.workspace.resolve(relative_path).resolve()
        except WorkspaceError as exc:
            raise _fail(409, "invalid_reference_path", "参考资产路径无效") from exc
        root = self.workspace.production_paths(
            project.record_id,
            project.id,
        ).references.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise _fail(409, "invalid_reference_path", "参考资产路径无效") from exc
        return candidate

    async def _clone_snapshot_assets(
        self,
        source_project: ProductionProject,
        branch: ProductionProject,
        snapshot: dict[str, object],
    ) -> tuple[list[ReferenceAsset], dict[UUID, UUID]]:
        raw_assets = snapshot.get("references", [])
        if not isinstance(raw_assets, list):
            raise _fail(409, "invalid_revision_snapshot", "源版本参考资产快照无效")
        cloned: list[ReferenceAsset] = []
        id_map: dict[UUID, UUID] = {}
        if self.project_assets is not None:
            for raw_asset in raw_assets:
                if not isinstance(raw_asset, dict):
                    raise _fail(409, "invalid_revision_snapshot", "源版本参考资产快照无效")
                if raw_asset.get("removed_at") or raw_asset.get("archived_at"):
                    continue
                linked = await self.project_assets.link_snapshot_reference(branch, raw_asset)
                raw_id = raw_asset.get("asset_id") or raw_asset.get("id")
                if raw_id is None:
                    raise _fail(409, "invalid_revision_snapshot", "源版本资产标识缺失")
                id_map[UUID(str(raw_id))] = linked.id
                cloned.append(linked)
            return cloned, id_map
        for raw_asset in raw_assets:
            try:
                source_asset = ReferenceAsset.model_validate(raw_asset)
            except ValidationError as exc:
                raise _fail(409, "invalid_revision_snapshot", "源版本参考资产快照无效") from exc
            if source_asset.archived_at is not None:
                continue
            source_original = self._resolve_reference_path(
                source_project,
                source_asset.relative_path,
            )
            filesystem_original = _filesystem_path(source_original)
            if not filesystem_original.is_file():
                raise _fail(409, "reference_file_missing", "源版本参考资产文件不存在")
            source_thumbnail = None
            if source_asset.thumbnail_relative_path:
                source_thumbnail = self._resolve_reference_path(
                    source_project,
                    source_asset.thumbnail_relative_path,
                )
                if not _filesystem_path(source_thumbnail).is_file():
                    source_thumbnail = None
            new_id = uuid4()
            destination_root = self.workspace.reference_asset_root(
                branch.record_id,
                branch.id,
                new_id,
            )
            destination_original = destination_root / source_original.name
            destination_thumbnail = destination_root / "thumbnail.webp"
            cloned_asset = ReferenceAsset.model_validate(
                {
                    **source_asset.model_dump(mode="python"),
                    "id": new_id,
                    "project_id": branch.id,
                    "relative_path": self.workspace.relative(destination_original),
                    "thumbnail_relative_path": (
                        self.workspace.relative(destination_thumbnail)
                        if source_thumbnail is not None
                        else None
                    ),
                    "created_at": utc_now(),
                    "archived_at": None,
                }
            )
            original_payload = await asyncio.to_thread(filesystem_original.read_bytes)
            await asyncio.to_thread(
                self._write_atomic,
                destination_original,
                original_payload,
            )
            if source_thumbnail is not None:
                thumbnail_payload = await asyncio.to_thread(
                    _filesystem_path(source_thumbnail).read_bytes
                )
                await asyncio.to_thread(
                    self._write_atomic,
                    destination_thumbnail,
                    thumbnail_payload,
                )
            await asyncio.to_thread(
                self._write_asset_metadata,
                branch,
                cloned_asset,
            )
            cloned.append(cloned_asset)
            id_map[source_asset.id] = cloned_asset.id
        return cloned, id_map

    async def _clone_snapshot_shots(
        self,
        source_project: ProductionProject,
        branch: ProductionProject,
        revision_id: UUID,
        snapshot: dict[str, object],
        asset_ids: dict[UUID, UUID],
    ) -> tuple[list[ShotPlan], list[ReferenceBinding]]:
        raw_plans = snapshot.get("shot_plans", [])
        if not isinstance(raw_plans, list):
            raise _fail(409, "invalid_revision_snapshot", "源版本分镜快照无效")
        cloned_plans: list[ShotPlan] = []
        cloned_bindings: list[ReferenceBinding] = []
        for raw_entry in raw_plans:
            if not isinstance(raw_entry, dict):
                raise _fail(409, "invalid_revision_snapshot", "源版本分镜快照无效")
            try:
                source_plan = ShotPlan.model_validate(raw_entry["shot_plan"])
                source_bindings = [
                    ReferenceBinding.model_validate(item)
                    for item in raw_entry.get("reference_bindings", [])
                ]
            except (KeyError, TypeError, ValidationError) as exc:
                raise _fail(409, "invalid_revision_snapshot", "源版本分镜快照无效") from exc
            cloned_plan_id = uuid4()
            source_keyframe_url = source_plan.source_keyframe_url
            source_keyframe_relative_path = None
            if source_plan.source_keyframe_relative_path is not None:
                try:
                    source_keyframe = self.workspace.resolve(
                        source_plan.source_keyframe_relative_path
                    ).resolve()
                except WorkspaceError as exc:
                    raise _fail(
                        409,
                        "source_keyframe_path_invalid",
                        "源版本关键帧路径无效",
                    ) from exc
                source_shot_root = self.workspace.production_shot_root(
                    source_project.record_id,
                    source_project.id,
                    source_plan.id,
                ).resolve()
                try:
                    source_keyframe.relative_to(source_shot_root)
                except ValueError as exc:
                    raise _fail(
                        409,
                        "source_keyframe_path_invalid",
                        "源版本关键帧路径无效",
                    ) from exc
                filesystem_source = _filesystem_path(source_keyframe)
                if not filesystem_source.is_file():
                    raise _fail(
                        409,
                        "source_keyframe_missing",
                        "源版本所选关键帧文件不存在",
                    )
                destination = (
                    self.workspace.production_shot_root(
                        branch.record_id,
                        branch.id,
                        cloned_plan_id,
                    )
                    / "source-keyframes"
                    / f"{revision_id}.jpg"
                )
                payload = await asyncio.to_thread(filesystem_source.read_bytes)
                await asyncio.to_thread(self._write_atomic, destination, payload)
                source_keyframe_relative_path = self.workspace.relative(destination)
                source_keyframe_url = (
                    f"/api/v1/production-shots/{cloned_plan_id}/source-keyframe"
                    f"?v={revision_id}"
                )
            cloned_plan = ShotPlan.model_validate(
                {
                    **source_plan.model_dump(mode="python"),
                    "id": cloned_plan_id,
                    "project_id": branch.id,
                    "revision_id": revision_id,
                    "source_keyframe_url": source_keyframe_url,
                    "source_keyframe_relative_path": source_keyframe_relative_path,
                    "approved_image_candidate_id": None,
                    "approved_video_candidate_id": None,
                    "image_status": (
                        WorkflowItemStatus.READY
                        if source_plan.image_prompt.strip()
                        else WorkflowItemStatus.DRAFT
                    ),
                    "video_status": WorkflowItemStatus.DRAFT,
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                }
            )
            cloned_plans.append(cloned_plan)
            for binding in source_bindings:
                mapped_asset_id = asset_ids.get(binding.reference_asset_id)
                if mapped_asset_id is None:
                    continue
                cloned_bindings.append(
                    ReferenceBinding.model_validate(
                        {
                            **binding.model_dump(mode="python"),
                            "id": uuid4(),
                            "shot_plan_id": cloned_plan.id,
                            "reference_asset_id": mapped_asset_id,
                            "created_at": utc_now(),
                        }
                    )
                )
        return cloned_plans, cloned_bindings

    @staticmethod
    def _write_atomic(destination: Path, payload: bytes) -> None:
        filesystem_destination = _filesystem_path(destination)
        filesystem_destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = filesystem_destination.parent / f".tmp-{uuid4().hex[:8]}"
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, filesystem_destination)
        except OSError as exc:
            raise _fail(507, "workspace_write_failed", "无法写入工作区文件") from exc
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _write_json_atomic(cls, destination: Path, payload: object) -> None:
        serialized = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        cls._write_atomic(destination, serialized)

    def _reference_response(
        self,
        asset: ReferenceAsset,
        current_revision_id: UUID | None,
    ) -> ReferenceAssetResponse:
        if current_revision_id is None:
            raise _fail(409, "revision_required", "创作方案尚无当前版本")
        return ReferenceAssetResponse(
            id=asset.id,
            project_id=asset.project_id,
            type=asset.type,
            name=asset.name,
            description=asset.description,
            mime_type=asset.mime_type,
            width=asset.width,
            height=asset.height,
            sha256=asset.sha256,
            tags=asset.tags,
            rights_confirmed=asset.rights_confirmed,
            rights_note=asset.rights_note,
            content_url=(
                f"/api/v1/assets/{asset.id}/content"
                if self.project_assets is not None
                else f"/api/v1/references/{asset.id}/content"
            ),
            thumbnail_url=(
                f"/api/v1/assets/{asset.id}/thumbnail"
                if self.project_assets is not None
                else f"/api/v1/references/{asset.id}/thumbnail"
            ),
            current_revision_id=current_revision_id,
            created_at=asset.created_at,
            archived_at=asset.archived_at,
        )
