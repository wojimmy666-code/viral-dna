from __future__ import annotations

from typing import Any

from .types import PoseObservation

CORE_INDICES = (5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)


def _bbox_area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _bbox_iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = _bbox_area(left) + _bbox_area(right) - intersection
    return intersection / union if union > 0 else 0.0


def choose_primary(
    observations: list[PoseObservation],
    *,
    previous: PoseObservation | None = None,
) -> PoseObservation | None:
    if not observations:
        return None
    if previous is None:
        return max(
            observations,
            key=lambda item: _bbox_area(item.bbox) * max(0.05, item.detection_score),
        )
    previous_area = max(1.0, _bbox_area(previous.bbox))

    def continuity(item: PoseObservation) -> float:
        visible = [
            index
            for index in CORE_INDICES
            if index < len(item.scores)
            and index < len(previous.scores)
            and item.scores[index] >= 0.25
            and previous.scores[index] >= 0.25
        ]
        if visible:
            distances = [
                float(
                    ((item.keypoints[index] - previous.keypoints[index]) ** 2).sum()
                    ** 0.5
                )
                for index in visible
            ]
            normalized_distance = sum(distances) / len(distances) / (previous_area**0.5)
            pose_score = max(0.0, 1.0 - normalized_distance)
        else:
            pose_score = 0.0
        return (
            0.5 * _bbox_iou(previous.bbox, item.bbox)
            + 0.35 * pose_score
            + 0.15 * item.detection_score
        )

    return max(observations, key=continuity)


def interpolate_short_gaps(
    sequence: list[PoseObservation | None],
    *,
    max_gap_frames: int,
    np: Any,
) -> tuple[list[PoseObservation | None], int]:
    result = list(sequence)
    interpolated = 0
    cursor = 0
    while cursor < len(result):
        if result[cursor] is not None:
            cursor += 1
            continue
        start = cursor
        while cursor < len(result) and result[cursor] is None:
            cursor += 1
        end = cursor
        gap = end - start
        left = result[start - 1] if start > 0 else None
        right = result[end] if end < len(result) else None
        if left is None or right is None or gap > max_gap_frames:
            continue
        for offset in range(gap):
            ratio = (offset + 1) / (gap + 1)
            keypoints = left.keypoints * (1 - ratio) + right.keypoints * ratio
            scores = np.minimum(left.scores, right.scores) * 0.9
            bbox = tuple(
                float(a * (1 - ratio) + b * ratio)
                for a, b in zip(left.bbox, right.bbox, strict=True)
            )
            result[start + offset] = PoseObservation(
                keypoints=keypoints,
                scores=scores,
                bbox=bbox,
                detection_score=min(left.detection_score, right.detection_score) * 0.9,
            )
            interpolated += 1
    return result, interpolated


def smooth_sequence(
    sequence: list[PoseObservation | None],
    *,
    alpha: float = 0.62,
    np: Any,
) -> list[PoseObservation | None]:
    smoothed: list[PoseObservation | None] = []
    previous: PoseObservation | None = None
    for item in sequence:
        if item is None:
            smoothed.append(None)
            previous = None
            continue
        if previous is None:
            current = item
        else:
            visibility = (item.scores >= 0.2) & (previous.scores >= 0.2)
            keypoints = item.keypoints.copy()
            keypoints[visibility] = (
                alpha * item.keypoints[visibility]
                + (1 - alpha) * previous.keypoints[visibility]
            )
            current = PoseObservation(
                keypoints=keypoints,
                scores=np.maximum(item.scores, previous.scores * 0.85),
                bbox=tuple(
                    float(alpha * a + (1 - alpha) * b)
                    for a, b in zip(item.bbox, previous.bbox, strict=True)
                ),
                detection_score=item.detection_score,
            )
        smoothed.append(current)
        previous = current
    return smoothed
