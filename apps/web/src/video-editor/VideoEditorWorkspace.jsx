import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowsOut,
  ArrowClockwise,
  ArrowCounterClockwise,
  ArrowDown,
  ArrowUp,
  CheckCircle,
  CircleNotch,
  ClockCounterClockwise,
  Pause,
  Play,
  Plus,
  SpeakerHigh,
  SpeakerSlash,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  ACTIVE_RENDER_STATUSES,
  editableTimelineSnapshot,
  formatEditorSeconds,
  revisionChangeLabel,
} from "./editor-state.js";
import { TimelineCanvas } from "./TimelineCanvas.jsx";
import {
  createTimelineSubtitle,
  nextTimelineClip,
  reflowTimelineDraft,
  reorderTimelineClips,
  sourceAudioPlaybackRate,
  sourceTimeToTimelineTime,
  timelineClipAtTime,
  timelineClipSourceBounds,
  timelineTimeToSourceAudioTime,
  timelineTimeToSourceTime,
} from "./timeline-math.js";
import { AutosaveStatus } from "../ui/system/index.js";
import "./video-editor.css";

const PREVIEW_MAX_HEIGHT_PX = 600;
const LOCAL_HISTORY_LIMIT = 20;
const TIMELINE_AUTOSAVE_DELAY_MS = 800;
const SOURCE_AUDIO_SYNC_TOLERANCE_SECONDS = 0.08;

function cloneTimelineDraft(timeline) {
  return typeof structuredClone === "function"
    ? structuredClone(timeline)
    : JSON.parse(JSON.stringify(timeline));
}

function clampPlaybackVolume(value) {
  return Math.min(1, Math.max(0, Number(value) || 0));
}

function timelineUpdatePayload(draft) {
  const lastEnabledClipId = draft.clips.filter((clip) => clip.enabled).at(-1)?.id;
  return {
    expected_revision_id: draft.revision_id,
    clip_order: draft.clips.map((clip) => clip.id),
    clip_updates: draft.clips.map((clip) => ({
      clip_id: clip.id,
      enabled: clip.enabled,
      trim_in_seconds: Number(clip.trim_in_seconds),
      trim_out_seconds: Number(clip.trim_out_seconds),
      timeline_duration_seconds: Number(clip.timeline_duration_seconds),
      audio_mode: clip.audio_mode,
      audio_volume: Number(clip.audio_volume),
      transition_after: clip.id === lastEnabledClipId
        ? { kind: "none", duration_seconds: 0 }
        : clip.transition_after,
    })),
    audio_track: draft.audio_track,
    background_audio_track: draft.background_audio_track,
    subtitle_cues: draft.subtitle_cues,
    summary: "从剪辑工作台自动保存时间线",
  };
}

function readAudioFileDuration(file) {
  return new Promise((resolve) => {
    const objectUrl = URL.createObjectURL(file);
    const audio = document.createElement("audio");
    let settled = false;
    function finish(value) {
      if (settled) return;
      settled = true;
      URL.revokeObjectURL(objectUrl);
      resolve(Number.isFinite(value) && value > 0 ? value : null);
    }
    audio.preload = "metadata";
    audio.onloadedmetadata = () => finish(audio.duration);
    audio.onerror = () => finish(null);
    audio.src = objectUrl;
    window.setTimeout(() => finish(null), 5000);
  });
}

function TimelineSkeleton() {
  return (
    <div aria-label="正在加载剪辑时间线" className="timeline-loading-skeleton">
      <span />
      <span />
      <span />
    </div>
  );
}

