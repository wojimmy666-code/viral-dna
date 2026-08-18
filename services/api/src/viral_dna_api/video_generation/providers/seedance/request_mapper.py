from __future__ import annotations

from ...contracts import ProviderVideoRequest
from ...media_transport import image_data_url, require_public_media_url

ROLE_LABELS = {
    "actor_identity": "人物身份与稳定外观",
    "scene": "环境、空间材质与灯光",
    "wardrobe": "服装款式、材质与颜色",
    "product": "产品结构与外观",
    "composition": "构图与画面布局",
    "first_frame": "起始构图",
    "last_frame": "结束构图",
    "transition": "转场目标画面",
}


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
    lines = [request.prompt.replace("图号顺序", "图片编号顺序")]
    for frame in reversed(request.reference_frames):
        lines[0] = lines[0].replace(
            f"图{frame.ordinal}",
            f"图片{frame.ordinal + len(managed_images)}",
        )
    material_rules: list[str] = ["素材职责（必须严格遵守）："]
    if managed_images or managed_videos:
        identity_label = "图片1" if managed_images else "视频1"
        material_rules.append(
            f"- {identity_label} 是唯一演员身份来源，决定人物身份、面部、年龄与稳定外观。"
        )
    for index, frame in enumerate(request.reference_frames, start=len(managed_images) + 1):
        purpose = ROLE_LABELS.get(frame.role, "构图与画面信息")
        material_rules.append(f"- 图片{index} 只提供{purpose}。")
    if request.depth_control_videos:
        start = len(managed_videos) + 1
        labels = "、".join(
            f"视频{index}"
            for index in range(start, start + len(request.depth_control_videos))
        )
        material_rules.extend(
            [
                f"- {labels} 是全场景深度控制视频，只提供动作、身体位置、遮挡关系、"
                "空间深度和镜头轨迹。",
                "- 禁止从深度视频继承灰度外观、人物身份、五官、年龄、服装、颜色、"
                "纹理、原场景、灯光、文字或水印。",
                "- 使用人物、服装、产品和场景图片对深度结构重新着色并重建画面。",
            ]
        )
    text = "\n".join([*material_rules, *lines])
    if request.negative_prompt:
        text = f"{text}\n避免：{request.negative_prompt[:500]}"
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
            {"type": "text", "text": text[:2000]},
            *managed_content,
            *[
                {
                    "type": "video_url",
                    "video_url": {"url": require_public_media_url(video)},
                    "role": "reference_video",
                }
                for video in request.depth_control_videos
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
