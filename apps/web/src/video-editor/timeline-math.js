export const TIMELINE_MIN_DURATION = 0.1;
export const TIMELINE_SNAP_STEP = 0.05;

const TIMELINE_BOUNDARY_EPSILON = 0.001;

export function clampTimelineValue(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, Number(value) || 0));
}

export function roundTimelineValue(value) {
  return Math.round((Number(value) || 0) * 1000) / 1000;
}

function roundSourceValue(value) {
  return Math.round((Number(value) || 0) * 1_000_000) / 1_000_000;
}

export function enabledTimelineClips(timeline) {
  return [...(timeline?.clips || [])]
    .filter((clip) => clip.enabled)
    .sort((first, second) => (
      Number(first.timeline_start_seconds) - Number(second.timeline_start_seconds)
      || Number(first.order) - Number(second.order)
    ));
}

export function timelineClipAtTime(timeline, timelineSeconds) {
  const clips = enabledTimelineClips(timeline);
  if (!clips.length) return null;
  const duration = Math.max(0, Number(timeline?.duration_seconds) || 0);
  const time = clampTimelineValue(timelineSeconds, 0, duration);
  if (time >= duration - TIMELINE_BOUNDARY_EPSILON) return clips.at(-1);

  const matching = clips.filter((clip) => (
    time >= Number(clip.timeline_start_seconds) - TIMELINE_BOUNDARY_EPSILON
    && time < Number(clip.timeline_end_seconds) - TIMELINE_BOUNDARY_EPSILON
  ));
  return matching.at(-1) || clips.find(
    (clip) => time < Number(clip.timeline_start_seconds),
  ) || clips.at(-1);
}

export function nextTimelineClip(timeline, clipId) {
  const clips = enabledTimelineClips(timeline);
  const index = clips.findIndex((clip) => clip.id === clipId);
  return index >= 0 ? clips[index + 1] || null : null;
}

export function timelineClipSourceBounds(clip) {
  if (!clip) return { start: 0, end: 0 };
  const sourceRange = clip.source_range;
  const rangeStart = sourceRange
    ? Number(sourceRange.start_pts)
      * Number(sourceRange.time_base_numerator || 1)
      / Number(sourceRange.time_base_denominator || 1_000_000)
    : 0;
  const rangeEnd = sourceRange
    ? Number(sourceRange.end_pts)
      * Number(sourceRange.time_base_numerator || 1)
      / Number(sourceRange.time_base_denominator || 1_000_000)
    : 0;
  const trimIn = Number(clip.trim_in_seconds);
  const trimOut = Number(clip.trim_out_seconds);
  const candidateDuration = Number(clip.candidate_duration_seconds);
  return {
    start: roundSourceValue(
      sourceRange && Math.abs(trimIn) <= 0.000001 ? rangeStart : rangeStart + trimIn,
    ),
    end: roundSourceValue(
      sourceRange && Math.abs(trimOut - candidateDuration) <= 0.001
        ? rangeEnd
        : rangeStart + trimOut,
    ),
  };
}

export function timelineTimeToSourceTime(clip, timelineSeconds) {
  if (!clip) return 0;
  const sourceBounds = timelineClipSourceBounds(clip);
  const timelineTime = clampTimelineValue(
    timelineSeconds,
    Number(clip.timeline_start_seconds),
    Number(clip.timeline_end_seconds),
  );
  const sourceTime = sourceBounds.start
    + (timelineTime - Number(clip.timeline_start_seconds)) * Number(clip.playback_rate || 1);
  return roundSourceValue(clampTimelineValue(
    sourceTime,
    sourceBounds.start,
    sourceBounds.end,
  ));
}

export function sourceTimeToTimelineTime(clip, sourceSeconds) {
  if (!clip) return 0;
  const sourceBounds = timelineClipSourceBounds(clip);
  const sourceTime = clampTimelineValue(
    sourceSeconds,
    sourceBounds.start,
    sourceBounds.end,
  );
  const timelineTime = Number(clip.timeline_start_seconds)
    + (sourceTime - sourceBounds.start) / Number(clip.playback_rate || 1);
  return roundTimelineValue(clampTimelineValue(
    timelineTime,
    Number(clip.timeline_start_seconds),
    Number(clip.timeline_end_seconds),
  ));
}

export function timelineTimeToSourceAudioTime(clip, timelineSeconds) {
  if (!clip) return 0;
  const timelineStart = Number(clip.timeline_start_seconds) || 0;
  const timelineDuration = Math.max(
    0.001,
    Number(clip.timeline_duration_seconds) || 0.001,
  );
  const sourceStart = Number(clip.source_audio_start_seconds) || 0;
  const sourceEnd = Math.max(
    sourceStart,
    Number(clip.source_audio_end_seconds) || sourceStart,
  );
  const progress = clampTimelineValue(
    (Number(timelineSeconds) - timelineStart) / timelineDuration,
    0,
    1,
  );
  return roundSourceValue(sourceStart + (sourceEnd - sourceStart) * progress);
}

