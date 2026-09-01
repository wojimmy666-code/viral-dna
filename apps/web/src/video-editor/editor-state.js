export const ACTIVE_RENDER_STATUSES = new Set(["queued", "running"]);

export function formatEditorSeconds(value) {
  const seconds = Math.max(0, Number(value) || 0);
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds - minutes * 60;
  return `${minutes}:${remainder.toFixed(1).padStart(4, "0")}`;
}

export function revisionChangeLabel(value) {
  return {
    initialized: "创建初始时间线",
    handoff_synced: "同步最新分段视频",
    clips_updated: "调整片段",
    tracks_updated: "调整轨道",
    restored: "恢复历史版本",
  }[value] || value;
}

export function editableTimelineSnapshot(timeline) {
  if (!timeline) return "";
  return JSON.stringify({
    clipOrder: timeline.clips.map((clip) => clip.id),
    clips: timeline.clips.map((clip) => ({
      id: clip.id,
      enabled: clip.enabled,
      trimIn: Number(clip.trim_in_seconds),
      trimOut: Number(clip.trim_out_seconds),
      duration: Number(clip.timeline_duration_seconds),
      audioMode: clip.audio_mode,
      audioVolume: Number(clip.audio_volume),
      transition: clip.transition_after,
    })),
    audio: timeline.audio_track,
    backgroundAudio: timeline.background_audio_track,
    subtitles: timeline.subtitle_cues,
  });
}
