import { CircleNotch, MagicWand, ShieldWarning } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CategoryProfilePicker } from "../category-profiles/index.js";
import { TextModelIndicator } from "../ui/text-model/TextModelIndicator.jsx";
import { ConceptComparison } from "./ConceptComparison.jsx";
import { CreativeIdeas } from "./CreativeIdeas.jsx";
import { batchLabel, creativeBriefText, creativeCost, creativeTiming, isCreativeRunning, mergeCreativeBatch, visibleCreativeBatch } from "./creative-workflow.js";
import { useViralInsight } from "./viral-report-ui.js";
import "./creative-workflow.css";

export function ReplicationWorkspace({ analysisId, recordId, request, onPublished, onNotice, onManageCategories, textModelLabel = "Qwen3.7 Plus" }) {
  const { insight, loading, error, reload } = useViralInsight({ analysisId, request });
  const [replacementValues, setReplacementValues] = useState({});
  const [history, setHistory] = useState([]);
  const [currentId, setCurrentId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [conceptError, setConceptError] = useState("");
  const [pending, setPending] = useState(false);
  const [retryRequest, setRetryRequest] = useState(null);
  const [publishingId, setPublishingId] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [pollPaused, setPollPaused] = useState(false);
  const [now, setNow] = useState(Date.now());
  const epoch = useRef(0);
  const submission = useRef(false);

  const loadHistory = useCallback(async () => {
    const version = ++epoch.current;
    setHistoryLoading(true); setConceptError("");
    const suffix = selectedCategoryId ? `?category_profile_id=${encodeURIComponent(selectedCategoryId)}` : "";
    try {
      const items = await request(`/analyses/${analysisId}/viral-concepts/history${suffix}`);
      if (version !== epoch.current) return;
      setHistory(items); setCurrentId(items[0]?.id || ""); setPollPaused(false);
    } catch (failure) {
      if (version === epoch.current) setConceptError(`历史读取失败：${failure.message}`);
    } finally { if (version === epoch.current) setHistoryLoading(false); }
  }, [analysisId, selectedCategoryId, request]);

  useEffect(() => {
    setHistory([]); setCurrentId(""); setSelectedId(""); setRetryRequest(null);
    setFeedback(null);
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
          setConceptError(`暂时无法读取任务状态：${failure.message}。服务端仍会按超时规则结束，可恢复查询。`);
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
  const idea = ideaBatch?.ideas?.find((item) => item.id === selectedId);
  const effectiveFeedback = feedback ?? creativeBriefText(current || display);
  const busy = pending || Boolean(activeJob) || Boolean(publishingId);
  const selectedReplacements = useMemo(() => Object.entries(replacementValues)
    .filter(([, value]) => value.trim())
    .map(([entity_id, replacement]) => ({ entity_id, replacement: replacement.trim() })), [replacementValues]);

  useEffect(() => { setSelectedId(display?.phase === "expanded" ? display.source_idea_id || "" : ""); }, [ideaBatch?.id, display?.phase, display?.source_idea_id]);

  async function submit(url, body, retry = false) {
    if (submission.current || activeJob) return;
    submission.current = true; setPending(true); setConceptError("");
    const version = epoch.current;
    const operation = { url, body: retry ? body : { ...body, request_id: crypto.randomUUID() } };
    setRetryRequest(operation);
    try {
      const batch = await request(operation.url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(operation.body) });
      if (version !== epoch.current) return;
      setHistory((items) => mergeCreativeBatch(items, batch));
      setCurrentId(batch.id); setRetryRequest(null); setPollPaused(false);
      setFeedback((value) => value === feedback ? null : value);
    } catch (failure) { if (version === epoch.current) setConceptError(failure.message); }
    finally { submission.current = false; setPending(false); }
  }

  function generateConcepts() {
    if (!selectedCategoryId) return;
    return submit(`/analyses/${analysisId}/viral-concepts`, { category_profile_id: selectedCategoryId, feedback: effectiveFeedback, replacements: selectedReplacements });
  }
  function actOnIdea(item, action) {
    return submit(`/viral-concept-sets/${ideaBatch.id}/ideas/${item.id}/${action}`, { feedback: effectiveFeedback });
  }
  async function cancelJob() {
    setPending(true); setConceptError("");
    const version = epoch.current;
    try {
      const batch = await request(`/viral-concept-sets/${activeJob.id}/cancel`, { method: "POST" });
      if (version === epoch.current) setHistory((items) => mergeCreativeBatch(items, batch));
    } catch (failure) { if (version === epoch.current) setConceptError(failure.message); }
    finally { setPending(false); }
  }
  async function publishConcept(concept) {
    if (submission.current || !display) return;
    submission.current = true; setPublishingId(concept.id); setConceptError("");
    try {
      const result = await request(`/viral-concept-sets/${display.id}/concepts/${concept.id}/publish`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ record_id: recordId, name: concept.name.slice(0, 120) }) });
      onNotice?.({ type: "success", message: `已创建“${result.project_name}”` });
      await onPublished?.(result);
    } catch (failure) { setConceptError(failure.message); }
    finally { setPublishingId(""); submission.current = false; }
  }

  if (loading && !insight) return <div className="viral-loading-state"><CircleNotch className="spin" size={22} />正在读取创意依据…</div>;
  if (error && !insight) return <div className="viral-error-state"><ShieldWarning size={22} /><div><strong>无法读取复刻信息</strong><p>{error}</p></div><button type="button" onClick={reload}>重试</button></div>;
  if (!insight) return null;

  return <div className="viral-report-page replication-workspace">
    <header className="viral-section-header"><div><h2>复刻与改进</h2></div></header>
    <ol className="creative-step-path" aria-label="创意流程"><li aria-current={!ideaBatch ? "step" : undefined}>选择品类</li><li aria-current={ideaBatch && display?.phase !== "expanded" ? "step" : undefined}>比较简短创意</li><li aria-current={display?.phase === "expanded" ? "step" : undefined}>展开并确认分镜</li></ol>
    <CategoryProfilePicker onChange={setSelectedCategoryId} onManage={onManageCategories} request={request} value={selectedCategoryId} />
    <label className="creative-feedback"><span>补充想法 <small>可选，对换新和展开都有效</small></span><textarea value={effectiveFeedback} maxLength={2000} rows={2} onChange={(event) => setFeedback(event.target.value)} placeholder="例如：保留冷光与快速硬切，希望画面有想象力，不要直接推销商品。" /></label>
    {insight.replacement_opportunities?.length > 0 && <details className="creative-replacements"><summary>指定元素替换（可选）</summary><p>只约束你填写的元素；留空不要求继续沿用原片场景或人物。</p><div className="replacement-opportunity-list">{insight.replacement_opportunities.map((item) => <label key={item.entity_id}><span>{item.label}</span><input maxLength={800} value={replacementValues[item.entity_id] || ""} onChange={(event) => setReplacementValues((values) => ({ ...values, [item.entity_id]: event.target.value }))} placeholder="填写希望采用的元素" /></label>)}</div></details>}
    <section className="replication-generate-bar"><div><TextModelIndicator label={textModelLabel} /><span>仅生成创意与分镜，不会立即生成图片或视频</span></div><button className="primary-button" type="button" disabled={busy || historyLoading || !selectedCategoryId || Boolean(retryRequest)} onClick={generateConcepts}>{pending ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} />}{history.some((item) => item.phase === "ideas") ? "换一批创意" : "生成 3 个简短创意"}</button></section>
    {history.length > 0 && <label className="creative-history"><span>历史批次</span><select value={currentId} disabled={pending || Boolean(publishingId)} onChange={(event) => { setCurrentId(event.target.value); setFeedback(null); }}>{history.map((item) => <option key={item.id} value={item.id}>{batchLabel(item)} · {item.category_profile?.display_name || "旧版"}</option>)}</select></label>}
    {historyLoading && <p className="creative-task-status" role="status">正在读取历史…</p>}
    {conceptError && <div className="viral-error-state compact" role="alert"><ShieldWarning size={19} /><span>{conceptError}</span>{retryRequest ? <button type="button" disabled={pending} onClick={() => submit(retryRequest.url, retryRequest.body, true)}>重试同一请求</button> : <button type="button" onClick={loadHistory}>恢复查询</button>}{retryRequest && <button type="button" disabled={pending} onClick={() => { setRetryRequest(null); loadHistory(); }}>核对任务状态</button>}</div>}
    {activeJob && <section className="creative-task-status" role="status"><CircleNotch className="spin" size={18} /><div><strong>{activeJob.phase === "expanded" ? "正在展开选定创意" : "正在构思不同方向"}</strong><p>{activeJob.requested_model} · {creativeTiming(activeJob, now)}</p><small>最长 240 秒；离开页面不会重复提交</small></div><button type="button" disabled={pending} onClick={cancelJob}>停止任务</button></section>}
    {current && !isCreativeRunning(current) && current.phase !== "legacy" && <div className="creative-run-meta"><span>{current.resolved_model || current.requested_model || "人工编辑"} · {creativeTiming(current)} · {creativeCost(current)}</span>{current.completed_at && <time dateTime={current.completed_at}>结束于 {new Date(current.completed_at).toLocaleTimeString("zh-CN")}</time>}</div>}
    {current?.error_message && <p className="creative-failure" role="alert">{current.error_message}。可调整想法后重新生成，或从历史批次继续。</p>}
    {ideaBatch && display?.phase !== "expanded" && <CreativeIdeas ideas={ideaBatch.ideas} selectedId={selectedId} onSelect={setSelectedId} busy={busy || Boolean(retryRequest)} onRegenerate={(item) => actOnIdea(item, "regenerate")} />}
    {ideaBatch && display?.phase !== "expanded" && <div className="creative-expand-action"><span>{idea ? `已选《${idea.name}》` : "选择一个喜欢的方向后，再展开完整分镜"}</span><button type="button" className="primary-button" disabled={!idea || busy || Boolean(retryRequest)} onClick={() => actOnIdea(idea, "expand")}>展开这个创意</button></div>}
    {display?.phase === "expanded" && <p className="creative-plan-heading">完整方案 · {display.concepts[0]?.shots?.length} 个新分镜 <button className="text-button" type="button" disabled={busy} onClick={() => setCurrentId(ideaBatch?.id || history.find((item) => item.phase === "ideas")?.id)}>返回创意选择</button></p>}
    {display?.phase === "legacy" && <p className="creative-snapshot">这是保留的旧版规则方案。选择品类后可生成新的模型创意，不会覆盖旧方案。</p>}
    {display?.phase !== "ideas" && <ConceptComparison conceptSet={display} historical={display?.phase === "legacy"} publishingId={publishingId} onPublish={publishConcept} />}
  </div>;
}
