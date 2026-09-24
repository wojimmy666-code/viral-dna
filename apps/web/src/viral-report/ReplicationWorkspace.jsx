import { Button } from "../ui/system/Button.jsx";
import { CaretDown, CircleNotch, MagicWand, ShieldWarning, Stop } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CategoryProfilePicker } from "../category-profiles/index.js";
import { ConceptComparison } from "./ConceptComparison.jsx";
import { CreativeIdeas } from "./CreativeIdeas.jsx";
import { batchLabel, creativeBriefText, creativeCost, creativeTiming, creativeTimingParts, isCreativeRunning, mergeCreativeBatch, visibleCreativeBatch } from "./creative-workflow.js";
import { useViralInsight } from "./viral-report-ui.js";
import "./creative-workflow.css";
import { VisualStyleControl } from "../visual-styles/VisualStyleControl.jsx";
import { ProductionStyleControl } from "../visual-styles/ProductionStyleControl.jsx";
import { hasVisualStyle, ORIGINAL_STYLE } from "../visual-styles/visual-style.js";

export function ReplicationWorkspace({ analysisId, recordId, request, onPublished, onPromptPreview, onNotice, onManageCategories }) {
  const { insight, loading, error, reload } = useViralInsight({ analysisId, request });
  const [replacementValues, setReplacementValues] = useState({});
  const [history, setHistory] = useState([]);
  const [currentId, setCurrentId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [visualStyle, setVisualStyle] = useState(null);
  const [styleSnapshot, setStyleSnapshot] = useState(null);
  const [stylePending, setStylePending] = useState(false);
  const [styleAvailable, setStyleAvailable] = useState(false);
  const [categoryStyle, setCategoryStyle] = useState(null);
  const [conceptError, setConceptError] = useState(null);
  const [pending, setPending] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [retryRequest, setRetryRequest] = useState(null);
  const [publishingId, setPublishingId] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [pollPaused, setPollPaused] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [revising, setRevising] = useState(false);
  const revisingRef = useRef(false);
  revisingRef.current = revising;
  const epoch = useRef(0);
  const submission = useRef(false);

  const loadHistory = useCallback(async () => {
    const version = ++epoch.current;
    setHistoryLoading(true); setConceptError(null);
    const suffix = selectedCategoryId ? `?category_profile_id=${encodeURIComponent(selectedCategoryId)}` : "";
    try {
      const items = await request(`/analyses/${analysisId}/viral-concepts/history${suffix}`);
      if (version !== epoch.current) return;
      setHistory(items);
      setCurrentId(id => revisingRef.current && items.some(item => item.id === id) ? id : items[0]?.id || "");
      setPollPaused(false);
    } catch (failure) {
      if (version === epoch.current) setConceptError({ message: `历史读取失败：${failure.message}`, recovery: "query" });
    } finally { if (version === epoch.current) setHistoryLoading(false); }
  }, [analysisId, selectedCategoryId, request]);

  useEffect(() => {
    setHistory([]); setCurrentId(""); setSelectedId(""); setRetryRequest(null);
    setFeedback(null);
    setVisualStyle(null); setStyleSnapshot(null); setStylePending(false);
    loadHistory();
    return () => { epoch.current += 1; };
  }, [loadHistory]);

  const activeJob = history.find(isCreativeRunning);
  const activeJobId = activeJob?.id;
  useEffect(() => {
    if (!activeJobId || pollPaused) return undefined;
    let active = true;
    let timer;
    let controller;
    const version = epoch.current;
    async function poll() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 15000);
      try {
        const item = await request(`/viral-concept-sets/${activeJobId}`, { signal: controller.signal });
        if (!active || version !== epoch.current) return;
        setHistory((items) => mergeCreativeBatch(items, item));
        if (isCreativeRunning(item)) timer = setTimeout(poll, 1500);
      } catch (failure) {
        if (active && version === epoch.current) {
          setConceptError({ message: `暂时无法读取任务状态：${failure.message}。服务端仍会按超时规则结束，可恢复查询。`, recovery: "query" });
          setPollPaused(true);
        }
      } finally { clearTimeout(timeout); }
    }
    timer = setTimeout(poll, 800);
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => { active = false; clearTimeout(timer); clearInterval(clock); controller?.abort(); };
  }, [activeJobId, pollPaused, request]);

  const current = history.find((item) => item.id === currentId);
  const display = visibleCreativeBatch(current);
  const parent = history.find((item) => item.id === display?.parent_set_id);
  const ideaBatch = display?.phase === "ideas" ? display : parent?.phase === "ideas" ? parent : null;
  const expandedPlan = display?.phase === "expanded";
  const returnBatchId = ideaBatch?.id || history.find((item) => item.phase === "ideas")?.id;
  const canPreview = current?.phase === "expanded" && (current.status === "completed" || current.error_code === "creative_prompt_language_invalid") && current.concepts?.length > 0;
  const effectiveFeedback = feedback ?? creativeBriefText(current || display);
  const idea = ideaBatch?.ideas?.find((item) => item.id === selectedId);
  const inheritedStyle = idea?.visual_style_snapshot ?? current?.visual_style_snapshot;
  const effectiveStyle = visualStyle ?? inheritedStyle?.selection ?? (inheritedStyle ? ORIGINAL_STYLE : categoryStyle) ?? ORIGINAL_STYLE;
  const styleBlocked = stylePending || (hasVisualStyle(effectiveStyle) && !styleAvailable);
  const busy = pending || Boolean(activeJob) || Boolean(publishingId);
  const locked = busy || revising || Boolean(retryRequest);
  // Older services silently ignore unknown request fields: never pay for ignored notes.
  const revisionSupported = Boolean(ideaBatch && Object.hasOwn(ideaBatch, "revision_notes"));
  const selectedReplacements = useMemo(() => Object.entries(replacementValues)
    .filter(([, value]) => value.trim())
    .map(([entity_id, replacement]) => ({ entity_id, replacement: replacement.trim() })), [replacementValues]);

  useEffect(() => { setSelectedId(display?.phase === "expanded" ? display.source_idea_id || "" : ""); }, [ideaBatch?.id, display?.phase, display?.source_idea_id]);

  async function submit(url, body, retry = false) {
    if (submission.current || activeJob) return;
    submission.current = true; setPending(true); setConceptError(null);
    const version = epoch.current;
    const operation = { url, body: retry ? body : { ...body, request_id: crypto.randomUUID() } };
    setRetryRequest(operation);
    try {
      const batch = await request(operation.url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(operation.body) });
      if (version !== epoch.current) return;
      setHistory((items) => mergeCreativeBatch(items, batch));
      setCurrentId(batch.id); setRetryRequest(null); setPollPaused(false);
      setFeedback((value) => value === feedback ? null : value);
    } catch (failure) {
      if (version === epoch.current) {
        setConceptError({ message: failure.message });
        // A rejected expansion did not start a billable task. Allow choosing or revising.
        if (operation.url.endsWith("/expand") && failure.status === 409 && failure.code === "idea_review_required") setRetryRequest(null);
      }
    }
    finally { submission.current = false; setPending(false); }
  }

  function generateConcepts() {
    if (!selectedCategoryId || styleBlocked) return;
    return submit(`/analyses/${analysisId}/viral-concepts`, { category_profile_id: selectedCategoryId, feedback: effectiveFeedback, replacements: selectedReplacements, visual_style: effectiveStyle });
  }
  function actOnIdea(item, action, revisionNotes) {
    const targetStyle = visualStyle ?? item.visual_style_snapshot?.selection ?? (item.visual_style_snapshot ? ORIGINAL_STYLE : effectiveStyle);
    if (styleBlocked || (hasVisualStyle(targetStyle) && !styleAvailable)) { setConceptError({ message: "请先应用或取消画面风格修改；如风格服务不可用，请重新读取" }); return; }
    if (revisionNotes !== undefined && !revisionSupported) {
      setConceptError({ message: "服务版本尚未更新，请更新并重启服务后刷新页面。" });
      return;
    }
    const body = { feedback: effectiveFeedback, visual_style: targetStyle };
    if (revisionNotes !== undefined) body.revision_notes = revisionNotes;
    return submit(`/viral-concept-sets/${ideaBatch.id}/ideas/${item.id}/${action}`, body);
  }
  async function cancelJob() {
    if (submission.current || !activeJob) return;
    submission.current = true;
    setPending(true); setCancelling(true); setConceptError(null);
    const version = epoch.current;
    try {
      const batch = await request(`/viral-concept-sets/${activeJob.id}/cancel`, { method: "POST" });
      if (version === epoch.current) setHistory((items) => mergeCreativeBatch(items, batch));
    } catch (failure) { if (version === epoch.current) setConceptError({ message: failure.message, recovery: "query" }); }
    finally { submission.current = false; setPending(false); setCancelling(false); }
  }
  async function publishConcept(concept) {
    if (submission.current || !display || stylePending || (expandedPlan && !styleAvailable)) return;
    submission.current = true; setPublishingId(concept.id); setConceptError(null);
    try {
      const result = await request(`/viral-concept-sets/${display.id}/concepts/${concept.id}/publish`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ record_id: recordId, name: concept.name.slice(0, 120) }) });
      onNotice?.({ type: "success", message: `已创建“${result.project_name}”` });
      await onPublished?.(result);
    } catch (failure) { setConceptError({ message: failure.message }); }
    finally { setPublishingId(""); submission.current = false; }
  }

  if (loading && !insight) return <div className="viral-loading-state"><CircleNotch className="spin" size={22} />正在读取创意依据…</div>;
  if (error && !insight) return <div className="viral-error-state"><ShieldWarning size={22} /><div><strong>无法读取复刻信息</strong><p>{error}</p></div><Button variant="secondary" size="compact" type="button" onClick={reload}>重试</Button></div>;
  if (!insight) return null;

  return <div className="viral-report-page replication-workspace">
    <header className="viral-section-header"><div><h2>复刻与改进</h2></div></header>
    <fieldset className="creative-category-lock" disabled={locked || stylePending}><CategoryProfilePicker onChange={(id, profile) => { setSelectedCategoryId(id); setCategoryStyle(profile?.default_visual_style || null); }} onManage={onManageCategories} request={request} value={selectedCategoryId} /></fieldset>
    {expandedPlan && display.status === "completed"
      ? <ProductionStyleControl key={display.id} batchId={display.id} request={request} disabled={locked} onPending={setStylePending} onAvailable={setStyleAvailable} />
      : <VisualStyleControl label="风格" value={effectiveStyle} snapshot={styleSnapshot ?? inheritedStyle} request={request} disabled={locked} onChange={(value, compiled) => { setVisualStyle(value); setStyleSnapshot(compiled); }} onPending={setStylePending} onAvailable={setStyleAvailable} />}
    <label className="creative-feedback"><span>补充想法</span><textarea disabled={locked} value={effectiveFeedback} maxLength={2000} rows={2} onChange={(event) => setFeedback(event.target.value)} placeholder="例如：保留冷光与快速硬切，希望画面有想象力，不要直接推销商品。" /></label>
    {insight.replacement_opportunities?.length > 0 && <details className="creative-replacements"><summary>指定元素替换（可选）</summary><p>只约束你填写的元素；留空不要求继续沿用原片场景或人物。</p><div className="replacement-opportunity-list">{insight.replacement_opportunities.map((item) => <label key={item.entity_id}><span>{item.label}</span><input maxLength={800} value={replacementValues[item.entity_id] || ""} onChange={(event) => setReplacementValues((values) => ({ ...values, [item.entity_id]: event.target.value }))} placeholder="填写希望采用的元素" /></label>)}</div></details>}
    <section className="replication-generate-bar action-only"><Button className="primary-button" type="button" disabled={locked || styleBlocked || historyLoading || !selectedCategoryId} onClick={generateConcepts}>{pending ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} />}{history.some((item) => item.phase === "ideas") ? "换一批创意" : "生成 3 个简短创意"}</Button></section>
    {history.length > 0 && <div className={`creative-batch-context${expandedPlan ? " is-expanded" : ""}`}>
      <div className="creative-batch-toolbar">
        <label className="creative-history"><span>历史批次</span><select value={currentId} disabled={locked || stylePending} onChange={(event) => { setCurrentId(event.target.value); setFeedback(null); setVisualStyle(null); setStyleSnapshot(null); setConceptError(null); }}>{history.map((item) => <option key={item.id} value={item.id}>{batchLabel(item)} · {item.category_profile?.display_name || "旧版"}</option>)}</select></label>
        {expandedPlan && <Button variant="text" size="compact" disabled={busy || !returnBatchId} onClick={() => setCurrentId(returnBatchId)}>返回创意选择</Button>}
      </div>
      {expandedPlan && <CreativeRunMeta key={current.id} batch={current} />}
    </div>}
    {historyLoading && <p className="creative-task-status" role="status">正在读取历史…</p>}
    {conceptError && <div className="viral-error-state compact" role="alert"><ShieldWarning size={19} /><span>{conceptError.message}</span>{retryRequest ? <Button variant="secondary" size="compact" type="button" disabled={pending} onClick={() => submit(retryRequest.url, retryRequest.body, true)}>重试同一请求</Button> : conceptError.recovery === "query" && <Button variant="secondary" size="compact" type="button" disabled={historyLoading || pending} onClick={loadHistory}>恢复查询</Button>}{retryRequest && <Button variant="secondary" size="compact" type="button" disabled={pending} onClick={() => { setRetryRequest(null); loadHistory(); }}>核对任务状态</Button>}</div>}
    {activeJob && <section className="creative-task-status" role="status"><CircleNotch className="spin" size={18} /><div><strong>{activeJob.phase === "expanded" ? "正在展开选定创意" : "正在构思不同方向"}</strong><p>{activeJob.requested_model} · {creativeTiming(activeJob, now)}</p><small>最长 240 秒；离开页面不会重复提交</small></div><Button variant="warning" size="compact" icon={<Stop />} loading={cancelling} loadingLabel="正在停止…" disabled={pending} onClick={cancelJob}>停止任务</Button></section>}
    {!expandedPlan && current && !isCreativeRunning(current) && current.phase !== "legacy" && <div className="creative-run-meta"><span>{current.resolved_model || current.requested_model || "人工编辑"} · {creativeTiming(current)} · {creativeCost(current)}</span>{current.completed_at && <time dateTime={current.completed_at}>结束于 {new Date(current.completed_at).toLocaleTimeString("zh-CN")}</time>}</div>}
    {current?.error_message && !ideaBatch && <p className="creative-failure" role="alert">{current.error_message}。可调整想法后重新生成，或从历史批次继续。</p>}
    {canPreview && !expandedPlan && <div className="creative-preview-action"><Button variant="text" type="button" onClick={() => onPromptPreview?.(current)}>{current.language_issues?.length ? "查看方案提示词并转为中文" : "查看方案提示词"}</Button></div>}
    {ideaBatch && display?.phase !== "expanded" && <CreativeIdeas key={ideaBatch.id} ideas={ideaBatch.ideas} selectedId={selectedId} onSelect={id => { if (stylePending) return; setSelectedId(id); setConceptError(null); }} busy={busy || stylePending || Boolean(retryRequest)} revisionSupported={revisionSupported} onRevisionOpenChange={setRevising} onRegenerate={(item, notes) => actOnIdea(item, "regenerate", notes)} />}
    {ideaBatch && display?.phase !== "expanded" && <div className="creative-expand-action">{!idea && <span>选择一个喜欢的方向后，再展开完整分镜</span>}<Button type="button" className="primary-button" disabled={!idea || locked || styleBlocked} onClick={() => actOnIdea(idea, "expand")}>展开这个创意</Button></div>}
    {display?.phase === "legacy" && <p className="creative-snapshot">这是保留的旧版规则方案。选择品类后可生成新的模型创意，不会覆盖旧方案。</p>}
    {display?.phase !== "ideas" && <ConceptComparison conceptSet={display} historical={display?.phase === "legacy"} publishingId={publishingId} publishDisabled={stylePending || (expandedPlan && !styleAvailable)} onPublish={publishConcept} onPromptPreview={canPreview ? () => onPromptPreview?.(current) : undefined} />}
  </div>;
}

function CreativeRunMeta({ batch }) {
  const { total, queue, model } = creativeTimingParts(batch);
  return <details className="creative-plan-run-meta">
    <summary><span className="creative-run-summary"><span>{batch.resolved_model || batch.requested_model || "人工编辑"}</span><span>总计 {total} 秒</span><span>{creativeCost(batch)}</span></span><span className="creative-run-details-toggle">运行详情<CaretDown size={14} aria-hidden="true" /></span></summary>
    <dl><div><dt>排队</dt><dd>{queue} 秒</dd></div><div><dt>模型</dt><dd>{model} 秒</dd></div>{batch.completed_at && <div><dt>结束于</dt><dd><time dateTime={batch.completed_at}>{new Date(batch.completed_at).toLocaleString("zh-CN")}</time></dd></div>}</dl>
  </details>;
}
