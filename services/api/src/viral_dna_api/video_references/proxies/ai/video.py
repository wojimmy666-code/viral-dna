from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from ....models import VideoProviderTaskStatus
from ....video_generation.catalog import load_video_model_catalog
from ....video_generation.contracts import OrderedReferenceVideo, ProviderVideoRequest
from ....video_generation.errors import VideoProviderError
from ....video_generation.media_transport import download_provider_video
from ....video_generation.providers.seedance import SeedanceVideoProvider
from ....video_generation.settings import VideoGenerationSettingsService
from ...domain import (
    ReferenceProxyEngineClass,
    ReferenceProxyKind,
    ReferenceProxyPrivacyMode,
    ReferenceProxyQualityStatus,
    ReferenceProxyRenderProfile,
    VideoReferenceMediaType,
)
from ..browser_video import FfmpegBrowserVideoEncoder
from ..contracts import (
    ProxyEngineCapability,
    ProxyEnhancementError,
    ProxyEnhancementRequest,
    ProxyGenerationOutput,
)
from ..dwpose import DWPoseWholeBodyEngine
from .prompts import VIDEO_MANNEQUIN_NEGATIVE_PROMPT, VIDEO_MANNEQUIN_PROMPT
from .quality import validate_ai_proxy


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _model_hash(provider: str, model: str, version: str) -> str:
    return hashlib.sha256(f"{provider}|{model}|{version}".encode()).hexdigest()


def _aspect_ratio(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "16:9"
    ratio = width / height
    candidates = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1, "4:3": 4 / 3, "3:4": 3 / 4}
    return min(candidates, key=lambda label: abs(candidates[label] - ratio))


def _extract_thumbnail(source: Path, destination: Path) -> None:
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("AI 视频白模无法提取预览帧：OpenCV 未安装") from exc
    capture = cv2.VideoCapture(str(source))
    ok, frame = capture.read() if capture.isOpened() else (False, None)
    capture.release()
    if not ok or frame is None:
        raise RuntimeError("AI 视频白模无法读取预览帧")
    success, encoded = cv2.imencode(".png", frame)
    if not success:
        raise RuntimeError("AI 视频白模无法编码预览帧")
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(str(destination))