function TimelinePreviewPlayer({
  aspectHeight,
  aspectWidth,
  isScrubbing,
  onTimelineTimeChange,
  previewUrl,
  resolveUrl,
  subtitleUrl,
  timeline,
  timelineCurrentTime,
}) {
  const playerRef = useRef(null);
  const videoRef = useRef(null);
  const sourceAudioRef = useRef(null);
  const frameCallbackRef = useRef(null);
  const playIntentRef = useRef(false);
  const lastPublishedTimeRef = useRef(-1);
  const [playing, setPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const safeWidth = Math.max(1, Number(aspectWidth) || 16);
  const safeHeight = Math.max(1, Number(aspectHeight) || 9);
  const maxWidth = Math.round(PREVIEW_MAX_HEIGHT_PX * safeWidth / safeHeight);
  const timelineDuration = Math.max(0, Number(timeline?.duration_seconds) || 0);
  const displayTime = Math.min(
    timelineDuration,
    Math.max(0, Number(timelineCurrentTime) || 0),
  );
  const usingCompositePreview = Boolean(previewUrl);
  const activeClip = useMemo(
    () => timelineClipAtTime(timeline, displayTime),
    [displayTime, timeline],
  );
  const sourceUrl = usingCompositePreview
    ? previewUrl
    : resolveUrl(activeClip?.candidate_content_url);
  const sourceAudioUrl = timeline?.audio_track?.source_audio_url
    ? resolveUrl(timeline.audio_track.source_audio_url)
    : "";
  const activeAudioMode = usingCompositePreview
    ? "composite"
    : !timeline?.audio_track?.enabled || timeline.audio_track.strategy === "muted"
      ? "muted"
      : activeClip?.audio_mode === "source" && sourceAudioUrl
        ? "source"
        : activeClip?.audio_mode === "candidate" && activeClip.candidate_audio_available
          ? "candidate"
          : "muted";
  const usesSourceAudio = activeAudioMode === "source";
  const usesCandidateAudio = activeAudioMode === "candidate";
  const hasPreviewAudio = usingCompositePreview || usesSourceAudio || usesCandidateAudio;
  const effectivelyMuted = muted || volume === 0 || !hasPreviewAudio;
  const atTimelineEnd = timelineDuration > 0 && displayTime >= timelineDuration - 0.01;

  function clipAudioMode(clip) {
    if (usingCompositePreview) return "composite";
    if (!timeline?.audio_track?.enabled || timeline.audio_track.strategy === "muted") {
      return "muted";
    }
    if (clip?.audio_mode === "source" && sourceAudioUrl) return "source";
    if (clip?.audio_mode === "candidate" && clip.candidate_audio_available) return "candidate";
    return "muted";
  }

  function syncSourceAudioToTimeline(
    audio,
    timelineTime = displayTime,
    clip = activeClip,
    { force = false } = {},
  ) {
    if (!audio || !clip || clipAudioMode(clip) !== "source") return;
    const nextTime = timelineTimeToSourceAudioTime(clip, timelineTime);
    audio.playbackRate = sourceAudioPlaybackRate(clip);
    try {
      if (force || Math.abs(audio.currentTime - nextTime) > SOURCE_AUDIO_SYNC_TOLERANCE_SECONDS) {
        audio.currentTime = nextTime;
      }
    } catch {
      // Metadata may still be loading; onLoadedMetadata performs the same synchronization.
    }
  }

  function applyAudioRouting(clip = activeClip) {
    const video = videoRef.current;
    const sourceAudio = sourceAudioRef.current;
    const mode = clipAudioMode(clip);
    const trackVolume = Number(timeline?.audio_track?.volume ?? 1);
    const clipVolume = Number(clip?.audio_volume ?? 1);
    const routedVolume = clampPlaybackVolume(volume * trackVolume * clipVolume);
    if (video) {
      video.volume = usingCompositePreview ? clampPlaybackVolume(volume) : routedVolume;
      video.muted = muted || volume === 0 || (!usingCompositePreview && mode !== "candidate");
    }
    if (sourceAudio) {
      sourceAudio.volume = routedVolume;
      sourceAudio.muted = muted || volume === 0 || mode !== "source";
      if (mode !== "source") sourceAudio.pause();
    }
    return mode;
  }

  async function playSourceAudio(timelineTime = displayTime, clip = activeClip) {
    const sourceAudio = sourceAudioRef.current;
    if (!sourceAudio || clipAudioMode(clip) !== "source") return;
    applyAudioRouting(clip);
    syncSourceAudioToTimeline(sourceAudio, timelineTime, clip, { force: true });
    try {
      await sourceAudio.play();
    } catch {
      // Keep visual playback available if the browser temporarily rejects auxiliary audio.
    }
  }

  function cancelFrameLoop() {
    const video = videoRef.current;
    if (frameCallbackRef.current == null) return;
    if (video?.cancelVideoFrameCallback && typeof frameCallbackRef.current === "number") {
      video.cancelVideoFrameCallback(frameCallbackRef.current);
    } else {
      window.cancelAnimationFrame(frameCallbackRef.current);
    }
    frameCallbackRef.current = null;
  }

  function finishPlayback() {
    playIntentRef.current = false;
    setPlaying(false);
    videoRef.current?.pause();
    sourceAudioRef.current?.pause();
    onTimelineTimeChange?.(timelineDuration);
  }

  function advanceFromClipBoundary() {
    if (!activeClip) {
      finishPlayback();
      return;
    }
    const nextClip = nextTimelineClip(timeline, activeClip.id);
    if (!nextClip || !playIntentRef.current) {
      finishPlayback();
      return;
    }
    sourceAudioRef.current?.pause();
    onTimelineTimeChange?.(Number(nextClip.timeline_start_seconds));
  }

  function publishMediaTime(mediaTime) {
    if (!Number.isFinite(mediaTime)) return;
    if (usingCompositePreview) {
      const nextTime = Math.min(timelineDuration, Math.max(0, mediaTime));
      if (Math.abs(nextTime - lastPublishedTimeRef.current) >= 0.008) {
        lastPublishedTimeRef.current = nextTime;
        onTimelineTimeChange?.(nextTime);
      }
      return;
    }
    if (!activeClip) return;
    const sourceEnd = timelineClipSourceBounds(activeClip).end;
    if (mediaTime >= sourceEnd - 0.02) {
      advanceFromClipBoundary();
      return;
    }
    const nextTime = sourceTimeToTimelineTime(activeClip, mediaTime);
    syncSourceAudioToTimeline(sourceAudioRef.current, nextTime, activeClip);
    if (Math.abs(nextTime - lastPublishedTimeRef.current) >= 0.008) {
      lastPublishedTimeRef.current = nextTime;
      onTimelineTimeChange?.(nextTime);
    }
  }

  function beginFrameLoop(video) {
    cancelFrameLoop();
    if (video.requestVideoFrameCallback) {
      const tick = (_timestamp, metadata) => {
        publishMediaTime(metadata.mediaTime);
        if (!video.paused && !video.ended) {
          frameCallbackRef.current = video.requestVideoFrameCallback(tick);
        }
      };
      frameCallbackRef.current = video.requestVideoFrameCallback(tick);
      return;
    }
    const tick = () => {
      publishMediaTime(video.currentTime);
      if (!video.paused && !video.ended) {
        frameCallbackRef.current = window.requestAnimationFrame(tick);
      }
    };
    frameCallbackRef.current = window.requestAnimationFrame(tick);
  }

  function syncVideoToTimeline(video, timelineTime = displayTime, clip = activeClip) {
    if (!video || !Number.isFinite(timelineTime)) return;
    const nextTime = usingCompositePreview
      ? timelineTime
      : timelineTimeToSourceTime(clip, timelineTime);
    video.playbackRate = usingCompositePreview ? 1 : Number(clip?.playback_rate || 1);
    if (Math.abs(video.currentTime - nextTime) > 0.06) {
      video.currentTime = nextTime;
    }
    syncSourceAudioToTimeline(sourceAudioRef.current, timelineTime, clip);
  }

  useEffect(() => {
    setPlaying(false);
    lastPublishedTimeRef.current = -1;
    cancelFrameLoop();
    sourceAudioRef.current?.pause();
  }, [sourceUrl]);

  useEffect(() => {
    const mode = applyAudioRouting();
    const video = videoRef.current;
    if (mode === "source" && video && !video.paused && !video.ended) {
      playSourceAudio();
    }
  }, [
    activeClip?.audio_mode,
    activeClip?.audio_volume,
    activeClip?.candidate_audio_available,
    activeClip?.id,
    activeClip?.source_audio_end_seconds,
    activeClip?.source_audio_start_seconds,
    activeClip?.timeline_duration_seconds,
    activeClip?.timeline_start_seconds,
    muted,
    sourceAudioUrl,
    timeline?.audio_track?.enabled,
    timeline?.audio_track?.strategy,
    timeline?.audio_track?.volume,
    usingCompositePreview,
    volume,
  ]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || video.readyState < 1) return;
    syncVideoToTimeline(video);
  }, [
    activeClip?.id,
    activeClip?.playback_rate,
    activeClip?.source_range?.end_pts,
    activeClip?.source_range?.start_pts,
    activeClip?.timeline_end_seconds,
    activeClip?.timeline_start_seconds,
    activeClip?.trim_in_seconds,
    activeClip?.trim_out_seconds,
    displayTime,
    sourceUrl,
    usingCompositePreview,
  ]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || video.paused || video.ended) return;
    beginFrameLoop(video);
  }, [
    activeClip?.id,
    activeClip?.playback_rate,
    activeClip?.source_range?.end_pts,
    activeClip?.source_range?.start_pts,
    activeClip?.timeline_end_seconds,
    activeClip?.timeline_start_seconds,
    activeClip?.trim_in_seconds,
    activeClip?.trim_out_seconds,
  ]);

  useEffect(() => {
    if (!isScrubbing) return;
    playIntentRef.current = false;
    videoRef.current?.pause();
    sourceAudioRef.current?.pause();
    setPlaying(false);
  }, [isScrubbing]);

  useEffect(() => () => {
    cancelFrameLoop();
    sourceAudioRef.current?.pause();
  }, []);

  async function togglePlayback() {
    const video = videoRef.current;
    if (!video || !sourceUrl) return;
    if (playing || !video.paused) {
      playIntentRef.current = false;
      video.pause();
      sourceAudioRef.current?.pause();
      return;
    }
    const requestedTime = atTimelineEnd ? 0 : displayTime;
    const requestedClip = timelineClipAtTime(timeline, requestedTime);
    const requestedSource = usingCompositePreview
      ? previewUrl
      : resolveUrl(requestedClip?.candidate_content_url);
    playIntentRef.current = true;
    if (requestedTime !== displayTime) onTimelineTimeChange?.(requestedTime);
    if (requestedSource !== sourceUrl) return;
    syncVideoToTimeline(video, requestedTime, requestedClip);
    try {
      await video.play();
      await playSourceAudio(requestedTime, requestedClip);
    } catch {
      playIntentRef.current = false;
      setPlaying(false);
    }
  }

  function seek(event) {
    const video = videoRef.current;
    const nextTime = Number(event.target.value);
    if (!video || !Number.isFinite(nextTime)) return;
    onTimelineTimeChange?.(nextTime);
  }

  function changeVolume(event) {
    const nextVolume = clampPlaybackVolume(event.target.value);
    setVolume(nextVolume);
    setMuted(nextVolume === 0);
  }

  function toggleMute() {
    if (muted || volume === 0) {
      if (volume === 0) setVolume(0.8);
      setMuted(false);
      return;
    }
    setMuted(true);
  }

  async function enterFullscreen() {
    const player = playerRef.current;
    const video = videoRef.current;
    try {
      if (player?.requestFullscreen) {
        await player.requestFullscreen();
      } else if (video?.webkitEnterFullscreen) {
        video.webkitEnterFullscreen();
      }
    } catch {
      // Fullscreen can be denied by browser or embedding policy; playback remains usable.
    }
  }

  return (
    <div className="timeline-preview-viewport">
      <div
        className="timeline-preview-player"
        ref={playerRef}
        style={{
          "--timeline-preview-aspect": `${safeWidth} / ${safeHeight}`,
          "--timeline-preview-max-width": `${maxWidth}px`,
        }}
      >
        <div className="timeline-preview-stage">
          <video
            aria-label="剪辑时间线视频预览"
            onClick={togglePlayback}
            onEnded={() => {
              if (usingCompositePreview) finishPlayback();
              else advanceFromClipBoundary();
            }}
            onLoadedMetadata={(event) => {
              const video = event.currentTarget;
              applyAudioRouting();
              syncVideoToTimeline(video);
              if (playIntentRef.current && !isScrubbing) {
                video.play()
                  .then(() => playSourceAudio())
                  .catch(() => {
                    playIntentRef.current = false;
                    setPlaying(false);
                  });
              }
            }}
            onPause={() => {
              cancelFrameLoop();
              sourceAudioRef.current?.pause();
              setPlaying(false);
            }}
            onPlay={(event) => {
              setPlaying(true);
              beginFrameLoop(event.currentTarget);
              playSourceAudio();
            }}
            onTimeUpdate={(event) => {
              publishMediaTime(event.currentTarget.currentTime);
            }}
            playsInline
            preload="metadata"
            ref={videoRef}
            src={sourceUrl}
          >
            {usingCompositePreview && subtitleUrl && <track default kind="subtitles" label="简体中文" src={subtitleUrl} srcLang="zh-CN" />}
          </video>
          <audio
            aria-hidden="true"
            hidden
            onLoadedMetadata={(event) => {
              applyAudioRouting();
              syncSourceAudioToTimeline(event.currentTarget, displayTime, activeClip, { force: true });
              if (playIntentRef.current && !videoRef.current?.paused && usesSourceAudio) {
                event.currentTarget.play().catch(() => {});
              }
            }}
            preload="auto"
            ref={sourceAudioRef}
            src={sourceAudioUrl}
          />
        </div>
        <div className="timeline-preview-controls" role="group" aria-label="视频播放控制">
          <button
            aria-label={playing ? "暂停" : atTimelineEnd ? "重新播放" : `从 ${formatEditorSeconds(displayTime)} 播放`}
            className="timeline-player-button primary"
            disabled={!sourceUrl}
            onClick={togglePlayback}
            type="button"
          >
            {playing
              ? <Pause size={17} weight="fill" />
              : atTimelineEnd
                ? <ArrowCounterClockwise size={17} />
                : <Play size={17} weight="fill" />}
          </button>
          <input
            aria-label="播放进度"
            className="timeline-player-progress"
            disabled={!timelineDuration}
            max={timelineDuration || 0}
            min="0"
            onChange={seek}
            step="0.01"
            type="range"
            value={displayTime}
          />
          <output className="timeline-player-time" aria-live="off">
            {formatEditorSeconds(displayTime)} / {formatEditorSeconds(timelineDuration)}
          </output>
          <button
            aria-label={effectivelyMuted ? "取消静音" : "静音"}
            className="timeline-player-button"
            disabled={!sourceUrl || !hasPreviewAudio}
            onClick={toggleMute}
            type="button"
          >
            {effectivelyMuted ? <SpeakerSlash size={17} /> : <SpeakerHigh size={17} />}
          </button>
          <input
            aria-label="播放音量"
            className="timeline-player-volume"
            disabled={!sourceUrl || !hasPreviewAudio}
            max="1"
            min="0"
            onChange={changeVolume}
            step="0.05"
            type="range"
            value={muted ? 0 : volume}
          />
          <button aria-label="全屏播放" className="timeline-player-button" disabled={!sourceUrl} onClick={enterFullscreen} type="button">
            <ArrowsOut size={17} />
          </button>
        </div>
      </div>
    </div>
  );
}

