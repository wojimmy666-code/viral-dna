from __future__ import annotations

from types import SimpleNamespace

import pytest

from viral_dna_api.production_media import (
    clamp_video_timestamp,
    map_timed_text,
    playback_alignment,
)


def test_clamp_video_timestamp_keeps_seek_inside_media() -> None:
    assert clamp_video_timestamp(-4, 8) == 0
    assert clamp_video_timestamp(3.4567, 8) == 3.457
    assert clamp_video_timestamp(8, 8) == 7.96


def test_map_timed_text_clips_to_shot_and_preserves_source_range() -> None:
    items = [
        SimpleNamespace(
            id="before-and-inside",
            start_seconds=1.5,
            end_seconds=3.5,
            text="第一句",
            language="zh",
        ),
        SimpleNamespace(
            id="inside",
            start_seconds=3.5,
            end_seconds=4.5,
            text="第二句",
            language="zh",
        ),
        SimpleNamespace(
            id="outside",
            start_seconds=6,
            end_seconds=7,
            text="不应出现",
            language="zh",
        ),
    ]

    mapped = map_timed_text(
        items,
        source_start_seconds=2,
        source_end_seconds=5,
        kind="transcript",
    )

    assert [item["id"] for item in mapped] == ["before-and-inside", "inside"]
    assert mapped[0]["clip_start_seconds"] == 0
    assert mapped[0]["clip_end_seconds"] == 1.5
    assert mapped[0]["clipped"] is True
    assert mapped[1]["clip_start_seconds"] == 1.5
    assert mapped[1]["clipped"] is False


@pytest.mark.parametrize(
    ("prepared", "timeline", "expected_rate", "expected_alignment"),
    [
        (4.0, 4.0, 1.0, "exact"),
        (4.8, 4.0, 1.2, "retime"),
        (6.0, 4.0, 1.5, "outside_safe_range"),
    ],
)
def test_playback_alignment_exposes_safe_retime_boundary(
    prepared: float,
    timeline: float,
    expected_rate: float,
    expected_alignment: str,
) -> None:
    rate, alignment = playback_alignment(prepared, timeline)
    assert rate == expected_rate
    assert alignment == expected_alignment
