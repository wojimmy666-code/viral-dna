import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle,
  CircleNotch,
  FilmSlate,
  ImageSquare,
  Scissors,
  ShieldCheck,
  SpeakerHigh,
  SpeakerSlash,
  WarningCircle,
} from "@phosphor-icons/react";

const MINIMUM_CLIP_SECONDS = 0.2;

function bounded(value, minimum, maximum) {
  const number = Number(value);
  if (!Number.isFinite(number)) return minimum;
  return Math.min(maximum, Math.max(minimum, number));
}

function rounded(value) {
  return Number(Number(value).toFixed(3));
}

function formatSeconds(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(1)}s` : "--";
}

function statusCopy(status) {
  return {
    passed: "通过",
    warning: "需复核",
    failed: "未通过",
    skipped: "未执行",
    informational: "信息",
  }[status] || "待检测";
}

function preparationDraft(preparation, candidate) {
  const duration = Math.max(
    MINIMUM_CLIP_SECONDS,
    Number(candidate?.duration_seconds || preparation?.trim_out_seconds || 1),
  );
  const trimIn = bounded(preparation?.trim_in_seconds ?? 0, 0, duration);
  const trimOut = bounded(preparation?.trim_out_seconds ?? duration, trimIn, duration);
  const cover = bounded(
    preparation?.cover_timestamp_seconds ?? trimIn + (trimOut - trimIn) / 2,
    trimIn,
    trimOut,
  );
  return {
    trimIn: rounded(trimIn),
    trimOut: rounded(trimOut),
    cover: rounded(cover),
    audioMode: preparation?.audio_mode || "",
  };
}

export function VideoPreparationPanel({
  busy,
  candidate,
  onPrepare,
  preparation,
  resolveUrl,
  shotIndex,
  timelineDuration,
}) {
  const [draft, setDraft] = useState(() => preparationDraft(preparation, candidate));
  const duration = Math.max(
    MINIMUM_CLIP_SECONDS,
    Number(candidate?.duration_seconds || preparation?.trim_out_seconds || 1),
  );
  const qualityChecks = useMemo(
    () => Object.entries(preparation?.quality_report?.automated_checks || {}),
    [preparation?.quality_report],
  );

  useEffect(() => {
    setDraft(preparationDraft(preparation, candidate));
  }, [candidate?.id, candidate?.duration_seconds, preparation?.id, preparation?.updated_at]);

  function updateTrimIn(rawValue) {
    const trimIn = rounded(bounded(rawValue, 0, draft.trimOut - MINIMUM_CLIP_SECONDS));
    setDraft((current) => ({
      ...current,
      trimIn,
      cover: rounded(bounded(current.cover, trimIn, current.trimOut)),
    }));
  }

  function updateTrimOut(rawValue) {
    const trimOut = rounded(bounded(rawValue, draft.trimIn + MINIMUM_CLIP_SECONDS, duration));
    setDraft((current) => ({
      ...current,
      trimOut,
      cover: rounded(bounded(current.cover, current.trimIn, trimOut)),
    }));
  }

  async function submit(event) {
    event.preventDefault();
    await onPrepare({
      trim_in_seconds: draft.trimIn,
      trim_out_seconds: draft.trimOut,
      cover_timestamp_seconds: draft.cover,
      ...(draft.audioMode ? { audio_mode: draft.audioMode } : {}),
    });
  }

  const preparedDuration = Math.max(0, draft.trimOut - draft.trimIn);
  const sourceAudioDisabled = preparation && !preparation.source_audio_available;
  const isReady = preparation?.status === "ready";
  const hasWarnings = preparation?.warning_messages?.length > 0;

  return (
    <form className={`video-preparation-panel ${preparation?.status || "new"}`} onSubmit={submit}>
      <header className="video-preparation-header">
        <div>
          <span className="video-preparation-kicker"><FilmSlate size={15} weight="fill" />剪辑准备</span>
          <strong>确定入出点、封面与原音轨衔接</strong>
          <small>候选原文件保持不变；这里保存的是可回退的剪辑参数。</small>
        </div>
        <span className={`video-preparation-status ${preparation?.status || "new"}`}>
          {isReady ? <CheckCircle size={15} weight="fill" /> : <WarningCircle size={15} />}
          {isReady ? (hasWarnings ? "可交接 · 有提示" : "可交接") : preparation?.status === "blocked" ? "需调整" : preparation?.status === "stale" ? "已过期" : "待准备"}
        </span>
      </header>

      {hasWarnings && (
        <div className="video-preparation-warnings" role="status">
          <WarningCircle size={16} />
          <span>{preparation.warning_messages.join("；")}</span>
        </div>
      )}

      {preparation?.blocker_messages?.length > 0 && (
        <div className="video-preparation-blockers" role="alert">
          <WarningCircle size={16} />
          <span>{preparation.blocker_messages.join("；")}</span>
        </div>
      )}

      <div className="video-preparation-body">
        <section className="video-preparation-cover">
          <div className="video-preparation-cover-frame">
            {preparation?.cover_url ? (
              <img alt={`分镜 ${shotIndex} 剪辑封面`} src={resolveUrl(preparation.cover_url)} />
            ) : (
              <div><ImageSquare size={25} /><span>保存后提取封面</span></div>
            )}
          </div>
          <span>
            <ImageSquare size={14} />封面 {formatSeconds(draft.cover)}
          </span>
        </section>

        <section className="video-preparation-controls">
          <div className="video-trim-heading">
            <span><Scissors size={15} />候选裁剪</span>
            <small>
              保留 {preparedDuration.toFixed(1)}s → 时间线 {formatSeconds(timelineDuration)}
              {preparation ? ` · ${preparation.video_playback_rate.toFixed(3)}×` : ""}
            </small>
          </div>

          <label className="video-preparation-range">
            <span>入点 <output>{formatSeconds(draft.trimIn)}</output></span>
            <input
              max={Math.max(0, draft.trimOut - MINIMUM_CLIP_SECONDS)}
              min={0}
              onChange={(event) => updateTrimIn(event.target.value)}
              step="0.1"
              type="range"
              value={draft.trimIn}
            />
          </label>
          <label className="video-preparation-range">
            <span>出点 <output>{formatSeconds(draft.trimOut)}</output></span>
            <input
              max={duration}
              min={Math.min(duration, draft.trimIn + MINIMUM_CLIP_SECONDS)}
              onChange={(event) => updateTrimOut(event.target.value)}
              step="0.1"
              type="range"
              value={draft.trimOut}
            />
          </label>
          <label className="video-preparation-range cover">
            <span>封面帧 <output>{formatSeconds(draft.cover)}</output></span>
            <input
              max={draft.trimOut}
              min={draft.trimIn}
              onChange={(event) => setDraft((current) => ({
                ...current,
                cover: rounded(Number(event.target.value)),
              }))}
              step="0.1"
              type="range"
              value={draft.cover}
            />
          </label>

          <fieldset className="video-preparation-audio">
            <legend>成片声音策略</legend>
            <label className={draft.audioMode === "source" ? "active" : ""}>
              <input
                checked={draft.audioMode === "source"}
                disabled={sourceAudioDisabled}
                name={`shot-${shotIndex}-audio-mode`}
                onChange={() => setDraft((current) => ({ ...current, audioMode: "source" }))}
                type="radio"
              />
              <SpeakerHigh size={16} />
              <span><strong>映射原视频音轨</strong><small>沿用该分镜原始时间区间的对白与声音</small></span>
            </label>
            <label className={draft.audioMode === "muted" ? "active" : ""}>
              <input
                checked={draft.audioMode === "muted"}
                name={`shot-${shotIndex}-audio-mode`}
                onChange={() => setDraft((current) => ({ ...current, audioMode: "muted" }))}
                type="radio"
              />
              <SpeakerSlash size={16} />
              <span><strong>静音画面</strong><small>不带入生成视频原生声音，后续单独配音</small></span>
            </label>
          </fieldset>
        </section>

        <aside className="video-preparation-quality">
          <div className="video-quality-heading">
            <span><ShieldCheck size={16} />基础质检</span>
            <small>{preparation ? statusCopy(preparation.quality_status) : "尚未执行"}</small>
          </div>
          {preparation ? (
            <>
              <div className="video-quality-checks">
                {qualityChecks.slice(0, 5).map(([id, check]) => (
                  <span className={check.status} key={id}>
                    {statusCopy(check.status)} · {{
                      file_integrity: "文件",
                      duration: "时长",
                      dimensions: "画幅",
                      frame_rate: "帧率",
                      native_audio: "候选声音",
                      visual_signals: "黑屏/静帧",
                    }[id] || id}
                  </span>
                ))}
              </div>
              <div className="video-preparation-evidence">
                <span>对白 {preparation.transcript_cues?.length || 0} 条</span>
                <span>字幕 {preparation.subtitle_cues?.length || 0} 条</span>
                <span>原音轨 {formatSeconds(preparation.source_audio_start_seconds)}–{formatSeconds(preparation.source_audio_end_seconds)}</span>
              </div>
              <p>{preparation.quality_report?.summary || "基础检测已完成，仍需人工检查动作与主体稳定性。"}</p>
            </>
          ) : (
            <p>保存后将检查文件可读性、时长、画幅、帧率、黑屏和持续静帧，并映射对白与字幕证据。</p>
          )}
        </aside>
      </div>

      <footer className="video-preparation-actions">
        <small>生成视频自带音频暂不进入成片；Batch 4.6 将读取这里的交接数据建立时间线。</small>
        <button className="primary-button compact" disabled={busy} type="submit">
          {busy ? <CircleNotch className="spin" size={16} /> : <ShieldCheck size={16} />}
          {preparation ? "保存并重新检测" : "检查并准备此片段"}
        </button>
      </footer>
    </form>
  );
}