function ClipInspector({ clip, clips, inspecting, onChange, onInspect, onMove }) {
  if (!clip) {
    return <div className="timeline-inspector-empty">选择一个片段后调整裁剪、节奏和转场。</div>;
  }
  const index = clips.findIndex((item) => item.id === clip.id);
  const enabled = clips.filter((item) => item.enabled);
  const lastEnabled = enabled.at(-1)?.id === clip.id;
  const maxTransition = Math.max(0.1, Math.min(2, clip.timeline_duration_seconds / 2));
  const qualityLabel = clip.quality_status === "passed"
    ? "质检通过"
    : clip.quality_status === "failed"
      ? "存在阻断"
      : "需要复核";
  return (
    <div className="timeline-inspector-form">
      <div className="timeline-inspector-heading">
        <div>
          <small>片段 {String(clip.order).padStart(2, "0")}</small>
          <h4>分镜 {clip.shot_index}</h4>
        </div>
        <label className="timeline-toggle">
          <input
            checked={clip.enabled}
            onChange={(event) => onChange({ enabled: event.target.checked })}
            type="checkbox"
          />
          <span>{clip.enabled ? "参与成片" : "已停用"}</span>
        </label>
      </div>

      <div className="timeline-order-actions" aria-label="调整片段顺序">
        <button disabled={index <= 0} onClick={() => onMove(-1)} type="button">
          <ArrowUp size={15} />向前
        </button>
        <button disabled={index < 0 || index >= clips.length - 1} onClick={() => onMove(1)} type="button">
          <ArrowDown size={15} />向后
        </button>
      </div>

      <div className="timeline-field-pair">
        <label>
          <span>入点</span>
          <div><input min="0" max={clip.trim_out_seconds - 0.05} step="0.05" type="number" value={clip.trim_in_seconds} onChange={(event) => onChange({ trim_in_seconds: Number(event.target.value) })} /><small>秒</small></div>
        </label>
        <label>
          <span>出点</span>
          <div><input min={clip.trim_in_seconds + 0.05} max={clip.candidate_duration_seconds} step="0.05" type="number" value={clip.trim_out_seconds} onChange={(event) => onChange({ trim_out_seconds: Number(event.target.value) })} /><small>秒</small></div>
        </label>
      </div>
      <label className="timeline-field">
        <span>成片时长</span>
        <div><input min="0.1" max="300" step="0.1" type="number" value={clip.timeline_duration_seconds} onChange={(event) => onChange({ timeline_duration_seconds: Number(event.target.value) })} /><small>秒</small></div>
        <em>自动保存后计算播放速率；当前约 {((clip.trim_out_seconds - clip.trim_in_seconds) / clip.timeline_duration_seconds).toFixed(2)}x</em>
      </label>
      <label className="timeline-field">
        <span>片段声音</span>
        <select value={clip.audio_mode} onChange={(event) => onChange({ audio_mode: event.target.value })}>
          <option value="source">沿用原分镜音频</option>
          <option disabled={!clip.candidate_audio_available} value="candidate">
            {clip.candidate_audio_available ? "使用候选新音频" : "候选没有新音频"}
          </option>
          <option value="muted">静音</option>
        </select>
      </label>
      <label className="timeline-field">
        <span>片段音量 · {Math.round(clip.audio_volume * 100)}%</span>
        <input max="2" min="0" step="0.05" type="range" value={clip.audio_volume} onChange={(event) => onChange({ audio_volume: Number(event.target.value) })} />
      </label>
      <div className="timeline-field-pair">
        <label>
          <span>片尾转场</span>
          <select
            value={lastEnabled ? "none" : clip.transition_after.kind}
            onChange={(event) => onChange({
              transition_after: {
                kind: event.target.value,
                duration_seconds: event.target.value === "none" ? 0 : Math.min(0.4, maxTransition),
              },
            })}
          >
            <option value="none">直接切换</option>
            {!lastEnabled && <option value="fade">淡入淡出</option>}
            {!lastEnabled && <option value="crossfade">叠化</option>}
          </select>
        </label>
        <label>
          <span>转场时长</span>
          <div>
            <input
              disabled={lastEnabled || clip.transition_after.kind === "none"}
              max={maxTransition}
              min="0.1"
              step="0.1"
              type="number"
              value={lastEnabled ? 0 : clip.transition_after.duration_seconds}
              onChange={(event) => onChange({
                transition_after: {
                  ...clip.transition_after,
                  duration_seconds: Number(event.target.value),
                },
              })}
            />
            <small>秒</small>
          </div>
        </label>
      </div>
      <section className={`timeline-quality-summary ${clip.quality_status || "warning"}`}>
        <div>
          {clip.quality_status === "passed"
            ? <CheckCircle size={17} weight="fill" />
            : <WarningCircle size={17} weight="fill" />}
          <strong>{qualityLabel}</strong>
        </div>
        {(clip.blocker_messages || []).map((message) => (
          <p className="blocking" key={message}>{message}</p>
        ))}
        {(clip.warning_messages || []).map((message) => <p key={message}>{message}</p>)}
        {!clip.quality_report?.schema_version && (
          <p>尚未在视频剪辑阶段执行基础技术质检。</p>
        )}
        <button
          className="secondary-button compact"
          disabled={inspecting}
          onClick={onInspect}
          title="检查文件、时长、画幅和帧率"
          type="button"
        >
          {inspecting ? <CircleNotch className="spin" size={15} /> : <CheckCircle size={15} />}
          {inspecting ? "正在质检" : "重新质检"}
        </button>
      </section>
    </div>
  );
}