class SeedanceMannequinVideoEnhancer:
    """Render a higher-fidelity mannequin from an anonymous DWPose video only."""

    MODEL_ALIAS = "seedance_2_0_fast"

    def __init__(
        self,
        settings: VideoGenerationSettingsService,
        verifier: DWPoseWholeBodyEngine,
        *,
        provider: SeedanceVideoProvider | None = None,
        video_encoder: FfmpegBrowserVideoEncoder | None = None,
    ) -> None:
        self.settings = settings
        self.verifier = verifier
        self.provider = provider or SeedanceVideoProvider()
        self.video_encoder = video_encoder or FfmpegBrowserVideoEncoder()
        self.spec = load_video_model_catalog().option(self.MODEL_ALIAS)

    @property
    def capability(self) -> ProxyEngineCapability:
        # Provider credentials and enabled models can change through the GUI.
        return self._capability()

    def _capability(self) -> ProxyEngineCapability:
        settings = self.settings.get()
        provider_settings = next(
            (item for item in settings.providers if item.provider == "volc_ark"),
            None,
        )
        available = bool(
            settings.enabled
            and provider_settings
            and provider_settings.api_key_configured
            and self.spec.available
            and self.verifier.capability.available
        )
        if available:
            note = "Seedance AI 视频白模已就绪；只上传 DWPose 匿名动作视频"
        elif not self.verifier.capability.available:
            note = "AI 视频白模依赖 DWPose WholeBody，请先完成安装"
        elif not provider_settings or not provider_settings.api_key_configured:
            note = "请先在模型与设置中配置并校验火山方舟 API Key"
        else:
            note = self.spec.availability_note or "Seedance AI 视频白模当前不可用"
        return ProxyEngineCapability(
            engine="seedance_mannequin_video",
            version="1.0.0",
            kinds=(ReferenceProxyKind.MOTION_PROXY_VIDEO,),
            available=available,
            availability_note=note,
            production_ready=True,
            wholebody=True,
            hand_keypoints=True,
            video_tracking=True,
            runtime_provider="volc_ark",
            engine_class=ReferenceProxyEngineClass.GENERATIVE_REMOTE,
            render_profiles=(ReferenceProxyRenderProfile.AI_ENHANCED,),
            privacy_modes=(ReferenceProxyPrivacyMode.ANONYMOUS_STRUCTURE_ONLY,),
            provider=self.spec.provider,
            model=self.spec.model,
            estimated_unit_cost_micros=None,
            cost_estimate_known=False,
        )

    async def _poll(self, task_id: str, *, api_key: str, base_url: str):
        settings = self.settings.get()
        deadline = asyncio.get_running_loop().time() + settings.task_timeout_seconds
        while True:
            result = await self.provider.poll(
                task_id,
                api_key=api_key,
                base_url=base_url,
                provider_model=self.spec.model,
            )
            if result.status in {
                VideoProviderTaskStatus.SUCCEEDED,
                VideoProviderTaskStatus.FAILED,
                VideoProviderTaskStatus.CANCELLED,
            }:
                return result
            if asyncio.get_running_loop().time() >= deadline:
                await self.provider.cancel(
                    task_id,
                    api_key=api_key,
                    base_url=base_url,
                    provider_model=self.spec.model,
                )
                raise RuntimeError("AI 视频白模生成超时，已尝试取消上游任务")
            await asyncio.sleep(settings.poll_interval_seconds)

    async def enhance(self, request: ProxyEnhancementRequest) -> ProxyGenerationOutput:
        if request.kind != ReferenceProxyKind.MOTION_PROXY_VIDEO:
            raise RuntimeError("Seedance AI 白模引擎只支持视频动作代理")
        if request.privacy_mode != ReferenceProxyPrivacyMode.ANONYMOUS_STRUCTURE_ONLY:
            raise RuntimeError("AI 视频白模必须使用仅上传匿名结构稿的隐私模式")
        if not self.capability.available:
            raise RuntimeError(self.capability.availability_note or "AI 视频白模引擎未就绪")
        if not request.allow_unknown_cost:
            raise RuntimeError("Seedance 白模费用暂不可预估，请确认未知成本后再生成")

        duration = max(0.1, float(request.duration_seconds or 0))
        provider_duration = min(
            self.spec.capability.maximum_duration_seconds,
            max(self.spec.capability.minimum_duration_seconds, round(duration)),
        )
        width = max(256, int(request.project.output_width))
        height = max(256, int(request.project.output_height))
        base_sha256 = await asyncio.to_thread(
            lambda: hashlib.sha256(request.base_output.path.read_bytes()).hexdigest()
        )
        reference = OrderedReferenceVideo(
            proxy_asset_id=request.request_id,
            visual_beat_id=request.shot.visual_beats[0].id,
            ordinal=1,
            title="匿名 DWPose 动作结构",
            path=request.base_output.path,
            relative_path=str(request.base_output.path),
            sha256=base_sha256,
            role="motion",
        )
        provider_request = ProviderVideoRequest(
            request_id=request.request_id,
            ordinal=1,
            model_alias=self.spec.alias,
            provider_model=self.spec.model or "",
            prompt=VIDEO_MANNEQUIN_PROMPT,
            negative_prompt=VIDEO_MANNEQUIN_NEGATIVE_PROMPT,
            reference_frames=(),
            reference_videos=(reference,),
            duration_seconds=provider_duration,
            resolution="720P",
            aspect_ratio=_aspect_ratio(width, height),
            width=width,
            height=height,
            route_id="anonymous_motion_proxy_render",
            effective_route_id="anonymous_motion_proxy_render",
            motion_semantics="structural_control",
            reference_manifest={
                "raw_source_uploaded": False,
                "source": "dwpose_wholebody_mannequin",
            },
        )
        api_key = self.settings.api_key("volc_ark")
        base_url = self.settings.base_url("volc_ark")
        try:
            submitted = await self.provider.submit(
                provider_request,
                api_key=api_key,
                base_url=base_url,
            )
            await asyncio.to_thread(
                _write_json,
                request.run_root / "provider-task.json",
                {
                    "task_id": submitted.task_id,
                    "submitted_at": datetime.now(UTC).isoformat(),
                    "response": submitted.raw,
                    "raw_source_uploaded": False,
                },
            )
            result = await self._poll(submitted.task_id, api_key=api_key, base_url=base_url)
        except VideoProviderError as exc:
            raise ProxyEnhancementError(
                str(exc),
                provider=self.spec.provider,
                provider_model=self.spec.model,
                provider_request_id=(submitted.task_id if "submitted" in locals() else None),
            ) from exc
        if result.status != VideoProviderTaskStatus.SUCCEEDED or not result.output_url:
            raise ProxyEnhancementError(
                result.error_message or "Seedance 未返回可用的 AI 视频白模",
                provider=self.spec.provider,
                provider_model=self.spec.model,
                provider_request_id=submitted.task_id,
                actual_cost_micros=result.actual_cost_micros,
                actual_cost_known=result.cost_known,
            )

        try:
            downloaded = request.run_root / "provider" / "generated.mp4"
            await download_provider_video(result.output_url, downloaded)
            await asyncio.to_thread(
                self.video_encoder.encode_segment,
                downloaded,
                request.destination_path,
                duration_seconds=duration,
            )
            await asyncio.to_thread(
                _extract_thumbnail,
                request.destination_path,
                request.thumbnail_path,
            )

            verification_root = request.run_root / "verification"
            verification_output = await asyncio.to_thread(
                self.verifier.generate,
                source_path=request.destination_path,
                destination_path=verification_root / "proxy.mp4",
                thumbnail_path=verification_root / "thumbnail.png",
                kind=ReferenceProxyKind.MOTION_PROXY_VIDEO,
            )
            if (
                request.base_output.manifest_path is None
                or verification_output.manifest_path is None
            ):
                raise RuntimeError("AI 视频白模缺少动作质检清单")
            report = await asyncio.to_thread(
                validate_ai_proxy,
                reference_manifest=request.base_output.manifest_path,
                candidate_manifest=verification_output.manifest_path,
                candidate_path=request.destination_path,
                media_type="video",
                base_quality_score=request.base_output.quality_score,
            )
            if report.status != ReferenceProxyQualityStatus.PASSED:
                raise RuntimeError(report.message)

            manifest_path = request.destination_path.with_name("pose-manifest.json")
            manifest_payload = json.loads(
                verification_output.manifest_path.read_text(encoding="utf-8")
            )
            manifest_payload.update(
                {
                    "schema": "viraldna.ai-mannequin-video/v1",
                    "base_engine": (
                        request.base_output.base_engine or "dwpose_wholebody_mannequin"
                    ),
                    "provider": self.spec.provider,
                    "provider_model": self.spec.model,
                    "provider_task_id": submitted.task_id,
                    "raw_source_uploaded": False,
                }
            )
            await asyncio.to_thread(_write_json, manifest_path, manifest_payload)
            quality_path = request.destination_path.with_name("quality-report.json")
            await asyncio.to_thread(
                _write_json,
                quality_path,
                {
                    "status": report.status.value,
                    "score": report.score,
                    "metrics": report.metrics,
                    "message": report.message,
                },
            )
        except (OSError, RuntimeError, ValueError, VideoProviderError) as exc:
            if isinstance(exc, ProxyEnhancementError):
                raise
            raise ProxyEnhancementError(
                str(exc),
                provider=self.spec.provider,
                provider_model=self.spec.model,
                provider_request_id=submitted.task_id,
                actual_cost_micros=result.actual_cost_micros,
                actual_cost_known=result.cost_known,
            ) from exc
        return ProxyGenerationOutput(
            path=request.destination_path,
            thumbnail_path=request.thumbnail_path,
            media_type=VideoReferenceMediaType.VIDEO,
            identity_removed=True,
            validation_message=report.message,
            semantic_validation_status=report.status,
            quality_score=report.score,
            quality_metrics=report.metrics,
            manifest_path=manifest_path,
            quality_report_path=quality_path,
            model_sha256=_model_hash(
                self.spec.provider,
                self.spec.model or "",
                self.capability.version,
            ),
            requested_render_profile=ReferenceProxyRenderProfile.AI_ENHANCED,
            effective_render_profile=ReferenceProxyRenderProfile.AI_ENHANCED,
            privacy_mode=request.privacy_mode,
            base_engine=request.base_output.base_engine or "dwpose_wholebody_mannequin",
            base_engine_version=request.base_output.base_engine_version or "1.0.0",
            provider=self.spec.provider,
            provider_model=self.spec.model,
            provider_request_id=submitted.task_id,
            raw_source_uploaded=False,
            estimated_cost_micros=None,
            actual_cost_micros=result.actual_cost_micros,
            cost_estimate_known=False,
            actual_cost_known=result.cost_known,
        )
