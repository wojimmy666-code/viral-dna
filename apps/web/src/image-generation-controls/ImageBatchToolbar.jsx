import { useEffect, useRef, useState } from "react";
import { activeImageBatch, changedBatchShots, imageBatchCounts } from "./image-batch-ui.js";
import { readOnce } from "../creation-workspace/read-request.js";
import { resolutionForDimensions } from "../media-resolution.js";
import "./image-batch.css";
import { useGenerationPreferences } from "./generation-preferences.js";
import { ImageGenerationChoiceFields, imageChoicePayload, imageChoiceState } from "./ImageGenerationChoiceFields.jsx";

const money = (value) => value == null ? "费用未知" : `¥${(value / 1_000_000).toFixed(2)}`;

export function ImageBatchToolbar({ projectId, request, onFlush, onResults, onState, onSelectShot, busy, settings, aspectRatio, pictureCount = 0 }) {
  const [batch, setBatch] = useState(null);
  const [preview, setPreview] = useState(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const [retryResults, setRetryResults] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [draftChoice, setDraftChoice] = useState(null);
  const dialogRef = useRef(null);
  const latest = useRef(null);
  const pendingResults = useRef(new Set());
  const callbacks = useRef({ onFlush, onResults, onState, onSelectShot });
  callbacks.current = { onFlush, onResults, onState, onSelectShot };
  const base = `/productions/${projectId}/image-batches`;
  const running = activeImageBatch(batch);
  const [choice, setChoice] = useGenerationPreferences(`viraldna:batch-image-options:${projectId}`, {
    model: settings?.remote_model_alias || "", resolution: `${settings?.image_width}x${settings?.image_height}`,
    allowUnknownCost: Boolean(settings?.allow_unknown_local_image_cost),
  });
  const selection = imageChoiceState(settings, aspectRatio, draftChoice || choice);
  const pendingRequest = useRef(null);

  useEffect(() => {
    if (dialogOpen) dialogRef.current?.showModal();
    else dialogRef.current?.close();
  }, [dialogOpen]);

  function openSettings() {
    if (!pendingRequest.current) {
      setDraftChoice({ ...choice, allowUnknownCost: false });
      setPreview(null); setError("");
    }
    setDialogOpen(true);
  }

  function closeSettings() {
    if (working) return;
    setDialogOpen(false);
    setPreview(null);
  }

  async function accept(next) {
    const previous = latest.current;
    latest.current = next;
    setBatch(next);
    if (previous?.status !== next?.status || JSON.stringify(previous?.items) !== JSON.stringify(next?.items)) {
      callbacks.current.onState?.((next?.items || []).map(item => ({ ...item,
        batch_created_at: next.created_at, batch_updated_at: next.updated_at, batch_completed_at: next.completed_at,
      })));
    }
    changedBatchShots(previous, next).forEach((id) => pendingResults.current.add(id));
    const changed = [...pendingResults.current];
    if (changed.length) {
      try {
        await callbacks.current.onResults?.(changed);
        changed.forEach((id) => pendingResults.current.delete(id));
        setRetryResults(pendingResults.current.size > 0);
      } catch (failure) {
        setRetryResults(true);
        throw failure;
      }
    }
  }

  useEffect(() => {
    let active = true;
    readOnce(request, `${base}/latest`).then((next) => { if (active) return accept(next); })
      .catch((failure) => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [base, request]);

  useEffect(() => {
    if (!running && !retryResults) return;
    let active = true, timer;
    async function poll() {
      try {
        const next = await readOnce(request, `${base}/latest`);
        if (active) { await accept(next); setError(""); }
      } catch (failure) { if (active) setError(`进度更新失败：${failure.message}。后台任务不会因此停止。`); }
      finally { if (active) timer = setTimeout(poll, 2000); }
    }
    timer = setTimeout(poll, 1000);
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => { active = false; clearTimeout(timer); clearInterval(clock); };
  }, [base, request, running, retryResults]);

  async function prepare() {
    setWorking(true); setError("");
    try {
      if (pendingRequest.current) {
        // Retry the frozen, idempotent submission directly: re-running preflight
        // could mistake this very batch for conflicting work after a lost reply.
        await accept(await request(base, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(pendingRequest.current) }));
        pendingRequest.current = null;
        setPreview(null);
        setDialogOpen(false);
        return;
      }
      await callbacks.current.onFlush();
      const project = await request(`/productions/${projectId}`);
      // Retain the id after an ambiguous transport failure; a network retry is
      // the same batch, a completed explicit click creates a new batch.
      const confirmedChoice = draftChoice || choice;
      setChoice(confirmedChoice);
      const payload = { request_id: crypto.randomUUID(), expected_revision_id: project.project.current_revision_id, mode: "all", ...imageChoicePayload(settings, aspectRatio, confirmedChoice), candidate_count: 1 };
      const value = await request(`${base}/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      setPreview({ ...value, payload });
      if (value.items.some(item => ["failed", "unknown", "running"].includes(item.status))) return;
      pendingRequest.current = payload;
      await accept(await request(base, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }));
      pendingRequest.current = null;
      setPreview(null);
      setDialogOpen(false);
    } catch (failure) {
      if (failure.status >= 400 && failure.status < 500) pendingRequest.current = null;
      setError(failure.message);
    }
    finally { setWorking(false); }
  }

  async function control(action) {
    setWorking(true); setError("");
    try {
      if (action === "resume") await callbacks.current.onFlush();
      await accept(await request(`${base}/${batch.id}/${action}`, { method: "POST" }));
    } catch (failure) { setError(failure.message); }
    finally { setWorking(false); }
  }

  const counts = imageBatchCounts(batch);
  const previewCounts = imageBatchCounts(preview);
  const elapsed = batch ? Math.max(0, Math.floor(((running ? now : Date.parse(batch.completed_at || batch.updated_at)) - Date.parse(batch.created_at)) / 1000)) : 0;
  const heartbeat = batch ? Math.max(0, Math.floor((now - Date.parse(batch.last_heartbeat_at)) / 1000)) : 0;
  const problems = batch?.items?.filter((item) => ["failed", "unknown"].includes(item.status)) || [];
  return <section className="image-batch-toolbar" aria-label="批量生成分镜图片">
    <div className="image-batch-actions">
      {!running && <button className="primary-button compact" disabled={busy || working || pictureCount === 0} onClick={openSettings} type="button">一键生成全部分镜图</button>}
      {batch && <span aria-live="polite">完成 {counts.completed}/{counts.total - counts.skipped} 个画面</span>}
      {batch && <small>耗时 {Math.floor(elapsed / 60)}分{elapsed % 60}秒{running ? ` · ${heartbeat} 秒前心跳` : ""}</small>}
      {running && <button className="secondary-button compact" disabled={working || batch.status === "stopping"} onClick={() => control("stop")} type="button">停止排队</button>}
      {!running && batch && (["interrupted", "cancelled"].includes(batch.status) || batch.items.some((item) => item.retryable || item.status === "unknown")) && <button className="secondary-button compact" disabled={working || busy || Boolean(pendingRequest.current)} onClick={() => control("resume")} type="button">继续未完成任务</button>}
    </div>
    {running && <progress aria-label="批量图片生成进度" max={counts.total || 1} value={counts.done} />}
    <dialog ref={dialogRef} className="image-batch-dialog" aria-labelledby={`batch-settings-${projectId}`} onCancel={event => { event.preventDefault(); closeSettings(); }} onClose={() => setDialogOpen(false)} onClick={event => {
      if (event.target !== event.currentTarget) return;
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeSettings();
    }}>
      {dialogOpen && <>
        <h2 id={`batch-settings-${projectId}`}>生成全部分镜图</h2>
        <div className="image-batch-options">
          <ImageGenerationChoiceFields prefix="本次" settings={settings} aspectRatio={aspectRatio} value={draftChoice || choice} disabled={working || Boolean(pendingRequest.current)} onChange={patch => { setDraftChoice(current => ({ ...(current || choice), ...patch })); setPreview(null); setError(""); }} />
        </div>
        <p>{pictureCount} 个分镜 · 每镜 1 张 · 共 {pictureCount} 张 · 预计 {money(selection.model?.unit_cost_micros == null ? null : pictureCount * selection.model.unit_cost_micros)}</p>
        <p className="image-batch-hint">保留历史图片及已采用结果，新图片需人工采用。本次设置不改变项目默认配置。</p>
        {preview && <div className="image-batch-confirm">
          <span>{preview.model_label} · {resolutionForDimensions(preview.width, preview.height)} · 可生成 {previewCounts.pending} 张 · 预计 {money(preview.estimated_cost_micros)}</span>
          {preview.items.filter(item => ["failed", "unknown", "running"].includes(item.status)).map(item => <p className="image-batch-error" key={item.visual_beat_id}>分镜 {item.shot_index}：{item.error_message || "已有任务未结束，请先核对当前任务。"}</p>)}
        </div>}
        {pendingRequest.current && <p className="image-batch-hint">提交结果尚未确认，重试将核对同一批次，不会重复创建。</p>}
        {error && <p role="alert" className="image-batch-error">{error}</p>}
        <footer><button className="secondary-button compact" disabled={working} type="button" onClick={closeSettings}>取消</button><button className="primary-button compact" disabled={working || busy || (!pendingRequest.current && (!selection.ready || running || pictureCount === 0))} type="button" onClick={prepare}>{working ? "正在提交…" : pendingRequest.current ? "重试确认提交" : "确认生成"}</button></footer>
      </>}
    </dialog>
    {error && !dialogOpen && <p role="alert" className="image-batch-error">{error}</p>}
    {problems.length > 0 && <details className="image-batch-problems"><summary>{problems.length} 个画面需要处理</summary>{problems.map((item) => <div key={item.visual_beat_id}><button className="text-button" onClick={() => callbacks.current.onSelectShot(item.shot_plan_id)} type="button">分镜 {item.shot_index} · 画面 {item.beat_index}</button><span>{item.error_message}</span></div>)}</details>}
  </section>;
}