function AudioInspector({
  audio,
  background,
  busy,
  duration,
  hasCandidateAudio,
  onBackgroundChange,
  onChange,
  onDeleteBackground,
  onUploadBackground,
}) {
  return (
    <div className="timeline-inspector-form">
      <div className="timeline-inspector-heading">
        <div><small>A1 主音轨</small><h4>分镜声音</h4></div>
        <label className="timeline-toggle">
          <input checked={audio.enabled} onChange={(event) => onChange({
            enabled: event.target.checked,
            strategy: event.target.checked && audio.strategy === "muted"
              ? "per_shot"
              : audio.strategy,
          })} disabled={!audio.source_audio_url && !hasCandidateAudio} type="checkbox" />
          <span>{audio.enabled ? "已启用" : "已静音"}</span>
        </label>
      </div>
      <label className="timeline-field">
        <span>主音轨策略</span>
        <select disabled={!audio.source_audio_url && !hasCandidateAudio} value={audio.enabled ? audio.strategy : "muted"} onChange={(event) => onChange({ strategy: event.target.value, enabled: event.target.value !== "muted" })}>
          {audio.source_audio_url && !hasCandidateAudio && <option value="continuous_source_track">连续原音轨</option>}
          {(audio.source_audio_url || hasCandidateAudio) && <option value="per_shot">按分镜声音来源</option>}
          <option value="muted">全局静音</option>
        </select>
        <em>{audio.source_audio_url || hasCandidateAudio ? "每个分镜可独立选择原音频、候选新音频或静音。" : "当前没有可用的分镜音频。"}</em>
      </label>
      <label className="timeline-field">
        <span>全局音量 · {Math.round(audio.volume * 100)}%</span>
        <input disabled={!audio.enabled} max="2" min="0" step="0.05" type="range" value={audio.volume} onChange={(event) => onChange({ volume: Number(event.target.value) })} />
      </label>
      <label className="timeline-toggle standalone">
        <input checked={audio.normalize_loudness} disabled={!audio.enabled} onChange={(event) => onChange({ normalize_loudness: event.target.checked })} type="checkbox" />
        <span>预览时执行响度标准化</span>
      </label>
      <label className="timeline-toggle standalone">
        <input
          checked={audio.linked_to_video !== false}
          disabled={!audio.enabled}
          onChange={(event) => onChange({
            linked_to_video: event.target.checked,
            source_trim_in_seconds: event.target.checked ? 0 : audio.source_trim_in_seconds,
            source_trim_out_seconds: event.target.checked ? duration : audio.source_trim_out_seconds,
            timeline_start_seconds: event.target.checked ? 0 : audio.timeline_start_seconds,
            timeline_end_seconds: event.target.checked ? duration : audio.timeline_end_seconds,
          })}
          type="checkbox"
        />
        <span>跟随视频轨同步</span>
      </label>
      {audio.enabled && audio.linked_to_video === false && (
        <div className="timeline-field-pair">
          <label>
            <span>主音轨开始</span>
            <div><input max={(audio.timeline_end_seconds ?? duration) - 0.1} min="0" onChange={(event) => onChange({ timeline_start_seconds: Number(event.target.value) })} step="0.05" type="number" value={audio.timeline_start_seconds || 0} /><small>秒</small></div>
          </label>
          <label>
            <span>主音轨结束</span>
            <div><input max={duration} min={(audio.timeline_start_seconds || 0) + 0.1} onChange={(event) => onChange({ timeline_end_seconds: Number(event.target.value) })} step="0.05" type="number" value={audio.timeline_end_seconds ?? duration} /><small>秒</small></div>
          </label>
        </div>
      )}
      <div className="timeline-inspector-divider" />
      <div className="timeline-inspector-heading">
        <div><small>A2 轻量轨道</small><h4>附加音频</h4></div>
        <label className="timeline-toggle">
          <input
            checked={background.enabled}
            disabled={!background.source_url}
            onChange={(event) => onBackgroundChange({ enabled: event.target.checked })}
            type="checkbox"
          />
          <span>{background.enabled ? "已启用" : "已关闭"}</span>
        </label>
      </div>
      <label className="timeline-audio-upload secondary-button compact">
        <input
          accept="audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/aac,audio/ogg,audio/flac,.mp3,.wav,.m4a,.aac,.ogg,.flac"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUploadBackground(file);
            event.target.value = "";
          }}
          type="file"
        />
        {busy ? <CircleNotch className="spin" size={15} /> : <SpeakerHigh size={15} />}
        {background.source_url ? "替换附加音频" : "添加附加音频"}
      </label>
      <small className="timeline-audio-file-name">
        {background.name || "支持 MP3、WAV、M4A、AAC、OGG、FLAC，最大 100 MB"}
      </small>
      {background.source_url && (
        <button className="timeline-destructive-button" onClick={onDeleteBackground} type="button">
          <Trash size={15} />删除附加音频
        </button>
      )}
      <label className="timeline-field">
        <span>附加音量 · {Math.round(background.volume * 100)}%</span>
        <input
          disabled={!background.enabled}
          max="2"
          min="0"
          onChange={(event) => onBackgroundChange({ volume: Number(event.target.value) })}
          step="0.05"
          type="range"
          value={background.volume}
        />
      </label>
      <label className="timeline-toggle standalone">
        <input
          checked={background.loop}
          disabled={!background.source_url}
          onChange={(event) => onBackgroundChange({ loop: event.target.checked })}
          type="checkbox"
        />
        <span>音频不足成片时循环播放</span>
      </label>
      {background.source_url && (
        <>
          <div className="timeline-field-pair">
            <label>
              <span>轨道开始</span>
              <div><input max={(background.timeline_end_seconds ?? duration) - 0.1} min="0" onChange={(event) => onBackgroundChange({ timeline_start_seconds: Number(event.target.value) })} step="0.05" type="number" value={background.timeline_start_seconds || 0} /><small>秒</small></div>
            </label>
            <label>
              <span>轨道结束</span>
              <div><input max={duration} min={(background.timeline_start_seconds || 0) + 0.1} onChange={(event) => onBackgroundChange({ timeline_end_seconds: Number(event.target.value) })} step="0.05" type="number" value={background.timeline_end_seconds ?? duration} /><small>秒</small></div>
            </label>
          </div>
          <div className="timeline-field-pair">
            <label>
              <span>素材入点</span>
              <div><input max={(background.source_trim_out_seconds ?? background.source_duration_seconds ?? duration) - 0.1} min="0" onChange={(event) => onBackgroundChange({ source_trim_in_seconds: Number(event.target.value) })} step="0.05" type="number" value={background.source_trim_in_seconds || 0} /><small>秒</small></div>
            </label>
            <label>
              <span>素材出点</span>
              <div><input max={background.source_duration_seconds || duration} min={(background.source_trim_in_seconds || 0) + 0.1} onChange={(event) => onBackgroundChange({ source_trim_out_seconds: Number(event.target.value) })} step="0.05" type="number" value={background.source_trim_out_seconds ?? background.source_duration_seconds ?? duration} /><small>秒</small></div>
            </label>
          </div>
        </>
      )}
    </div>
  );
}

