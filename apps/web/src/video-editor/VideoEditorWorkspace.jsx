import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowsOut,
  ArrowDown,
  ArrowUp,
  CheckCircle,
  CircleNotch,
  ClockCounterClockwise,
  FilmSlate,
  FloppyDisk,
  Pause,
  Play,
  SpeakerHigh,
  SpeakerSlash,
  Subtitles,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  ACTIVE_RENDER_STATUSES,
  editableTimelineSnapshot,
  formatEditorSeconds,
  revisionChangeLabel,
} from "./editor-state.js";
import "./video-editor.css";

const PREVIEW_MAX_HEIGHT_PX = 600;

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
  sourceUrl,
  subtitleUrl,
}) {
  const playerRef = useRef(null);
  const videoRef = useRef(null);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const safeWidth = Math.max(1, Number(aspectWidth) || 16);
  const safeHeight = Math.max(1, Number(aspectHeight) || 9);
  const maxWidth = Math.round(PREVIEW_MAX_HEIGHT_PX * safeWidth / safeHeight);

  useEffect(() => {
    setDuration(0);
    setCurrentTime(0);
    setPlaying(false);
  }, [sourceUrl]);

  async function togglePlayback() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused || video.ended) {
      if (video.ended) video.currentTime = 0;
      try {
        await video.play();
      } catch {
        setPlaying(false);
      }
      return;
    }
    video.pause();
  }

  function seek(event) {
    const video = videoRef.current;
    const nextTime = Number(event.target.value);
    if (!video || !Number.isFinite(nextTime)) return;
    video.currentTime = nextTime;
    setCurrentTime(nextTime);
  }

  function changeVolume(event) {
    const video = videoRef.current;
    const nextVolume = Math.min(1, Math.max(0, Number(event.target.value)));
    if (!video) return;
    video.volume = nextVolume;
    video.muted = nextVolume === 0;
    setVolume(nextVolume);
    setMuted(nextVolume === 0);
  }

  function toggleMute() {
    const video = videoRef.current;
    if (!video) return;
    if (video.muted || video.volume === 0) {
      const restoredVolume = video.volume === 0 ? 0.8 : video.volume;
      video.volume = restoredVolume;
      video.muted = false;
      setVolume(restoredVolume);
      setMuted(false);
      return;
    }
    video.muted = true;
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
            key={sourceUrl}
            onClick={togglePlayback}
            onDurationChange={(event) => setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)}
            onEnded={() => setPlaying(false)}
            onLoadedMetadata={(event) => {
              const video = event.currentTarget;
              setDuration(Number.isFinite(video.duration) ? video.duration : 0);
              setVolume(video.volume);
              setMuted(video.muted);
            }}
            onPause={() => setPlaying(false)}
            onPlay={() => setPlaying(true)}
            onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
            onVolumeChange={(event) => {
              setVolume(event.currentTarget.volume);
              setMuted(event.currentTarget.muted);
            }}
            playsInline
            preload="metadata"
            ref={videoRef}
            src={sourceUrl}
          >
            {subtitleUrl && <track default kind="subtitles" label="简体中文" src={subtitleUrl} srcLang="zh-CN" />}
          </video>
        </div>
        <div className="timeline-preview-controls" role="group" aria-label="视频播放控制">
          <button
            aria-label={playing ? "暂停" : "播放"}
            className="timeline-player-button primary"
            disabled={!sourceUrl}
            onClick={togglePlayback}
            type="button"
          >
            {playing ? <Pause size={17} weight="fill" /> : <Play size={17} weight="fill" />}
          </button>
          <input
            aria-label="播放进度"
            className="timeline-player-progress"
            disabled={!duration}
            max={duration || 0}
            min="0"
            onChange={seek}
            step="0.01"
            type="range"
            value={Math.min(currentTime, duration || 0)}
          />
          <output className="timeline-player-time" aria-live="off">
            {formatEditorSeconds(currentTime)} / {formatEditorSeconds(duration)}
          </output>
          <button
            aria-label={muted || volume === 0 ? "取消静音" : "静音"}
            className="timeline-player-button"
            disabled={!sourceUrl}
            onClick={toggleMute}
            type="button"
          >
            {muted || volume === 0 ? <SpeakerSlash size={17} /> : <SpeakerHigh size={17} />}
          </button>
          <input
            aria-label="播放音量"
            className="timeline-player-volume"
            disabled={!sourceUrl}
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

