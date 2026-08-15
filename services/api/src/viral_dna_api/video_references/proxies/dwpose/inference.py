from __future__ import annotations

from pathlib import Path
from typing import Any

from .types import PoseObservation


def _nms(boxes: Any, scores: Any, threshold: float, np: Any) -> list[int]:
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        index = int(order[0])
        keep.append(index)
        xx1 = np.maximum(x1[index], x1[order[1:]])
        yy1 = np.maximum(y1[index], y1[order[1:]])
        xx2 = np.minimum(x2[index], x2[order[1:]])
        yy2 = np.minimum(y2[index], y2[order[1:]])
        width = np.maximum(0, xx2 - xx1 + 1)
        height = np.maximum(0, yy2 - yy1 + 1)
        overlap = width * height / (areas[index] + areas[order[1:]] - width * height)
        order = order[np.where(overlap <= threshold)[0] + 1]
    return keep


class DWPoseOnnxEstimator:
    """Small ONNX Runtime adapter for the official DWPose detector and pose model."""

    def __init__(self, detector_path: Path, pose_path: Path) -> None:
        try:
            import cv2  # type: ignore[import-not-found]
            import numpy as np  # type: ignore[import-not-found]
            import onnxruntime as ort  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional runtime
            raise RuntimeError("缺少 DWPose 运行依赖：opencv、numpy 或 onnxruntime") from exc
        self.cv2 = cv2
        self.np = np
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.intra_op_num_threads = max(1, min(4, (os_cpu_count() or 2) // 2))
        providers = ["CPUExecutionProvider"]
        self.detector = ort.InferenceSession(str(detector_path), options, providers=providers)
        self.pose = ort.InferenceSession(str(pose_path), options, providers=providers)
        self.runtime_provider = self.pose.get_providers()[0]

    def _detect(self, frame: Any) -> Any:
        cv2, np = self.cv2, self.np
        target_h, target_w = 640, 640
        height, width = frame.shape[:2]
        ratio = min(target_h / height, target_w / width)
        resized = cv2.resize(
            frame,
            (max(1, int(width * ratio)), max(1, int(height * ratio))),
            interpolation=cv2.INTER_LINEAR,
        )
        padded = np.full((target_h, target_w, 3), 114, dtype=np.uint8)
        padded[: resized.shape[0], : resized.shape[1]] = resized
        tensor = np.ascontiguousarray(padded.transpose(2, 0, 1), dtype=np.float32)[None]
        input_name = self.detector.get_inputs()[0].name
        predictions = self.detector.run(None, {input_name: tensor})[0][0]
        grids: list[Any] = []
        strides: list[Any] = []
        for stride in (8, 16, 32):
            grid_h, grid_w = target_h // stride, target_w // stride
            yv, xv = np.meshgrid(np.arange(grid_h), np.arange(grid_w), indexing="ij")
            grid = np.stack((xv, yv), axis=2).reshape(1, -1, 2)
            grids.append(grid)
            strides.append(np.full((*grid.shape[:2], 1), stride))
        grid = np.concatenate(grids, axis=1)[0]
        stride = np.concatenate(strides, axis=1)[0]
        predictions[:, :2] = (predictions[:, :2] + grid) * stride
        predictions[:, 2:4] = np.exp(predictions[:, 2:4]) * stride
        boxes = np.empty_like(predictions[:, :4])
        boxes[:, 0] = predictions[:, 0] - predictions[:, 2] / 2
        boxes[:, 1] = predictions[:, 1] - predictions[:, 3] / 2
        boxes[:, 2] = predictions[:, 0] + predictions[:, 2] / 2
        boxes[:, 3] = predictions[:, 1] + predictions[:, 3] / 2
        boxes /= ratio
        class_scores = predictions[:, 4:5] * predictions[:, 5:]
        person_scores = class_scores[:, 0]
        mask = person_scores >= 0.3
        boxes, person_scores = boxes[mask], person_scores[mask]
        if boxes.size == 0:
            return []
        keep = _nms(boxes, person_scores, 0.45, np)
        return [(boxes[index], float(person_scores[index])) for index in keep[:6]]

    def _estimate_pose(self, frame: Any, bbox: Any, detection_score: float) -> PoseObservation:
        cv2, np = self.cv2, self.np
        input_meta = self.pose.get_inputs()[0]
        shape = input_meta.shape
        input_h = int(shape[2]) if isinstance(shape[2], int) else 384
        input_w = int(shape[3]) if isinstance(shape[3], int) else 288
        x1, y1, x2, y2 = [float(value) for value in bbox]
        center = np.array([(x1 + x2) / 2, (y1 + y2) / 2], dtype=np.float32)
        box_w, box_h = max(2.0, x2 - x1), max(2.0, y2 - y1)
        aspect = input_w / input_h
        if box_w > aspect * box_h:
            box_h = box_w / aspect
        else:
            box_w = box_h * aspect
        scale = np.array([box_w * 1.25, box_h * 1.25], dtype=np.float32)
        src = np.float32(
            [
                center,
                center + np.array([0, -scale[1] / 2], dtype=np.float32),
                center + np.array([-scale[0] / 2, 0], dtype=np.float32),
            ]
        )
        dst = np.float32(
            [
                [input_w / 2, input_h / 2],
                [input_w / 2, 0],
                [0, input_h / 2],
            ]
        )
        transform = cv2.getAffineTransform(src, dst)
        crop = cv2.warpAffine(frame, transform, (input_w, input_h), flags=cv2.INTER_LINEAR)
        # Match the official DWPose ONNX adapter exactly: images loaded by
        # OpenCV remain in BGR order and are normalized in the 0-255 domain.
        # Converting to RGB here changes the model contract and noticeably
        # reduces keypoint stability with the official weights.
        normalized = crop.astype(np.float32)
        normalized = (
            normalized
            - np.array([123.675, 116.28, 103.53], dtype=np.float32)
        ) / np.array([58.395, 57.12, 57.375], dtype=np.float32)
        tensor = np.ascontiguousarray(normalized.transpose(2, 0, 1))[None]
        outputs = self.pose.run(None, {input_meta.name: tensor})
        if len(outputs) < 2:
            raise RuntimeError("DWPose 姿态模型输出格式不受支持")
        simcc_x, simcc_y = outputs[0], outputs[1]
        x_index = np.argmax(simcc_x, axis=2)[0]
        y_index = np.argmax(simcc_y, axis=2)[0]
        x_score = np.max(simcc_x, axis=2)[0]
        y_score = np.max(simcc_y, axis=2)[0]
        scores = np.minimum(x_score, y_score).astype(np.float32)
        crop_points = np.stack((x_index, y_index), axis=1).astype(np.float32) / 2.0
        inverse = cv2.invertAffineTransform(transform)
        crop_points = crop_points @ inverse[:, :2].T + inverse[:, 2]
        return PoseObservation(
            keypoints=crop_points,
            scores=scores,
            bbox=(x1, y1, x2, y2),
            detection_score=detection_score,
        )

    def estimate(self, frame: Any) -> list[PoseObservation]:
        return [self._estimate_pose(frame, box, score) for box, score in self._detect(frame)]


def os_cpu_count() -> int | None:
    import os

    return os.cpu_count()
