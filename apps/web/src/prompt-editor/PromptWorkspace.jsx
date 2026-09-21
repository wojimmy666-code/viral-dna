import { useEffect, useRef, useState } from "react";
import { flushAccountDrafts } from "../accounts/account-client.js";
import { creativeCost, isCreativeRunning } from "../viral-report/creative-workflow.js";
import { PromptEditor } from "./PromptEditor.jsx";
import { ProductionPromptDocument } from "./ProductionPromptDocument.jsx";
import { parsePromptSource, productionPromptsToText } from "./prompt-sources.js";
import "./prompt-workspace.css";

export function PromptWorkspace({ selectedSource = "source", onSourceChange, onEditProduction, onPublished, recordId, ...originalProps }) {
  const { analysisId, request, onCopy } = originalProps;
  const [sources, setSources] = useState([]);
  const [sourceError, setSourceError] = useState("");
  const [selection, setSelection] = useState(selectedSource);
  const [document, setDocument] = useState(null);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [estimate, setEstimate] = useState(null);
  const [revision, setRevision] = useState(0);
  const [catalogVersion, setCatalogVersion] = useState(0);
  const epoch = useRef(0);
  const submitLock = useRef(false);
  const translationRequest = useRef(null);
  const parsed = parsePromptSource(selection);
  const selected = sources.find(item => item.key === selection);
  const batchId = parsed.kind === "concept" ? parsed.id : selected?.batch_id;

  useEffect(() => {
    let active = true;
    request(`/analyses/${analysisId}/prompt-sources`, { signal: AbortSignal.timeout(15000) })
      .then(items => { if (active) { setSources(items); setSourceError(""); } })
      .catch(failure => { if (active) setSourceError(failure.message || "方案列表读取失败"); });
    return () => { active = false; };
  }, [analysisId, request, revision, selection, catalogVersion]);

  useEffect(() => {
    if (selectedSource === selection) return;
    let active = true;
    flushAccountDrafts().then(() => { if (active) setSelection(selectedSource); })
      .catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [selectedSource, selection]);

  useEffect(() => {
    const current = ++epoch.current;
    let timer;
    let active = true;
    setDocument(null); setJob(null); setError(""); setEstimate(null); translationRequest.current = null;
    if (["source", "scheme"].includes(parsed.kind)) { setLoading(false); return () => { active = false; }; }
    setLoading(true);
    async function load() {
      try {
        if (parsed.kind === "concept") {
          const next = await request(`/viral-concept-sets/${parsed.id}`, { signal: AbortSignal.timeout(15000) });
          if (!active || current !== epoch.current) return;
          setJob(next);
          if (isCreativeRunning(next)) { setLoading(false); timer = setTimeout(load, 1500); return; }
          if (next.status !== "completed" && next.error_code !== "creative_prompt_language_invalid") {
            setLoading(false); setError(next.error_message || "此任务未完成，原方案未改变"); return;
          }
        }
        const path = parsed.kind === "production" ? `/productions/${parsed.id}/prompt-document` : `/viral-concept-sets/${parsed.id}/prompt-document`;
        const next = await request(path, { signal: AbortSignal.timeout(15000) });
        if (active && current === epoch.current) { setDocument(next); setLoading(false); }
      } catch (failure) {
        if (active && current === epoch.current) { setError(`${failure.message || "读取失败"}。可恢复查询，不会重新提交模型任务。`); setLoading(false); }
      }
    }
    load();
    return () => { active = false; clearTimeout(timer); };
  }, [selection, revision, request]);

  async function choose(key) {
    if (submitLock.current || busy) return;
    try { await flushAccountDrafts(); onSourceChange(key); }
    catch (failure) { setError(failure.message); }
  }
  async function action(operation) {
    if (submitLock.current) return;
    submitLock.current = true; setBusy(true); setError("");
    const current = epoch.current;
    try { await flushAccountDrafts(); await operation(() => current === epoch.current); }
    catch (failure) { if (current === epoch.current) setError(failure.message || "请求未完成，请重试"); }
    finally { submitLock.current = false; setBusy(false); }
  }
  function getEstimate() {
    return action(async valid => {
      const suffix = parsed.kind === "production" ? `?project_id=${parsed.id}` : "";
      const result = await request(`/viral-concept-sets/${batchId}/localization-estimate${suffix}`, { signal: AbortSignal.timeout(15000) });
      if (valid()) { setEstimate(result); translationRequest.current = null; }
    });
  }
  function translate() {
    return action(async valid => {
      const body = translationRequest.current || {
        request_id: crypto.randomUUID(), project_id: parsed.kind === "production" ? parsed.id : null,
        expected_estimate: estimate.estimate_token, confirm_cost: true,
      };
      translationRequest.current = body;
      const result = await request(`/viral-concept-sets/${batchId}/localize`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(30000) });
      if (valid()) { setEstimate(null); onSourceChange(`concept:${result.id}`); }
    });
  }
  function applyTranslation() {
    return action(async valid => {
      const result = await request(`/viral-concept-sets/${parsed.id}/apply-language`, { method: "POST", signal: AbortSignal.timeout(30000) });
      if (valid() && result.project_id) { onSourceChange(`production:${result.project_id}`); }
    });
  }
  function publish() {
    return action(async valid => {
      const result = await request(`/viral-concept-sets/${parsed.id}/concepts/${job.concepts[0].id}/publish`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ record_id: recordId, name: document.name.slice(0, 120) }), signal: AbortSignal.timeout(30000),
      });
      if (valid()) await onPublished?.(result);
    });
  }
  function cancel() { return action(async valid => {
    await request(`/viral-concept-sets/${parsed.id}/cancel`, { method: "POST" });
    if (valid()) setRevision(value => value + 1);
  }); }
  const isTranslation = job?.operation === "localize";
  const canApply = isTranslation && document?.project_id && job?.status === "completed";
  const hasEnglish = Boolean(document?.language_issues?.length);

  return <div className="prompt-workspace">
    <div className="prompt-source-controls" aria-label="提示词来源">
      <div className="prompt-source-switch">
        <button type="button" aria-pressed={parsed.kind === "source"} disabled={busy} onClick={() => choose("source")}>原片提示词</button>
        <button type="button" aria-pressed={parsed.kind !== "source"} disabled={busy || !sources.length} onClick={() => {
          if (parsed.kind === "source") choose(sources.length === 1 ? sources[0].key : "scheme");
        }}>方案提示词</button>
      </div>
      {parsed.kind !== "source" && <label><span>方案</span><select aria-label="选择提示词方案" value={selected ? selection : ""} disabled={busy} onChange={event => choose(event.target.value)}>
        <option value="" disabled>选择具体方案</option>
        {sources.map(item => <option key={item.key} value={item.key}>{item.name} · {item.kind === "production" ? "制作中" : item.operation === "localize" ? "中文校正" : "未创建"}{item.created_at ? ` · ${new Date(item.created_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}` : ""}</option>)}
      </select></label>}
      {parsed.kind === "source" && <span className="prompt-source-caption">原视频分析 · {originalProps.promptPackage?.shots?.length || 0} 个分镜</span>}
    </div>
    {sourceError && <p className="scheme-prompt-error" role="alert">{sourceError} <button type="button" className="text-button" onClick={() => setCatalogVersion(value => value + 1)}>重试读取列表</button></p>}
    {error && <p className="scheme-prompt-error" role="alert">{error}{!document && <button type="button" className="text-button" disabled={busy} onClick={() => setRevision(value => value + 1)}>恢复查询</button>}</p>}
    {parsed.kind === "source" ? <PromptEditor {...originalProps} /> : <>
      {parsed.kind === "scheme" && <p className="scheme-prompt-status">请选择要查看的方案；不会自动切换到最新批次。</p>}
      {loading && <p className="scheme-prompt-status" role="status">正在读取所选方案…</p>}
      {isCreativeRunning(job) && <div className="scheme-prompt-status" role="status"><span>正在生成中文预览，原提示词尚未修改。最长 240 秒。</span><button type="button" className="secondary-button compact" disabled={busy} onClick={cancel}>停止任务</button></div>}
      {job && <p className="prompt-source-caption">{job.resolved_model || job.requested_model} · {creativeCost(job)}</p>}
      {document && <ProductionPromptDocument key={`${selection}:${revision}`} document={document} request={request} onCopy={onCopy} onEditProduction={onEditProduction}>
        {hasEnglish && <div className="scheme-language-notice"><span>检测到英文提示词。中文校正只处理描述文字，保留当前分镜和素材。</span>{batchId && <button type="button" className="secondary-button compact" disabled={busy || Boolean(estimate)} onClick={getEstimate}>转为中文</button>}</div>}
        {estimate && <section className="scheme-language-confirm" aria-label="中文校正费用确认">
          <p>{estimate.model} · 预估 ¥{(estimate.estimated_cost_micros / 1000000).toFixed(4)}，最终按实际用量计费。不会生成图片或视频。</p>
          <button type="button" className="primary-button compact" disabled={busy} onClick={translate}>{busy ? "提交中…" : "确认生成中文预览"}</button>
          <button type="button" className="text-button" disabled={busy} onClick={() => { setEstimate(null); translationRequest.current = null; }}>取消</button>
        </section>}
        {isTranslation && document.source_document && <div className="scheme-language-confirm">
          <details><summary>对照原提示词</summary><pre>{productionPromptsToText(document.source_document)}</pre></details>
          {canApply && <><p>确认后仅更新本方案的提示词，分镜、已采用素材及历史版本保留。</p><button type="button" className="primary-button compact" disabled={busy} onClick={applyTranslation}>{document.applied_revision_id ? "查看已应用方案" : "确认应用到原方案"}</button></>}
        </div>}
        {document.read_only && !document.project_id && !hasEnglish && job?.status === "completed" && <div className="scheme-language-confirm"><button type="button" className="primary-button compact" disabled={busy} onClick={publish}>确认创建制作项目</button></div>}
      </ProductionPromptDocument>}
    </>}
  </div>;
}