function TimelineTrack({ timeline, selectedClipId, onSelect, resolveUrl }) {
  const enabledClipIds = new Set(
    timeline.clips.filter((clip) => clip.enabled).map((clip) => clip.id),
  );
  return (
    <div className="timeline-tracks" role="region" aria-label="受控时间线轨道">
      <div className="timeline-track-row video-track-row">
        <span className="timeline-track-label"><FilmSlate size={17} />V1 视频</span>
        <div className="timeline-track-scroll">
          {timeline.clips.map((clip) => (
            <button
              aria-pressed={selectedClipId === clip.id}
              className={`timeline-clip ${selectedClipId === clip.id ? "selected" : ""} ${clip.enabled ? "" : "disabled"}`}
              key={clip.id}
              onClick={() => onSelect(clip.id)}
              style={{ "--clip-grow": Math.max(1.5, clip.timeline_duration_seconds) }}
              type="button"
            >
              <img alt="" src={resolveUrl(clip.cover_url)} />
              <span>
                <strong>分镜 {clip.shot_index}</strong>
                <small>{formatEditorSeconds(clip.timeline_start_seconds)}–{formatEditorSeconds(clip.timeline_end_seconds)}</small>
              </span>
              {!clip.enabled && <em>已停用</em>}
            </button>
          ))}
        </div>
      </div>
      <div className="timeline-track-row audio-track-row">
        <span className="timeline-track-label">
          {timeline.audio_track.enabled ? <SpeakerHigh size={17} /> : <SpeakerSlash size={17} />}
          A1 原音
        </span>
        <div className={`timeline-audio-strip ${timeline.audio_track.enabled ? "" : "muted"}`}>
          {timeline.audio_track.enabled ? "映射源视频音频" : "全局静音"}
        </div>
      </div>
      <div className="timeline-track-row audio-track-row secondary-audio-track-row">
        <span className="timeline-track-label">
          {timeline.background_audio_track.enabled ? <SpeakerHigh size={17} /> : <SpeakerSlash size={17} />}
          A2 附加
        </span>
        <div className={`timeline-audio-strip secondary ${timeline.background_audio_track.enabled ? "" : "muted"}`}>
          {timeline.background_audio_track.enabled
            ? timeline.background_audio_track.name || "附加背景音频"
            : timeline.background_audio_track.source_url
              ? "附加音轨已关闭"
              : "尚未添加音频"}
        </div>
      </div>
      <div className="timeline-track-row subtitle-track-row">
        <span className="timeline-track-label"><Subtitles size={17} />T1 字幕</span>
        <div className="timeline-subtitle-strip">
          {timeline.subtitle_cues.filter(
            (cue) => cue.enabled && (cue.clip_id === null || enabledClipIds.has(cue.clip_id)),
          ).map((cue) => (
            <span key={cue.id} title={cue.text}>{cue.text}</span>
          ))}
          {!timeline.subtitle_cues.some((cue) => cue.enabled) && <small>字幕轨已关闭</small>}
        </div>
      </div>
    </div>
  );
}

