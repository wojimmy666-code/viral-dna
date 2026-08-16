from __future__ import annotations

from ...contracts import ProviderVideoRequest
from ...errors import VideoProviderError
from ...media_transport import image_data_url


def _build_wan_r2v_request(request: ProviderVideoRequest) -> dict[str, object]:
    parameters: dict[str, object] = {
        "resolution": request.resolution,
        "ratio": request.aspect_ratio,
        "duration": round(request.duration_seconds),
        "prompt_extend": True,
        "watermark": False,
    }
    if request.seed is not None:
        parameters["seed"] = request.seed
    return {
        "model": request.provider_model,
        "input": {
            "prompt": request.prompt[:5000],
            "negative_prompt": request.negative_prompt[:500],
            "media": [
                {
                    "type": "reference_image",
                    "url": image_data_url(frame.path),
                }
                for frame in request.reference_frames
            ],
        },
        "parameters": parameters,
    }


def _public_media_urls(request: ProviderVideoRequest) -> tuple[str, str]:
    values = request.reference_manifest.get("provider_media_urls")
    media = values if isinstance(values, dict) else {}
    identity_url = str(media.get("identity_image_url") or "").strip()
    control_url = str(media.get("control_video_url") or "").strip()
    if not identity_url.startswith(("https://", "http://")) or not control_url.startswith(
        ("https://", "http://")
    ):
        raise VideoProviderError(
            409,
            "video_public_media_transport_required",
            "Wan VACE 要求 Provider 可访问的目标人物图片 URL 和白模控制视频 URL；"
            "请先配置媒体暂存服务",
        )
    return identity_url, control_url


def _build_wan_vace_request(request: ProviderVideoRequest) -> dict[str, object]:
    identity_url, control_url = _public_media_urls(request)
    return {
        "model": request.provider_model,
        "input": {
            "prompt": request.prompt[:5000],
            "function": "video_repainting",
            "video_url": control_url,
            "ref_images_url": [identity_url],
        },
        "parameters": {
            "control_condition": request.control_condition or "posebody",
            "strength": 1.0,
            "prompt_extend": False,
            "watermark": False,
        },
    }


def build_bailian_request(request: ProviderVideoRequest) -> dict[str, object]:
    if request.route_id == "wan_vace_posebody_repaint":
        return _build_wan_vace_request(request)
    return _build_wan_r2v_request(request)
