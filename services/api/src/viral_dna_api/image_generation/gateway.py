from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from ..chinese import to_simplified
from ..generation import generate_simulated_images
from ..models import (
    GenerationCandidate,
    GenerationCostSource,
    GenerationKind,
    GenerationRun,
    ImageExecutionMode,
    ImageGenerationCapability,
    ImageGenerationInputMode,
    ProductionProject,
    ProductionRunStatus,
    ReferenceAsset,
    ReferenceBinding,
    ShotPlan,
)
from ..runtime_config import get_config_value
from ..workspace import WorkspaceError, WorkspaceManager
from .catalog import ImageModelCatalogError, load_image_model_catalog
from .codex_local import (
    local_tool_proxy_delivery,
    local_tool_proxy_environment_url,
)
from .contracts import (
    IMAGE_PROMPT_VERSION,
    IMAGE_REQUEST_SCHEMA_VERSION,
    AdapterIdentity,
    AdapterRequest,
    AdapterResult,
    GeneratedImage,
    ImageGenerationError,
    ImageGenerationRequest,
    build_reference_inputs,
)
from .dashscope import DashScopeQwenImageAdapter
from .identity_policy import (
    IdentityPolicyState,
    IdentityPolicyViolation,
    build_input_manifest,
    identity_reference,
    policy_snapshot,
    validate_identity_bindings,
    validate_identity_generation,
)
from .local_tool import LocalToolImageAdapter, detect_local_tool
from .process_slots import ProcessSlotLimiter
from .semantic_quality import ImageSemanticQualityService, SemanticQualityOutcome
from .settings import (
    IMAGE_ADAPTER_ID,
    IMAGE_ADAPTER_VERSION,
    ImageGenerationSettingsService,
)

GATEWAY_VERSION = "1.0.0"
MAX_CANDIDATE_PIXELS = 64_000_000


class ImageGenerationGatewayError(ImageGenerationError):
    """Public error type translated by the production service."""


class ImageGenerationCacheRepository(Protocol):
    async def list_generation_runs(
        self,
        project_id: UUID,
        shot_plan_id: UUID | None = None,
    ) -> list[GenerationRun]: ...

    async def list_generation_candidates(
        self,
        generation_run_id: UUID,
    ) -> list[GenerationCandidate]: ...


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


def _rounded_multiple(value: float, multiple: int = 16) -> int:
    return max(multiple, round(value / multiple) * multiple)


def _output_dimensions(
    width: int,
    height: int,
    capability: ImageGenerationCapability,
) -> tuple[int, int]:
    scale = min(
        1.0,
        capability.maximum_width / width,
        capability.maximum_height / height,
        math.sqrt(capability.maximum_pixels / (width * height)),
    )
    output_width = _rounded_multiple(width * scale)
    output_height = _rounded_multiple(height * scale)
    while (
        output_width > capability.maximum_width
        or output_height > capability.maximum_height
        or output_width * output_height > capability.maximum_pixels
    ):
        output_width = max(256, output_width - 16)
        output_height = max(256, output_height - 16)
    if output_width * output_height < 512 * 512:
        upscale = math.sqrt((512 * 512) / (output_width * output_height))
        candidate_width = _rounded_multiple(output_width * upscale)
        candidate_height = _rounded_multiple(output_height * upscale)
        if (
            candidate_width <= capability.maximum_width
            and candidate_height <= capability.maximum_height
            and candidate_width * candidate_height <= capability.maximum_pixels
        ):
            output_width, output_height = candidate_width, candidate_height
    return output_width, output_height


def _compiled_prompt(request: ImageGenerationRequest) -> str:
    role_labels = {
        "identity": "唯一人物身份来源",
        "product": "产品外观与结构",
        "scene": "场景环境",
        "wardrobe": "服装款式与材质",
        "style": "整体视觉风格",
        "layout": "道具或布局",
    }
    mention_labels = {
        item.reference_asset_id: item.label
        for item in request.shot.image_prompt_mentions
    }
    primary_identity = identity_reference(request.references)
    if request.input_mode == ImageGenerationInputMode.TEXT_TO_IMAGE:
        lines = [
            "本次任务是纯文字生成，不使用原视频关键帧或参考图片。",
            f"生成要求：{request.shot.image_prompt.strip()}",
            "根据文字从零构建完整画面，严格遵循主体、场景、构图、镜头、光影和风格描述。",
        ]
        reference_offset = 1
    elif primary_identity is not None:
        lines = [
            "这是受控人物身份替换任务，必须严格区分每张输入图的职责。",
            "图像1仅用于保留原视频关键帧的姿态、构图、动作关系、机位、运镜意图和光影逻辑。",
            "严禁从图像1继承人物的年龄、五官、脸型、肤色、发型、身份或其他生物特征。",
            (
                "图像2（@"
                f"{mention_labels.get(primary_identity.asset_id, primary_identity.name)}"
                "）是生成结果中人物身份的唯一来源。"
            ),
            "人物年龄、五官、脸型、肤色和可识别身份必须以图像2为准；不得与图像1的人脸融合，不得生成第三个人物身份。",
            "当图像1与图像2发生冲突时，身份一律服从图像2，姿态、构图和动作一律服从图像1。",
            f"编辑要求：{request.shot.image_prompt.strip()}",
        ]
        reference_offset = 2
    else:
        lines = [
            "图像1是原视频分镜关键帧，作为基础图进行编辑。",
            "除下方明确要求替换的内容外，保留原图的镜头视角、构图、主体姿态、动作关系和光影逻辑。",
            f"编辑要求：{request.shot.image_prompt.strip()}",
        ]
        reference_offset = 2
    for index, reference in enumerate(request.references, start=reference_offset):
        label = role_labels.get(reference.role, reference.role)
        mention_label = mention_labels.get(reference.asset_id)
        if reference.role == "identity":
            detail = (
                f"图像{index}对应提示词中的 @{mention_label}，是唯一人物身份来源"
                if mention_label
                else f"图像{index}是人物资产“{reference.name}”，是唯一人物身份来源"
            )
        else:
            detail = (
                f"图像{index}对应提示词中的 @{mention_label}，用于参考{label}"
                if mention_label
                else f"图像{index}是参考资产“{reference.name}”，用于参考{label}"
            )
        if reference.notes:
            detail += f"，说明：{reference.notes.strip()}"
        if reference.crop_hint:
            detail += f"，裁切提示：{reference.crop_hint.strip()}"
        lines.append(detail + "。")
    lines.append("生成结果必须是完整画面，不要输出解释、边框、拼图或参考图标注。")
    return (to_simplified("\n".join(lines)) or "\n".join(lines)).strip()


