from __future__ import annotations

from ...contracts import ProviderVideoRequest
from ...media_transport import image_data_url


def build_seedance_request(request: ProviderVideoRequest) -> dict[str, object]:
    text = request.prompt.replace("图号顺序", "图片编号顺序")
    for frame in reversed(request.reference_frames):
        text = text.replace(f"图{frame.ordinal}", f"图片{frame.ordinal}")
    text = text[:2000]
    if request.negative_prompt:
        text = f"{text}\n避免：{request.negative_prompt[:500]}"
    payload: dict[str, object] = {
        "model": request.provider_model,
        "content": [
            {"type": "text", "text": text},
            *[
                {
                    "type": "image_url",
                    "image_url": {"url": image_data_url(frame.path)},
                    "role": "reference_image",
                }
                for frame in request.reference_frames
            ],
        ],
        "duration": round(request.duration_seconds),
        "ratio": request.aspect_ratio,
        "resolution": request.resolution.lower(),
        "generate_audio": False,
        "watermark": False,
    }
    if request.seed is not None:
        payload["seed"] = request.seed
    return payload
