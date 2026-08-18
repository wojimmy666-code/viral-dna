from __future__ import annotations

from ...contracts import ProviderVideoRequest
from ...media_transport import image_data_url, require_public_media_url


def build_minimax_h3_request(request: ProviderVideoRequest) -> dict[str, object]:
    prompt = request.prompt
    include_depth_video = (
        request.route_id == "minimax_identity_depth_guidance"
        and bool(request.depth_control_videos)
    )
    if include_depth_video:
        prompt = (
            "图片1是唯一人物身份与外观来源；其他图片按各自角色提供场景、服装、产品或构图。"
            "参考视频是全场景深度控制，只提供动作、位置、遮挡、空间深度和镜头轨迹。"
            "禁止继承深度视频中的灰度、人物身份、五官、服装、纹理、颜色或原场景。\n"
            f"{prompt}"
        )
    if request.negative_prompt:
        prompt = f"{prompt}\n负面约束：{request.negative_prompt}"
    return {
        "model": request.provider_model,
        "content": [
            {"type": "text", "text": prompt[:7000]},
            *[
                {
                    "type": "image_url",
                    "image_url": {"url": image_data_url(frame.path)},
                    "role": "reference_image",
                }
                for frame in request.reference_frames
            ],
            *(
                [
                    {
                        "type": "video_url",
                        "video_url": {"url": require_public_media_url(video)},
                        "role": "reference_video",
                    }
                    for video in request.depth_control_videos
                ]
                if include_depth_video
                else []
            ),
        ],
        "duration": round(request.duration_seconds),
        "resolution": request.resolution,
        "ratio": request.aspect_ratio,
        "aigc_watermark": False,
    }
