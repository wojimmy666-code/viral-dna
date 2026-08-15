from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ..domain import (
    ReferenceProxyKind,
    ReferenceProxyQualityStatus,
    VideoReferenceMediaType,
)
from .browser_video import FfmpegBrowserVideoEncoder
from .contracts import ProxyEngineCapability, ProxyGenerationOutput


class OpenCvSilhouetteEngine:
    """Privacy proxy renderer that never copies source pixels to its output.

    The engine preserves only a coarse person silhouette and screen position. It
    deliberately does not claim to be a 3D pose/white-model engine.
    """

    capability = ProxyEngineCapability(
        engine="opencv_silhouette",
        version="1.1.0",
        kinds=(
            ReferenceProxyKind.SILHOUETTE_IMAGE,
            ReferenceProxyKind.SILHOUETTE_VIDEO,
        ),
        available=True,
        production_ready=False,
        availability_note="输出无纹理白色剪影；不保留原始人物像素",
    )

    def __init__(self, *, video_encoder: FfmpegBrowserVideoEncoder | None = None) -> None:
        self.video_encoder = video_encoder or FfmpegBrowserVideoEncoder()

    @staticmethod
    def _modules() -> tuple[Any, Any]:
        try:
            import cv2  # type: ignore[import-not-found]
            import numpy as np  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on optional runtime
            raise RuntimeError("未安装 OpenCV 动作代理依赖") from exc
        return cv2, np

    @staticmethod
    def _detector(cv2: Any) -> Any:
        detector = cv2.HOGDescriptor()
        detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        return detector

    @staticmethod
    def _read_image(path: Path, cv2: Any, np: Any) -> Any | None:
        """Decode through numpy so Windows extended-length paths remain supported."""

        try:
            payload = np.fromfile(str(path), dtype=np.uint8)
        except OSError:
            return None
        if payload.size == 0:
            return None
        return cv2.imdecode(payload, cv2.IMREAD_COLOR)

    @staticmethod
    def _write_image(path: Path, frame: Any, cv2: Any) -> bool:
        """Encode first so OpenCV never has to open a long destination path."""

        suffix = path.suffix.lower() if path.suffix else ".png"
        ok, encoded = cv2.imencode(suffix, frame)
        if not ok:
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            encoded.tofile(str(path))
        except OSError:
            return False
        return True

    @staticmethod
    def _largest_person(detector: Any, frame: Any) -> tuple[int, int, int, int] | None:
        height, width = frame.shape[:2]
        scale = min(1.0, 960 / max(width, height))
        detection_frame = frame
        if scale < 1:
            cv2, _ = OpenCvSilhouetteEngine._modules()
            detection_frame = cv2.resize(frame, None, fx=scale, fy=scale)
        boxes, _weights = detector.detectMultiScale(
            detection_frame,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05,
        )
        if len(boxes) == 0:
            return None
        x, y, box_width, box_height = max(boxes, key=lambda item: item[2] * item[3])
        inverse = 1 / scale
        return tuple(round(value * inverse) for value in (x, y, box_width, box_height))

    @staticmethod
    def _largest_face(frame: Any, cv2: Any) -> tuple[int, int, int, int] | None:
        """Find a face anchor when full-body HOG misses a close or half-body portrait."""

        height, width = frame.shape[:2]
        scale = min(1.0, 960 / max(width, height))
        detection_frame = frame
        if scale < 1:
            detection_frame = cv2.resize(frame, None, fx=scale, fy=scale)
        grayscale = cv2.cvtColor(detection_frame, cv2.COLOR_BGR2GRAY)
        cascade_path = str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        detector = cv2.CascadeClassifier(cascade_path)
        if detector.empty():
            return None
        minimum = max(24, round(min(detection_frame.shape[:2]) * 0.035))
        boxes = detector.detectMultiScale(
            grayscale,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(minimum, minimum),
        )
        if len(boxes) == 0:
            return None
        x, y, box_width, box_height = max(boxes, key=lambda item: item[2] * item[3])
        inverse = 1 / scale
        return tuple(round(value * inverse) for value in (x, y, box_width, box_height))

    @staticmethod
    def _person_box_from_face(
        face: tuple[int, int, int, int],
        *,
        frame_width: int,
        frame_height: int,
    ) -> tuple[int, int, int, int]:
        """Expand a face anchor into a conservative upper/full-body composition box."""

        x, y, face_width, face_height = face
        center_x = x + face_width / 2
        target_width = min(frame_width, max(face_width * 4.2, frame_width * 0.28))
        left = max(0, round(center_x - target_width / 2))
        right = min(frame_width, round(center_x + target_width / 2))
        top = max(0, round(y - face_height * 0.45))
        bottom = min(frame_height, round(y + face_height * 5.0))
        if bottom - top < face_height * 2.4:
            bottom = min(frame_height, round(top + face_height * 2.4))
        return left, top, max(2, right - left), max(2, bottom - top)

    def _find_person_box(
        self,
        detector: Any,
        frame: Any,
        cv2: Any,
    ) -> tuple[tuple[int, int, int, int] | None, str | None]:
        box = self._largest_person(detector, frame)
        if box is not None:
            return box, "full_body_hog"
        face = self._largest_face(frame, cv2)
        if face is None:
            return None, None
        height, width = frame.shape[:2]
        return (
            self._person_box_from_face(
                face,
                frame_width=width,
                frame_height=height,
            ),
            "face_anchor_fallback",
        )

    @staticmethod
    def _render_proxy(frame: Any, box: tuple[int, int, int, int], cv2: Any, np: Any) -> Any:
        height, width = frame.shape[:2]
        canvas = np.full((height, width, 3), 214, dtype=np.uint8)
        x, y, box_width, box_height = box
        x = max(0, min(x, width - 1))
        y = max(0, min(y, height - 1))
        box_width = max(2, min(box_width, width - x))
        box_height = max(2, min(box_height, height - y))

        head_center = (x + box_width // 2, y + max(2, box_height // 8))
        head_radius = max(4, min(box_width // 5, box_height // 10))
        cv2.circle(canvas, head_center, head_radius, (250, 250, 250), -1, cv2.LINE_AA)
        shoulder_y = y + box_height // 4
        hip_y = y + (box_height * 3) // 5
        body = np.array(
            [
                [x + box_width // 4, shoulder_y],
                [x + (box_width * 3) // 4, shoulder_y],
                [x + (box_width * 2) // 3, hip_y],
                [x + box_width // 3, hip_y],
            ],
            dtype=np.int32,
        )
        cv2.fillConvexPoly(canvas, body, (250, 250, 250), cv2.LINE_AA)
        limb_width = max(3, box_width // 10)
        center_x = x + box_width // 2
        cv2.line(
            canvas,
            (x + box_width // 4, shoulder_y),
            (x + box_width // 10, y + box_height // 2),
            (250, 250, 250),
            limb_width,
            cv2.LINE_AA,
        )
        cv2.line(
            canvas,
            (x + (box_width * 3) // 4, shoulder_y),
            (x + (box_width * 9) // 10, y + box_height // 2),
            (250, 250, 250),
            limb_width,
            cv2.LINE_AA,
        )
        cv2.line(
            canvas,
            (center_x - box_width // 8, hip_y),
            (x + box_width // 3, y + box_height),
            (250, 250, 250),
            limb_width,
            cv2.LINE_AA,
        )
        cv2.line(
            canvas,
            (center_x + box_width // 8, hip_y),
            (x + (box_width * 2) // 3, y + box_height),
            (250, 250, 250),
            limb_width,
            cv2.LINE_AA,
        )
        return canvas

    def generate(
        self,
        *,
        source_path: Path,
        destination_path: Path,
        thumbnail_path: Path,
        kind: ReferenceProxyKind,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
    ) -> ProxyGenerationOutput:
        if kind not in self.capability.kinds:
            raise RuntimeError("当前 OpenCV 引擎不支持该动作代理类型")
        cv2, np = self._modules()
        detector = self._detector(cv2)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        if kind == ReferenceProxyKind.SILHOUETTE_IMAGE:
            frame = self._read_image(source_path, cv2, np)
            if frame is None:
                raise RuntimeError("无法读取动作代理源图片")
            box, _detection_mode = self._find_person_box(detector, frame, cv2)
            if box is None:
                raise RuntimeError("未在源图片中检测到可用于动作代理的人物")
            proxy = self._render_proxy(frame, box, cv2, np)
            if not self._write_image(destination_path, proxy, cv2):
                raise RuntimeError("无法写入图片动作代理")
            if not self._write_image(thumbnail_path, proxy, cv2):
                raise RuntimeError("无法写入图片白模缩略图")
            return ProxyGenerationOutput(
                path=destination_path,
                thumbnail_path=thumbnail_path,
                media_type=VideoReferenceMediaType.IMAGE,
                identity_removed=True,
                semantic_validation_status=ReferenceProxyQualityStatus.LEGACY_UNVERIFIED,
                quality_score=0,
                quality_metrics={"legacy_placeholder": True},
                validation_message="输出只包含程序绘制的无纹理人物剪影，未复制源图人物像素",
            )

        capture = cv2.VideoCapture(str(source_path))
        if not capture.isOpened():
            raise RuntimeError("无法读取动作代理源视频")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 25)
        if start_seconds is not None:
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0, start_seconds) * 1000)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if width < 2 or height < 2:
            capture.release()
            raise RuntimeError("源视频尺寸无效")
        video_temp = tempfile.TemporaryDirectory(prefix="viraldna-white-model-render-")
        intermediate_path = Path(video_temp.name) / "proxy.avi"
        writer = cv2.VideoWriter(
            str(intermediate_path),
            cv2.VideoWriter_fourcc(*"MJPG"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            capture.release()
            video_temp.cleanup()
            raise RuntimeError("无法创建视频动作代理文件")
        last_box: tuple[int, int, int, int] | None = None
        first_proxy: Any | None = None
        frames_written = 0
        while True:
            if end_seconds is not None:
                position_seconds = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0) / 1000
                if position_seconds >= end_seconds:
                    break
            ok, frame = capture.read()
            if not ok:
                break
            detected = self._largest_person(detector, frame)
            if detected is not None:
                last_box = detected
            if last_box is None:
                continue
            proxy = self._render_proxy(frame, last_box, cv2, np)
            writer.write(proxy)
            first_proxy = proxy if first_proxy is None else first_proxy
            frames_written += 1
        capture.release()
        writer.release()
        if frames_written == 0 or first_proxy is None:
            video_temp.cleanup()
            raise RuntimeError("未在源视频中检测到可用于动作代理的人物")
        try:
            self.video_encoder.encode(intermediate_path, destination_path)
        finally:
            video_temp.cleanup()
        if not self._write_image(thumbnail_path, first_proxy, cv2):
            destination_path.unlink(missing_ok=True)
            raise RuntimeError("无法写入视频白模缩略图")
        return ProxyGenerationOutput(
            path=destination_path,
            thumbnail_path=thumbnail_path,
            media_type=VideoReferenceMediaType.VIDEO,
            identity_removed=True,
            semantic_validation_status=ReferenceProxyQualityStatus.LEGACY_UNVERIFIED,
            quality_score=0,
            quality_metrics={"legacy_placeholder": True},
            validation_message="视频逐帧重绘为无纹理人物剪影，未复制源视频人物像素",
        )
