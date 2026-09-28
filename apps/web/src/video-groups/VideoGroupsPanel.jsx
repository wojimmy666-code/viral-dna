import { Button } from "../ui/system/Button.jsx";
import { useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { videoDurationOptions, preferredVideoResolution } from "../production-ui.js";
import { groupDefinition, groupModelOptions, suggestedGroups, plannedCuts, cutsValid } from "./group-planning.js";
import "./video-groups.css";
import { AssetReferenceEditor } from '../prompt-references/AssetReferenceEditor.jsx';
import { promptAssetReference, promptMentionData } from '../prompt-references/prompt-assets.js';
import { GlobalPromptEditor } from '../prompt-context/GlobalPromptEditor.jsx';
import { PromptSectionHeader } from '../prompt-context/PromptSectionHeader.jsx';
import { adjacentSelection, groupReferences, groupShotLabel } from './group-references.js';

const ACTIVE = new Set(["queued", "running", "cancellation_requested"]);
const json = body => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(60000) });

function CandidateReview({ candidate, group, request, projectId, revision, onReload, disabled }) {
  const [cuts, setCuts] = useState(() => plannedCuts(group.shots, candidate.duration_seconds));
  const [reviewed, setReviewed] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function adopt() {
    setPending(true); setError("");
    try {
      await request(`/productions/${projectId}/video-groups/${group.id}/adopt`, json({ expected_revision_id: revision, candidate_id: candidate.id, cuts, content_reviewed: reviewed }));
      await onReload();
    } catch (failure) { setError(failure.message); } finally { setPending(false); }
  }
  return <section className="video-group-review" aria-label="核对生成组切点">
    <video controls preload="metadata" src={candidate.content_url} aria-label="生成组候选视频" />
    <p>以下是建议切点，请先播放核对。采用后按实际范围剪辑，不自动加速。</p>
    {cuts.map((cut, index) => <div className="video-group-cut" key={cut.shot_plan_id}>
      <span>分镜 {group.shots[index].index}</span>
      {["trim_in_seconds", "trim_out_seconds"].map((field, position) => <label key={field}>{position ? "出点（秒）" : "入点（秒）"}<input type="number" min="0" max={candidate.duration_seconds} step="0.01" value={cut[field]} disabled={pending} onChange={event => { setReviewed(false); setCuts(values => values.map((item, i) => i === index ? { ...item, [field]: event.target.value === "" ? "" : Number(event.target.value) } : item)); }} /></label>)}
    </div>)}
    {error && <p role="alert" className="video-group-error">{error}</p>}
    <div className="video-group-review-actions">
      <label className="video-group-check"><input type="checkbox" checked={reviewed} disabled={pending} onChange={event => setReviewed(event.target.checked)} />我已确认场景、顺序和实际切点</label>
      <Button type="button" className="primary-button" disabled={disabled || pending || !reviewed || !cutsValid(cuts, candidate.duration_seconds)} onClick={adopt}>{pending ? "正在采用…" : "采用这些片段"}</Button>
    </div>
  </section>;
}