def _negative_prompt(request: ImageGenerationRequest) -> str:
    primary_identity = identity_reference(request.references)
    identity_constraints = (
        [
            "继承图像1人物的年龄、五官、脸型、肤色、发型或身份",
            "混合图像1与图像2的人脸或身份",
            "改变图像2人物的年龄、五官、脸型或肤色",
            "生成第三个人物身份",
            "人物身份漂移",
            "面部融合",
            "双人脸",
            "人脸重影",
        ]
        if primary_identity is not None
        else []
    )
    base = [
        "低清晰度",
        "模糊",
        "水印",
        "额外文字",
        "拼接画面",
        "多余肢体",
        "手指畸形",
        "产品结构变形",
    ]
    values = [*identity_constraints, *request.shot.image_negative_constraints, *base]
    normalized: list[str] = []
    for value in values:
        text = (to_simplified(value) or value).strip()
        if text and text not in normalized:
            normalized.append(text)
    return "，".join(normalized)[:1000]


def _candidate_quality_report(
    image: Image.Image,
    *,
    target_width: int,
    target_height: int,
    reference_roles: set[str],
) -> dict[str, Any]:
    target_aspect = target_width / target_height
    actual_aspect = image.width / image.height
    aspect_error = abs(actual_aspect - target_aspect) / target_aspect
    resolution_ratio = (image.width * image.height) / max(1, target_width * target_height)
    automated_warnings: list[str] = []
    if aspect_error > 0.03:
        automated_warnings.append("输出画幅与目标画幅偏差超过 3%")
    if resolution_ratio < 0.25:
        automated_warnings.append("输出像素数不足目标像素数的 25%")

    manual_checks = [
        {
            "id": "subject_and_composition",
            "label": "主体与构图",
            "status": "required",
        },
        {
            "id": "text_artifacts",
            "label": "异常文字与水印",
            "status": "required",
        }
    ]
    role_checks = {
        "identity": ("identity_consistency", "人物身份一致性"),
        "product": ("product_shape", "产品形态与结构"),
        "wardrobe": ("wardrobe_consistency", "服装款式与材质"),
        "scene": ("scene_consistency", "场景一致性"),
    }
    for role, (check_id, label) in role_checks.items():
        if role in reference_roles:
            manual_checks.append({"id": check_id, "label": label, "status": "required"})

    manual_labels = "、".join(item["label"] for item in manual_checks)
    summary = (
        "；".join(automated_warnings) + f"；需人工核对{manual_labels}"
        if automated_warnings
        else f"基础文件与画幅检查通过；需人工核对{manual_labels}"
    )
    return {
        "schema_version": "viral-dna-image-quality/v1",
        "status": "warning" if automated_warnings else "manual_review_required",
        "summary": summary,
        "automated_checks": {
            "file_integrity": {"status": "passed", "decoded": True},
            "dimensions": {
                "status": "warning" if automated_warnings else "passed",
                "actual_width": image.width,
                "actual_height": image.height,
                "target_width": target_width,
                "target_height": target_height,
                "aspect_ratio_error": round(aspect_error, 6),
                "resolution_ratio": round(resolution_ratio, 6),
                "warnings": automated_warnings,
            },
        },
        "manual_checks": manual_checks,
    }


def _save_candidate(
    workspace: WorkspaceManager,
    run_root: Path,
    run_id: UUID,
    ordinal: int,
    image: GeneratedImage,
    *,
    request_fingerprint: str,
    provider: str,
    model: str,
    target_width: int,
    target_height: int,
    reference_roles: set[str],
) -> GenerationCandidate:
    try:
        with Image.open(BytesIO(image.payload)) as source:
            rendered = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise ImageGenerationGatewayError(
            502,
            "generated_image_invalid",
            "生成候选不是有效图片",
        ) from exc
    if rendered.width * rendered.height > MAX_CANDIDATE_PIXELS:
        raise ImageGenerationGatewayError(
            502,
            "generated_image_dimensions",
            "生成候选像素尺寸超过工作区安全限制",
        )
    candidate_output = BytesIO()
    rendered.save(candidate_output, format="JPEG", quality=94, optimize=True)
    candidate_payload = candidate_output.getvalue()
    thumbnail = rendered.copy()
    thumbnail.thumbnail((640, 640), Image.Resampling.LANCZOS)
    thumbnail_output = BytesIO()
    thumbnail.save(thumbnail_output, format="WEBP", quality=84, method=4)

    candidate_path = run_root / f"candidate_{ordinal:03d}.jpg"
    thumbnail_path = run_root / f"candidate_{ordinal:03d}.webp"
    metadata_path = run_root / f"candidate_{ordinal:03d}.json"
    sha256 = hashlib.sha256(candidate_payload).hexdigest()
    quality_report = _candidate_quality_report(
        rendered,
        target_width=target_width,
        target_height=target_height,
        reference_roles=reference_roles,
    )
    metadata = {
        "schema_version": "viral-dna-generation-candidate/v1",
        "ordinal": ordinal,
        "provider": provider,
        "model": model,
        "request_fingerprint": request_fingerprint,
        "source_media_type": image.media_type,
        "source_sha256": hashlib.sha256(image.payload).hexdigest(),
        "sha256": sha256,
        "width": rendered.width,
        "height": rendered.height,
        "quality_report": quality_report,
        "adapter_metadata": image.metadata,
    }
    _write_atomic(candidate_path, candidate_payload)
    _write_atomic(thumbnail_path, thumbnail_output.getvalue())
    _write_atomic(metadata_path, _canonical_json(metadata) + b"\n")
    return GenerationCandidate(
        generation_run_id=run_id,
        ordinal=ordinal,
        kind=GenerationKind.IMAGE,
        relative_path=workspace.relative(candidate_path),
        thumbnail_relative_path=workspace.relative(thumbnail_path),
        width=rendered.width,
        height=rendered.height,
        sha256=sha256,
        metadata_relative_path=workspace.relative(metadata_path),
        quality_report=quality_report,
    )


