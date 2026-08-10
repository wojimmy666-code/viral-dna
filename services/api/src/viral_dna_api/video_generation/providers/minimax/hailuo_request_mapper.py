from __future__ import annotations

from ...contracts import ProviderVideoRequest
from ...media_transport import image_data_url


def build_minimax_hailuo_request(request: ProviderVideoRequest) -> dict[str, object]:
    prompt = request.prompt[:2000]
    if request.negative_prompt:
        prompt = f"{prompt}\nAvoid: {request.negative_prompt[:500]}"
    return {
        "model": request.provider_model,
        "prompt": prompt,
        "first_frame_image": image_data_url(request.reference_frames[0].path),
        "duration": round(request.duration_seconds),
        "resolution": request.resolution,
        "prompt_optimizer": True,
    }
