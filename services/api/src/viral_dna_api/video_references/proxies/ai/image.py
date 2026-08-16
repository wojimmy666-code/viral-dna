from __future__ import annotations

import asyncio
import hashlib
import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from ....image_generation.gateway import (
    ImageGenerationGateway,
    ImageGenerationGatewayError,
)
from ...domain import (
    ReferenceProxyEngineClass,
    ReferenceProxyKind,
    ReferenceProxyPrivacyMode,
    ReferenceProxyQualityStatus,
    ReferenceProxyRenderProfile,
    VideoReferenceMediaType,
)
from ..contracts import (
    ProxyEngineCapability,
    ProxyEnhancementError,
    ProxyEnhancementRequest,
    ProxyGenerationOutput,
)
from ..dwpose import DWPoseWholeBodyEngine
from .prompts import IMAGE_MANNEQUIN_NEGATIVE_PROMPT, IMAGE_MANNEQUIN_PROMPT
from .quality import validate_ai_proxy


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _model_hash(provider: str, model: str, snapshot: str) -> str:
    return hashlib.sha256(f"{provider}|{model}|{snapshot}".encode()).hexdigest()


def _save_png(payload: bytes, destination: Path, thumbnail: Path) -> None:
    try:
        with Image.open(BytesIO(payload)) as source:
            rendered = source.convert("RGB")
            destination.parent.mkdir(parents=True, exist_ok=True)
            rendered.save(destination, format="PNG", optimize=True)
            preview = rendered.copy()
            preview.thumbnail((720, 720), Image.Resampling.LANCZOS)
            preview.save(thumbnail, format="PNG", optimize=True)
    except (OSError, ValueError) as exc:
        raise RuntimeError("图片模型返回的 AI 白模文件无法读取") from exc


