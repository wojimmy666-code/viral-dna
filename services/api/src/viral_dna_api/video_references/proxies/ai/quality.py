from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...domain import ReferenceProxyQualityStatus


@dataclass(frozen=True, slots=True)
class AIProxyQualityReport:
    status: ReferenceProxyQualityStatus
    score: float
    metrics: dict[str, float | int | str | bool]
    message: str


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("AI 白模姿态清单无法读取") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("AI 白模姿态清单格式无效")
    return payload


def _poses(payload: dict[str, Any]) -> list[dict[str, Any] | None]:
    if isinstance(payload.get("pose"), dict):
        return [payload["pose"]]
    frames = payload.get("frames")
    if isinstance(frames, list):
        return [item if isinstance(item, dict) else None for item in frames]
    return []


def _sample(values: list[Any], count: int = 16) -> list[Any]:
    if len(values) <= count:
        return values
    return [
        values[round(index * (len(values) - 1) / (count - 1))]
        for index in range(count)
    ]


def _point_map(pose: dict[str, Any] | None) -> dict[int, tuple[float, float, float]]:
    if not pose:
        return {}
    result: dict[int, tuple[float, float, float]] = {}
    for raw in pose.get("keypoints") or []:
        if not isinstance(raw, dict):
            continue
        try:
            result[int(raw["index"])] = (
                float(raw["x"]),
                float(raw["y"]),
                float(raw.get("score") or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _bbox_iou(left: dict[str, Any] | None, right: dict[str, Any] | None) -> float:
    if not left or not right:
        return 0.0
    try:
        ax1, ay1, ax2, ay2 = [float(item) for item in left["bbox"]]
        bx1, by1, bx2, by2 = [float(item) for item in right["bbox"]]
    except (KeyError, TypeError, ValueError):
        return 0.0
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(
        0.0, min(ay2, by2) - max(ay1, by1)
    )
    union = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1) + max(
        0.0, bx2 - bx1
    ) * max(0.0, by2 - by1) - intersection
    return intersection / union if union > 0 else 0.0


def _pose_fidelity(
    reference_manifest: Path,
    candidate_manifest: Path,
) -> tuple[float, float, float, int]:
    reference = _sample(_poses(_load(reference_manifest)))
    candidate = _sample(_poses(_load(candidate_manifest)))
    pair_count = min(len(reference), len(candidate))
    if pair_count < 1:
        return 1.0, 0.0, 0.0, 0
    errors: list[float] = []
    overlaps: list[float] = []
    matched_frames = 0
    for index in range(pair_count):
        ref_pose = reference[round(index * (len(reference) - 1) / max(1, pair_count - 1))]
        out_pose = candidate[round(index * (len(candidate) - 1) / max(1, pair_count - 1))]
        ref_points = _point_map(ref_pose)
        out_points = _point_map(out_pose)
        common = [
            key
            for key in set(ref_points).intersection(out_points)
            if ref_points[key][2] >= 0.2 and out_points[key][2] >= 0.2
        ]
        body_common = [key for key in common if 5 <= key <= 16]
        if len(body_common) < 4:
            continue
        matched_frames += 1
        errors.extend(
            math.hypot(
                ref_points[key][0] - out_points[key][0],
                ref_points[key][1] - out_points[key][1],
            )
            for key in common
        )
        overlaps.append(_bbox_iou(ref_pose, out_pose))
    mean_error = sum(errors) / len(errors) if errors else 1.0
    mean_iou = sum(overlaps) / len(overlaps) if overlaps else 0.0
    coverage = matched_frames / pair_count
    return mean_error, mean_iou, coverage, matched_frames


def _face_scan(path: Path, *, media_type: str) -> tuple[int, int, bool]:
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError:
        return 0, 0, False
    cascade_root = getattr(getattr(cv2, "data", None), "haarcascades", "")
    classifier = cv2.CascadeClassifier(
        str(Path(cascade_root) / "haarcascade_frontalface_default.xml")
    )
    if classifier.empty():
        return 0, 0, False
    frames: list[Any] = []
    if media_type == "image":
        frame = cv2.imread(str(path))
        if frame is not None:
            frames.append(frame)
    else:
        capture = cv2.VideoCapture(str(path))
        if capture.isOpened():
            total = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 1))
            for frame_index in sorted({round(i * (total - 1) / 11) for i in range(12)}):
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if ok:
                    frames.append(frame)
        capture.release()
    detected = 0
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        detected += len(
            classifier.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(36, 36),
            )
        )
    return detected, len(frames), True


def validate_ai_proxy(
    *,
    reference_manifest: Path,
    candidate_manifest: Path,
    candidate_path: Path,
    media_type: str,
    base_quality_score: float | None,
) -> AIProxyQualityReport:
    mean_error, bbox_iou, coverage, matched_frames = _pose_fidelity(
        reference_manifest,
        candidate_manifest,
    )
    face_count, sampled_frames, face_gate_available = _face_scan(
        candidate_path,
        media_type=media_type,
    )
    base_score = float(base_quality_score or 0)
    fidelity = max(0.0, 1.0 - mean_error / 0.22)
    score = max(
        0.0,
        min(1.0, 0.5 * fidelity + 0.2 * bbox_iou + 0.15 * coverage + 0.15 * base_score),
    )
    strict_error = 0.12 if media_type == "image" else 0.14
    passed = bool(
        face_gate_available
        and face_count == 0
        and matched_frames >= 1
        and mean_error <= strict_error
        and bbox_iou >= 0.4
        and coverage >= (1.0 if media_type == "image" else 0.55)
    )
    if passed:
        status = ReferenceProxyQualityStatus.PASSED
        message = "AI 白模身份去除、姿态一致性和主体构图检查通过"
    elif face_count > 0:
        status = ReferenceProxyQualityStatus.FAILED
        message = "AI 白模检测到人脸样式区域，已禁止提交并回退本机结构白模"
    elif not face_gate_available:
        status = ReferenceProxyQualityStatus.FAILED
        message = "AI 白模身份门禁不可用，已失败关闭并回退本机结构白模"
    else:
        status = ReferenceProxyQualityStatus.REVIEW_REQUIRED
        message = "AI 白模姿态或构图偏离结构稿，已禁止自动提交"
    return AIProxyQualityReport(
        status=status,
        score=round(score, 4),
        metrics={
            "pose_mean_normalized_error": round(mean_error, 5),
            "person_bbox_iou": round(bbox_iou, 5),
            "matched_frame_ratio": round(coverage, 5),
            "matched_frame_count": matched_frames,
            "face_like_region_count": face_count,
            "identity_scan_frame_count": sampled_frames,
            "identity_gate_available": face_gate_available,
            "raw_source_uploaded": False,
        },
        message=message,
    )
