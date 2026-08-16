from __future__ import annotations

import json
from pathlib import Path

from viral_dna_api.video_references.domain import ReferenceProxyQualityStatus
from viral_dna_api.video_references.proxies.ai import quality


def _pose(*, offset_x: float = 0.0) -> dict:
    return {
        "bbox": [0.2 + offset_x, 0.1, 0.8 + offset_x, 0.95],
        "keypoints": [
            {
                "index": index,
                "x": 0.35 + (index - 5) * 0.025 + offset_x,
                "y": 0.2 + (index - 5) * 0.045,
                "score": 0.99,
            }
            for index in range(5, 17)
        ],
    }


def _manifest(path: Path, pose: dict) -> Path:
    path.write_text(json.dumps({"pose": pose}), encoding="utf-8")
    return path


def test_ai_proxy_quality_passes_matching_pose_without_face_like_regions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(quality, "_face_scan", lambda *_args, **_kwargs: (0, 1, True))
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(b"not-read-because-face-scan-is-stubbed")

    report = quality.validate_ai_proxy(
        reference_manifest=_manifest(tmp_path / "reference.json", _pose()),
        candidate_manifest=_manifest(tmp_path / "candidate.json", _pose()),
        candidate_path=candidate,
        media_type="image",
        base_quality_score=0.95,
    )

    assert report.status == ReferenceProxyQualityStatus.PASSED
    assert report.metrics["raw_source_uploaded"] is False
    assert report.metrics["face_like_region_count"] == 0
    assert report.metrics["matched_frame_ratio"] == 1.0


def test_ai_proxy_quality_requires_review_when_pose_drifts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(quality, "_face_scan", lambda *_args, **_kwargs: (0, 1, True))
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(b"not-read-because-face-scan-is-stubbed")

    report = quality.validate_ai_proxy(
        reference_manifest=_manifest(tmp_path / "reference.json", _pose()),
        candidate_manifest=_manifest(
            tmp_path / "candidate.json",
            _pose(offset_x=0.24),
        ),
        candidate_path=candidate,
        media_type="image",
        base_quality_score=0.95,
    )

    assert report.status == ReferenceProxyQualityStatus.REVIEW_REQUIRED
    assert report.metrics["pose_mean_normalized_error"] > 0.12


def test_ai_proxy_quality_fails_closed_when_face_like_region_is_detected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(quality, "_face_scan", lambda *_args, **_kwargs: (1, 1, True))
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(b"not-read-because-face-scan-is-stubbed")

    report = quality.validate_ai_proxy(
        reference_manifest=_manifest(tmp_path / "reference.json", _pose()),
        candidate_manifest=_manifest(tmp_path / "candidate.json", _pose()),
        candidate_path=candidate,
        media_type="image",
        base_quality_score=0.95,
    )

    assert report.status == ReferenceProxyQualityStatus.FAILED
    assert report.metrics["face_like_region_count"] == 1
