from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...domain import (
    ReferenceProxyKind,
    ReferenceProxyQualityStatus,
    VideoReferenceMediaType,
)
from ..browser_video import FfmpegBrowserVideoEncoder
from ..contracts import ProxyEngineCapability, ProxyGenerationOutput
from .inference import DWPoseOnnxEstimator
from .models import ARTIFACTS, DWPoseModelManager
from .quality import image_quality, video_quality
from .renderer import render_mannequin
from .tracking import choose_primary, interpolate_short_gaps, smooth_sequence
from .types import PoseObservation, PoseQualityReport

EstimatorFactory = Callable[[Path, Path], Any]


def _combined_model_hash() -> str:
    payload = "|".join(artifact.sha256 for artifact in ARTIFACTS).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _quality_status(value: str) -> ReferenceProxyQualityStatus:
    return {
        "passed": ReferenceProxyQualityStatus.PASSED,
        "review_required": ReferenceProxyQualityStatus.REVIEW_REQUIRED,
        "failed": ReferenceProxyQualityStatus.FAILED,
    }.get(value, ReferenceProxyQualityStatus.FAILED)


class DWPoseWholeBodyEngine:
    """WholeBody pose-to-mannequin engine with no source-pixel passthrough."""

    def __init__(
        self,
        *,
        model_manager: DWPoseModelManager | None = None,
        estimator_factory: EstimatorFactory | None = None,
        video_encoder: FfmpegBrowserVideoEncoder | None = None,
        force_available: bool = False,
    ) -> None:
        self.model_manager = model_manager or DWPoseModelManager()
        self.estimator_factory = estimator_factory or DWPoseOnnxEstimator
        self.video_encoder = video_encoder or FfmpegBrowserVideoEncoder()
        available, note = self._availability(force_available=force_available)
        self.capability = ProxyEngineCapability(
            engine="dwpose_wholebody_mannequin",
            version="1.0.0",
            kinds=(
                ReferenceProxyKind.POSE_PROXY_IMAGE,
                ReferenceProxyKind.MOTION_PROXY_VIDEO,
            ),
            available=available,
            availability_note=note,
            production_ready=True,
            wholebody=True,
            hand_keypoints=True,
            video_tracking=True,
            runtime_provider="CPUExecutionProvider",
        )
        self._estimator: Any | None = None

    def _availability(self, *, force_available: bool) -> tuple[bool, str]:
        if force_available:
            return True, "测试姿态引擎已就绪"
        try:
            import cv2  # type: ignore[import-not-found]  # noqa: F401
            import numpy  # type: ignore[import-not-found]  # noqa: F401
            import onnxruntime  # type: ignore[import-not-found]  # noqa: F401
        except ModuleNotFoundError as exc:
            return False, f"缺少 {exc.name}；请运行 scripts/start.bat 安装白模依赖"
        except (ImportError, OSError):
            return False, "DWPose 运行时加载失败；请运行 scripts/start.bat 修复 ONNX Runtime"
        return self.model_manager.validate()

    def _modules(self) -> tuple[Any, Any]:
        try:
            import cv2  # type: ignore[import-not-found]
            import numpy as np  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional runtime
            raise RuntimeError("缺少 DWPose 白模运行依赖") from exc
        return cv2, np

    def _get_estimator(self) -> Any:
        if not self.capability.available:
            raise RuntimeError(self.capability.availability_note)
        if self._estimator is None:
            self._estimator = self.estimator_factory(
                self.model_manager.detector_path,
                self.model_manager.pose_path,
            )
        return self._estimator

    @staticmethod
    def _read_image(path: Path, cv2: Any, np: Any) -> Any | None:
        try:
            payload = np.fromfile(str(path), dtype=np.uint8)
        except OSError:
            return None
        return cv2.imdecode(payload, cv2.IMREAD_COLOR) if payload.size else None

    @staticmethod
    def _write_image(path: Path, frame: Any, cv2: Any) -> bool:
        suffix = path.suffix.lower() or ".png"
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
    def _manifest_pose(
        pose: PoseObservation | None,
        width: int,
        height: int,
    ) -> dict[str, Any] | None:
        if pose is None:
            return None
        retained = [*range(23), *range(91, min(133, len(pose.scores)))]
        return {
            "keypoints": [
                {
                    "index": index,
                    "x": round(float(pose.keypoints[index][0]) / max(1, width), 5),
                    "y": round(float(pose.keypoints[index][1]) / max(1, height), 5),
                    "score": round(float(pose.scores[index]), 5),
                }
                for index in retained
            ],
            "bbox": [
                round(float(pose.bbox[0]) / max(1, width), 5),
                round(float(pose.bbox[1]) / max(1, height), 5),
                round(float(pose.bbox[2]) / max(1, width), 5),
                round(float(pose.bbox[3]) / max(1, height), 5),
            ],
        }

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _output(
        self,
        *,
        destination_path: Path,
        thumbnail_path: Path,
        media_type: VideoReferenceMediaType,
        report: PoseQualityReport,
        manifest_path: Path,
        quality_path: Path,
    ) -> ProxyGenerationOutput:
        return ProxyGenerationOutput(
            path=destination_path,
            thumbnail_path=thumbnail_path,
            media_type=media_type,
            identity_removed=True,
            validation_message=(
                "输出只含程序渲染的无纹理白模；不复制源人物像素。"
                f"{report.message}"
            ),
            semantic_validation_status=_quality_status(report.status),
            quality_score=report.score,
            quality_metrics=report.metrics,
            manifest_path=manifest_path,
            quality_report_path=quality_path,
            model_sha256=_combined_model_hash(),
        )

    def _generate_image(
        self,
        *,
        source_path: Path,
        destination_path: Path,
        thumbnail_path: Path,
        cv2: Any,
        np: Any,
    ) -> ProxyGenerationOutput:
        frame = self._read_image(source_path, cv2, np)
        if frame is None:
            raise RuntimeError("无法读取图片白模的源图片")
        observations = self._get_estimator().estimate(frame)
        pose = choose_primary(observations)
        if pose is None:
            raise RuntimeError("未检测到可用于姿态代理的人物")
        height, width = frame.shape[:2]
        report = image_quality(
            pose,
            frame_width=width,
            frame_height=height,
            person_count=len(observations),
        )
        rendered = render_mannequin(pose, width=width, height=height, cv2=cv2, np=np)
        if not self._write_image(destination_path, rendered, cv2):
            raise RuntimeError("无法写入图片姿态代理")
        if not self._write_image(thumbnail_path, rendered, cv2):
            destination_path.unlink(missing_ok=True)
            raise RuntimeError("无法写入图片姿态代理缩略图")
        manifest_path = destination_path.with_name("pose-manifest.json")
        quality_path = destination_path.with_name("quality-report.json")
        self._write_json(
            manifest_path,
            {
                "schema": "viraldna.pose-proxy/v1",
                "engine": self.capability.engine,
                "frame_size": [width, height],
                "identity_geometry_included": False,
                "pose": self._manifest_pose(pose, width, height),
            },
        )
        self._write_json(
            quality_path,
            {"status": report.status, "score": report.score, "metrics": report.metrics},
        )
        return self._output(
            destination_path=destination_path,
            thumbnail_path=thumbnail_path,
            media_type=VideoReferenceMediaType.IMAGE,
            report=report,
            manifest_path=manifest_path,
            quality_path=quality_path,
        )

    def _capture_sequence(
        self,
        source_path: Path,
        *,
        start_seconds: float | None,
        end_seconds: float | None,
        cv2: Any,
    ) -> tuple[list[PoseObservation | None], float, int, int]:
        capture = cv2.VideoCapture(str(source_path))
        if not capture.isOpened():
            raise RuntimeError("无法读取视频白模的源视频")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 25)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if width < 2 or height < 2:
            capture.release()
            raise RuntimeError("源视频尺寸无效")
        if start_seconds is not None:
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0, start_seconds) * 1000)
        sequence: list[PoseObservation | None] = []
        previous: PoseObservation | None = None
        estimator = self._get_estimator()
        while True:
            if end_seconds is not None:
                position = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0) / 1000
                if position >= end_seconds:
                    break
            ok, frame = capture.read()
            if not ok:
                break
            selected = choose_primary(estimator.estimate(frame), previous=previous)
            sequence.append(selected)
            if selected is not None:
                previous = selected
        capture.release()
        if not sequence or not any(item is not None for item in sequence):
            raise RuntimeError("未在源视频中检测到可用于动作代理的人物")
        return sequence, fps, width, height

    def _render_video(
        self,
        *,
        source_path: Path,
        destination_path: Path,
        thumbnail_path: Path,
        sequence: list[PoseObservation | None],
        fps: float,
        width: int,
        height: int,
        start_seconds: float | None,
        cv2: Any,
        np: Any,
    ) -> None:
        capture = cv2.VideoCapture(str(source_path))
        if not capture.isOpened():
            raise RuntimeError("无法重新读取源视频以渲染动作代理")
        if start_seconds is not None:
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0, start_seconds) * 1000)
        with tempfile.TemporaryDirectory(prefix="viraldna-dwpose-render-") as root:
            intermediate = Path(root) / "proxy.avi"
            writer = cv2.VideoWriter(
                str(intermediate),
                cv2.VideoWriter_fourcc(*"MJPG"),
                fps,
                (width, height),
            )
            if not writer.isOpened():
                capture.release()
                raise RuntimeError("无法创建视频姿态代理文件")
            thumbnail_frame: Any | None = None
            frames_written = 0
            try:
                for pose in sequence:
                    ok, _source_frame = capture.read()
                    if not ok:
                        break
                    rendered = render_mannequin(
                        pose,
                        width=width,
                        height=height,
                        cv2=cv2,
                        np=np,
                    )
                    writer.write(rendered)
                    frames_written += 1
                    if thumbnail_frame is None and pose is not None:
                        thumbnail_frame = rendered
            finally:
                capture.release()
                writer.release()
            if thumbnail_frame is None:
                raise RuntimeError("视频动作代理没有可用预览帧")
            if frames_written != len(sequence):
                raise RuntimeError("视频动作代理渲染帧数与姿态清单不一致")
            self.video_encoder.encode(intermediate, destination_path)
            if not self._write_image(thumbnail_path, thumbnail_frame, cv2):
                destination_path.unlink(missing_ok=True)
                raise RuntimeError("无法写入视频动作代理缩略图")

    def _generate_video(
        self,
        *,
        source_path: Path,
        destination_path: Path,
        thumbnail_path: Path,
        start_seconds: float | None,
        end_seconds: float | None,
        cv2: Any,
        np: Any,
    ) -> ProxyGenerationOutput:
        raw, fps, width, height = self._capture_sequence(
            source_path,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            cv2=cv2,
        )
        interpolated, interpolated_count = interpolate_short_gaps(
            raw,
            max_gap_frames=max(1, round(fps * 0.35)),
            np=np,
        )
        sequence = smooth_sequence(interpolated, np=np)
        report = video_quality(
            sequence,
            fps=fps,
            interpolated_frames=interpolated_count,
            raw_detected_frames=sum(item is not None for item in raw),
        )
        self._render_video(
            source_path=source_path,
            destination_path=destination_path,
            thumbnail_path=thumbnail_path,
            sequence=sequence,
            fps=fps,
            width=width,
            height=height,
            start_seconds=start_seconds,
            cv2=cv2,
            np=np,
        )
        manifest_path = destination_path.with_name("pose-manifest.json")
        quality_path = destination_path.with_name("quality-report.json")
        self._write_json(
            manifest_path,
            {
                "schema": "viraldna.motion-proxy/v1",
                "engine": self.capability.engine,
                "frame_size": [width, height],
                "fps": fps,
                "identity_geometry_included": False,
                "frames": [self._manifest_pose(item, width, height) for item in sequence],
            },
        )
        self._write_json(
            quality_path,
            {"status": report.status, "score": report.score, "metrics": report.metrics},
        )
        return self._output(
            destination_path=destination_path,
            thumbnail_path=thumbnail_path,
            media_type=VideoReferenceMediaType.VIDEO,
            report=report,
            manifest_path=manifest_path,
            quality_path=quality_path,
        )

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
            raise RuntimeError("DWPose WholeBody 引擎不支持该代理类型")
        cv2, np = self._modules()
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        if kind == ReferenceProxyKind.POSE_PROXY_IMAGE:
            return self._generate_image(
                source_path=source_path,
                destination_path=destination_path,
                thumbnail_path=thumbnail_path,
                cv2=cv2,
                np=np,
            )
        return self._generate_video(
            source_path=source_path,
            destination_path=destination_path,
            thumbnail_path=thumbnail_path,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            cv2=cv2,
            np=np,
        )