function ClipInspector({ clip, clips, dirty, inspecting, onChange, onInspect, onMove }) {
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
        <em>保存后自动计算播放速率；当前约 {((clip.trim_out_seconds - clip.trim_in_seconds) / clip.timeline_duration_seconds).toFixed(2)}x</em>
      </label>
      <label className="timeline-field">
        <span>片段声音</span>
        <select value={clip.audio_mode} onChange={(event) => onChange({ audio_mode: event.target.value })}>
          <option value="source">映射原视频音轨</option>
          <option value="muted">静音画面</option>
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
          disabled={dirty || inspecting}
          onClick={onInspect}
          title={dirty ? "请先保存时间线修改" : "检查文件、时长、画幅和帧率"}
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
  dirty,
  onBackgroundChange,
  onChange,
  onUploadBackground,
}) {
  return (
    <div className="timeline-inspector-form">
      <div className="timeline-inspector-heading">
        <div><small>全局轨道</small><h4>原视频声音</h4></div>
        <label className="timeline-toggle">
          <input checked={audio.enabled} onChange={(event) => onChange({
            enabled: event.target.checked,
            strategy: event.target.checked && audio.strategy === "muted"
              ? "continuous_source_track"
              : audio.strategy,
          })} disabled={!audio.source_audio_url} type="checkbox" />
          <span>{audio.enabled ? "已启用" : "已静音"}</span>
        </label>
      </div>
      <label className="timeline-field">
        <span>映射策略</span>
        <select disabled={!audio.source_audio_url} value={audio.enabled ? audio.strategy : "muted"} onChange={(event) => onChange({ strategy: event.target.value, enabled: event.target.value !== "muted" })}>
          {audio.source_audio_url && <option value="continuous_source_track">连续原音轨</option>}
          {audio.source_audio_url && <option value="per_shot">逐片段映射</option>}
          <option value="muted">全局静音</option>
        </select>
        <em>{audio.source_audio_url ? "声音来自被分析的源视频，不使用生成候选自带音频。" : "当前分析没有可用原音轨。"}</em>
      </label>
      <label className="timeline-field">
        <span>全局音量 · {Math.round(audio.volume * 100)}%</span>
        <input disabled={!audio.enabled} max="2" min="0" step="0.05" type="range" value={audio.volume} onChange={(event) => onChange({ volume: Number(event.target.value) })} />
      </label>
      <label className="timeline-toggle standalone">
        <input checked={audio.normalize_loudness} disabled={!audio.enabled} onChange={(event) => onChange({ normalize_loudness: event.target.checked })} type="checkbox" />
        <span>预览时执行响度标准化</span>
      </label>
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
          disabled={busy || dirty}
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
      {dirty && <em className="timeline-audio-help">请先保存当前修改，再上传或替换音频。</em>}
    </div>
  );
}