export function sourceAudioPlaybackRate(clip) {
  if (!clip) return 1;
  const sourceDuration = Math.max(
    0.001,
    Number(clip.source_audio_end_seconds) - Number(clip.source_audio_start_seconds),
  );
  return roundSourceValue(Math.min(8, Math.max(0.25, sourceDuration / Math.max(
    0.001,
    Number(clip.timeline_duration_seconds) || 0.001,
  ))));
}

export function snapTimelineTime(
  value,
  { points = [], step = TIMELINE_SNAP_STEP, threshold = 0.08 } = {},
) {
  const numeric = Number(value) || 0;
  const nearestPoint = points.reduce((nearest, point) => (
    Math.abs(point - numeric) < Math.abs(nearest - numeric) ? point : nearest
  ), Number.POSITIVE_INFINITY);
  if (Number.isFinite(nearestPoint) && Math.abs(nearestPoint - numeric) <= threshold) {
    return roundTimelineValue(nearestPoint);
  }
  return roundTimelineValue(Math.round(numeric / step) * step);
}

export function timelineSnapPoints(timeline, ignoredId = "") {
  const clipPoints = (timeline?.clips || []).flatMap((clip) => (
    clip.id === ignoredId || !clip.enabled
      ? []
      : [clip.timeline_start_seconds, clip.timeline_end_seconds]
  ));
  const cuePoints = (timeline?.subtitle_cues || []).flatMap((cue) => (
    cue.id === ignoredId || !cue.enabled ? [] : [cue.start_seconds, cue.end_seconds]
  ));
  return [0, Number(timeline?.duration_seconds) || 0, ...clipPoints, ...cuePoints]
    .map(Number)
    .filter(Number.isFinite);
}

export function trimTimelineClip(clip, edge, deltaSeconds) {
  const playbackRate = Math.max(
    0.01,
    Number(clip.playback_rate)
      || (clip.trim_out_seconds - clip.trim_in_seconds) / clip.timeline_duration_seconds,
  );
  let trimIn = Number(clip.trim_in_seconds);
  let trimOut = Number(clip.trim_out_seconds);
  if (edge === "start") {
    trimIn = clampTimelineValue(
      snapTimelineTime(trimIn + deltaSeconds),
      0,
      trimOut - TIMELINE_MIN_DURATION,
    );
  } else {
    trimOut = clampTimelineValue(
      snapTimelineTime(trimOut + deltaSeconds),
      trimIn + TIMELINE_MIN_DURATION,
      Number(clip.candidate_duration_seconds),
    );
  }
  const timelineDuration = Math.max(
    TIMELINE_MIN_DURATION,
    (trimOut - trimIn) / playbackRate,
  );
  return {
    ...clip,
    trim_in_seconds: roundTimelineValue(trimIn),
    trim_out_seconds: roundTimelineValue(trimOut),
    timeline_duration_seconds: roundTimelineValue(timelineDuration),
  };
}

export function reorderTimelineClips(clips, clipId, targetIndex) {
  const ordered = [...clips].sort((first, second) => first.order - second.order);
  const sourceIndex = ordered.findIndex((clip) => clip.id === clipId);
  const safeTarget = clampTimelineValue(targetIndex, 0, ordered.length - 1);
  if (sourceIndex < 0 || sourceIndex === safeTarget) return ordered;
  const [moved] = ordered.splice(sourceIndex, 1);
  ordered.splice(safeTarget, 0, moved);
  return ordered.map((clip, index) => ({ ...clip, order: index + 1 }));
}

export function moveTimelineRange(item, deltaSeconds, timelineDuration) {
  const start = Number(item.timeline_start_seconds ?? item.start_seconds ?? 0);
  const end = Number(item.timeline_end_seconds ?? item.end_seconds ?? start + 1);
  const duration = Math.max(TIMELINE_MIN_DURATION, end - start);
  const nextStart = snapTimelineTime(clampTimelineValue(
    start + deltaSeconds,
    0,
    Math.max(0, timelineDuration - duration),
  ));
  const nextEnd = roundTimelineValue(nextStart + duration);
  if ("start_seconds" in item) {
    return {
      ...item,
      clip_id: null,
      clip_start_seconds: null,
      clip_end_seconds: null,
      start_seconds: nextStart,
      end_seconds: nextEnd,
    };
  }
  return {
    ...item,
    timeline_start_seconds: nextStart,
    timeline_end_seconds: nextEnd,
  };
}

