import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  moveTimelineRange,
  nextTimelineClip,
  reflowTimelineDraft,
  reorderTimelineClips,
  snapTimelineTime,
  sourceAudioPlaybackRate,
  sourceTimeToTimelineTime,
  timelineClipAtTime,
  timelineClipSourceBounds,
  timelineTimeToSourceAudioTime,
  timelineTimeToSourceTime,
  trimTimelineClip,
  trimTimelineRange,
} from "../src/video-editor/timeline-math.js";

const canvasSource = readFileSync(
  new URL("../src/video-editor/TimelineCanvas.jsx", import.meta.url),
  "utf8",
);
const workspaceSource = readFileSync(
  new URL("../src/video-editor/VideoEditorWorkspace.jsx", import.meta.url),
  "utf8",
);

function clip(id, order, start = 0, duration = 2) {
  return {
    id,
    order,
    enabled: true,
    candidate_duration_seconds: 8,
    trim_in_seconds: start,
    trim_out_seconds: start + duration,
    playback_rate: 1,
    timeline_duration_seconds: duration,
    timeline_start_seconds: 0,
    timeline_end_seconds: duration,
    transition_after: { kind: "none", duration_seconds: 0 },
  };
}

test("snaps edits to frames and nearby item boundaries", () => {
  assert.equal(snapTimelineTime(1.023), 1);
  assert.equal(snapTimelineTime(2.94, { points: [3] }), 3);
  assert.equal(snapTimelineTime(2.88, { points: [3] }), 2.9);
});

test("trims video without changing its playback speed", () => {
  const source = { ...clip("first", 1, 1, 4), playback_rate: 2, timeline_duration_seconds: 2 };
  const trimmed = trimTimelineClip(source, "end", -1);

  assert.equal(trimmed.trim_in_seconds, 1);
  assert.equal(trimmed.trim_out_seconds, 4);
  assert.equal(trimmed.timeline_duration_seconds, 1.5);
  assert.equal((trimmed.trim_out_seconds - trimmed.trim_in_seconds) / trimmed.timeline_duration_seconds, 2);
});

test("maps the global playhead to trimmed source time and back", () => {
  const first = {
    ...clip("first", 1, 1, 4),
    playback_rate: 2,
    timeline_start_seconds: 3,
    timeline_end_seconds: 5,
    timeline_duration_seconds: 2,
  };

  assert.equal(timelineTimeToSourceTime(first, 4.25), 3.5);
  assert.equal(sourceTimeToTimelineTime(first, 3.5), 4.25);
  assert.equal(timelineTimeToSourceTime(first, 8), 5);
});

test("maps source-range clips onto the original video clock", () => {
  const ranged = {
    ...clip("source", 1, 0.5, 2),
    source_range: {
      start_pts: 2_667_000,
      end_pts: 5_167_000,
      time_base_numerator: 1,
      time_base_denominator: 1_000_000,
    },
    timeline_start_seconds: 4,
    timeline_end_seconds: 6,
  };

  assert.deepEqual(timelineClipSourceBounds(ranged), { start: 3.167, end: 5.167 });
  assert.equal(timelineTimeToSourceTime(ranged, 5), 4.167);
  assert.equal(sourceTimeToTimelineTime(ranged, 4.167), 5);

  const unrounded = {
    ...clip("unrounded-source", 1, 0, 2.5),
    candidate_duration_seconds: 2.500333,
    source_range: {
      start_pts: 2_667_123,
      end_pts: 5_167_456,
      time_base_numerator: 1,
      time_base_denominator: 1_000_000,
    },
  };
  assert.deepEqual(
    timelineClipSourceBounds(unrounded),
    { start: 2.667123, end: 5.167456 },
  );
});

