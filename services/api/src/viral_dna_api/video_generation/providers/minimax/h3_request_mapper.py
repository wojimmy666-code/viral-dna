from __future__ import annotations

from ...contracts import ProviderVideoRequest
from ...media_transport import image_data_url


def build_minimax_h3_request(request: ProviderVideoRequest) -> dict[str, object]:
    prompt = request.prompt
    if request.negative_prompt:
        prompt = f"{prompt}\nNegative constraints: {request.negative_prompt}"
    return {
        "model": request.provider_model,
        "content": [
            {"type": "text", "text": prompt[:7000]},
            {
                "type": "image_url",
                "image_url": {"url": image_data_url(request.first_frame_path)},
                "role": "first_frame",
            },
        ],
        "duration": round(request.duration_seconds),
        "resolution": request.resolution,
        "aigc_watermark": False,
    }