export function trimTimelineRange(
  item,
  edge,
  deltaSeconds,
  timelineDuration,
  { syncSource = false } = {},
) {
  const isCue = "start_seconds" in item;
  const startKey = isCue ? "start_seconds" : "timeline_start_seconds";
  const endKey = isCue ? "end_seconds" : "timeline_end_seconds";
  const start = Number(item[startKey] || 0);
  const end = Number(item[endKey] ?? timelineDuration);
  let nextStart = start;
  let nextEnd = end;
  if (edge === "start") {
    nextStart = snapTimelineTime(clampTimelineValue(
      start + deltaSeconds,
      0,
      end - TIMELINE_MIN_DURATION,
    ));
  } else {
    nextEnd = snapTimelineTime(clampTimelineValue(
      end + deltaSeconds,
      start + TIMELINE_MIN_DURATION,
      timelineDuration,
    ));
  }
  const update = {
    ...item,
    [startKey]: roundTimelineValue(nextStart),
    [endKey]: roundTimelineValue(nextEnd),
  };
  if (isCue) {
    return {
      ...update,
      clip_id: null,
      clip_start_seconds: null,
      clip_end_seconds: null,
    };
  }
  if (syncSource && edge === "start") {
    update.source_trim_in_seconds = roundTimelineValue(clampTimelineValue(
      Number(item.source_trim_in_seconds || 0) + (nextStart - start),
      0,
      Math.max(0, Number(item.source_trim_out_seconds || timelineDuration) - TIMELINE_MIN_DURATION),
    ));
  }
  if (syncSource && edge === "end") {
    const sourceDuration = Number(item.source_duration_seconds || timelineDuration);
    update.source_trim_out_seconds = roundTimelineValue(clampTimelineValue(
      Number(item.source_trim_out_seconds || sourceDuration) + (nextEnd - end),
      Number(item.source_trim_in_seconds || 0) + TIMELINE_MIN_DURATION,
      sourceDuration,
    ));
  }
  return update;
}

export function reflowTimelineDraft(timeline) {
  if (!timeline) return timeline;
  const clips = [...timeline.clips]
    .sort((first, second) => first.order - second.order)
    .map((clip, index) => ({ ...clip, order: index + 1 }));
  const positions = new Map();
  let cursor = 0;
  const nextClips = clips.map((clip) => {
    const start = roundTimelineValue(cursor);
    const end = roundTimelineValue(start + Number(clip.timeline_duration_seconds));
    const next = {
      ...clip,
      timeline_start_seconds: start,
      timeline_end_seconds: end,
    };
    if (clip.enabled) {
      positions.set(clip.id, next);
      cursor = end;
      if (clip.transition_after?.kind === "crossfade") {
        cursor = Math.max(start, cursor - Number(clip.transition_after.duration_seconds || 0));
      }
    }
    return next;
  });
  const duration = roundTimelineValue(Math.max(cursor, TIMELINE_MIN_DURATION));
  const subtitleCues = timeline.subtitle_cues.map((cue) => {
    const clip = cue.clip_id ? positions.get(cue.clip_id) : null;
    if (!clip || cue.clip_start_seconds == null || cue.clip_end_seconds == null) {
      const start = clampTimelineValue(cue.start_seconds, 0, Math.max(0, duration - TIMELINE_MIN_DURATION));
      return {
        ...cue,
        start_seconds: roundTimelineValue(start),
        end_seconds: roundTimelineValue(clampTimelineValue(
          cue.end_seconds,
          start + TIMELINE_MIN_DURATION,
          duration,
        )),
      };
    }
    return {
      ...cue,
      start_seconds: roundTimelineValue(clip.timeline_start_seconds + cue.clip_start_seconds),
      end_seconds: roundTimelineValue(Math.min(
        clip.timeline_end_seconds,
        clip.timeline_start_seconds + cue.clip_end_seconds,
      )),
    };
  });
  const audioTrack = timeline.audio_track.linked_to_video !== false
    ? {
      ...timeline.audio_track,
      source_duration_seconds: duration,
      source_trim_in_seconds: 0,
      source_trim_out_seconds: duration,
      timeline_start_seconds: 0,
      timeline_end_seconds: duration,
    }
    : timeline.audio_track;
  return {
    ...timeline,
    clips: nextClips,
    duration_seconds: duration,
    audio_track: audioTrack,
    subtitle_cues: subtitleCues,
  };
}

export function createTimelineSubtitle(playheadSeconds, timelineDuration) {
  const start = snapTimelineTime(clampTimelineValue(
    playheadSeconds,
    0,
    Math.max(0, timelineDuration - TIMELINE_MIN_DURATION),
  ));
  return {
    id: globalThis.crypto?.randomUUID?.() || `subtitle-${Date.now()}`,
    source_cue_id: null,
    clip_id: null,
    text: "新字幕",
    language: "zh-CN",
    start_seconds: start,
    end_seconds: roundTimelineValue(Math.min(timelineDuration, start + 2)),
    clip_start_seconds: null,
    clip_end_seconds: null,
    enabled: true,
  };
}
