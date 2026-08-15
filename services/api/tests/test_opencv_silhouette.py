from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from viral_dna_api.video_references.domain import ReferenceProxyKind
from viral_dna_api.video_references.proxies.browser_video import FfmpegBrowserVideoEncoder
from viral_dna_api.video_references.proxies.opencv_silhouette import OpenCvSilhouetteEngine


def test_image_proxy_uses_face_anchor_when_full_body_detector_misses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    source = tmp_path / "portrait.jpg"
    destination = tmp_path / "proxy.png"
    thumbnail = tmp_path / "thumbnail.png"
    frame = np.full((320, 480, 3), 180, dtype=np.uint8)
    assert cv2.imwrite(str(source), frame)

    engine = OpenCvSilhouetteEngine()
    monkeypatch.setattr(engine, "_largest_person", lambda _detector, _frame: None)
    monkeypatch.setattr(engine, "_largest_face", lambda _frame, _cv2: (190, 48, 72, 72))

    output = engine.generate(
        source_path=source,
        destination_path=destination,
        thumbnail_path=thumbnail,
        kind=ReferenceProxyKind.SILHOUETTE_IMAGE,
    )

    rendered = cv2.imread(str(destination))
    assert output.identity_removed is True
    assert rendered is not None
    assert rendered.shape == frame.shape
    assert destination.is_file()
    assert thumbnail.is_file()
    assert int(rendered.max()) == 250


def test_browser_encoder_outputs_h264_yuv420p_mp4(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("FFmpeg is required for browser video proxy encoding")

    source = tmp_path / "source.avi"
    destination = tmp_path / "browser.mp4"
    writer = cv2.VideoWriter(
        str(source),
        cv2.VideoWriter_fourcc(*"MJPG"),
        12,
        (96, 64),
    )
    assert writer.isOpened()
    for level in (40, 80, 120, 160):
        writer.write(np.full((64, 96, 3), level, dtype=np.uint8))
    writer.release()

    FfmpegBrowserVideoEncoder(ffmpeg).encode(source, destination)
    payload = json.loads(
        subprocess.check_output(
            [
                ffprobe,
                "-v",
                "error",
                "-show_streams",
                "-of",
                "json",
                str(destination),
            ],
            text=True,
        )
    )

    stream = payload["streams"][0]
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"
    assert destination.stat().st_size > 0
