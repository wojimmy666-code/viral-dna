from __future__ import annotations

from ...contracts import ProviderVideoRequest
from ...media_transport import image_data_url


def build_bailian_request(request: ProviderVideoRequest) -> dict[str, object]:
    parameters: dict[str, object] = {
        "resolution": request.resolution,
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
                    "type": "first_frame",
                    "url": image_data_url(request.first_frame_path),
                }
            ],
        },
        "parameters": parameters,
    }