test("maps original shot audio onto an edited clip duration", () => {
  const edited = {
    ...clip("generated", 1, 0, 4),
    timeline_start_seconds: 5,
    timeline_end_seconds: 9,
    timeline_duration_seconds: 4,
    source_audio_start_seconds: 12.6,
    source_audio_end_seconds: 18.6,
  };

  assert.equal(timelineTimeToSourceAudioTime(edited, 5), 12.6);
  assert.equal(timelineTimeToSourceAudioTime(edited, 7), 15.6);
  assert.equal(timelineTimeToSourceAudioTime(edited, 9), 18.6);
  assert.equal(sourceAudioPlaybackRate(edited), 1.5);
});

test("selects the incoming clip at boundaries and finds the next enabled clip", () => {
  const first = { ...clip("first", 1), timeline_start_seconds: 0, timeline_end_seconds: 2 };
  const second = { ...clip("second", 2), timeline_start_seconds: 2, timeline_end_seconds: 4 };
  const disabled = { ...clip("disabled", 3), enabled: false, timeline_start_seconds: 4, timeline_end_seconds: 6 };
  const timeline = { clips: [first, second, disabled], duration_seconds: 4 };

  assert.equal(timelineClipAtTime(timeline, 1.9).id, "first");
  assert.equal(timelineClipAtTime(timeline, 2).id, "second");
  assert.equal(timelineClipAtTime(timeline, 4).id, "second");
  assert.equal(nextTimelineClip(timeline, "first").id, "second");
  assert.equal(nextTimelineClip(timeline, "second"), null);
});

test("reorders clips magnetically and recomputes sequential positions", () => {
  const timeline = {
    clips: [clip("first", 1), clip("second", 2), clip("third", 3)],
    audio_track: { linked_to_video: true },
    background_audio_track: {},
    subtitle_cues: [],
  };
  const reordered = reorderTimelineClips(timeline.clips, "third", 0);
  const reflowed = reflowTimelineDraft({ ...timeline, clips: reordered });

  assert.deepEqual(reflowed.clips.map((item) => item.id), ["third", "first", "second"]);
  assert.deepEqual(reflowed.clips.map((item) => item.timeline_start_seconds), [0, 2, 4]);
  assert.equal(reflowed.duration_seconds, 6);
  assert.equal(reflowed.audio_track.timeline_end_seconds, 6);
});

test("moves and trims subtitles as detached global cues", () => {
  const cue = {
    id: "cue-1",
    clip_id: "clip-1",
    clip_start_seconds: 0.2,
    clip_end_seconds: 1.2,
    start_seconds: 1,
    end_seconds: 2,
  };
  const moved = moveTimelineRange(cue, 1.25, 8);
  const trimmed = trimTimelineRange(cue, "end", 0.5, 8);

  assert.equal(moved.start_seconds, 2.25);
  assert.equal(moved.end_seconds, 3.25);
  assert.equal(moved.clip_id, null);
  assert.equal(trimmed.end_seconds, 2.5);
  assert.equal(trimmed.clip_start_seconds, null);
});

test("ships pointer, keyboard, audio upload, and subtitle editing controls", () => {
  assert.match(canvasSource, /setPointerCapture/);
  assert.match(canvasSource, /type: "clip-reorder"/);
  assert.match(canvasSource, /type: "clip-trim"/);
  assert.match(canvasSource, /type: "range-move"/);
  assert.match(canvasSource, /event\.key === "Delete"/);
  assert.match(canvasSource, /aria-label="时间线缩放"/);
  assert.match(canvasSource, /在播放头添加字幕/);
  assert.doesNotMatch(canvasSource, /previewFrameUrl|TimelineFilmstrip|cover_url/);
  assert.match(canvasSource, /sourceRangesContinue/);
  assert.match(canvasSource, /原视频 ·/);
  assert.match(canvasSource, /onScrubStart/);
  assert.match(workspaceSource, /duration_seconds", String\(durationSeconds\)/);
  assert.match(workspaceSource, /createTimelineSubtitle/);
  assert.match(workspaceSource, /deleteBackgroundAudio/);
  assert.match(workspaceSource, /requestVideoFrameCallback/);
  assert.match(workspaceSource, /timelineTimeToSourceTime/);
});