class QwenMannequinImageEnhancer:
    """Render an anonymous DWPose image with the configured DashScope model."""

    def __init__(
        self,
        gateway: ImageGenerationGateway,
        verifier: DWPoseWholeBodyEngine,
    ) -> None:
        self.gateway = gateway
        self.verifier = verifier

    @property
    def capability(self) -> ProxyEngineCapability:
        # Settings are edited from the GUI, so readiness must not be frozen at
        # API startup time.
        return self._capability()

    def _capability(self) -> ProxyEngineCapability:
        settings = self.gateway.settings_service.get()
        selected = next(
            (
                item
                for item in settings.models
                if item.alias == settings.remote_model_alias
            ),
            None,
        )
        remote_selected = settings.execution_mode.value == "remote_api"
        available = bool(
            settings.enabled
            and remote_selected
            and settings.api_key_configured
            and settings.selected_capabilities
            and settings.selected_capabilities.image_to_image
            and self.verifier.capability.available
        )
        if available:
            note = "百炼图片模型已就绪；仅上传 DWPose 匿名结构图"
        elif not self.verifier.capability.available:
            note = "AI 图片白模依赖 DWPose WholeBody，请先完成安装"
        elif not settings.enabled or not settings.api_key_configured:
            note = "请先在模型与设置中配置并校验百炼图片 API Key"
        elif not remote_selected:
            note = "AI 图片白模当前只使用国内 API 模式，不会调用本机 imagegen"
        else:
            note = "当前图片模型不支持结构图编辑"
        return ProxyEngineCapability(
            engine="qwen_mannequin_image",
            version="1.0.0",
            kinds=(ReferenceProxyKind.POSE_PROXY_IMAGE,),
            available=available,
            availability_note=note,
            production_ready=True,
            wholebody=True,
            hand_keypoints=True,
            runtime_provider="dashscope",
            engine_class=ReferenceProxyEngineClass.GENERATIVE_REMOTE,
            render_profiles=(ReferenceProxyRenderProfile.AI_ENHANCED,),
            privacy_modes=(ReferenceProxyPrivacyMode.ANONYMOUS_STRUCTURE_ONLY,),
            provider=settings.remote_provider,
            model=(selected.model if selected else settings.remote_model),
            estimated_unit_cost_micros=(selected.unit_cost_micros if selected else None),
            cost_estimate_known=selected is not None,
        )

    async def enhance(self, request: ProxyEnhancementRequest) -> ProxyGenerationOutput:
        if request.kind != ReferenceProxyKind.POSE_PROXY_IMAGE:
            raise RuntimeError("百炼 AI 白模引擎只支持图片姿态代理")
        if request.privacy_mode != ReferenceProxyPrivacyMode.ANONYMOUS_STRUCTURE_ONLY:
            raise RuntimeError("AI 图片白模必须使用仅上传匿名结构稿的隐私模式")
        if not self.capability.available:
            raise RuntimeError(self.capability.availability_note or "AI 图片白模引擎未就绪")
        try:
            identity, result = await self.gateway.generate_auxiliary_image(
                project=request.project,
                shot=request.shot,
                source_path=request.base_output.path,
                run_root=request.run_root / "provider",
                positive_prompt=IMAGE_MANNEQUIN_PROMPT,
                negative_prompt=IMAGE_MANNEQUIN_NEGATIVE_PROMPT,
                allow_unknown_cost=request.allow_unknown_cost,
            )
        except ImageGenerationGatewayError as exc:
            raise RuntimeError(str(exc)) from exc

        try:
            generated = result.images[0]
            await asyncio.to_thread(
                _save_png,
                generated.payload,
                request.destination_path,
                request.thumbnail_path,
            )

            verification_root = request.run_root / "verification"
            verification_output = await asyncio.to_thread(
                self.verifier.generate,
                source_path=request.destination_path,
                destination_path=verification_root / "proxy.png",
                thumbnail_path=verification_root / "thumbnail.png",
                kind=ReferenceProxyKind.POSE_PROXY_IMAGE,
            )
            if (
                request.base_output.manifest_path is None
                or verification_output.manifest_path is None
            ):
                raise RuntimeError("AI 图片白模缺少姿态质检清单")
            report = await asyncio.to_thread(
                validate_ai_proxy,
                reference_manifest=request.base_output.manifest_path,
                candidate_manifest=verification_output.manifest_path,
                candidate_path=request.destination_path,
                media_type="image",
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
                    "schema": "viraldna.ai-mannequin-image/v1",
                    "base_engine": (
                        request.base_output.base_engine or "dwpose_wholebody_mannequin"
                    ),
                    "provider": identity.provider,
                    "provider_model": identity.model,
                    "raw_source_uploaded": False,
                }
            )
            _write_json(manifest_path, manifest_payload)
            quality_path = request.destination_path.with_name("quality-report.json")
            _write_json(
                quality_path,
                {
                    "status": report.status.value,
                    "score": report.score,
                    "metrics": report.metrics,
                    "message": report.message,
                },
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProxyEnhancementError(
                str(exc),
                provider=identity.provider,
                provider_model=identity.model,
                provider_request_id=result.provider_request_id,
                estimated_cost_micros=identity.estimated_cost_micros,
                actual_cost_micros=result.actual_cost_micros,
                cost_estimate_known=identity.cost_estimate_known,
                actual_cost_known=result.actual_cost_micros is not None,
            ) from exc
        return ProxyGenerationOutput(
            path=request.destination_path,
            thumbnail_path=request.thumbnail_path,
            media_type=VideoReferenceMediaType.IMAGE,
            identity_removed=True,
            validation_message=report.message,
            semantic_validation_status=report.status,
            quality_score=report.score,
            quality_metrics=report.metrics,
            manifest_path=manifest_path,
            quality_report_path=quality_path,
            model_sha256=_model_hash(
                identity.provider,
                identity.model,
                identity.model_snapshot,
            ),
            requested_render_profile=ReferenceProxyRenderProfile.AI_ENHANCED,
            effective_render_profile=ReferenceProxyRenderProfile.AI_ENHANCED,
            privacy_mode=request.privacy_mode,
            base_engine=request.base_output.base_engine or "dwpose_wholebody_mannequin",
            base_engine_version=request.base_output.base_engine_version or "1.0.0",
            provider=identity.provider,
            provider_model=identity.model,
            provider_request_id=result.provider_request_id,
            raw_source_uploaded=False,
            estimated_cost_micros=identity.estimated_cost_micros,
            actual_cost_micros=result.actual_cost_micros,
            cost_estimate_known=identity.cost_estimate_known,
            actual_cost_known=result.actual_cost_micros is not None,
        )
