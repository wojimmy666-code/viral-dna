from __future__ import annotations

from typing import Any

from .types import PoseObservation

BODY_CONNECTIONS = (
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
)


def _point(pose: PoseObservation, index: int, threshold: float = 0.2) -> tuple[int, int] | None:
    if index >= len(pose.scores) or float(pose.scores[index]) < threshold:
        return None
    return tuple(round(float(value)) for value in pose.keypoints[index])


def _limb_width(pose: PoseObservation) -> int:
    shoulder_left, shoulder_right = _point(pose, 5), _point(pose, 6)
    if shoulder_left and shoulder_right:
        distance = (
            (shoulder_left[0] - shoulder_right[0]) ** 2
            + (shoulder_left[1] - shoulder_right[1]) ** 2
        ) ** 0.5
        return max(5, round(distance * 0.16))
    x1, _y1, x2, _y2 = pose.bbox
    return max(5, round((x2 - x1) * 0.07))


def render_mannequin(
    pose: PoseObservation | None,
    *,
    width: int,
    height: int,
    cv2: Any,
    np: Any,
) -> Any:
    """Render a featureless mannequin without copying any source pixels."""

    canvas = np.full((height, width, 3), (224, 226, 230), dtype=np.uint8)
    for y in range(height):
        level = 224 - round(18 * y / max(1, height - 1))
        canvas[y, :, :] = (level + 4, level + 3, level)
    if pose is None:
        return canvas
    white = (248, 248, 246)
    outline = (196, 198, 202)
    limb_width = _limb_width(pose)
    for start, end in BODY_CONNECTIONS:
        point_a, point_b = _point(pose, start), _point(pose, end)
        if point_a is None or point_b is None:
            continue
        cv2.line(canvas, point_a, point_b, outline, limb_width + 4, cv2.LINE_AA)
        cv2.line(canvas, point_a, point_b, white, limb_width, cv2.LINE_AA)
        cv2.circle(canvas, point_a, limb_width // 2, white, -1, cv2.LINE_AA)
        cv2.circle(canvas, point_b, limb_width // 2, white, -1, cv2.LINE_AA)

    shoulders = (_point(pose, 5), _point(pose, 6))
    hips = (_point(pose, 11), _point(pose, 12))
    if all((*shoulders, *hips)):
        torso = np.array([shoulders[0], shoulders[1], hips[1], hips[0]], dtype=np.int32)
        cv2.fillConvexPoly(canvas, torso, outline, cv2.LINE_AA)
        inset_center = torso.mean(axis=0)
        inset = ((torso - inset_center) * 0.91 + inset_center).astype(np.int32)
        cv2.fillConvexPoly(canvas, inset, white, cv2.LINE_AA)

    nose = _point(pose, 0, 0.18)
    left_ear, right_ear = _point(pose, 3, 0.18), _point(pose, 4, 0.18)
    if nose is not None:
        if left_ear and right_ear:
            radius = max(
                limb_width,
                round(
                    ((left_ear[0] - right_ear[0]) ** 2 + (left_ear[1] - right_ear[1]) ** 2)
                    ** 0.5
                    * 0.72
                ),
            )
        else:
            radius = max(limb_width * 2, round((pose.bbox[2] - pose.bbox[0]) * 0.09))
        cv2.circle(canvas, nose, radius + 2, outline, -1, cv2.LINE_AA)
        cv2.circle(canvas, nose, radius, white, -1, cv2.LINE_AA)

    for offset in (91, 112):
        hand_width = max(2, limb_width // 3)
        for finger_start in (1, 5, 9, 13, 17):
            chain = [offset, *range(offset + finger_start, offset + finger_start + 4)]
            for start, end in zip(chain, chain[1:], strict=False):
                point_a, point_b = _point(pose, start, 0.18), _point(pose, end, 0.18)
                if point_a and point_b:
                    cv2.line(canvas, point_a, point_b, white, hand_width, cv2.LINE_AA)
        palm = [
            _point(pose, index, 0.18)
            for index in (offset, offset + 5, offset + 9, offset + 13, offset + 17)
        ]
        if all(palm):
            cv2.fillConvexPoly(canvas, np.array(palm, dtype=np.int32), white, cv2.LINE_AA)
    return canvas
