from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from viral_dna_api.video_references.domain import (
    ReferenceProxyAsset,
    ReferenceProxyKind,
    ReferenceProxyQualityStatus,
    ReferenceProxyStatus,
    VideoReferenceMediaType,
)
from viral_dna_api.video_references.proxies.dwpose.engine import DWPoseWholeBodyEngine
from viral_dna_api.video_references.proxies.dwpose.inference import DWPoseOnnxEstimator
from viral_dna_api.video_references.proxies.dwpose.types import PoseObservation


def _pose(np, *, x_offset: float = 0) -> PoseObservation:
    points = np.zeros((133, 2), dtype=np.float32)
    scores = np.full((133,), 0.92, dtype=np.float32)
    body = {
        0: (160, 60),
        3: (145, 62),
        4: (175, 62),
        5: (130, 105),
        6: (190, 105),
        7: (110, 150),
        8: (210, 150),
        9: (95, 200),
        10: (225, 200),
        11: (140, 210),
        12: (180, 210),
        13: (135, 280),
        14: (185, 280),
        15: (130, 350),
        16: (190, 350),
    }
    for index, (x_value, y_value) in body.items():
        points[index] = (x_value + x_offset, y_value)
    for hand_offset, wrist_index in ((91, 9), (112, 10)):
        wrist = points[wrist_index]
        for index in range(21):
            points[hand_offset + index] = (
                wrist[0] + (index % 5) * 3,
                wrist[1] + (index // 5) * 4,
            )
    return PoseObservation(
        keypoints=points,
        scores=scores,
        bbox=(80 + x_offset, 35, 240 + x_offset, 370),
        detection_score=0.95,
    )


class FakeEstimator:
    def __init__(self, np, *, sequence=None) -> None:
        self.np = np
        self.sequence = list(sequence or [])
        self.calls = 0

    def estimate(self, _frame):
        if self.sequence:
            index = min(self.calls, len(self.sequence) - 1)
            value = self.sequence[index]
            self.calls += 1
            return value
        return [_pose(self.np)]


class CopyVideoEncoder:
    def encode(self, source_path: Path, destination_path: Path) -> Path:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination_path)
        return destination_path


def test_official_pose_preprocessing_keeps_opencv_bgr_channel_order() -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    class InputMeta:
        name = "input"
        shape = [1, 3, 384, 288]

    class PoseSession:
        def __init__(self) -> None:
            self.tensor = None

        @staticmethod
        def get_inputs():
            return [InputMeta()]

        def run(self, _outputs, inputs):
            self.tensor = inputs["input"]
            simcc_x = np.zeros((1, 133, 576), dtype=np.float32)
            simcc_y = np.zeros((1, 133, 768), dtype=np.float32)
            simcc_x[:, :, 288] = 1
            simcc_y[:, :, 384] = 1
            return [simcc_x, simcc_y]

    pose_session = PoseSession()
    estimator = DWPoseOnnxEstimator.__new__(DWPoseOnnxEstimator)
    estimator.cv2 = cv2
    estimator.np = np
    estimator.pose = pose_session
    frame = np.full((384, 288, 3), (10, 20, 30), dtype=np.uint8)

    estimator._estimate_pose(frame, (0, 0, 288, 384), 0.95)

    assert pose_session.tensor is not None
    center = pose_session.tensor[0, :, 192, 144]
    expected = (
        np.array([10, 20, 30], dtype=np.float32)
        - np.array([123.675, 116.28, 103.53], dtype=np.float32)
    ) / np.array([58.395, 57.12, 57.375], dtype=np.float32)
    np.testing.assert_allclose(center, expected, rtol=1e-6, atol=1e-6)


