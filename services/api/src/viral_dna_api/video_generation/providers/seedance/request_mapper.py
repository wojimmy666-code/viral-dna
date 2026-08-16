from __future__ import annotations

from ...contracts import ProviderVideoRequest
from ...media_transport import image_data_url, require_public_media_url


def build_seedance_request(request: ProviderVideoRequest) -> dict[str, object]:
    managed_images = tuple(
        reference
        for reference in request.managed_asset_references
        if reference.media_type == "image"
    )
    managed_videos = tuple(
        reference
        for reference in request.managed_asset_references
        if reference.media_type == "video"
    )
    text = request.prompt.replace("图号顺序", "图片编号顺序")
    for frame in reversed(request.reference_frames):
        text = text.replace(
            f"图{frame.ordinal}",
            f"图片{frame.ordinal + len(managed_images)}",
        )
    if managed_images:
        identity_label = "图片1"
    elif managed_videos:
        identity_label = "视频1"
    else:
        identity_label = ""
    if identity_label:
        text = (
            f"{identity_label}是本分镜唯一演员身份来源；必须保持该人物的身份、面部、"
            "年龄与稳定外观特征。后续参考画面只提供姿态、动作、构图、服装或场景，"
            "禁止继承其中人物的身份、年龄和五官。\n"
            f"{text}"
        )
    if request.reference_videos:
        motion_labels = "、".join(
            f"视频{index}"
            for index in range(
                len(managed_videos) + 1,
                len(managed_videos) + len(request.reference_videos) + 1,
            )
        )
        text = (
            f"{motion_labels}是无身份、无纹理的动作代理，只用于人物位置、姿态变化、"
            "动作节奏和镜头运动；不得把代理外观当作人物身份或服装来源。\n"
            f"{text}"
        )
    if request.negative_prompt:
        text = f"{text}\n避免：{request.negative_prompt[:500]}"
    text = text[:2000]
    managed_content = [
        {
            "type": "image_url" if reference.media_type == "image" else "video_url",
            "image_url" if reference.media_type == "image" else "video_url": {
                "url": reference.uri
            },
            "role": (
                "reference_image" if reference.media_type == "image" else "reference_video"
            ),
        }
        for reference in request.managed_asset_references
        if reference.media_type in {"image", "video"}
    ]
    payload: dict[str, object] = {
        "model": request.provider_model,
        "content": [
            {"type": "text", "text": text},
            *managed_content,
            *[
                {
                    "type": "video_url",
                    "video_url": {"url": require_public_media_url(video)},
                    "role": "reference_video",
                }
                for video in request.reference_videos
            ],
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
