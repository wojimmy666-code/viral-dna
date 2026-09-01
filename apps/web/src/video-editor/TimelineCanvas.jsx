import { useEffect, useMemo, useRef, useState } from "react";
import {
  FilmSlate,
  Link,
  LinkBreak,
  Minus,
  Plus,
  SpeakerHigh,
  SpeakerSlash,
  Subtitles,
  Trash,
} from "@phosphor-icons/react";
import { formatEditorSeconds } from "./editor-state.js";
import {
  moveTimelineRange,
  snapTimelineTime,
  timelineSnapPoints,
  trimTimelineClip,
  trimTimelineRange,
} from "./timeline-math.js";

const DEFAULT_ZOOM = 80;
const MIN_ZOOM = 40;
const MAX_ZOOM = 160;

function sourceRangeBounds(clip) {
  const sourceRange = clip?.source_range;
  if (!sourceRange) return null;
  const pointsPerSecond = (
    Number(sourceRange.time_base_denominator || 1_000_000)
    / Number(sourceRange.time_base_numerator || 1)
  );
  const trimIn = Number(clip.trim_in_seconds);
  const trimOut = Number(clip.trim_out_seconds);
  const candidateDuration = Number(clip.candidate_duration_seconds);
  return {
    start: Math.abs(trimIn) <= 0.000001
      ? Number(sourceRange.start_pts)
      : Number(sourceRange.start_pts) + Math.round(trimIn * pointsPerSecond),
    end: Math.abs(trimOut - candidateDuration) <= 0.001
      ? Number(sourceRange.end_pts)
      : Number(sourceRange.start_pts) + Math.round(trimOut * pointsPerSecond),
  };
}

function sourceRangesContinue(left, right) {
  const leftRange = left?.source_range;
  const rightRange = right?.source_range;
  const leftBounds = sourceRangeBounds(left);
  const rightBounds = sourceRangeBounds(right);
  if (!leftRange || !rightRange || !leftBounds || !rightBounds) return false;
  const leftDuration = Number(left.trim_out_seconds) - Number(left.trim_in_seconds);
  const rightDuration = Number(right.trim_out_seconds) - Number(right.trim_in_seconds);
  return (
    leftRange.source_video_id === rightRange.source_video_id
    && leftRange.source_sha256 === rightRange.source_sha256
    && Number(leftRange.time_base_numerator || 1) === Number(rightRange.time_base_numerator || 1)
    && Number(leftRange.time_base_denominator || 1_000_000) === Number(rightRange.time_base_denominator || 1_000_000)
    && leftBounds.end === rightBounds.start
    && left.transition_after?.kind === "none"
    && Math.abs(Number(left.playback_rate) - 1) <= 0.000001
    && Math.abs(Number(right.playback_rate) - 1) <= 0.000001
    && Math.abs(leftDuration - Number(left.timeline_duration_seconds)) <= 0.001
    && Math.abs(rightDuration - Number(right.timeline_duration_seconds)) <= 0.001
  );
}

function keyboardDelta(event) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return null;
  return (event.key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 1 : 0.05);
}

function TrimHandle({ edge, label, onKeyDown, onPointerDown }) {
  return (
    <button
      aria-label={label}
      className={`timeline-trim-handle ${edge}`}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      title={`${label}；方向键微调，Shift + 方向键调整 1 秒`}
      type="button"
    >
      <span />
    </button>
  );
}

function TrackLabel({ children, icon, action, actionLabel }) {
  return (
    <div className="timeline-canvas-track-label">
      <span>{icon}{children}</span>
      {action && (
        <button aria-label={actionLabel} onClick={action} title={actionLabel} type="button">
          <Plus size={14} />
        </button>
      )}
    </div>
  );
}