def test_wholebody_image_proxy_removes_pixels_and_persists_quality_manifest(
    tmp_path: Path,
) -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    source = tmp_path / "source.png"
    destination = tmp_path / "proxy.png"
    thumbnail = tmp_path / "thumbnail.png"
    frame = np.zeros((400, 320, 3), dtype=np.uint8)
    frame[:, :, 1] = 180
    assert cv2.imwrite(str(source), frame)
    estimator = FakeEstimator(np)
    engine = DWPoseWholeBodyEngine(
        estimator_factory=lambda _detector, _pose_path: estimator,
        force_available=True,
    )

    output = engine.generate(
        source_path=source,
        destination_path=destination,
        thumbnail_path=thumbnail,
        kind=ReferenceProxyKind.POSE_PROXY_IMAGE,
    )

    rendered = cv2.imread(str(destination))
    assert rendered is not None
    assert rendered.shape == frame.shape
    assert not np.array_equal(rendered, frame)
    assert output.identity_removed is True
    assert output.semantic_validation_status == ReferenceProxyQualityStatus.PASSED
    assert output.quality_score is not None and output.quality_score >= 0.58
    assert output.manifest_path is not None
    manifest = json.loads(output.manifest_path.read_text(encoding="utf-8"))
    retained = {item["index"] for item in manifest["pose"]["keypoints"]}
    assert not retained.intersection(range(23, 91))
    assert manifest["identity_geometry_included"] is False


def test_wholebody_video_proxy_interpolates_short_gaps_without_source_pixels(
    tmp_path: Path,
) -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    source = tmp_path / "source.avi"
    writer = cv2.VideoWriter(
        str(source),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10,
        (320, 400),
    )
    assert writer.isOpened()
    for level in (20, 40, 60, 80, 100, 120):
        writer.write(np.full((400, 320, 3), level, dtype=np.uint8))
    writer.release()
    sequence = [
        [_pose(np, x_offset=0)],
        [_pose(np, x_offset=2)],
        [],
        [_pose(np, x_offset=6)],
        [_pose(np, x_offset=8)],
        [_pose(np, x_offset=10)],
    ]
    estimator = FakeEstimator(np, sequence=sequence)
    engine = DWPoseWholeBodyEngine(
        estimator_factory=lambda _detector, _pose_path: estimator,
        video_encoder=CopyVideoEncoder(),
        force_available=True,
    )
    destination = tmp_path / "proxy.mp4"
    output = engine.generate(
        source_path=source,
        destination_path=destination,
        thumbnail_path=tmp_path / "thumbnail.png",
        kind=ReferenceProxyKind.MOTION_PROXY_VIDEO,
        start_seconds=0,
        end_seconds=0.6,
    )

    assert destination.is_file()
    assert output.semantic_validation_status == ReferenceProxyQualityStatus.PASSED
    assert output.quality_metrics is not None
    assert output.quality_metrics["interpolated_frame_count"] == 1
    assert output.quality_metrics["raw_pose_coverage_ratio"] == pytest.approx(5 / 6, abs=1e-4)
    assert output.manifest_path is not None
    manifest = json.loads(output.manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["frames"]) == 6
    assert all(frame_pose is not None for frame_pose in manifest["frames"])


def test_proxy_generation_boundary_requires_semantic_evidence_bundle() -> None:
    proxy = ReferenceProxyAsset(
        visual_beat_id=uuid4(),
        kind=ReferenceProxyKind.POSE_PROXY_IMAGE,
        media_type=VideoReferenceMediaType.IMAGE,
        status=ReferenceProxyStatus.READY,
        source_image_candidate_id=uuid4(),
        relative_path="reference-proxies/proxy.png",
        sha256="a" * 64,
        engine="wholebody-test",
        engine_version="1.0",
        identity_removed=True,
        validation_status="passed",
        semantic_validation_status=ReferenceProxyQualityStatus.PASSED,
        quality_score=0.92,
    )

    assert proxy.usable_for_generation is False

    verified = proxy.model_copy(
        update={
            "manifest_relative_path": "reference-proxies/pose-manifest.json",
            "quality_report_relative_path": "reference-proxies/quality-report.json",
            "model_sha256": "b" * 64,
        }
    )
    assert verified.usable_for_generation is True

    review_required = verified.model_copy(
        update={
            "semantic_validation_status": ReferenceProxyQualityStatus.REVIEW_REQUIRED
        }
    )
    assert review_required.usable_for_generation is False