def _merge_semantic_quality(
    base_report: dict[str, Any],
    outcome: SemanticQualityOutcome,
) -> dict[str, Any]:
    report = dict(base_report)
    semantic = dict(outcome.report)
    report["semantic_quality"] = semantic
    if semantic.get("status") == "warning":
        report["status"] = "warning"
    base_summary = str(report.get("summary") or "基础文件检查已完成")
    semantic_summary = str(semantic.get("summary") or "VLM 质检未返回摘要")
    report["summary"] = f"{base_summary}；{semantic_summary}"[:1200]
    return report


def _update_candidate_quality_metadata(
    workspace: WorkspaceManager,
    candidate: GenerationCandidate,
) -> None:
    metadata_path = workspace.resolve(candidate.metadata_relative_path)
    try:
        metadata = json.loads(_filesystem_path(metadata_path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImageGenerationGatewayError(
            500,
            "candidate_metadata_invalid",
            "无法更新候选图片质检元数据",
        ) from exc
    metadata["quality_report"] = candidate.quality_report
    _write_atomic(metadata_path, _canonical_json(metadata) + b"\n")


def _sum_model_usage(outcomes: list[SemanticQualityOutcome]) -> dict[str, Any]:
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
        "image_count",
    )
    totals = {
        field: sum(getattr(outcome.usage, field) for outcome in outcomes)
        for field in fields
    }
    totals["call_count"] = sum(
        bool(outcome.report.get("provider_request_id")) for outcome in outcomes
    )
    return totals


class ImageGenerationGateway:
    def __init__(
        self,
        workspace: WorkspaceManager,
        settings_service: ImageGenerationSettingsService | None = None,
        *,
        repository: ImageGenerationCacheRepository | None = None,
        semantic_quality_service: ImageSemanticQualityService | None = None,
        process_slot_limiter: ProcessSlotLimiter | None = None,
    ) -> None:
        self.workspace = workspace
        self.settings_service = settings_service or ImageGenerationSettingsService()
        self.repository = repository
        self.semantic_quality_service = semantic_quality_service or ImageSemanticQualityService()
        self.process_slot_limiter = process_slot_limiter or ProcessSlotLimiter(
            workspace.paths.metadata_dir / "locks"
        )
        self._local_semaphores: dict[int, asyncio.Semaphore] = {}

    async def generate_auxiliary_image(
        self,
        *,
        project: ProductionProject,
        shot: ShotPlan,
        source_path: Path,
        run_root: Path,
        positive_prompt: str,
        negative_prompt: str,
        allow_unknown_cost: bool = False,
        seed: int | None = None,
    ) -> tuple[AdapterIdentity, AdapterResult]:
        """Generate one derived image without creating a shot image candidate.

        Reference-proxy rendering uses this narrow seam so provider selection,
        credentials, cost snapshots and payload validation remain owned by the
        image-generation package.  Only the already anonymized structural image
        is passed as ``source_path``.
        """

        settings = self.settings_service.get()
        if not settings.enabled:
            raise ImageGenerationGatewayError(
                409,
                "image_generation_not_configured",
                "请先在“模型与设置”中校验并启用真实图片生成引擎",
            )
        if not await asyncio.to_thread(source_path.is_file):
            raise ImageGenerationGatewayError(
                409,
                "auxiliary_image_source_missing",
                "AI 白模增强缺少本机生成的匿名结构图",
            )
        identity, adapter = await self._adapter(
            ImageExecutionMode.REMOTE_API,
            settings,
            candidate_count=1,
        )
        if not identity.capability.image_to_image:
            raise ImageGenerationGatewayError(
                422,
                "auxiliary_image_edit_unsupported",
                "当前图片模型不支持基于结构图进行编辑",
            )
        if not identity.cost_estimate_known and not allow_unknown_cost:
            raise ImageGenerationGatewayError(
                409,
                "image_unknown_cost_confirmation_required",
                "AI 白模增强费用无法预估，请确认未知成本后重试",
            )
        if (
            project.budget_limit_micros is not None
            and identity.cost_estimate_known
            and project.actual_cost_micros + identity.estimated_cost_micros
            > project.budget_limit_micros
        ):
            remaining = max(0, project.budget_limit_micros - project.actual_cost_micros)
            raise ImageGenerationGatewayError(
                409,
                "production_budget_exceeded",
                (
                    f"AI 白模预计成本 ¥{identity.estimated_cost_micros / 1_000_000:.2f}，"
                    f"方案剩余预算 ¥{remaining / 1_000_000:.2f}"
                ),
            )
        width, height = _output_dimensions(
            project.output_width,
            project.output_height,
            identity.capability,
        )
        await asyncio.to_thread(run_root.mkdir, parents=True, exist_ok=True)
        request = AdapterRequest(
            request_id=uuid4(),
            run_root=run_root,
            project=project,
            shot=shot,
            input_mode=ImageGenerationInputMode.KEYFRAME_EDIT,
            source_path=source_path,
            source_sha256=_sha256_file(source_path),
            references=(),
            candidate_count=1,
            width=width,
            height=height,
            positive_prompt=(to_simplified(positive_prompt) or positive_prompt).strip(),
            negative_prompt=(to_simplified(negative_prompt) or negative_prompt).strip(),
            seed=seed,
            capability=identity.capability,
        )
        try:
            result = await adapter.generate(request)
        except ImageGenerationError as exc:
            raise ImageGenerationGatewayError(
                exc.status_code,
                exc.code,
                str(exc),
                retryable=exc.retryable,
            ) from exc
        if len(result.images) != 1:
            raise ImageGenerationGatewayError(
                502,
                "auxiliary_image_candidate_count_mismatch",
                "图片模型没有返回唯一的 AI 白模结果",
            )
        return identity, result

    async def generate(
        self,
        project: ProductionProject,
        shot: ShotPlan,
        revision_id: UUID,
        bindings: list[ReferenceBinding],
        assets: list[ReferenceAsset],
        *,
        candidate_count: int,
        source_path: Path | None,
        input_mode: ImageGenerationInputMode | str = ImageGenerationInputMode.KEYFRAME_EDIT,
        execution_mode: str | None = None,
        allow_unknown_cost: bool = False,
        seed: int | None = None,
        reuse_cache: bool = True,
        run_id: UUID | None = None,
        cancel_event: Any | None = None,
    ) -> tuple[GenerationRun, list[GenerationCandidate]]:
        try:
            selected_input_mode = ImageGenerationInputMode(input_mode)
        except ValueError as exc:
            raise ImageGenerationGatewayError(
                422,
                "image_input_mode_invalid",
                "图片生成输入模式无效",
            ) from exc
        settings = self.settings_service.get()
        if not settings.enabled:
            raise ImageGenerationGatewayError(
                409,
                "image_generation_not_configured",
                "请先在“模型与设置”中校验并启用真实图片生成引擎",
            )
        try:
            selected_mode = ImageExecutionMode(execution_mode or settings.execution_mode)
        except ValueError as exc:
            raise ImageGenerationGatewayError(
                422,
                "image_execution_mode_invalid",
                "图片生成执行模式无效",
            ) from exc
        if selected_mode == ImageExecutionMode.SIMULATED:
            raise ImageGenerationGatewayError(
                422,
                "simulated_override_forbidden",
                "启用真实图片生成后不能通过业务接口切回模拟模式",
            )
        try:
            identity_policy = validate_identity_bindings(bindings, assets)
            validate_identity_generation(
                state=identity_policy,
                input_mode=selected_input_mode,
                source_present=source_path is not None,
            )
        except IdentityPolicyViolation as exc:
            raise ImageGenerationGatewayError(
                exc.status_code,
                exc.code,
                str(exc),
            ) from exc
        if (
            selected_input_mode == ImageGenerationInputMode.KEYFRAME_EDIT
            and (source_path is None or not await asyncio.to_thread(source_path.is_file))
        ):
            raise ImageGenerationGatewayError(
                409,
                "source_keyframe_required",
                "真实图片生成需要可读取的原分镜关键帧",
            )
        if selected_input_mode == ImageGenerationInputMode.TEXT_TO_IMAGE:
            references = ()
            source_path = None
        else:
            try:
                references = build_reference_inputs(
                    bindings,
                    assets,
                    resolve_path=self.workspace.resolve,
                )
            except WorkspaceError as exc:
                raise ImageGenerationGatewayError(
                    409,
                    "reference_path_invalid",
                    "参考资产文件路径无效",
                ) from exc
        for reference in references:
            if not await asyncio.to_thread(reference.path.is_file):
                raise ImageGenerationGatewayError(
                    409,
                    "reference_file_missing",
                    "参考资产文件不存在，请重新上传",
                )
            if _sha256_file(reference.path) != reference.sha256:
                raise ImageGenerationGatewayError(
                    409,
                    "reference_hash_changed",
                    "参考资产文件已发生变化，请重新上传",
                )
        source_sha256 = _sha256_file(source_path) if source_path is not None else None
        identity, adapter = await self._adapter(
            selected_mode,
            settings,
            candidate_count=candidate_count,
        )
        try:
            validate_identity_generation(
                state=identity_policy,
                input_mode=selected_input_mode,
                source_present=source_path is not None,
                references=references,
                capability=identity.capability,
            )
        except IdentityPolicyViolation as exc:
            raise ImageGenerationGatewayError(
                exc.status_code,
                exc.code,
                str(exc),
            ) from exc
        if candidate_count > identity.capability.max_candidates:
            raise ImageGenerationGatewayError(
                422,
                "candidate_count_unsupported",
                f"当前模型或工具最多生成 {identity.capability.max_candidates} 个候选",
            )
        if (
            selected_input_mode == ImageGenerationInputMode.TEXT_TO_IMAGE
            and not identity.capability.text_to_image
        ):
            raise ImageGenerationGatewayError(
                422,
                "text_to_image_unsupported",
                "当前模型或本机工具不支持纯文字生图",
            )
        if (
            selected_input_mode == ImageGenerationInputMode.KEYFRAME_EDIT
            and not identity.capability.image_to_image
        ):
            raise ImageGenerationGatewayError(
                422,
                "image_to_image_unsupported",
                "当前模型或本机工具不支持关键帧编辑",
            )
        if len(references) > identity.capability.max_reference_images:
            raise ImageGenerationGatewayError(
                422,
                "reference_count_unsupported",
                (
                    f"当前模型或工具最多接收 {identity.capability.max_reference_images} 张参考图，"
                    f"当前已绑定 {len(references)} 张"
                ),
            )
        request = ImageGenerationRequest(
            project=project,
            shot=shot,
            revision_id=revision_id,
            input_mode=selected_input_mode,
            source_path=source_path,
            source_sha256=source_sha256,
            references=references,
            candidate_count=candidate_count,
            execution_mode=selected_mode,
            allow_unknown_cost=allow_unknown_cost,
            seed=seed,
        )
        width, height = _output_dimensions(
            project.output_width,
            project.output_height,
            identity.capability,
        )
        prompt = _compiled_prompt(request)
        negative_prompt = _negative_prompt(request)
        input_payload = self._input_payload(
            request,
            identity,
            identity_policy=identity_policy,
            width=width,
            height=height,
            prompt=prompt,
            negative_prompt=negative_prompt,
        )
        fingerprint = self._fingerprint(input_payload)
        run_id = run_id or uuid4()
        run_root = (
            self.workspace.production_shot_root(project.record_id, project.id, shot.id)
            / "images"
            / str(run_id)
        )
        input_path = run_root / "input.json"
        started = time.perf_counter()
        cached = (
            await self._reuse_cached_generation(
                project,
                shot,
                revision_id,
                identity,
                run_id=run_id,
                run_root=run_root,
                input_path=input_path,
                input_payload=input_payload,
                fingerprint=fingerprint,
                candidate_count=candidate_count,
                started=started,
            )
            if reuse_cache
            else None
        )
        if cached is not None:
            return cached
        if (
            identity.cost_source == GenerationCostSource.UNKNOWN
            and not allow_unknown_cost
        ):
            raise ImageGenerationGatewayError(
                409,
                "unknown_cost_confirmation_required",
                "本机工具无法返回可靠成本；确认接受未知成本后才能生成",
            )
        if (
            project.budget_limit_micros is not None
            and identity.cost_estimate_known
            and project.actual_cost_micros + identity.estimated_cost_micros
            > project.budget_limit_micros
        ):
            remaining = max(0, project.budget_limit_micros - project.actual_cost_micros)
            raise ImageGenerationGatewayError(
                409,
                "production_budget_exceeded",
                (
                    f"本次预计成本 ¥{identity.estimated_cost_micros / 1_000_000:.2f}，"
                    f"方案剩余预算 ¥{remaining / 1_000_000:.2f}"
                ),
            )
        _write_atomic(input_path, _canonical_json(input_payload) + b"\n")
        adapter_request = AdapterRequest(
            request_id=run_id,
            run_root=run_root,
            project=project,
            shot=shot,
            input_mode=request.input_mode,
            source_path=source_path,
            source_sha256=source_sha256,
            references=references,
            candidate_count=candidate_count,
            width=width,
            height=height,
            positive_prompt=prompt,
            negative_prompt=negative_prompt,
            seed=request.seed,
            capability=identity.capability,
            cancel_event=cancel_event,
        )
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise ImageGenerationError(409, "generation_cancelled", "图片生成任务已取消")
            if selected_mode == ImageExecutionMode.LOCAL_TOOL:
                concurrency = max(1, int(settings.local_concurrency))
                semaphore = self._local_semaphores.setdefault(
                    concurrency,
                    asyncio.Semaphore(concurrency),
                )
                async with semaphore:
                    async with self.process_slot_limiter.acquire(concurrency):
                        result = await adapter.generate(adapter_request)
            else:
                result = await adapter.generate(adapter_request)
            if cancel_event is not None and cancel_event.is_set():
                raise ImageGenerationError(409, "generation_cancelled", "图片生成任务已取消")
            if not result.images:
                raise ImageGenerationError(
                    502,
                    "generation_candidates_missing",
                    "图片生成任务没有返回候选",
                )
            candidates = [
                _save_candidate(
                    self.workspace,
                    run_root,
                    run_id,
                    index,
                    image,
                    request_fingerprint=fingerprint,
                    provider=identity.provider,
                    model=identity.model,
                    target_width=width,
                    target_height=height,
                    reference_roles={item.role for item in references},
                )
                for index, image in enumerate(result.images, start=1)
            ]
        except ImageGenerationError as exc:
            run = self._failed_run(
                project,
                shot,
                revision_id,
                identity,
                input_mode=request.input_mode,
                input_payload=input_payload,
                run_id=run_id,
                fingerprint=fingerprint,
                input_path=input_path,
                started=started,
                error=exc,
            )
            return run, []

        actual_cost, cost_source = self._actual_cost(
            identity,
            result.actual_cost_micros,
            len(candidates),
        )
        semantic_outcomes: list[SemanticQualityOutcome] = []
        if settings.semantic_quality_enabled:
            remaining_budget = (
                None
                if project.budget_limit_micros is None
                else max(
                    0,
                    project.budget_limit_micros
                    - project.actual_cost_micros
                    - actual_cost,
                )
            )
            reviewed_candidates: list[GenerationCandidate] = []
            reference_paths = tuple(item.path for item in references)
            reference_labels = tuple(
                f"{item.role}：{item.label}" for item in references
            )
            for candidate in candidates:
                if cancel_event is not None and cancel_event.is_set():
                    raise ImageGenerationGatewayError(
                        409,
                        "generation_cancelled",
                        "图片生成任务已取消",
                    )
                outcome = await self.semantic_quality_service.assess(
                    shot=shot,
                    candidate_path=self.workspace.resolve(candidate.relative_path),
                    source_path=source_path,
                    reference_paths=reference_paths,
                    reference_labels=reference_labels,
                    budget_remaining_micros=remaining_budget,
                )
                semantic_outcomes.append(outcome)
                if remaining_budget is not None:
                    remaining_budget = max(
                        0,
                        remaining_budget - outcome.actual_cost_micros,
                    )
                reviewed = candidate.model_copy(
                    update={
                        "quality_report": _merge_semantic_quality(
                            candidate.quality_report,
                            outcome,
                        )
                    }
                )
                _update_candidate_quality_metadata(self.workspace, reviewed)
                reviewed_candidates.append(reviewed)
            candidates = reviewed_candidates

        semantic_estimated_cost = sum(
            outcome.estimated_cost_micros
            for outcome in semantic_outcomes
            if outcome.report.get("status") != "skipped_budget"
        )
        semantic_actual_cost = sum(
            outcome.actual_cost_micros for outcome in semantic_outcomes
        )
        estimated_cost = identity.estimated_cost_micros + semantic_estimated_cost
        actual_cost += semantic_actual_cost
        if semantic_actual_cost > 0:
            cost_source = GenerationCostSource.PROVIDER_REPORTED
        usage_payload: dict[str, Any] = result.usage
        if semantic_outcomes:
            usage_payload = {
                "image_generation": result.usage,
                "semantic_quality": _sum_model_usage(semantic_outcomes),
                "semantic_quality_cost_micros": semantic_actual_cost,
            }
        execution_summary = dict(identity.execution_summary)
        execution_summary["identity_policy"] = input_payload["identity_policy"]
        execution_summary["input_manifest"] = input_payload["input_manifest"]
        execution_summary["semantic_quality"] = {
            "enabled": settings.semantic_quality_enabled,
            "candidate_count": len(semantic_outcomes),
            "estimated_cost_micros": semantic_estimated_cost,
            "actual_cost_micros": semantic_actual_cost,
        }
        manifest_path = run_root / "manifest.json"
        manifest = {
            "schema_version": "viral-dna-image-generation-result/v1",
            "status": "completed",
            "request_id": str(run_id),
            "provider_request_id": result.provider_request_id,
            "candidate_ids": [str(item.id) for item in candidates],
            "candidate_sha256": [item.sha256 for item in candidates],
            "quality_statuses": [
                item.quality_report.get("status", "unknown") for item in candidates
            ],
            "usage": usage_payload,
            "semantic_quality": [outcome.report for outcome in semantic_outcomes],
            "identity_policy": input_payload["identity_policy"],
            "input_manifest": input_payload["input_manifest"],
            "estimated_cost_micros": estimated_cost,
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
            kind=GenerationKind.IMAGE,
            input_mode=request.input_mode,
            provider=identity.provider,
            model=identity.model,
            model_snapshot=identity.model_snapshot,
            prompt_version=IMAGE_PROMPT_VERSION,
            schema_version=IMAGE_REQUEST_SCHEMA_VERSION,
            pricing_version=(
                identity.model_option.pricing_version
                if identity.model_option is not None
                else "local-tool-cost-v1"
            ),
            request_fingerprint=fingerprint,
            input_snapshot_relative_path=self.workspace.relative(input_path),
            execution_mode=identity.execution_mode,
            adapter_id=identity.adapter_id,
            adapter_version=identity.adapter_version,
            protocol_version=identity.protocol_version,
            provider_request_id=result.provider_request_id,
            capability_snapshot=identity.capability.model_dump(mode="json"),
            execution_summary=execution_summary,
            cost_source=cost_source,
            cost_estimate_known=identity.cost_estimate_known,
            usage=usage_payload,
            output_manifest_relative_path=self.workspace.relative(manifest_path),
            status=ProductionRunStatus.COMPLETED,
            estimated_cost_micros=estimated_cost,
            actual_cost_micros=actual_cost,
            latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
            completed_at=completed_at,
        )
        return run, candidates

    @staticmethod
    def _fingerprint(input_payload: dict[str, Any]) -> str:
        source = input_payload["source"]
        references = input_payload["references"]
        stable_payload = {
            "schema_version": input_payload["schema_version"],
            "input_mode": input_payload["input_mode"],
            "execution": input_payload["execution"],
            "output": input_payload["output"],
            "prompt": input_payload["prompt"],
            "seed": input_payload["seed"],
            "source": {"sha256": source["sha256"]} if source is not None else None,
            "references": [
                {
                    "role": item["role"],
                    "sha256": item["sha256"],
                    "weight": item["weight"],
                    "crop_hint": item["crop_hint"],
                    "notes": item["notes"],
                }
                for item in references
            ],
            "locks": input_payload["locks"],
            "identity_policy": input_payload["identity_policy"],
        }
        return hashlib.sha256(_canonical_json(stable_payload)).hexdigest()

    async def _reuse_cached_generation(
        self,
        project: ProductionProject,
        shot: ShotPlan,
        revision_id: UUID,
        identity: AdapterIdentity,
        *,
        run_id: UUID,
        run_root: Path,
        input_path: Path,
        input_payload: dict[str, Any],
        fingerprint: str,
        candidate_count: int,
        started: float,
    ) -> tuple[GenerationRun, list[GenerationCandidate]] | None:
        if self.repository is None:
            return None
        runs = await self.repository.list_generation_runs(project.id, shot.id)
        for source_run in reversed(runs):
            if (
                source_run.request_fingerprint != fingerprint
                or source_run.status
                not in {ProductionRunStatus.COMPLETED, ProductionRunStatus.CACHED}
            ):
                continue
            source_candidates = await self.repository.list_generation_candidates(
                source_run.id
            )
            if len(source_candidates) != candidate_count:
                continue
            reusable = True
            for candidate in source_candidates:
                try:
                    content_path = self.workspace.resolve(candidate.relative_path)
                    metadata_path = self.workspace.resolve(candidate.metadata_relative_path)
                    if (
                        not await asyncio.to_thread(
                            _filesystem_path(content_path).is_file
                        )
                        or not await asyncio.to_thread(
                            _filesystem_path(metadata_path).is_file
                        )
                        or await asyncio.to_thread(_sha256_file, content_path)
                        != candidate.sha256
                    ):
                        reusable = False
                        break
                    if candidate.thumbnail_relative_path:
                        thumbnail_path = self.workspace.resolve(
                            candidate.thumbnail_relative_path
                        )
                        if not await asyncio.to_thread(
                            _filesystem_path(thumbnail_path).is_file
                        ):
                            reusable = False
                            break
                except (OSError, WorkspaceError):
                    reusable = False
                    break
            if not reusable:
                continue

            candidates = [
                GenerationCandidate(
                    generation_run_id=run_id,
                    ordinal=item.ordinal,
                    kind=item.kind,
                    relative_path=item.relative_path,
                    thumbnail_relative_path=item.thumbnail_relative_path,
                    width=item.width,
                    height=item.height,
                    duration_seconds=item.duration_seconds,
                    sha256=item.sha256,
                    metadata_relative_path=item.metadata_relative_path,
                    quality_report=(
                        item.quality_report
                        or {
                            "schema_version": "viral-dna-image-quality/v1",
                            "status": "legacy_manual_review_required",
                            "summary": "缓存来源是旧候选；请人工核对人物、产品和异常文字。",
                            "manual_checks": [],
                        }
                    ),
                )
                for item in source_candidates
            ]
            _write_atomic(input_path, _canonical_json(input_payload) + b"\n")
            manifest_path = run_root / "manifest.json"
            manifest = {
                "schema_version": "viral-dna-image-generation-result/v1",
                "status": "cached",
                "request_id": str(run_id),
                "cache_source_run_id": str(source_run.id),
                "candidate_ids": [str(item.id) for item in candidates],
                "candidate_sha256": [item.sha256 for item in candidates],
                "estimated_cost_micros": 0,
                "actual_cost_micros": 0,
                "cost_source": GenerationCostSource.UNMETERED.value,
            }
            _write_atomic(manifest_path, _canonical_json(manifest) + b"\n")
            completed_at = datetime.now(UTC)
            run = GenerationRun(
                id=run_id,
                project_id=project.id,
                shot_plan_id=shot.id,
                revision_id=revision_id,
                kind=GenerationKind.IMAGE,
                input_mode=ImageGenerationInputMode(
                    input_payload.get("input_mode", ImageGenerationInputMode.KEYFRAME_EDIT)
                ),
                provider=identity.provider,
                model=identity.model,
                model_snapshot=identity.model_snapshot,
                prompt_version=IMAGE_PROMPT_VERSION,
                schema_version=IMAGE_REQUEST_SCHEMA_VERSION,
                pricing_version=(
                    identity.model_option.pricing_version
                    if identity.model_option is not None
                    else "local-tool-cost-v1"
                ),
                request_fingerprint=fingerprint,
                input_snapshot_relative_path=self.workspace.relative(input_path),
                execution_mode=identity.execution_mode,
                adapter_id=identity.adapter_id,
                adapter_version=identity.adapter_version,
                protocol_version=identity.protocol_version,
                capability_snapshot=identity.capability.model_dump(mode="json"),
                execution_summary={
                    **identity.execution_summary,
                    "cache_hit": True,
                    "cache_source_run_id": str(source_run.id),
                    "identity_policy": input_payload["identity_policy"],
                    "input_manifest": input_payload["input_manifest"],
                },
                cost_source=GenerationCostSource.UNMETERED,
                cost_estimate_known=True,
                usage={"cache_hit": True, "source_run_id": str(source_run.id)},
                output_manifest_relative_path=self.workspace.relative(manifest_path),
                status=ProductionRunStatus.CACHED,
                estimated_cost_micros=0,
                actual_cost_micros=0,
                latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
                completed_at=completed_at,
            )
            return run, candidates
        return None

    async def _generate_simulated(
        self,
        project: ProductionProject,
        shot: ShotPlan,
        revision_id: UUID,
        bindings: list[ReferenceBinding],
        assets: list[ReferenceAsset],
        *,
        candidate_count: int,
        source_path: Path | None,
        input_mode: ImageGenerationInputMode,
    ) -> tuple[GenerationRun, list[GenerationCandidate]]:
        return await asyncio.to_thread(
            generate_simulated_images,
            self.workspace,
            project,
            shot,
            revision_id,
            bindings,
            assets,
            candidate_count=candidate_count,
            source_path=source_path,
            input_mode=input_mode,
        )

    async def _adapter(
        self,
        mode: ImageExecutionMode,
        settings: Any,
        *,
        candidate_count: int,
    ) -> tuple[AdapterIdentity, Any]:
        if mode == ImageExecutionMode.REMOTE_API:
            try:
                catalog = load_image_model_catalog()
                option = catalog.option(settings.remote_model_alias)
            except ImageModelCatalogError as exc:
                raise ImageGenerationGatewayError(
                    503,
                    "image_catalog_unavailable",
                    str(exc),
                ) from exc
            api_key = get_config_value("DASHSCOPE_API_KEY", "").strip()
            if not api_key:
                raise ImageGenerationGatewayError(
                    409,
                    "image_api_key_required",
                    "国内 API 模式尚未配置 API Key",
                )
            base_url = settings.remote_base_url
            identity = AdapterIdentity(
                execution_mode=mode,
                provider=option.provider,
                model=option.model,
                model_snapshot=f"{option.model}@{catalog.catalog_version}",
                adapter_id=IMAGE_ADAPTER_ID,
                adapter_version=IMAGE_ADAPTER_VERSION,
                protocol_version="dashscope-multimodal-generation/v1",
                capability=option.capabilities,
                model_option=option,
                estimated_cost_micros=option.unit_cost_micros * candidate_count,
                cost_estimate_known=True,
                cost_source=GenerationCostSource.CONFIGURED_RATE,
                execution_summary={
                    "endpoint_host": urlsplit(base_url).hostname,
                    "catalog_version": catalog.catalog_version,
                },
            )
            return identity, DashScopeQwenImageAdapter(
                identity=identity,
                api_key=api_key,
                base_url=base_url,
                timeout_seconds=300,
            )

        if not settings.local_executable_path:
            raise ImageGenerationGatewayError(
                409,
                "local_tool_not_configured",
                "本机工具模式尚未配置可执行文件",
            )
        proxy_environment_url = local_tool_proxy_environment_url(
            settings.local_adapter_id,
            settings.local_proxy_mode,
            settings.local_proxy_effective_url,
            settings.local_proxy_source,
        )
        proxy_delivery = local_tool_proxy_delivery(
            settings.local_adapter_id,
            settings.local_proxy_mode,
            settings.local_proxy_effective_url,
            settings.local_proxy_source,
        )
        try:
            detection = await detect_local_tool(
                settings.local_executable_path,
                settings.local_fixed_args,
                timeout_seconds=min(120, settings.local_timeout_seconds),
                expected_protocol=settings.local_protocol_version,
                proxy_url=proxy_environment_url,
            )
        except ImageGenerationError as exc:
            raise ImageGenerationGatewayError(
                exc.status_code,
                exc.code,
                str(exc),
                retryable=exc.retryable,
            ) from exc
        source = settings.local_cost_source
        unit_cost = settings.local_unit_cost_micros or 0
        known = source in {
            GenerationCostSource.CONFIGURED_RATE,
            GenerationCostSource.UNMETERED,
        }
        estimated = (
            unit_cost * candidate_count if source == GenerationCostSource.CONFIGURED_RATE else 0
        )
        resolved_executable = await asyncio.to_thread(Path(settings.local_executable_path).resolve)
        executable_path_hash = hashlib.sha256(str(resolved_executable).encode("utf-8")).hexdigest()
        identity = AdapterIdentity(
            execution_mode=mode,
            provider="local_tool",
            model=settings.local_model or detection.tool_id,
            model_snapshot=(
                f"{settings.local_model}@{detection.tool_version}"
                if settings.local_model
                else detection.tool_version
            ),
            adapter_id=settings.local_adapter_id,
            adapter_version=GATEWAY_VERSION,
            protocol_version=detection.protocol_version,
            capability=detection.capability,
            model_option=None,
            estimated_cost_micros=estimated,
            cost_estimate_known=known,
            cost_source=source,
            execution_summary={
                "executable_name": Path(settings.local_executable_path).name,
                "executable_path_sha256": executable_path_hash,
                "fixed_arg_count": len(settings.local_fixed_args),
                "concurrency_limit": settings.local_concurrency,
                "model_policy": settings.local_model_policy,
                "model": settings.local_model,
                "reasoning_effort": settings.local_reasoning_effort,
                "proxy_source": settings.local_proxy_source,
                "proxy_enabled": bool(settings.local_proxy_effective_url),
                "proxy_delivery": proxy_delivery,
                "windows_sandbox_mode": settings.local_windows_sandbox_mode,
            },
        )
        return identity, LocalToolImageAdapter(
            identity=identity,
            executable_path=settings.local_executable_path,
            fixed_args=settings.local_fixed_args,
            timeout_seconds=settings.local_timeout_seconds,
            proxy_url=proxy_environment_url,
        )

    @staticmethod
    def _actual_cost(
        identity: AdapterIdentity,
        reported: int | None,
        image_count: int,
    ) -> tuple[int, GenerationCostSource]:
        if reported is not None:
            return reported, GenerationCostSource.PROVIDER_REPORTED
        if identity.cost_source == GenerationCostSource.CONFIGURED_RATE:
            if identity.model_option is not None:
                return (
                    identity.model_option.unit_cost_micros * image_count,
                    GenerationCostSource.CONFIGURED_RATE,
                )
            unit = identity.estimated_cost_micros // max(1, image_count)
            return unit * image_count, GenerationCostSource.CONFIGURED_RATE
        return 0, identity.cost_source

    def _input_payload(
        self,
        request: ImageGenerationRequest,
        identity: AdapterIdentity,
        *,
        identity_policy: IdentityPolicyState,
        width: int,
        height: int,
        prompt: str,
        negative_prompt: str,
    ) -> dict[str, Any]:
        input_manifest = build_input_manifest(
            source_present=request.source_path is not None,
            references=request.references,
        )
        identity_snapshot = policy_snapshot(
            state=identity_policy,
        )
        return {
            "schema_version": IMAGE_REQUEST_SCHEMA_VERSION,
            "input_mode": request.input_mode.value,
            "project_id": str(request.project.id),
            "shot_plan_id": str(request.shot.id),
            "revision_id": str(request.revision_id),
            "execution": {
                "mode": identity.execution_mode.value,
                "provider": identity.provider,
                "model": identity.model,
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
                "candidate_count": request.candidate_count,
            },
            "prompt": {
                "positive": prompt,
                "negative": negative_prompt,
                "version": IMAGE_PROMPT_VERSION,
                "asset_mentions": [
                    {
                        "asset_id": str(item.reference_asset_id),
                        "label": item.label,
                    }
                    for item in request.shot.image_prompt_mentions
                ],
            },
            "seed": request.seed,
            "source": (
                {
                    "relative_url": request.shot.source_keyframe_url,
                    "sha256": request.source_sha256,
                }
                if request.source_path is not None and request.source_sha256 is not None
                else None
            ),
            "references": [
                {
                    "asset_id": str(item.asset_id),
                    "name": item.name,
                    "role": item.role,
                    "relative_path": item.relative_path,
                    "sha256": item.sha256,
                    "weight": item.weight,
                    "crop_hint": item.crop_hint,
                    "notes": item.notes,
                }
                for item in request.references
            ],
            "identity_policy": identity_snapshot,
            "input_manifest": input_manifest,
            "locks": [item.value for item in request.shot.locks],
            "cost": {
                "estimated_cost_micros": identity.estimated_cost_micros,
                "estimate_known": identity.cost_estimate_known,
                "source": identity.cost_source.value,
            },
        }

    def _failed_run(
        self,
        project: ProductionProject,
        shot: ShotPlan,
        revision_id: UUID,
        identity: AdapterIdentity,
        *,
        input_mode: ImageGenerationInputMode,
        input_payload: dict[str, Any],
        run_id: UUID,
        fingerprint: str,
        input_path: Path,
        started: float,
        error: ImageGenerationError,
    ) -> GenerationRun:
        return GenerationRun(
            id=run_id,
            project_id=project.id,
            shot_plan_id=shot.id,
            revision_id=revision_id,
            kind=GenerationKind.IMAGE,
            input_mode=input_mode,
            provider=identity.provider,
            model=identity.model,
            model_snapshot=identity.model_snapshot,
            prompt_version=IMAGE_PROMPT_VERSION,
            schema_version=IMAGE_REQUEST_SCHEMA_VERSION,
            pricing_version=(
                identity.model_option.pricing_version
                if identity.model_option is not None
                else "local-tool-cost-v1"
            ),
            request_fingerprint=fingerprint,
            input_snapshot_relative_path=self.workspace.relative(input_path),
            execution_mode=identity.execution_mode,
            adapter_id=identity.adapter_id,
            adapter_version=identity.adapter_version,
            protocol_version=identity.protocol_version,
            capability_snapshot=identity.capability.model_dump(mode="json"),
            execution_summary={
                **identity.execution_summary,
                "identity_policy": input_payload["identity_policy"],
                "input_manifest": input_payload["input_manifest"],
            },
            cost_source=identity.cost_source,
            cost_estimate_known=identity.cost_estimate_known,
            status=ProductionRunStatus.FAILED,
            estimated_cost_micros=identity.estimated_cost_micros,
            actual_cost_micros=0,
            latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
            error_code=error.code,
            error_message=str(error),
            completed_at=datetime.now(UTC),
        )