function GroupEditor({ group, ordinal, models, revision, projectId, request, resolveUrl, onSave, onReload, onDirty, registerSave, beforeGenerate, disabled, assets, onAddAssets, globalPromptRef, onAdjust, onEditShot }) {
  const [prompt, setPrompt] = useState(group.video_prompt || "");
  const [mentions, setMentions] = useState(group.video_prompt_mentions || []);
  const [transition, setTransition] = useState(group.transition || "cut");
  const latestDraft = useRef({ prompt, mentions, transition });
  latestDraft.current = { prompt, mentions, transition };
  const [alias, setAlias] = useState(models[0]?.alias || "");
  const model = models.find(item => item.alias === alias) || models[0];
  const durations = videoDurationOptions(model);
  const [duration, setDuration] = useState(durations.find(value => value >= group.target_duration_seconds) || durations.at(-1));
  const [resolution, setResolution] = useState(preferredVideoResolution(model));
  const [estimate, setEstimate] = useState(null);
  const [acceptUnknown, setAcceptUnknown] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const ownGlobalRef = useRef(null);
  const contextRef = globalPromptRef || ownGlobalRef;
  const [context, setContext] = useState({});
  const [submissionUncertain, setSubmissionUncertain] = useState(false);
  const dirty = prompt !== (group.video_prompt || "") || transition !== group.transition || JSON.stringify(mentions) !== JSON.stringify(group.video_prompt_mentions || []);
  const definitionKey = JSON.stringify(groupDefinition(group));
  const [baseKey, setBaseKey] = useState(definitionKey);
  const serverDraftKey = JSON.stringify([group.video_prompt || '', group.video_prompt_mentions || [], group.transition || 'cut']);
  const localDraftKey = JSON.stringify([prompt, mentions, transition]);
  const acceptedDraft = useRef(serverDraftKey);
  useEffect(() => {
    if (serverDraftKey !== acceptedDraft.current && localDraftKey === acceptedDraft.current) {
      setPrompt(group.video_prompt || ''); setMentions(group.video_prompt_mentions || []); setTransition(group.transition || 'cut');
      setBaseKey(definitionKey); setEstimate(null); acceptedDraft.current = serverDraftKey;
    } else if (serverDraftKey === localDraftKey) acceptedDraft.current = serverDraftKey;
  }, [serverDraftKey, localDraftKey, definitionKey, group]);
  const conflict = baseKey !== definitionKey && dirty;
  useEffect(() => { if (!dirty) setBaseKey(definitionKey); }, [dirty, definitionKey]);
  useEffect(() => { onDirty(group.id, dirty); return () => onDirty(group.id, false); }, [onDirty, group.id, dirty]);
  const running = group.runs?.find(run => ACTIVE.has(run.status));
  const references = groupReferences(group, mentions, assets);
  const referenceCount = references.all.length;
  const confirmationKey = JSON.stringify([group.input_fingerprint, model?.alias, duration, resolution, context.common_video_prompt, context.common_video_mentions]);
  const canGenerate = !disabled && !pending && !running && !dirty && !group.error && model && !submissionUncertain
    && group.input_plan?.input_policy === 'adopted_images_v1'
    && Object.hasOwn(context, 'common_video_prompt')
    && referenceCount <= model.capabilities.maximum_reference_images && duration >= group.target_duration_seconds;
  const busyRef = useRef(false);
  const pendingSave = useRef(null);
  const alive = useRef(false);
  const latestInputs = useRef(null);
  latestInputs.current = { confirmationKey, disabled };
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const save = useCallback(async () => {
    if (pendingSave.current) return pendingSave.current;
    if (busyRef.current) return false;
    // Input and blur/navigation can run before React commits the new state.
    // Read the synchronous draft, not the previous render's save closure.
    const draft = latestDraft.current;
    const unchanged = JSON.stringify([draft.prompt, draft.mentions, draft.transition]) === serverDraftKey;
    if (unchanged) return true;
    if (baseKey !== definitionKey) { setError("其他页面已修改组要求，当前文字已保留。请复制备份后重新读取再核对。"); return false; }
    if (busyRef.current || disabled) return false;
    busyRef.current = true; setPending(true); setError("");
    pendingSave.current = (async () => {
      try { const saved = { ...groupDefinition(group), video_prompt: draft.prompt, video_prompt_mentions: draft.mentions, transition: draft.transition }; await onSave(saved); setBaseKey(JSON.stringify(saved)); return true; }
      catch (failure) { setError(failure.message); return false; }
      finally { busyRef.current = false; setPending(false); }
    })();
    try { return await pendingSave.current; }
    finally { pendingSave.current = null; }
  }, [baseKey, definitionKey, serverDraftKey, disabled, group, onSave]);
  useEffect(() => registerSave(group.id, save), [group.id, registerSave, save]);
  useEffect(() => {
    if (!dirty || conflict || pending || error || running) return;
    const timer = setTimeout(() => void save(), 900);
    return () => clearTimeout(timer);
  }, [dirty, conflict, pending, error, running, save]);
  useEffect(() => {
    const warn = event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  async function act(operation) {
    if (busyRef.current) return;
    busyRef.current = true; setPending(true); setError("");
    try { await operation(); } catch (failure) { setError(failure.message || "操作失败，请重试"); }
    finally { busyRef.current = false; setPending(false); }
  }
  const parameters = { model_alias: model?.alias, duration_seconds: Number(duration), resolution, candidate_count: 1 };
  const cancel = () => act(async () => { await request(`/generation-runs/${running.id}/cancel`, json({})); await onReload(); });
  const price = () => act(async () => {
    await beforeGenerate?.();
    const latest = await onReload();
    if (!alive.current || latestInputs.current.disabled) return;
    if (latest?.groups.find(item => item.id === group.id)?.input_fingerprint !== group.input_fingerprint) {
      setEstimate(null); throw new Error("分镜输入已更新，请核对新的合并提示词后重新预览费用");
    }
    const result = await request("/video-generation/estimate", json(parameters));
    setEstimate({ key: confirmationKey, result }); setAcceptUnknown(false);
  });
  const generate = () => act(async () => {
    if (estimate?.key !== confirmationKey) throw new Error("输入已变化，请重新预览费用");
    await beforeGenerate?.();
    const latest = await onReload();
    if (!alive.current || latestInputs.current.disabled || latestInputs.current.confirmationKey !== confirmationKey) {
      setEstimate(null); throw new Error('编辑目标或输入已变化，请重新确认费用');
    }
    if (!latest || latest.groups.find(item => item.id === group.id)?.input_fingerprint !== group.input_fingerprint) {
      setEstimate(null); throw new Error('本组输入已变化，请核对参考图和提示词后重新确认费用');
    }
    try { await request(`/production-shots/${group.anchor_shot_id}/video-runs`, json({ ...parameters,
      expected_revision_id: latest.expected_revision_id, generation_group_id: group.id, expected_group_fingerprint: group.input_fingerprint,
      execution_mode: "remote_api", audio_strategy: "muted", allow_unknown_cost: acceptUnknown,
      input_plan: group.input_plan,
    })); } catch (failure) {
      if (!failure.status || failure.status >= 500) { setSubmissionUncertain(true); setEstimate(null); throw new Error('生成受理结果待核验，请先重新读取任务状态，不要重复生成。'); }
      throw failure;
    }
    setEstimate(null); setSubmissionUncertain(true);
    await onReload(); setSubmissionUncertain(false);
  });
  return <section className="video-group" aria-label={`生成组 ${ordinal} 编辑器`}>
    <header className="shot-video-editor-title"><div><strong>生成组 {ordinal}</strong><span>{group.images?.length || 0} 张分镜图 · {Math.max(0, referenceCount - (group.images?.length || 0))} 项附加参考 → 1 段视频</span></div><Button variant="quiet" size="compact" disabled={pending || disabled || Boolean(running)} onClick={onAdjust}>调整组合</Button></header>
    {group.error && <p role="alert" className="video-group-error">{group.error}</p>}
    {group.input_plan?.input_policy !== 'adopted_images_v1' && <p role="alert" className="video-group-error">后端尚未启用独立视频输入，请更新并重启本地服务后刷新。</p>}
      {conflict && <p role="alert" className="video-group-error">组要求已在其他页面更新。<Button className="text-button" type="button" onClick={() => { setPrompt(group.video_prompt); setMentions(group.video_prompt_mentions || []); setTransition(group.transition); setBaseKey(definitionKey); setEstimate(null); setError(""); }}>放弃本地组要求，读取新内容</Button></p>}
      <div className="video-group-prompt-panel">
      <PromptSectionHeader title="组视频提示词" state={error ? 'error' : pending && dirty ? 'saving' : dirty ? 'dirty' : 'saved'} onRetry={() => void save()} />
      <AssetReferenceEditor label="本组补充要求" rows={3} maxLength={8000} value={prompt} references={references.mentions} options={references.options} resolveUrl={resolveUrl} disabled={pending || disabled || Boolean(running)}
        referencePart="video" pinnedReferences={references.pinned} preserveReferenceOrder showPinnedTokens
        referenceLimit={model?.capabilities?.maximum_reference_images}
        reservedReferenceIds={references.pinned.map(item => item.reference_id)}
        onAddAssets={onAddAssets && ((insert, options) => onAddAssets(selected => insert(selected.map(asset => promptAssetReference(asset, 'video'))), options))}
        onBlur={() => void save()}
        onChange={(value, refs) => { const nextMentions = promptMentionData(refs, 'video'); latestDraft.current = { ...latestDraft.current, prompt: value, mentions: nextMentions }; setError(''); setEstimate(null); setPrompt(value); setMentions(nextMentions); }} placeholder="补充本组共同动作、运镜或衔接要求；输入 @ 引用资产。原分镜动作在下方保留。" />
      <p className="video-group-meta">{groupShotLabel(group)}，按图片编号顺序提交。外观以已采用图片为准；生图时的资产和风格不重复传入。</p>
      <div className="video-group-actions"><label>场景切换<select value={transition} disabled={pending || disabled || Boolean(running)} onChange={event => { latestDraft.current = { ...latestDraft.current, transition: event.target.value }; setError(''); setEstimate(null); setTransition(event.target.value); }}><option value="cut">硬切</option><option value="continuous">连续运动</option><option value="dissolve">叠化</option></select></label><span className="video-group-meta">成片目标 {Number(group.target_duration_seconds.toFixed(2))} 秒</span></div>
      <details className="video-group-script-details" open><summary>各分镜动作与完整提示词{dirty ? ' · 待保存更新' : ''}</summary><p className="video-group-script">{group.compiled_prompt}</p><div className="video-group-members">{group.shots.map(shot => <Button key={shot.id} variant="text" size="compact" disabled={pending || disabled} onClick={() => onEditShot?.(shot.id)}>编辑分镜 {shot.index} 动作</Button>)}</div></details>
      </div>
      <GlobalPromptEditor ref={contextRef} path={`/productions/${projectId}/prompt-context`} request={request} part="video" disabled={disabled || Boolean(running)} onChange={setContext} hideShotStyle hideVisualStyle assets={assets} onAddAssets={onAddAssets} resolveUrl={resolveUrl} />
      <div className="video-group-actions">
        <label>视频模型<select value={model?.alias || ""} disabled={disabled || pending || Boolean(running)} onChange={event => { const next = models.find(item => item.alias === event.target.value); setAlias(event.target.value); const values = videoDurationOptions(next); setDuration(values.find(value => value >= group.target_duration_seconds) || values.at(-1)); setResolution(preferredVideoResolution(next)); setEstimate(null); }}><option value="" disabled>选择有序多图模型</option>{models.map(item => <option key={item.alias} value={item.alias}>{item.label}</option>)}</select></label>
        <label>生成时长<select value={duration} disabled={disabled || pending || Boolean(running)} onChange={event => setDuration(Number(event.target.value))}>{durations.map(value => <option key={value} value={value}>{value} 秒</option>)}</select></label>
        <label>分辨率<select value={resolution} disabled={disabled || pending || Boolean(running)} onChange={event => setResolution(event.target.value)}>{(model?.capabilities.supported_resolutions || []).map(value => <option key={value}>{value}</option>)}</select></label>
        {!running && estimate?.key !== confirmationKey && <Button type="button" className="primary-button" disabled={!canGenerate} onClick={price}>{pending ? "处理中…" : "生成 1 段视频"}</Button>}
      </div>
      {!model && <p>未配置可用的有序多图模型。请配置模型，或拆组后独立生成再剪辑。</p>}
      {model && (referenceCount > model.capabilities.maximum_reference_images || duration < group.target_duration_seconds) && <p role="alert" className="video-group-error">本组共 {referenceCount} 项参考，模型上限 {model.capabilities.maximum_reference_images} 项；生成时长须至少 {group.target_duration_seconds} 秒。请调整模型、时长或组合，不会自动丢弃参考。</p>}
      {estimate?.key === confirmationKey && <div className="video-group-confirm"><strong>确认本次生成</strong><p>{group.images.length} 张分镜图 · {referenceCount - group.images.length} 项额外参考 → 1 段视频 · {duration} 秒 · {resolution} · {model.label} · 静音</p><p>{estimate.result.estimate_known ? `预计费用 ¥${(estimate.result.estimated_cost_micros / 1000000).toFixed(4)}` : "当前模型无法预估费用，不代表免费，将按供应商实际用量记录"}</p>{!estimate.result.estimate_known && <label className="video-group-check"><input type="checkbox" checked={acceptUnknown} onChange={event => setAcceptUnknown(event.target.checked)} />确认接受费用未知</label>}<div className="video-group-actions"><Button disabled={pending} onClick={() => setEstimate(null)}>取消</Button><Button type="button" className="primary-button" disabled={!canGenerate || (!estimate.result.estimate_known && !acceptUnknown)} onClick={generate}>确认费用并生成</Button></div></div>}
    {running && <p role="status">{running.status === "queued" ? "排队中" : "生成中"}，完成后需要核对场景与切点。<Button type="button" variant="warning" size="compact" disabled={pending || disabled || running.status === "cancellation_requested"} onClick={cancel}>{running.status === "cancellation_requested" ? "正在停止…" : "取消任务"}</Button></p>}
    {group.runs?.filter(run => !ACTIVE.has(run.status)).map((run, index) => <details key={run.id} open={index === 0}>
      <summary>{run.status === "failed" ? "生成失败" : run.status === "cancelled" ? "已取消" : "生成结果"} · {new Date(run.created_at).toLocaleString("zh-CN")}</summary>
      <p>{run.actual_cost_known ? `已记录费用 ¥${(Number(run.actual_cost_micros || 0) / 1000000).toFixed(4)}` : "实际费用待回传"}</p>
      {run.error_message && <p role="alert">{run.error_message}</p>}
      {(group.error || group.stale_run_ids?.includes(run.id)) && <p className="video-group-error">输入已变化，此历史结果仅供查看，不能按当前分组直接采用。</p>}
      {run.candidates?.filter(candidate => ["ready", "selected"].includes(candidate.status)).map(candidate => group.error
        ? <div className="video-group-review" key={candidate.id}><video controls preload="metadata" src={resolveUrl(candidate.content_url)} aria-label="生成组历史视频（只读）" /></div>
        : <CandidateReview key={`${candidate.id}:${group.input_fingerprint}`} candidate={{ ...candidate, content_url: resolveUrl(candidate.content_url) }} group={group} request={request} revision={revision} projectId={projectId} onReload={onReload} disabled={disabled || dirty || Boolean(running) || group.stale_run_ids?.includes(run.id)} />)}
    </details>)}
    {error && <p role="alert" className="video-group-error">{error}</p>}
    {submissionUncertain && <Button variant="text" onClick={onReload}>重新读取任务状态</Button>}
  </section>;
}

export function VideoGroupsPanel({ project, shots, settings, request, resolveUrl, onChanged, flushRef, beforeGenerate, disabled = false, assets = [], onAddAssets, children, selectedShotId, onSelectShot, globalPromptRef }) {
  const [state, setState] = useState(null), [error, setError] = useState("");
  const [selected, setSelected] = useState([]), [pending, setPending] = useState(false), [suggestions, setSuggestions] = useState([]);
  const [suggested, setSuggested] = useState(false), [dirtyGroups, setDirtyGroups] = useState({});
  const onDirty = useCallback((id, value) => setDirtyGroups(current => current[id] === value ? current : { ...current, [id]: value }), []);
  const saves = useRef(new Map());
  const registerSave = useCallback((id, save) => { saves.current.set(id, save); return () => saves.current.delete(id); }, []);
  const flush = useCallback(async () => {
    for (const save of [...saves.current.values()]) if (await save() === false) return false;
    return true;
  }, []);
  useImperativeHandle(flushRef, () => ({ flush }));
  const [view, setView] = useState(null);
  const [adjusting, setAdjusting] = useState(null);
  const controlsRef = useRef(null);
  const models = groupModelOptions(settings?.models);
  const epoch = useRef(0), operation = useRef(false);
  const latestState = useRef(null);
  const load = useCallback(async () => {
    const ticket = ++epoch.current;
    try { const value = await request(`/productions/${project.id}/video-groups`); if (ticket === epoch.current) { latestState.current = value; setState(value); setError(""); } return value; }
    catch (failure) { if (ticket === epoch.current) setError(failure.message); }
  }, [project.id, request]);
  useEffect(() => { load(); return () => { epoch.current++; }; }, [load, project.current_revision_id]);
  const running = state?.groups.some(group => group.runs?.some(run => ACTIVE.has(run.status)));
  useEffect(() => { if (!running) return; const timer = setInterval(load, 5000); return () => clearInterval(timer); }, [running, load]);
  const reload = useCallback(async () => { const value = await load(); await onChanged(); return value; }, [load, onChanged]);
  const update = useCallback(async groups => {
    const saved = await request(`/productions/${project.id}/video-groups`, { ...json({ expected_revision_id: latestState.current.expected_revision_id, groups }), method: "PUT" });
    latestState.current = saved; setState(saved); await onChanged(); return saved;
  }, [project.id, request, onChanged]);
  const navigate = async action => {
    if (operation.current || disabled) return;
    operation.current = true; setPending(true); setError('');
    try {
      if (!await flush()) throw new Error('请先处理未保存的组要求，当前内容已保留');
      await beforeGenerate?.();
      await action();
    } catch (failure) { setError(failure.message); }
    finally { operation.current = false; setPending(false); }
  };
  const mutate = async callback => {
    if (operation.current) return;
    operation.current = true; setPending(true); setError("");
    try {
      if (!await flush()) throw new Error('请先处理未保存的组要求，当前内容已保留');
      await beforeGenerate?.();
      // A global or single-shot draft save may have advanced the project revision.
      if (!await load()) throw new Error('无法核对最新分组，请重试');
      await callback(); setSelected([]); setSuggestions([]); setAdjusting(null);
    } catch (failure) { setError(failure.message); }
    finally { operation.current = false; setPending(false); }
  };
  const grouped = new Set(state?.groups.flatMap(group => group.shot_plan_ids) || []);
  const adjustingGroup = state?.groups.find(group => group.id === adjusting);
  const eligible = shots.filter(row => !grouped.has((row.plan || row).id) || adjustingGroup?.shot_plan_ids.includes((row.plan || row).id));
  const imageCount = shots.reduce((count, row) => count + ((row.plan || row).visual_beats || []).filter(beat => beat.approved_image_candidate_id).length, 0);
  const addGroups = async lists => {
    const additions = lists.map(ids => ({ id: crypto.randomUUID(), shot_plan_ids: ids, video_prompt: '', transition: 'cut' }));
    await update([...(latestState.current?.groups || []).map(groupDefinition), ...additions]);
    setView({ groupId: additions[0].id, shotId: selectedShotId });
    if (controlsRef.current) controlsRef.current.open = false;
  };
  const autoGroup = state?.groups.find(group => group.shot_plan_ids.includes(selectedShotId));
  const activeGroupId = view && view.shotId === selectedShotId ? view.groupId : autoGroup?.id;
  const activeGroup = state?.groups.find(group => group.id === activeGroupId);
  const chooseGroup = groupId => navigate(async () => {
    const latest = await load();
    const group = latest?.groups.find(item => item.id === groupId);
    if (!group) throw new Error('此生成组已变化，请重新选择');
    const anchor = group.shot_plan_ids[0];
    if (await onSelectShot?.(anchor, { deferSelection: true }) === false) return;
    setView({ groupId, shotId: anchor });
  });
  const chooseShot = shotId => navigate(async () => {
    // Parent selection has its own revision/save guards. Keep this editor if it fails.
    const accepted = await onSelectShot?.(shotId, { deferSelection: true });
    if (accepted === false) return;
    setView({ groupId: null, shotId });
  });
  const adjust = group => navigate(async () => {
    setAdjusting(group.id); setSelected(group.shot_plan_ids);
    if (controlsRef.current) { controlsRef.current.open = true; controlsRef.current.scrollIntoView({ block: 'nearest' }); }
  });
  const toolbar = <section className="video-groups-panel" aria-label="视频生成分组">
    <header><h3>生成组合</h3><span>{shots.length} 个分镜 · {imageCount} 张已采用图片 · {(state?.groups.length || 0) + shots.filter(row => !grouped.has((row.plan || row).id)).length} 个生成单元</span></header>
    {error && <p role="alert" className="video-group-error">{error}<Button type="button" className="text-button" onClick={load}>重新读取</Button></p>}
    {!state ? <p role="status">正在读取分组…</p> : <>
      <details ref={controlsRef}><summary>合并相邻分镜 / 调整组合</summary><p>{adjustingGroup ? `调整${groupShotLabel(adjustingGroup)}的组合，` : ''}选择相邻分镜合成一段视频。原分镜和历史素材保留，不会自动生成。</p>
        <div className="video-group-choices">{eligible.map(row => { const plan = row.plan || row; return <label key={plan.id}><input type="checkbox" disabled={pending || disabled || running} checked={selected.includes(plan.id)} onChange={event => setSelected(ids => event.target.checked ? [...ids, plan.id] : ids.filter(id => id !== plan.id))} />分镜 {plan.index} · {plan.duration_seconds} 秒</label>; })}</div>
        <div className="video-group-actions"><Button type="button" className="secondary-button" disabled={!adjacentSelection(shots, selected) || pending || disabled || running} onClick={() => mutate(async () => {
          const ids = shots.map(row => (row.plan || row).id).filter(id => selected.includes(id));
          if (adjustingGroup) {
            await update(latestState.current.groups.map(item => item.id === adjustingGroup.id ? { ...groupDefinition(item), shot_plan_ids: ids } : groupDefinition(item)));
            setView({ groupId: adjustingGroup.id, shotId: selectedShotId }); controlsRef.current.open = false;
          } else await addGroups([ids]);
        })}>{adjustingGroup ? '应用组合' : '合并选中分镜'}</Button>{adjustingGroup ? <Button variant="text" disabled={pending} onClick={() => { setAdjusting(null); setSelected([]); }}>取消调整</Button> : <Button type="button" className="text-button" disabled={!models.length || disabled || pending || running} onClick={() => { setSuggestions(suggestedGroups(shots, models[0], grouped)); setSuggested(true); }}>建议短镜头分组</Button>}</div>
        {selected.length > 1 && !adjacentSelection(shots, selected) && <p role="status" className="video-group-error">请选择按当前顺序排列的相邻分镜；本次不支持跨镜跳选。</p>}
        {suggested && !suggestions.length && <p role="status">没有符合当前模型时长、图片数量限制的相邻短镜头组合，可手动选择或保持独立生成。</p>}
        {suggestions.length > 0 && <div className="video-group-confirm"><p>建议 {suggestions.length} 个生成组：{suggestions.map(ids => ids.map(id => (shots.find(row => (row.plan || row).id === id)?.plan || shots.find(row => row.id === id))?.index).join("、")).join("；")}。确认仅保存分组，不会生成或扣费。</p><Button type="button" className="secondary-button" disabled={pending || disabled || running} onClick={() => mutate(() => addGroups(suggestions))}>确认建议分组</Button></div>}
        {state.groups.map((group, index) => <div className="video-group-actions" key={group.id}><span>生成组 {index + 1} · {groupShotLabel(group, shots)}</span><Button variant="text" disabled={pending || disabled || running} onClick={() => adjust(group)}>调整</Button><Button type="button" className="text-button" disabled={pending || disabled || running} onClick={() => mutate(async () => { await update(latestState.current.groups.filter(item => item.id !== group.id).map(groupDefinition)); setView(null); })}>拆为独立生成</Button></div>)}
      </details>
    </>}
  </section>;
  const editor = activeGroup && <GroupEditor key={activeGroup.id} group={activeGroup} ordinal={state.groups.indexOf(activeGroup) + 1} models={models} revision={state.expected_revision_id} projectId={project.id} request={request} resolveUrl={resolveUrl} disabled={disabled} assets={assets} onAddAssets={onAddAssets} onReload={reload} onDirty={onDirty} registerSave={registerSave} beforeGenerate={beforeGenerate} globalPromptRef={globalPromptRef} onAdjust={() => adjust(activeGroup)} onEditShot={chooseShot} onSave={saved => update(latestState.current.groups.map(item => item.id === saved.id ? saved : groupDefinition(item)))} />;
  const workspace = { toolbar, editor, groups: state?.groups || [], activeGroupId: activeGroup?.id, onSelectGroup: chooseGroup, onSelectShot: chooseShot, pending };
  return children ? children(workspace) : <>{toolbar}<div className="video-groups-standalone">{editor}</div></>;
}