function SubtitleInspector({ cues, onAdd, onChange, onDelete, onSelect, selectedCueId }) {
  return (
    <div className="timeline-subtitle-editor">
      <div className="timeline-inspector-heading">
        <div><small>文本轨道</small><h4>字幕与对白</h4></div>
        <button className="secondary-button compact" onClick={onAdd} type="button"><Plus size={15} />添加字幕</button>
      </div>
      <small className="timeline-subtitle-count">{cues.filter((cue) => cue.enabled).length}/{cues.length} 条启用</small>
      {cues.length === 0 && <div className="timeline-inspector-empty">播放头移动到目标位置后添加第一条字幕。</div>}
      {cues.map((cue) => (
        <div className={`timeline-subtitle-item ${cue.enabled ? "" : "disabled"} ${selectedCueId === cue.id ? "selected" : ""}`} key={cue.id} onClick={() => onSelect(cue.id)}>
          <input aria-label="启用字幕" checked={cue.enabled} onChange={(event) => onChange(cue.id, { enabled: event.target.checked })} type="checkbox" />
          <span>
            <small>{formatEditorSeconds(cue.start_seconds)}–{formatEditorSeconds(cue.end_seconds)}</small>
            <textarea rows="2" value={cue.text} onChange={(event) => onChange(cue.id, { text: event.target.value })} />
            <span className="timeline-subtitle-time-fields">
              <label>开始<input max={cue.end_seconds - 0.1} min="0" onChange={(event) => onChange(cue.id, { clip_id: null, clip_start_seconds: null, clip_end_seconds: null, start_seconds: Number(event.target.value) })} step="0.05" type="number" value={cue.start_seconds} /></label>
              <label>结束<input min={cue.start_seconds + 0.1} onChange={(event) => onChange(cue.id, { clip_id: null, clip_start_seconds: null, clip_end_seconds: null, end_seconds: Number(event.target.value) })} step="0.05" type="number" value={cue.end_seconds} /></label>
            </span>
          </span>
          <button aria-label="删除字幕" className="timeline-subtitle-delete" onClick={(event) => { event.stopPropagation(); onDelete(cue.id); }} title="删除字幕" type="button"><Trash size={15} /></button>
        </div>
      ))}
    </div>
  );
}