function SubtitleInspector({ cues, onChange }) {
  return (
    <div className="timeline-subtitle-editor">
      <div className="timeline-inspector-heading">
        <div><small>文本轨道</small><h4>字幕与对白</h4></div>
        <span>{cues.filter((cue) => cue.enabled).length}/{cues.length} 条启用</span>
      </div>
      {cues.length === 0 && <div className="timeline-inspector-empty">交接清单中没有字幕或对白。</div>}
      {cues.map((cue) => (
        <label className={`timeline-subtitle-item ${cue.enabled ? "" : "disabled"}`} key={cue.id}>
          <input checked={cue.enabled} onChange={(event) => onChange(cue.id, { enabled: event.target.checked })} type="checkbox" />
          <span>
            <small>{formatEditorSeconds(cue.start_seconds)}–{formatEditorSeconds(cue.end_seconds)}</small>
            <textarea rows="2" value={cue.text} onChange={(event) => onChange(cue.id, { text: event.target.value })} />
          </span>
        </label>
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
  const [inspectorTab, setInspectorTab] = useState("clip");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [renderJob, setRenderJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
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

  async function loadTimeline() {
    setLoading(true);
    setError("");
    try {
      const nextTimeline = await request(`/productions/${project.id}/timeline`);
      const [nextRevisions, nextValidation] = await Promise.all([
        request(`/productions/${project.id}/timeline/revisions`),
        request(`/productions/${project.id}/timeline/validation`),
      ]);
      setTimeline(nextTimeline);
      setSavedSnapshot(editableTimelineSnapshot(nextTimeline));
      setSelectedClipId((current) => (
        nextTimeline.clips.some((clip) => clip.id === current)
          ? current
          : nextTimeline.clips[0]?.id || ""
      ));
      setRevisions(nextRevisions.items || []);
      setValidation(nextValidation);
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

  function updateClip(values) {
    if (!selectedClip) return;
    setTimeline((current) => ({
      ...current,
      clips: current.clips.map((clip) => (
        clip.id === selectedClip.id ? { ...clip, ...values } : clip
      )),
    }));
  }

  function moveSelectedClip(direction) {
    setTimeline((current) => {
      const clips = [...current.clips];
      const index = clips.findIndex((clip) => clip.id === selectedClipId);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= clips.length) return current;
      [clips[index], clips[target]] = [clips[target], clips[index]];
      return { ...current, clips: clips.map((clip, order) => ({ ...clip, order: order + 1 })) };
    });
  }

  function updateAudio(values) {
    setTimeline((current) => ({
      ...current,
      audio_track: { ...current.audio_track, ...values },
    }));
  }

  function updateBackgroundAudio(values) {
    setTimeline((current) => ({
      ...current,
      background_audio_track: { ...current.background_audio_track, ...values },
    }));
  }

  function updateSubtitle(cueId, values) {
    setTimeline((current) => ({
      ...current,
      subtitle_cues: current.subtitle_cues.map((cue) => (
        cue.id === cueId ? { ...cue, ...values } : cue
      )),
    }));
  }

  async function saveTimeline() {
    if (!timeline || !dirty) return;
    const lastEnabledClipId = timeline.clips.filter((clip) => clip.enabled).at(-1)?.id;
    setBusy(true);
    setError("");
    try {
      const saved = await request(`/productions/${project.id}/timeline`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: timeline.revision_id,
          clip_order: timeline.clips.map((clip) => clip.id),
          clip_updates: timeline.clips.map((clip) => ({
            clip_id: clip.id,
            enabled: clip.enabled,
            trim_in_seconds: Number(clip.trim_in_seconds),
            trim_out_seconds: Number(clip.trim_out_seconds),
            cover_timestamp_seconds: clip.cover_timestamp_seconds == null
              ? null
              : Number(clip.cover_timestamp_seconds),
            timeline_duration_seconds: Number(clip.timeline_duration_seconds),
            audio_mode: clip.audio_mode,
            audio_volume: Number(clip.audio_volume),
            transition_after: clip.id === lastEnabledClipId
              ? { kind: "none", duration_seconds: 0 }
              : clip.transition_after,
          })),
          audio_track: timeline.audio_track,
          background_audio_track: timeline.background_audio_track,
          subtitle_cues: timeline.subtitle_cues,
          summary: "从剪辑工作台更新时间线",
        }),
      });
      const [nextValidation, nextRevisions] = await Promise.all([
        request(`/productions/${project.id}/timeline/validation`),
        request(`/productions/${project.id}/timeline/revisions`),
      ]);
      setTimeline(saved);
      setSavedSnapshot(editableTimelineSnapshot(saved));
      setValidation(nextValidation);
      setRevisions(nextRevisions.items || []);
      setRenderJob(null);
      onNotice({ type: "success", title: "时间线已保存", message: `已创建版本 ${saved.revision_number}` });
    } catch (requestError) {
      setError(requestError.message);
      onNotice({ type: "error", title: "时间线保存失败", message: requestError.message });
    } finally {
      setBusy(false);
    }
  }

  async function uploadBackgroundAudio(file) {
    if (!timeline || dirty || !file) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("expected_revision_id", timeline.revision_id);
      form.append("file", file);
      const updated = await request(
        `/productions/${project.id}/timeline/background-audio`,
        { method: "POST", body: form },
      );
      const nextRevisions = await request(`/productions/${project.id}/timeline/revisions`);
      setTimeline(updated);
      setSavedSnapshot(editableTimelineSnapshot(updated));
      setRevisions(nextRevisions.items || []);
      setRenderJob(null);
      onNotice({ type: "success", title: "附加音轨已添加", message: file.name });
    } catch (requestError) {
      setError(requestError.message);
      onNotice({ type: "error", title: "附加音轨上传失败", message: requestError.message });
    } finally {
      setBusy(false);
    }
  }

  async function inspectSelectedClip() {
    if (!timeline || !selectedClip || dirty) return;
    setBusy(true);
    setError("");
    try {
      const inspected = await request(
        `/productions/${project.id}/timeline/clips/${selectedClip.id}/inspect`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_revision_id: timeline.revision_id }),
        },
      );
      const [nextValidation, nextRevisions] = await Promise.all([
        request(`/productions/${project.id}/timeline/validation`),
        request(`/productions/${project.id}/timeline/revisions`),
      ]);
      setTimeline(inspected);
      setSavedSnapshot(editableTimelineSnapshot(inspected));
      setValidation(nextValidation);
      setRevisions(nextRevisions.items || []);
      setRenderJob(null);
      const inspectedClip = inspected.clips.find((item) => item.id === selectedClip.id);
      onNotice({
        type: inspectedClip?.quality_status === "passed" ? "success" : "warning",
        title: `分镜 ${selectedClip.shot_index} 已完成基础质检`,
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
    if (!timeline || dirty) return;
    setBusy(true);
    setError("");
    try {
      const job = await request(`/productions/${project.id}/timeline/preview-renders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision_id: timeline.revision_id }),
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
    if (!timeline || dirty || revision.id === timeline.revision_id) return;
    setBusy(true);
    setError("");
    try {
      const restored = await request(`/productions/${project.id}/timeline/revisions/${revision.id}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision_id: timeline.revision_id }),
      });
      setTimeline(restored);
      setSavedSnapshot(editableTimelineSnapshot(restored));
      setSelectedClipId(restored.clips[0]?.id || "");
      setHistoryOpen(false);
      setRenderJob(null);
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
          <button className="secondary-button compact" onClick={() => setHistoryOpen((value) => !value)} type="button">
            <ClockCounterClockwise size={16} />版本 {timeline.revision_number}
          </button>
          <button className="secondary-button compact" disabled={!dirty || busy} onClick={saveTimeline} type="button">
            {busy && dirty ? <CircleNotch className="spin" size={16} /> : <FloppyDisk size={16} />}保存时间线
          </button>
          <button className="primary-button compact" disabled={dirty || busy || ACTIVE_RENDER_STATUSES.has(renderJob?.status)} onClick={generatePreview} type="button">
            <Play size={16} weight="fill" />{renderJob?.status === "succeeded" ? "重新生成合成预览" : "生成合成预览"}
          </button>
        </div>
      </header>

      {historyOpen && (
        <div className="timeline-history-panel">
          <div><strong>时间线版本</strong><small>恢复历史会创建新版本，不覆盖旧快照。</small></div>
          <div className="timeline-history-list">
            {[...revisions].reverse().map((revision) => (
              <button disabled={dirty || busy || revision.id === timeline.revision_id} key={revision.id} onClick={() => restoreRevision(revision)} type="button">
                <span><strong>v{revision.revision_number}</strong><small>{revisionChangeLabel(revision.change_kind)}</small></span>
                <em>{revision.id === timeline.revision_id ? "当前" : "恢复"}</em>
              </button>
            ))}
          </div>
        </div>
      )}

      {(error || dirty || validation?.warnings?.length > 0) && (
        <div className={`timeline-context-notice ${error ? "error" : dirty ? "warning" : "info"}`}>
          <WarningCircle size={17} />
          <span>{error || (dirty ? "有未保存修改；保存后才能生成新预览。" : validation.warnings[0])}</span>
        </div>
      )}

      <div className="timeline-editor-grid">
        <div className="timeline-canvas-column">
          <div className="timeline-preview-panel">
            <div className="timeline-preview-heading">
              <div>
                <strong>{previewUrl ? "低清合成预览" : `分镜 ${selectedClip?.shot_index || "-"} 源片段`}</strong>
                <small>{previewUrl ? "已包含原音轨映射、字幕轨和转场" : "保存时间线后生成完整预览"}</small>
              </div>
              {renderJob?.status === "succeeded" && <span><CheckCircle size={15} weight="fill" />预览就绪</span>}
              {renderJob?.status === "failed" && <span className="failed"><WarningCircle size={15} />生成失败</span>}
            </div>
            <TimelinePreviewPlayer
              aspectHeight={timeline.output_height}
              aspectWidth={timeline.output_width}
              sourceUrl={previewUrl || resolveUrl(selectedClip?.candidate_content_url)}
              subtitleUrl={previewSubtitleUrl}
            />
          </div>
          <div className="timeline-track-zone">
            <TimelineTrack timeline={timeline} selectedClipId={selectedClip?.id} onSelect={(clipId) => { setSelectedClipId(clipId); setInspectorTab("clip"); }} resolveUrl={resolveUrl} />
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
              dirty={dirty}
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
              dirty={dirty}
              onBackgroundChange={updateBackgroundAudio}
              onChange={updateAudio}
              onUploadBackground={uploadBackgroundAudio}
            />
          )}
          {inspectorTab === "subtitles" && <SubtitleInspector cues={timeline.subtitle_cues} onChange={updateSubtitle} />}
        </aside>
      </div>
    </section>
  );
}