function AudioBlock({
  kind,
  label,
  selected,
  timeline,
  track,
  zoom,
  onBeginGesture,
  onChange,
  onDelete,
  onSelect,
}) {
  const start = Number(track.timeline_start_seconds || 0);
  const end = Number(track.timeline_end_seconds ?? timeline.duration_seconds);
  const width = Math.max(42, (end - start) * zoom);
  const linked = kind === "source" && track.linked_to_video !== false;

  function nudge(event) {
    const delta = keyboardDelta(event);
    if (delta == null || linked) return;
    event.preventDefault();
    onChange(moveTimelineRange(track, delta, timeline.duration_seconds));
  }

  function trim(edge, delta) {
    onChange(trimTimelineRange(
      track,
      edge,
      delta,
      timeline.duration_seconds,
      { syncSource: !track.loop },
    ));
  }

  return (
    <div
      aria-label={`${selected ? "已选择，" : ""}${label}，${formatEditorSeconds(start)} 至 ${formatEditorSeconds(end)}`}
      className={`timeline-range-block audio ${kind} ${selected ? "selected" : ""} ${track.enabled ? "" : "disabled"}`}
      data-timeline-item={`${kind}-audio`}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Delete" && onDelete) {
          event.preventDefault();
          onDelete();
          return;
        }
        nudge(event);
      }}
      onPointerDown={(event) => {
        if (linked || event.target.closest("button")) return;
        onSelect();
        onBeginGesture(event, { type: "range-move", kind, initial: track });
      }}
      role="group"
      style={{ left: start * zoom, width }}
      tabIndex="0"
      title={linked ? "与视频轨同步；解除关联后可单独移动和裁剪" : "拖动调整位置；方向键微调"}
    >
      {!linked && (
        <TrimHandle
          edge="start"
          label={`调整${label}入点`}
          onKeyDown={(event) => {
            const delta = keyboardDelta(event);
            if (delta == null) return;
            event.preventDefault();
            event.stopPropagation();
            trim("start", delta);
          }}
          onPointerDown={(event) => {
            event.stopPropagation();
            onBeginGesture(event, { type: "range-trim", kind, edge: "start", initial: track });
          }}
        />
      )}
      <span className="timeline-range-block-content">
        <strong>{label}</strong>
        <small>{formatEditorSeconds(end - start)}{track.loop ? " · 循环" : ""}</small>
      </span>
      {kind === "source" && (
        <button
          aria-label={linked ? "解除原音与视频同步" : "将原音重新关联到视频"}
          className="timeline-range-inline-action"
          onClick={(event) => {
            event.stopPropagation();
            onChange({
              ...track,
              linked_to_video: !linked,
              timeline_start_seconds: 0,
              timeline_end_seconds: timeline.duration_seconds,
              source_trim_in_seconds: 0,
              source_trim_out_seconds: timeline.duration_seconds,
            });
          }}
          title={linked ? "解除同步" : "关联视频"}
          type="button"
        >
          {linked ? <Link size={14} /> : <LinkBreak size={14} />}
        </button>
      )}
      {kind === "background" && onDelete && (
        <button
          aria-label="删除附加音频"
          className="timeline-range-inline-action delete"
          onClick={(event) => {
            event.stopPropagation();
            onDelete();
          }}
          title="删除附加音频"
          type="button"
        >
          <Trash size={14} />
        </button>
      )}
      {!linked && (
        <TrimHandle
          edge="end"
          label={`调整${label}出点`}
          onKeyDown={(event) => {
            const delta = keyboardDelta(event);
            if (delta == null) return;
            event.preventDefault();
            event.stopPropagation();
            trim("end", delta);
          }}
          onPointerDown={(event) => {
            event.stopPropagation();
            onBeginGesture(event, { type: "range-trim", kind, edge: "end", initial: track });
          }}
        />
      )}
    </div>
  );
}