export function VideoEditorWorkspace({
  project,
  request,
  resolveUrl,
  onNotice,
  onNotificationsChanged,
}) {
  const [timeline, setTimeline] = useState(null);
  const [savedSnapshot, setSavedSnapshot] = useState("");
  const [validation, setValidation] = useState(null);
  const [revisions, setRevisions] = useState([]);
  const [selectedClipId, setSelectedClipId] = useState("");
  const [selectedCueId, setSelectedCueId] = useState("");
  const [selectedTrack, setSelectedTrack] = useState("");
  const [playheadSeconds, setPlayheadSeconds] = useState(0);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const [inspectorTab, setInspectorTab] = useState("clip");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [renderJob, setRenderJob] = useState(null);
  const [undoStack, setUndoStack] = useState([]);
  const [redoStack, setRedoStack] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [autosaveState, setAutosaveState] = useState("saved");
  const [error, setError] = useState("");
  const timelineRef = useRef(timeline);
  const savedSnapshotRef = useRef(savedSnapshot);
  const gestureSnapshotRef = useRef(null);
  const autosaveTimerRef = useRef(null);
  const saveInFlightRef = useRef(null);
  const projectIdRef = useRef(project.id);
  timelineRef.current = timeline;
  projectIdRef.current = project.id;
  const dirty = Boolean(timeline && editableTimelineSnapshot(timeline) !== savedSnapshot);
  const selectedClip = useMemo(
    () => timeline?.clips.find((clip) => clip.id === selectedClipId) || timeline?.clips[0] || null,
    [selectedClipId, timeline],
  );
  const previewUrl = renderJob?.status === "succeeded" && renderJob.output_url
    ? resolveUrl(renderJob.output_url)
    : "";
  const previewSubtitleUrl = renderJob?.status === "succeeded" && renderJob.subtitle_url
    ? resolveUrl(renderJob.subtitle_url)
    : "";
  const compositePreviewUrl = (
    previewUrl
    && !dirty
    && renderJob?.timeline_revision_id === timeline?.revision_id
  ) ? previewUrl : "";
  const playheadClip = useMemo(
    () => timelineClipAtTime(timeline, playheadSeconds),
    [playheadSeconds, timeline],
  );

  function markTimelineSnapshotSaved(nextTimeline) {
    const snapshot = editableTimelineSnapshot(nextTimeline);
    savedSnapshotRef.current = snapshot;
    setSavedSnapshot(snapshot);
  }

  function rememberSnapshot(snapshot) {
    if (!snapshot) return;
    setUndoStack((current) => [
      ...current.slice(-(LOCAL_HISTORY_LIMIT - 1)),
      cloneTimelineDraft(snapshot),
    ]);
    setRedoStack([]);
  }

  function applyTimelineEdit(updater, { record = true } = {}) {
    const current = timelineRef.current;
    if (!current) return;
    const next = updater(current);
    if (!next || editableTimelineSnapshot(next) === editableTimelineSnapshot(current)) return;
    if (record) rememberSnapshot(current);
    timelineRef.current = next;
    setTimeline(next);
    setError("");
    setAutosaveState(saveInFlightRef.current ? "saving" : "dirty");
  }

  function beginTimelineGesture() {
    if (!gestureSnapshotRef.current && timelineRef.current) {
      gestureSnapshotRef.current = cloneTimelineDraft(timelineRef.current);
    }
  }

  function endTimelineGesture() {
    const before = gestureSnapshotRef.current;
    gestureSnapshotRef.current = null;
    if (
      before
      && timelineRef.current
      && editableTimelineSnapshot(before) !== editableTimelineSnapshot(timelineRef.current)
    ) {
      rememberSnapshot(before);
    }
  }

  function undoTimelineEdit() {
    if (!undoStack.length || !timelineRef.current) return;
    const previous = undoStack.at(-1);
    setUndoStack((current) => current.slice(0, -1));
    setRedoStack((current) => [
      ...current.slice(-(LOCAL_HISTORY_LIMIT - 1)),
      cloneTimelineDraft(timelineRef.current),
    ]);
    timelineRef.current = cloneTimelineDraft(previous);
    setTimeline(timelineRef.current);
    setError("");
    setAutosaveState(saveInFlightRef.current ? "saving" : "dirty");
  }

  function redoTimelineEdit() {
    if (!redoStack.length || !timelineRef.current) return;
    const next = redoStack.at(-1);
    setRedoStack((current) => current.slice(0, -1));
    setUndoStack((current) => [
      ...current.slice(-(LOCAL_HISTORY_LIMIT - 1)),
      cloneTimelineDraft(timelineRef.current),
    ]);
    timelineRef.current = cloneTimelineDraft(next);
    setTimeline(timelineRef.current);
    setError("");
    setAutosaveState(saveInFlightRef.current ? "saving" : "dirty");
  }

  async function loadTimeline() {
    if (autosaveTimerRef.current) window.clearTimeout(autosaveTimerRef.current);
    setLoading(true);
    setError("");
    setAutosaveState("saved");
    try {
      const nextTimeline = await request(`/productions/${project.id}/timeline`);
      const [nextRevisions, nextValidation] = await Promise.all([
        request(`/productions/${project.id}/timeline/revisions`),
        request(`/productions/${project.id}/timeline/validation`),
      ]);
      timelineRef.current = nextTimeline;
      setTimeline(nextTimeline);
      markTimelineSnapshotSaved(nextTimeline);
      setSelectedClipId((current) => (
        nextTimeline.clips.some((clip) => clip.id === current)
          ? current
          : nextTimeline.clips[0]?.id || ""
      ));
      setRevisions(nextRevisions.items || []);
      setValidation(nextValidation);
      setUndoStack([]);
      setRedoStack([]);
      setPlayheadSeconds((current) => Math.min(current, nextTimeline.duration_seconds));
      if (nextTimeline.last_preview_job_id) {
        try {
          const job = await request(
            `/productions/${project.id}/render-jobs/${nextTimeline.last_preview_job_id}`,
          );
          setRenderJob(job);
        } catch {
          setRenderJob(null);
        }
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTimeline();
  }, [project.id]);

  useEffect(() => {
    if (!renderJob?.id || !ACTIVE_RENDER_STATUSES.has(renderJob.status)) return undefined;
    let disposed = false;
    let timer = null;
    async function poll() {
      try {
        const next = await request(`/productions/${project.id}/render-jobs/${renderJob.id}`);
        if (disposed) return;
        setRenderJob(next);
        if (ACTIVE_RENDER_STATUSES.has(next.status)) {
          timer = window.setTimeout(poll, 1000);
        } else {
          await onNotificationsChanged?.();
        }
      } catch {
        if (!disposed) timer = window.setTimeout(poll, 1800);
      }
    }
    timer = window.setTimeout(poll, 500);
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [project.id, renderJob?.id, renderJob?.status]);

  useEffect(() => {
    if (!timeline) return;
    setPlayheadSeconds((current) => Math.min(current, timeline.duration_seconds));
  }, [timeline?.duration_seconds]);

  useEffect(() => {
    if (autosaveTimerRef.current) window.clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = null;
    if (!timeline || loading) return undefined;
    if (!dirty) {
      if (!saveInFlightRef.current) setAutosaveState("saved");
      return undefined;
    }
    autosaveTimerRef.current = window.setTimeout(() => {
      autosaveTimerRef.current = null;
      flushTimelineSave().catch(() => {});
    }, TIMELINE_AUTOSAVE_DELAY_MS);
    return () => {
      if (autosaveTimerRef.current) window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    };
  }, [dirty, loading, project.id, timeline]);

  useEffect(() => {
    if (!dirty) return undefined;
    const warnBeforeUnload = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [dirty]);

  useEffect(() => () => {
    if (autosaveTimerRef.current) window.clearTimeout(autosaveTimerRef.current);
  }, []);

  function updateClip(values) {
    if (!selectedClip) return;
    applyTimelineEdit((current) => reflowTimelineDraft({
      ...current,
      clips: current.clips.map((clip) => (
        clip.id === selectedClip.id ? { ...clip, ...values } : clip
      )),
    }));
  }

  function updateCanvasClip(clipId, nextClip, options = {}) {
    applyTimelineEdit((current) => reflowTimelineDraft({
      ...current,
      clips: current.clips.map((clip) => clip.id === clipId ? nextClip : clip),
    }), { record: !options.transient });
  }

  function reorderCanvasClip(clipId, targetIndex, options = {}) {
    applyTimelineEdit((current) => reflowTimelineDraft({
      ...current,
      clips: reorderTimelineClips(current.clips, clipId, targetIndex),
    }), { record: !options.transient });
  }

  function moveSelectedClip(direction) {
    applyTimelineEdit((current) => {
      const clips = [...current.clips].sort((first, second) => first.order - second.order);
      const index = clips.findIndex((clip) => clip.id === selectedClipId);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= clips.length) return current;
      return reflowTimelineDraft({
        ...current,
        clips: reorderTimelineClips(clips, selectedClipId, target),
      });
    });
  }

  function updateAudio(values, options = {}) {
    applyTimelineEdit((current) => reflowTimelineDraft({
      ...current,
      audio_track: { ...current.audio_track, ...values },
    }), { record: !options.transient });
  }

  function updateBackgroundAudio(values, options = {}) {
    applyTimelineEdit((current) => ({
      ...current,
      background_audio_track: { ...current.background_audio_track, ...values },
    }), { record: !options.transient });
  }

  function updateSubtitle(cueId, values, options = {}) {
    applyTimelineEdit((current) => reflowTimelineDraft({
      ...current,
      subtitle_cues: current.subtitle_cues.map((cue) => (
        cue.id === cueId ? { ...cue, ...values } : cue
      )),
    }), { record: !options.transient });
  }

  function addSubtitle() {
    if (!timeline) return;
    const cue = createTimelineSubtitle(playheadSeconds, timeline.duration_seconds);
    applyTimelineEdit((current) => ({
      ...current,
      subtitle_cues: [...current.subtitle_cues, cue],
    }));
    setSelectedCueId(cue.id);
    setInspectorTab("subtitles");
  }

  function deleteSubtitle(cueId) {
    applyTimelineEdit((current) => ({
      ...current,
      subtitle_cues: current.subtitle_cues.filter((cue) => cue.id !== cueId),
    }));
    setSelectedCueId((current) => current === cueId ? "" : current);
  }

  function deleteBackgroundAudio() {
    applyTimelineEdit((current) => ({
      ...current,
      background_audio_track: {
        source_relative_path: null,
        source_url: null,
        name: null,
        enabled: false,
        volume: current.background_audio_track.volume,
        loop: true,
        source_duration_seconds: null,
        source_trim_in_seconds: 0,
        source_trim_out_seconds: null,
        timeline_start_seconds: 0,
        timeline_end_seconds: null,
      },
    }));
    setSelectedTrack("");
  }

  function persistCurrentTimeline() {
    if (saveInFlightRef.current) return saveInFlightRef.current;
    const draft = timelineRef.current;
    const sentSnapshot = editableTimelineSnapshot(draft);
    if (!draft || sentSnapshot === savedSnapshotRef.current) {
      setAutosaveState("saved");
      return Promise.resolve(draft);
    }

    const projectId = project.id;
    setAutosaveState("saving");
    setError("");
    const saveTask = (async () => {
      try {
        const saved = await request(`/productions/${projectId}/timeline`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(timelineUpdatePayload(draft)),
        });
        if (projectIdRef.current !== projectId) return timelineRef.current;

        const current = timelineRef.current;
        const currentSnapshot = editableTimelineSnapshot(current);
        const nextTimeline = currentSnapshot === sentSnapshot
          ? saved
          : {
            ...current,
            revision_id: saved.revision_id,
            revision_number: saved.revision_number,
            updated_at: saved.updated_at,
            last_preview_job_id: null,
            last_export_job_id: null,
          };
        const persistedSnapshot = editableTimelineSnapshot(saved);
        timelineRef.current = nextTimeline;
        savedSnapshotRef.current = persistedSnapshot;
        setTimeline(nextTimeline);
        setSavedSnapshot(persistedSnapshot);
        setAutosaveState(
          editableTimelineSnapshot(nextTimeline) === persistedSnapshot ? "saved" : "dirty",
        );
        setRenderJob(null);

        Promise.all([
          request(`/productions/${projectId}/timeline/validation`),
          request(`/productions/${projectId}/timeline/revisions`),
        ]).then(([nextValidation, nextRevisions]) => {
          if (projectIdRef.current !== projectId) return;
          setValidation(nextValidation);
          setRevisions(nextRevisions.items || []);
        }).catch(() => {
          // The timeline is already saved; metadata will refresh on the next save or page load.
        });
        return nextTimeline;
      } catch (requestError) {
        if (projectIdRef.current === projectId) {
          setAutosaveState("error");
          setError(requestError.message);
          onNotice({ type: "error", title: "时间线自动保存失败", message: requestError.message });
        }
        throw requestError;
      } finally {
        saveInFlightRef.current = null;
      }
    })();
    saveInFlightRef.current = saveTask;
    return saveTask;
  }

  async function flushTimelineSave() {
    if (autosaveTimerRef.current) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    for (let attempt = 0; attempt < 10; attempt += 1) {
      if (saveInFlightRef.current) await saveInFlightRef.current;
      const current = timelineRef.current;
      if (!current || editableTimelineSnapshot(current) === savedSnapshotRef.current) {
        setAutosaveState("saved");
        return current;
      }
      await persistCurrentTimeline();
    }
    throw new Error("时间线仍在持续修改，请稍后重试");
  }

  async function uploadBackgroundAudio(file) {
    if (!timelineRef.current || !file) return;
    setBusy(true);
    setError("");
    try {
      const savedTimeline = await flushTimelineSave();
      const durationSeconds = await readAudioFileDuration(file);
      const form = new FormData();
      form.append("expected_revision_id", savedTimeline.revision_id);
      if (durationSeconds) form.append("duration_seconds", String(durationSeconds));
      form.append("file", file);
      const updated = await request(
        `/productions/${project.id}/timeline/background-audio`,
        { method: "POST", body: form },
      );
      const nextRevisions = await request(`/productions/${project.id}/timeline/revisions`);
      timelineRef.current = updated;
      setTimeline(updated);
      markTimelineSnapshotSaved(updated);
      setAutosaveState("saved");
      setRevisions(nextRevisions.items || []);
      setRenderJob(null);
      setUndoStack([]);
      setRedoStack([]);
      onNotice({ type: "success", title: "附加音轨已添加", message: file.name });
    } catch (requestError) {
      setError(requestError.message);
      onNotice({ type: "error", title: "附加音轨上传失败", message: requestError.message });
    } finally {
      setBusy(false);
    }
  }

  async function inspectSelectedClip() {
    if (!timelineRef.current || !selectedClip) return;
    const selectedClipIdForInspection = selectedClip.id;
    const selectedShotIndex = selectedClip.shot_index;
    setBusy(true);
    setError("");
    try {
      const savedTimeline = await flushTimelineSave();
      const inspected = await request(
        `/productions/${project.id}/timeline/clips/${selectedClipIdForInspection}/inspect`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_revision_id: savedTimeline.revision_id }),
        },
      );
      const [nextValidation, nextRevisions] = await Promise.all([
        request(`/productions/${project.id}/timeline/validation`),
        request(`/productions/${project.id}/timeline/revisions`),
      ]);
      timelineRef.current = inspected;
      setTimeline(inspected);
      markTimelineSnapshotSaved(inspected);
      setAutosaveState("saved");
      setValidation(nextValidation);
      setRevisions(nextRevisions.items || []);
      setRenderJob(null);
      setUndoStack([]);
      setRedoStack([]);
      const inspectedClip = inspected.clips.find((item) => item.id === selectedClipIdForInspection);
      onNotice({
        type: inspectedClip?.quality_status === "passed" ? "success" : "warning",
        title: `分镜 ${selectedShotIndex} 已完成基础质检`,
        message: inspectedClip?.warning_messages?.[0] || "技术信息已更新。",
      });
    } catch (requestError) {
      setError(requestError.message);
      onNotice({ type: "error", title: "片段质检失败", message: requestError.message });
    } finally {
      setBusy(false);
    }
  }

  async function generatePreview() {
    if (!timelineRef.current) return;
    setBusy(true);
    setError("");
    try {
      const savedTimeline = await flushTimelineSave();
      const job = await request(`/productions/${project.id}/timeline/preview-renders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision_id: savedTimeline.revision_id }),
      });
      setRenderJob(job);
      onNotice({ type: "info", title: "低清预览已排队", message: "可以继续留在页面查看进度。" });
      await onNotificationsChanged?.();
    } catch (requestError) {
      setError(requestError.message);
      onNotice({ type: "error", title: "无法生成预览", message: requestError.message });
    } finally {
      setBusy(false);
    }
  }

  async function cancelPreview() {
    if (!renderJob?.id) return;
    try {
      const next = await request(`/productions/${project.id}/render-jobs/${renderJob.id}/cancel`, { method: "POST" });
      setRenderJob(next);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function restoreRevision(revision) {
    if (!timelineRef.current || revision.id === timelineRef.current.revision_id) return;
    setBusy(true);
    setError("");
    try {
      const savedTimeline = await flushTimelineSave();
      const restored = await request(`/productions/${project.id}/timeline/revisions/${revision.id}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision_id: savedTimeline.revision_id }),
      });
      timelineRef.current = restored;
      setTimeline(restored);
      markTimelineSnapshotSaved(restored);
      setAutosaveState("saved");
      setSelectedClipId(restored.clips[0]?.id || "");
      setSelectedCueId("");
      setSelectedTrack("");
      setPlayheadSeconds(0);
      setHistoryOpen(false);
      setRenderJob(null);
      setUndoStack([]);
      setRedoStack([]);
      const next = await request(`/productions/${project.id}/timeline/revisions`);
      setRevisions(next.items || []);
      onNotice({ type: "success", title: "时间线已恢复", message: `已从版本 ${revision.revision_number} 创建新版本。` });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <TimelineSkeleton />;
  if (error && !timeline) {
    return <div className="production-inline-error timeline-load-error" role="alert"><WarningCircle size={18} />{error}<button onClick={loadTimeline} type="button">重试</button></div>;
  }
  if (!timeline) return null;

  return (
    <section className="editing-timeline-workspace">
      <header className="timeline-workspace-toolbar">
        <div>
          <span className="timeline-eyebrow">独立模块 · 受控时间线</span>
          <h3>视频剪辑工作台</h3>
          <p>{timeline.clips.filter((clip) => clip.enabled).length} 个片段 · {formatEditorSeconds(timeline.duration_seconds)} · {timeline.output_aspect_ratio}</p>
        </div>
        <div className="timeline-toolbar-actions">
          {renderJob && ACTIVE_RENDER_STATUSES.has(renderJob.status) && (
            <div className="timeline-render-progress" aria-live="polite">
              <CircleNotch className="spin" size={16} />
              <span>预览渲染 {renderJob.progress_percent}%</span>
              <button onClick={cancelPreview} type="button">取消</button>
            </div>
          )}
          <div className="timeline-local-history" role="group" aria-label="本地编辑历史">
            <button aria-label="撤销" disabled={!undoStack.length || busy} onClick={undoTimelineEdit} title="撤销" type="button"><ArrowCounterClockwise size={16} /></button>
            <button aria-label="重做" disabled={!redoStack.length || busy} onClick={redoTimelineEdit} title="重做" type="button"><ArrowClockwise size={16} /></button>
          </div>
          <button className="secondary-button compact" onClick={() => setHistoryOpen((value) => !value)} type="button">
            <ClockCounterClockwise size={16} />版本 {timeline.revision_number}
          </button>
          <AutosaveStatus
            onRetry={() => flushTimelineSave().catch(() => {})}
            state={autosaveState}
          />
          <button className="primary-button compact" disabled={busy || ACTIVE_RENDER_STATUSES.has(renderJob?.status)} onClick={generatePreview} type="button">
            <Play size={16} weight="fill" />{renderJob?.status === "succeeded" ? "重新生成合成预览" : "生成合成预览"}
          </button>
        </div>
      </header>

      {historyOpen && (
        <div className="timeline-history-panel">
          <div><strong>时间线版本</strong><small>恢复历史会创建新版本，不覆盖旧快照。</small></div>
          <div className="timeline-history-list">
            {[...revisions].reverse().map((revision) => (
              <button disabled={busy || revision.id === timeline.revision_id} key={revision.id} onClick={() => restoreRevision(revision)} type="button">
                <span><strong>v{revision.revision_number}</strong><small>{revisionChangeLabel(revision.change_kind)}</small></span>
                <em>{revision.id === timeline.revision_id ? "当前" : "恢复"}</em>
              </button>
            ))}
          </div>
        </div>
      )}

      {(error || validation?.warnings?.length > 0) && (
        <div className={`timeline-context-notice ${error ? "error" : "info"}`}>
          <WarningCircle size={17} />
          <span>{error || validation.warnings[0]}</span>
        </div>
      )}

      <div className="timeline-editor-grid">
        <div className="timeline-canvas-column">
          <div className="timeline-preview-panel">
            <div className="timeline-preview-heading">
              <div>
                <strong>{compositePreviewUrl ? "低清合成预览" : `分镜 ${playheadClip?.shot_index || "-"} 实时预览`}</strong>
                <small>{compositePreviewUrl ? "已包含分镜音频、字幕轨和转场" : "画面跟随播放轴；生成预览后可检查完整转场与混音"}</small>
              </div>
              {compositePreviewUrl && <span><CheckCircle size={15} weight="fill" />预览就绪</span>}
              {renderJob?.status === "failed" && <span className="failed"><WarningCircle size={15} />生成失败</span>}
            </div>
            <TimelinePreviewPlayer
              aspectHeight={timeline.output_height}
              aspectWidth={timeline.output_width}
              isScrubbing={isScrubbing}
              onTimelineTimeChange={setPlayheadSeconds}
              previewUrl={compositePreviewUrl}
              resolveUrl={resolveUrl}
              subtitleUrl={previewSubtitleUrl}
              timeline={timeline}
              timelineCurrentTime={playheadSeconds}
            />
          </div>
          <div className="timeline-track-zone">
            <TimelineCanvas
              activeClipId={playheadClip?.id}
              onAddSubtitle={addSubtitle}
              onAudioChange={updateAudio}
              onBackgroundChange={updateBackgroundAudio}
              onClipChange={updateCanvasClip}
              onClipReorder={reorderCanvasClip}
              onCueChange={updateSubtitle}
              onDeleteBackground={deleteBackgroundAudio}
              onDeleteCue={deleteSubtitle}
              onGestureEnd={endTimelineGesture}
              onGestureStart={beginTimelineGesture}
              onPlayheadChange={setPlayheadSeconds}
              onScrubEnd={() => setIsScrubbing(false)}
              onScrubStart={() => setIsScrubbing(true)}
              onSelectAudio={(track) => { setSelectedTrack(track); setInspectorTab("audio"); }}
              onSelectClip={(clipId) => { setSelectedClipId(clipId); setInspectorTab("clip"); }}
              onSelectCue={(cueId) => { setSelectedCueId(cueId); setInspectorTab("subtitles"); }}
              playheadSeconds={playheadSeconds}
              selectedClipId={selectedClip?.id}
              selectedCueId={selectedCueId}
              selectedTrack={selectedTrack}
              timeline={timeline}
            />
          </div>
        </div>

        <aside className="timeline-inspector">
          <nav aria-label="时间线属性">
            <button className={inspectorTab === "clip" ? "active" : ""} onClick={() => setInspectorTab("clip")} type="button">片段</button>
            <button className={inspectorTab === "audio" ? "active" : ""} onClick={() => setInspectorTab("audio")} type="button">音轨</button>
            <button className={inspectorTab === "subtitles" ? "active" : ""} onClick={() => setInspectorTab("subtitles")} type="button">字幕</button>
          </nav>
          {inspectorTab === "clip" && (
            <ClipInspector
              clip={selectedClip}
              clips={timeline.clips}
              inspecting={busy}
              onChange={updateClip}
              onInspect={inspectSelectedClip}
              onMove={moveSelectedClip}
            />
          )}
          {inspectorTab === "audio" && (
            <AudioInspector
              audio={timeline.audio_track}
              background={timeline.background_audio_track}
              busy={busy}
              duration={timeline.duration_seconds}
              hasCandidateAudio={timeline.clips.some(
                (clip) => clip.enabled && clip.candidate_audio_available,
              )}
              onBackgroundChange={updateBackgroundAudio}
              onChange={updateAudio}
              onDeleteBackground={deleteBackgroundAudio}
              onUploadBackground={uploadBackgroundAudio}
            />
          )}
          {inspectorTab === "subtitles" && (
            <SubtitleInspector
              cues={timeline.subtitle_cues}
              onAdd={addSubtitle}
              onChange={updateSubtitle}
              onDelete={deleteSubtitle}
              onSelect={setSelectedCueId}
              selectedCueId={selectedCueId}
            />
          )}
        </aside>
      </div>
    </section>
  );
}
