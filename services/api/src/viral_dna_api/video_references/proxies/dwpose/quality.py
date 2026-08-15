from __future__ import annotations

from .types import PoseObservation, PoseQualityReport

BODY_INDICES = tuple(range(5, 17))
CORE_INDICES = (5, 6, 11, 12)
LEFT_HAND_INDICES = tuple(range(91, 112))
RIGHT_HAND_INDICES = tuple(range(112, 133))


def _visible_ratio(pose: PoseObservation, indices: tuple[int, ...], threshold: float) -> float:
    valid = [index for index in indices if index < len(pose.scores)]
    if not valid:
        return 0.0
    return sum(float(pose.scores[index]) >= threshold for index in valid) / len(valid)


def image_quality(
    pose: PoseObservation,
    *,
    frame_width: int,
    frame_height: int,
    person_count: int,
) -> PoseQualityReport:
    body = _visible_ratio(pose, BODY_INDICES, 0.25)
    core = _visible_ratio(pose, CORE_INDICES, 0.3)
    left_hand = _visible_ratio(pose, LEFT_HAND_INDICES, 0.2)
    right_hand = _visible_ratio(pose, RIGHT_HAND_INDICES, 0.2)
    x1, y1, x2, y2 = pose.bbox
    area_ratio = max(0.0, x2 - x1) * max(0.0, y2 - y1) / max(
        1, frame_width * frame_height
    )
    ambiguity = person_count > 1
    score = min(
        1.0,
        0.42 * body
        + 0.28 * core
        + 0.12 * min(1.0, area_ratio / 0.12)
        + 0.09 * left_hand
        + 0.09 * right_hand,
    )
    if body < 0.5 or core < 0.5 or area_ratio < 0.012:
        status = "failed"
        message = "主体姿态关键点不足，不能可靠传递人物动作"
    elif ambiguity or score < 0.58:
        status = "review_required"
        message = "已生成姿态代理，但存在多人或低置信关键点，请人工核对"
    else:
        status = "passed"
        message = "WholeBody 姿态、主体位置与身份去除检查通过"
    return PoseQualityReport(
        status=status,
        score=round(score, 4),
        metrics={
            "body_visible_ratio": round(body, 4),
            "core_visible_ratio": round(core, 4),
            "left_hand_visible_ratio": round(left_hand, 4),
            "right_hand_visible_ratio": round(right_hand, 4),
            "person_bbox_area_ratio": round(area_ratio, 4),
            "detected_person_count": person_count,
            "multiple_people_ambiguous": ambiguity,
        },
        message=message,
    )


def video_quality(
    sequence: list[PoseObservation | None],
    *,
    fps: float,
    interpolated_frames: int,
    raw_detected_frames: int,
) -> PoseQualityReport:
    total = max(1, len(sequence))
    detected = sum(item is not None for item in sequence)
    coverage = detected / total
    raw_coverage = max(0, min(raw_detected_frames, total)) / total
    longest_gap = 0
    current_gap = 0
    body_ratios: list[float] = []
    for item in sequence:
        if item is None:
            current_gap += 1
            longest_gap = max(longest_gap, current_gap)
        else:
            current_gap = 0
            body_ratios.append(_visible_ratio(item, BODY_INDICES, 0.25))
    mean_body = sum(body_ratios) / len(body_ratios) if body_ratios else 0.0
    longest_gap_seconds = longest_gap / max(1.0, fps)
    score = min(1.0, 0.52 * raw_coverage + 0.18 * coverage + 0.3 * mean_body)
    if (
        coverage < 0.7
        or raw_coverage < 0.55
        or mean_body < 0.45
        or longest_gap_seconds > 0.75
    ):
        status = "failed"
        message = "视频姿态覆盖不足或连续丢失过长，不能可靠传递动作"
    elif (
        coverage < 0.88
        or raw_coverage < 0.75
        or mean_body < 0.58
        or longest_gap_seconds > 0.35
    ):
        status = "review_required"
        message = "视频动作代理存在短时姿态缺失，请人工播放核对"
    else:
        status = "passed"
        message = "视频主体跟踪、短缺失插值与姿态覆盖检查通过"
    return PoseQualityReport(
        status=status,
        score=round(score, 4),
        metrics={
            "frame_count": len(sequence),
            "pose_coverage_ratio": round(coverage, 4),
            "raw_pose_coverage_ratio": round(raw_coverage, 4),
            "mean_body_visible_ratio": round(mean_body, 4),
            "interpolated_frame_count": interpolated_frames,
            "longest_missing_gap_seconds": round(longest_gap_seconds, 4),
        },
        message=message,
    )
