from __future__ import annotations

from ...contracts import ProviderVideoRequest
from ...media_transport import image_data_url


def _image_part(path) -> dict[str, str]:
    data_url = image_data_url(path)
    header, encoded = data_url.split(",", 1)
    mime_type = header.removeprefix("data:").split(";", 1)[0]
    return {"type": "image", "data": encoded, "mime_type": mime_type}


def _replace_frame_labels(text: str, request: ProviderVideoRequest) -> str:
    mapped = text
    use_reference_tags = len(request.reference_frames) > 2
    for index, frame in reversed(list(enumerate(request.reference_frames))):
        label = f"<IMAGE_REF_{index}>" if use_reference_tags else f"Image{index + 1}"
        mapped = mapped.replace(f"图片{frame.ordinal}", label)
        mapped = mapped.replace(f"图{frame.ordinal}", label)
    return mapped


def _reference_instructions(request: ProviderVideoRequest) -> list[str]:
    frames = request.reference_frames
    if len(frames) == 1:
        return [
            "[# Sources <FIRST_FRAME>@Image1]",
            "Use Image1 as the exact starting frame and preserve its visual identity.",
        ]
    if len(frames) == 2:
        return [
            "[# Sources <FIRST_FRAME>@Image1 <LAST_FRAME>@Image2]",
            "Use Image1 as the first frame and Image2 as the last frame, "
            "with a continuous transition between them.",
        ]
    declarations = " ".join(
        f"<IMAGE_REF_{index}>@Image{index + 1}" for index in range(len(frames))
    )
    timing = []
    for index, frame in enumerate(frames):
        start = max(0.0, frame.start_ratio * request.duration_seconds)
        end = min(request.duration_seconds, frame.end_ratio * request.duration_seconds)
        timing.append(
            f"[{start:.2f}-{end:.2f}s] Follow the composition and subject "
            f"continuity of <IMAGE_REF_{index}>."
        )
    return [
        f"[# References {declarations}]",
        "Use the reference images in the supplied order; preserve identities, "
        "products, scene continuity and camera direction.",
        *timing,
    ]


def build_gemini_omni_request(request: ProviderVideoRequest) -> dict[str, object]:
    prompt_lines = [
        *_reference_instructions(request),
        _replace_frame_labels(request.prompt, request),
    ]
    if request.negative_prompt:
        prompt_lines.append(f"Do not include: {request.negative_prompt[:1000]}")
    if request.generate_audio:
        prompt_lines.append("Generate synchronized native audio that follows the scene and action.")
    else:
        prompt_lines.append(
            "No dialogue, no music, and no sound effects. "
            "Keep the generated soundtrack silent."
        )
    prompt = "\n".join(line for line in prompt_lines if line.strip())[:10_000]
    resolution = request.resolution.lower()
    payload: dict[str, object] = {
        "model": request.provider_model,
        "input": [
            *[_image_part(frame.path) for frame in request.reference_frames],
            {"type": "text", "text": prompt},
        ],
        "response_format": {
            "type": "video",
            "aspect_ratio": request.aspect_ratio,
            "duration": f"{round(request.duration_seconds):d}s",
            "resolution": resolution,
            "delivery": "uri" if resolution in {"1080p", "4k"} else "inline",
        },
        "generation_config": {
            "video_config": {
                "task": (
                    "reference_to_video"
                    if len(request.reference_frames) > 2
                    else "image_to_video"
                )
            }
        },
        "background": True,
        "store": True,
        "stream": False,
    }
    return payload