export function TimelineCanvas({
  activeClipId,
  timeline,
  playheadSeconds,
  selectedClipId,
  selectedCueId,
  selectedTrack,
  onAddSubtitle,
  onAudioChange,
  onBackgroundChange,
  onClipChange,
  onClipReorder,
  onCueChange,
  onDeleteBackground,
  onDeleteCue,
  onGestureEnd,
  onGestureStart,
  onPlayheadChange,
  onScrubEnd,
  onScrubStart,
  onSelectAudio,
  onSelectClip,
  onSelectCue,
}) {
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [dragging, setDragging] = useState("");
  const [scrubbing, setScrubbing] = useState(false);
  const gestureRef = useRef(null);
  const scrubFrameRef = useRef(null);
  const rootRef = useRef(null);
  const orderedClips = useMemo(
    () => [...timeline.clips].sort((first, second) => first.order - second.order),
    [timeline.clips],
  );
  const enabledClips = orderedClips.filter((clip) => clip.enabled);
  const disabledClips = orderedClips.filter((clip) => !clip.enabled);
  const timelineWidth = Math.max(520, Math.ceil(timeline.duration_seconds * zoom) + 32);
  const rulerMarks = Array.from(
    { length: Math.floor(timeline.duration_seconds) + 1 },
    (_, index) => index,
  );

  useEffect(() => () => {
    if (scrubFrameRef.current != null) window.cancelAnimationFrame(scrubFrameRef.current);
  }, []);

  function beginGesture(event, descriptor) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    gestureRef.current = {
      ...descriptor,
      pointerId: event.pointerId,
      originX: event.clientX,
      lastTargetIndex: null,
    };
    onGestureStart?.();
    setDragging(descriptor.type);
  }

  function updateGesture(event) {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const rawDelta = (event.clientX - gesture.originX) / zoom;
    let delta = Math.round(rawDelta / 0.05) * 0.05;
    if (gesture.type === "range-move" || gesture.type === "range-trim") {
      const isCue = gesture.kind === "cue";
      const start = Number(
        isCue ? gesture.initial.start_seconds : gesture.initial.timeline_start_seconds || 0,
      );
      const end = Number(
        isCue
          ? gesture.initial.end_seconds
          : gesture.initial.timeline_end_seconds ?? timeline.duration_seconds,
      );
      const anchor = gesture.type === "range-trim" && gesture.edge === "end" ? end : start;
      const snapped = snapTimelineTime(anchor + rawDelta, {
        points: timelineSnapPoints(timeline, gesture.initial.id),
      });
      delta = snapped - anchor;
    }
    if (gesture.type === "clip-trim") {
      onClipChange(
        gesture.initial.id,
        trimTimelineClip(gesture.initial, gesture.edge, delta),
        { transient: true },
      );
      return;
    }
    if (gesture.type === "clip-reorder") {
      const elements = [...rootRef.current.querySelectorAll("[data-timeline-clip-id]")];
      const target = elements.findIndex((element) => {
        const bounds = element.getBoundingClientRect();
        return event.clientX < bounds.left + bounds.width / 2;
      });
      const targetElementIndex = target < 0 ? elements.length - 1 : target;
      const targetId = elements[targetElementIndex]?.dataset.timelineClipId;
      const targetIndex = orderedClips.findIndex((clip) => clip.id === targetId);
      if (targetIndex >= 0 && targetIndex !== gesture.lastTargetIndex) {
        gesture.lastTargetIndex = targetIndex;
        onClipReorder(gesture.initial.id, targetIndex, { transient: true });
      }
      return;
    }
    if (gesture.type === "range-move") {
      const next = moveTimelineRange(gesture.initial, delta, timeline.duration_seconds);
      if (gesture.kind === "source") onAudioChange(next, { transient: true });
      if (gesture.kind === "background") onBackgroundChange(next, { transient: true });
      if (gesture.kind === "cue") onCueChange(gesture.initial.id, next, { transient: true });
      return;
    }
    if (gesture.type === "range-trim") {
      const next = trimTimelineRange(
        gesture.initial,
        gesture.edge,
        delta,
        timeline.duration_seconds,
        { syncSource: gesture.kind !== "cue" && !gesture.initial.loop },
      );
      if (gesture.kind === "source") onAudioChange(next, { transient: true });
      if (gesture.kind === "background") onBackgroundChange(next, { transient: true });
      if (gesture.kind === "cue") onCueChange(gesture.initial.id, next, { transient: true });
    }
  }

  function endGesture(event) {
    if (gestureRef.current?.pointerId !== event.pointerId) return;
    gestureRef.current = null;
    setDragging("");
    onGestureEnd?.();
  }

  function seekFromPosition(element, clientX) {
    const bounds = element.getBoundingClientRect();
    const time = Math.max(0, Math.min(
      timeline.duration_seconds,
      (clientX - bounds.left) / zoom,
    ));
    onPlayheadChange(Math.round(time * 100) / 100);
  }

  function scheduleSeekFromPointer(event) {
    const element = event.currentTarget;
    const clientX = event.clientX;
    if (scrubFrameRef.current != null) window.cancelAnimationFrame(scrubFrameRef.current);
    scrubFrameRef.current = window.requestAnimationFrame(() => {
      scrubFrameRef.current = null;
      seekFromPosition(element, clientX);
    });
  }

  function beginScrub(event) {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setScrubbing(true);
    onScrubStart?.();
    seekFromPosition(event.currentTarget, event.clientX);
  }

  function endScrub(event) {
    if (!event.currentTarget.hasPointerCapture?.(event.pointerId)) return;
    if (scrubFrameRef.current != null) {
      window.cancelAnimationFrame(scrubFrameRef.current);
      scrubFrameRef.current = null;
    }
    seekFromPosition(event.currentTarget, event.clientX);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    setScrubbing(false);
    onScrubEnd?.();
  }

  function cancelScrub(event) {
    if (scrubFrameRef.current != null) {
      window.cancelAnimationFrame(scrubFrameRef.current);
      scrubFrameRef.current = null;
    }
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    setScrubbing(false);
    onScrubEnd?.();
  }

  const pointerHandlers = {
    onPointerMove: updateGesture,
    onPointerUp: endGesture,
    onPointerCancel: endGesture,
  };

  return (
    <section className={`timeline-canvas ${dragging ? "is-dragging" : ""} ${scrubbing ? "is-scrubbing" : ""}`} ref={rootRef}>
      <header className="timeline-canvas-toolbar">
        <div>
          <strong>时间线</strong>
          <span>{formatEditorSeconds(playheadSeconds)} / {formatEditorSeconds(timeline.duration_seconds)}</span>
        </div>
        <label>
          <Minus size={13} aria-hidden="true" />
          <span>缩放</span>
          <input
            aria-label="时间线缩放"
            max={MAX_ZOOM}
            min={MIN_ZOOM}
            onChange={(event) => setZoom(Number(event.target.value))}
            step="10"
            type="range"
            value={zoom}
          />
          <Plus size={13} aria-hidden="true" />
        </label>
      </header>
      {disabledClips.length > 0 && (
        <div className="timeline-disabled-clips">
          <span>未参与成片</span>
          {disabledClips.map((clip) => (
            <button key={clip.id} onClick={() => onSelectClip(clip.id)} type="button">
              分镜 {clip.shot_index}
            </button>
          ))}
        </div>
      )}
      <div className="timeline-canvas-scroll">
        <div
          className="timeline-canvas-grid"
          style={{
            "--timeline-playhead-left": `${86 + playheadSeconds * zoom}px`,
            "--timeline-width": `${timelineWidth}px`,
          }}
          {...pointerHandlers}
        >
          <div className="timeline-canvas-corner">时间</div>
          <div
            aria-label="拖动播放头"
            aria-valuemax={timeline.duration_seconds}
            aria-valuemin="0"
            aria-valuenow={playheadSeconds}
            className="timeline-ruler-lane"
            onKeyDown={(event) => {
              const delta = keyboardDelta(event);
              if (delta == null) return;
              event.preventDefault();
              onScrubStart?.();
              onPlayheadChange(Math.max(0, Math.min(timeline.duration_seconds, playheadSeconds + delta)));
              window.requestAnimationFrame(() => onScrubEnd?.());
            }}
            onPointerCancel={cancelScrub}
            onPointerDown={beginScrub}
            onPointerMove={(event) => {
              if (event.currentTarget.hasPointerCapture?.(event.pointerId)) scheduleSeekFromPointer(event);
            }}
            onPointerUp={endScrub}
            role="slider"
            tabIndex="0"
          >
            {rulerMarks.map((second) => (
              <span
                className={second % 5 === 0 ? "major" : ""}
                key={second}
                style={{ left: second * zoom }}
              >
                <i />
                {(zoom >= 60 || second % 2 === 0) && <small>{formatEditorSeconds(second)}</small>}
              </span>
            ))}
          </div>

          <TrackLabel icon={<FilmSlate size={16} />}>V1 视频</TrackLabel>
          <div className="timeline-canvas-lane video">
            {enabledClips.map((clip, enabledIndex) => {
              const width = Math.max(48, clip.timeline_duration_seconds * zoom);
              const selected = selectedClipId === clip.id;
              const active = activeClipId === clip.id;
              const orderIndex = orderedClips.findIndex((item) => item.id === clip.id);
              const continuesFromPrevious = sourceRangesContinue(
                enabledClips[enabledIndex - 1],
                clip,
              );
              const continuesToNext = sourceRangesContinue(
                clip,
                enabledClips[enabledIndex + 1],
              );
              return (
                <div
                  aria-label={`${selected ? "已选择，" : ""}${active ? "当前播放，" : ""}分镜 ${clip.shot_index}，${formatEditorSeconds(clip.timeline_duration_seconds)}`}
                  className={`timeline-video-block ${selected ? "selected" : ""} ${active ? "active" : ""} ${width < 130 ? "compact" : ""} ${clip.source_range ? "source-range" : "generated"} ${continuesFromPrevious ? "continues-from-previous" : ""} ${continuesToNext ? "continues-to-next" : ""}`}
                  data-timeline-clip-id={clip.id}
                  key={clip.id}
                  onClick={() => onSelectClip(clip.id)}
                  onKeyDown={(event) => {
                    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                    event.preventDefault();
                    onClipReorder(
                      clip.id,
                      Math.max(0, Math.min(orderedClips.length - 1, orderIndex + (event.key === "ArrowLeft" ? -1 : 1))),
                    );
                  }}
                  onPointerDown={(event) => {
                    if (event.target.closest("button")) return;
                    onSelectClip(clip.id);
                    beginGesture(event, { type: "clip-reorder", initial: clip });
                  }}
                  role="group"
                  style={{ left: clip.timeline_start_seconds * zoom, width }}
                  tabIndex="0"
                  title="拖动调整分镜顺序；方向键前后移动"
                >
                  <TrimHandle
                    edge="start"
                    label={`裁剪分镜 ${clip.shot_index} 入点`}
                    onKeyDown={(event) => {
                      const delta = keyboardDelta(event);
                      if (delta == null) return;
                      event.preventDefault();
                      event.stopPropagation();
                      onClipChange(clip.id, trimTimelineClip(clip, "start", delta));
                    }}
                    onPointerDown={(event) => {
                      event.stopPropagation();
                      beginGesture(event, { type: "clip-trim", edge: "start", initial: clip });
                    }}
                  />
                  <span className="timeline-video-meta">
                    <strong>分镜 {clip.shot_index}</strong>
                    <small>{clip.source_range ? "原视频 · " : ""}{formatEditorSeconds(clip.timeline_duration_seconds)}</small>
                  </span>
                  <TrimHandle
                    edge="end"
                    label={`裁剪分镜 ${clip.shot_index} 出点`}
                    onKeyDown={(event) => {
                      const delta = keyboardDelta(event);
                      if (delta == null) return;
                      event.preventDefault();
                      event.stopPropagation();
                      onClipChange(clip.id, trimTimelineClip(clip, "end", delta));
                    }}
                    onPointerDown={(event) => {
                      event.stopPropagation();
                      beginGesture(event, { type: "clip-trim", edge: "end", initial: clip });
                    }}
                  />
                </div>
              );
            })}
          </div>

          <TrackLabel icon={timeline.audio_track.enabled ? <SpeakerHigh size={16} /> : <SpeakerSlash size={16} />}>A1 分镜音频</TrackLabel>
          <div className="timeline-canvas-lane audio">
            {timeline.audio_track.enabled ? (
              <AudioBlock
                kind="source"
                label="分镜主音轨"
                onBeginGesture={beginGesture}
                onChange={onAudioChange}
                onSelect={() => onSelectAudio("source")}
                selected={selectedTrack === "source"}
                timeline={timeline}
                track={timeline.audio_track}
                zoom={zoom}
              />
            ) : <span className="timeline-empty-lane">分镜音轨已静音</span>}
          </div>

          <TrackLabel
            action={() => onSelectAudio("background")}
            actionLabel="添加或设置附加音频"
            icon={timeline.background_audio_track.enabled ? <SpeakerHigh size={16} /> : <SpeakerSlash size={16} />}
          >
            A2 附加
          </TrackLabel>
          <div className="timeline-canvas-lane audio secondary">
            {timeline.background_audio_track.source_url ? (
              <AudioBlock
                kind="background"
                label={timeline.background_audio_track.name || "附加音频"}
                onBeginGesture={beginGesture}
                onChange={onBackgroundChange}
                onDelete={onDeleteBackground}
                onSelect={() => onSelectAudio("background")}
                selected={selectedTrack === "background"}
                timeline={timeline}
                track={timeline.background_audio_track}
                zoom={zoom}
              />
            ) : <span className="timeline-empty-lane">在音轨属性中添加音频</span>}
          </div>

          <TrackLabel action={onAddSubtitle} actionLabel="在播放头添加字幕" icon={<Subtitles size={16} />}>T1 字幕</TrackLabel>
          <div className="timeline-canvas-lane subtitles">
            {timeline.subtitle_cues.filter((cue) => cue.enabled).map((cue) => {
              const selected = cue.id === selectedCueId;
              return (
                <div
                  aria-label={`${selected ? "已选择，" : ""}字幕：${cue.text}`}
                  className={`timeline-range-block cue ${selected ? "selected" : ""}`}
                  key={cue.id}
                  onClick={() => onSelectCue(cue.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Delete") {
                      event.preventDefault();
                      onDeleteCue(cue.id);
                      return;
                    }
                    const delta = keyboardDelta(event);
                    if (delta == null) return;
                    event.preventDefault();
                    onCueChange(cue.id, moveTimelineRange(cue, delta, timeline.duration_seconds));
                  }}
                  onPointerDown={(event) => {
                    if (event.target.closest("button")) return;
                    onSelectCue(cue.id);
                    beginGesture(event, { type: "range-move", kind: "cue", initial: cue });
                  }}
                  role="group"
                  style={{
                    left: cue.start_seconds * zoom,
                    width: Math.max(40, (cue.end_seconds - cue.start_seconds) * zoom),
                  }}
                  tabIndex="0"
                  title="拖动调整字幕位置；Delete 删除"
                >
                  <TrimHandle
                    edge="start"
                    label="调整字幕入点"
                    onKeyDown={(event) => {
                      const delta = keyboardDelta(event);
                      if (delta == null) return;
                      event.preventDefault();
                      event.stopPropagation();
                      onCueChange(cue.id, trimTimelineRange(cue, "start", delta, timeline.duration_seconds));
                    }}
                    onPointerDown={(event) => {
                      event.stopPropagation();
                      beginGesture(event, { type: "range-trim", kind: "cue", edge: "start", initial: cue });
                    }}
                  />
                  <span className="timeline-range-block-content"><strong>{cue.text}</strong></span>
                  <TrimHandle
                    edge="end"
                    label="调整字幕出点"
                    onKeyDown={(event) => {
                      const delta = keyboardDelta(event);
                      if (delta == null) return;
                      event.preventDefault();
                      event.stopPropagation();
                      onCueChange(cue.id, trimTimelineRange(cue, "end", delta, timeline.duration_seconds));
                    }}
                    onPointerDown={(event) => {
                      event.stopPropagation();
                      beginGesture(event, { type: "range-trim", kind: "cue", edge: "end", initial: cue });
                    }}
                  />
                </div>
              );
            })}
            {!timeline.subtitle_cues.some((cue) => cue.enabled) && <span className="timeline-empty-lane">暂无启用字幕</span>}
          </div>

          <div aria-hidden="true" className="timeline-playhead">
            <span>{formatEditorSeconds(playheadSeconds)}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
