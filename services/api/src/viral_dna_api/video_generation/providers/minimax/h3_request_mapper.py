from __future__ import annotations

from ...contracts import ProviderVideoRequest
from ...media_transport import image_data_url, video_data_url


def build_minimax_h3_request(request: ProviderVideoRequest) -> dict[str, object]:
    prompt = request.prompt
    include_motion_video = (
        request.route_id == "minimax_identity_image_motion_proxy"
        and request.effective_route_id == "minimax_identity_image_motion_proxy"
        and bool(request.reference_videos)
    )
    if include_motion_video:
        prompt = (
            "图片1是唯一人物身份与外观来源；参考视频只提供动作节奏、姿态变化和镜头运动，"
            "不得继承其中的身份、五官、年龄、服装或纹理。\n"
            f"{prompt}"
        )
    elif request.effective_route_id == "pose_image_text_fallback":
        prompt = (
            "使用参考图保持目标人物身份；按文字描述还原动作。当前未提交动作视频，"
            "不要假设存在强姿态控制。\n"
            f"{prompt}"
        )
    if request.negative_prompt:
        prompt = f"{prompt}\nNegative constraints: {request.negative_prompt}"
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
                        "video_url": {"url": video_data_url(video.path)},
                        "role": "reference_video",
                    }
                    for video in request.reference_videos
                ]
                if include_motion_video
                else []
            ),
        ],
        "duration": round(request.duration_seconds),
        "resolution": request.resolution,
        "ratio": request.aspect_ratio,
        "aigc_watermark": False,
    }
