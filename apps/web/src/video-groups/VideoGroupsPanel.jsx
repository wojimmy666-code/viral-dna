import { Button } from "../ui/system/Button.jsx";
import { useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { videoDurationOptions, preferredVideoResolution } from "../production-ui.js";
import { groupDefinition, groupModelOptions, suggestedGroups, plannedCuts, cutsValid } from "./group-planning.js";
import "./video-groups.css";
import { AssetReferenceEditor } from '../prompt-references/AssetReferenceEditor.jsx';
import { promptAssetReference, promptMentionData } from '../prompt-references/prompt-assets.js';

const ACTIVE = new Set(["queued", "running", "cancellation_requested"]);
const json = body => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

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

function GroupEditor({ group, ordinal, models, revision, projectId, request, resolveUrl, onSave, onReload, onDirty, registerSave, beforeGenerate, disabled, assets, onAddAssets }) {
  const [prompt, setPrompt] = useState(group.video_prompt || "");
  const [mentions, setMentions] = useState(group.video_prompt_mentions || []);
  const [transition, setTransition] = useState(group.transition || "cut");
  const [alias, setAlias] = useState(models[0]?.alias || "");
  const model = models.find(item => item.alias === alias) || models[0];
  const durations = videoDurationOptions(model);
  const [duration, setDuration] = useState(durations.find(value => value >= group.target_duration_seconds) || durations.at(-1));
  const [resolution, setResolution] = useState(preferredVideoResolution(model));
  const [estimate, setEstimate] = useState(null);
  const [acceptUnknown, setAcceptUnknown] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const dirty = prompt !== (group.video_prompt || "") || transition !== group.transition || JSON.stringify(mentions) !== JSON.stringify(group.video_prompt_mentions || []);
  const definitionKey = JSON.stringify(groupDefinition(group));
  const [baseKey, setBaseKey] = useState(definitionKey);
  const conflict = baseKey !== definitionKey && dirty;
  useEffect(() => { if (!dirty) setBaseKey(definitionKey); }, [dirty, definitionKey]);
  useEffect(() => { onDirty(group.id, dirty); return () => onDirty(group.id, false); }, [onDirty, group.id, dirty]);
  const running = group.runs?.find(run => ACTIVE.has(run.status));
  const confirmationKey = JSON.stringify([group.input_fingerprint, model?.alias, duration, resolution]);
  const canGenerate = !disabled && !pending && !running && !dirty && !group.error && model
    && group.input_plan?.references.length <= model.capabilities.maximum_reference_images && duration >= group.target_duration_seconds;
  const busyRef = useRef(false);
  const save = useCallback(async () => {
    if (!dirty) return true;
    if (conflict) { setError("其他页面已修改组要求，当前文字已保留。请复制备份后重新读取再核对。"); return false; }
    if (busyRef.current || disabled) return false;
    busyRef.current = true; setPending(true); setError("");
    try { const saved = { ...groupDefinition(group), video_prompt: prompt, video_prompt_mentions: mentions, transition }; await onSave(saved); setBaseKey(JSON.stringify(saved)); return true; }
    catch (failure) { setError(failure.message); return false; }
    finally { busyRef.current = false; setPending(false); }
  }, [dirty, conflict, disabled, group, prompt, mentions, transition, onSave]);
  useEffect(() => registerSave(group.id, save), [group.id, registerSave, save]);
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
    if (latest?.groups.find(item => item.id === group.id)?.input_fingerprint !== group.input_fingerprint) {
      setEstimate(null); throw new Error("分镜输入已更新，请核对新的合并提示词后重新预览费用");
    }
    const result = await request("/video-generation/estimate", json(parameters));
    setEstimate({ key: confirmationKey, result }); setAcceptUnknown(false);
  });
  const generate = () => act(async () => {
    if (estimate?.key !== confirmationKey) throw new Error("输入已变化，请重新预览费用");
    await request(`/production-shots/${group.anchor_shot_id}/video-runs`, json({ ...parameters,
      expected_revision_id: revision, generation_group_id: group.id, expected_group_fingerprint: group.input_fingerprint,
      execution_mode: "remote_api", audio_strategy: "muted", allow_unknown_cost: acceptUnknown,
      input_plan: group.input_plan,
    }));
    setEstimate(null); await onReload();
  });
  return <details className="video-group" open>
    <summary>生成组 {ordinal} · {group.shot_plan_ids.length} 个成片分镜 · {group.images?.length || 0} 张图 → 1 段视频</summary>
    {group.error ? <p role="alert" className="video-group-error">{group.error}</p> : <>
      <div className="video-group-images">{group.images.map(image => <figure key={image.id}><img src={resolveUrl(image.url)} alt={`本组参考图 ${image.index}`} /><figcaption>图 {image.index}</figcaption></figure>)}</div>
      {group.input_plan.references.some(item => item.reference_kind !== "approved_image") && <p>同时引用：{group.input_plan.references.filter(item => item.reference_kind !== "approved_image").map(item => item.label).join("、")}</p>}
      {conflict && <p role="alert" className="video-group-error">组要求已在其他页面更新。<Button className="text-button" type="button" onClick={() => { setPrompt(group.video_prompt); setMentions(group.video_prompt_mentions || []); setTransition(group.transition); setBaseKey(definitionKey); setEstimate(null); setError(""); }}>放弃本地组要求，读取新内容</Button></p>}
      <div className="production-field"><span>组视频补充要求</span><AssetReferenceEditor label="组视频补充要求" rows={3} maxLength={8000} value={prompt} references={mentions} options={(assets || []).map(asset => promptAssetReference(asset, 'video'))} resolveUrl={resolveUrl} disabled={pending || disabled || Boolean(running)}
        referenceLimit={model?.capabilities?.maximum_reference_images}
        reservedReferenceCount={(group.input_plan?.references || []).filter(item => !mentions.some(mention => mention.reference_kind === item.reference_kind && mention.reference_id === item.reference_id)).length}
        onAddAssets={onAddAssets && ((insert, options) => onAddAssets(selected => insert(selected.map(asset => promptAssetReference(asset, 'video'))), options))}
        onChange={(value, refs) => { setPrompt(value); setMentions(promptMentionData(refs, 'video')); }} placeholder="逐段动作沿用下方分镜提示词；输入 @ 引用本组共同资产。" /></div>
      <div className="video-group-actions"><label>场景切换<select value={transition} disabled={pending || disabled || Boolean(running)} onChange={event => setTransition(event.target.value)}><option value="cut">硬切</option><option value="continuous">连续运动</option><option value="dissolve">叠化</option></select></label><Button type="button" className="secondary-button" disabled={!dirty || pending || disabled || Boolean(running)} onClick={save}>保存组要求</Button></div>
      <details><summary>查看完整分段提示词 · 目标 {Number(group.target_duration_seconds.toFixed(2))} 秒</summary><p className="video-group-script">{group.compiled_prompt}</p></details>
      <div className="video-group-actions">
        <label>视频模型<select value={model?.alias || ""} disabled={pending || Boolean(running)} onChange={event => { const next = models.find(item => item.alias === event.target.value); setAlias(event.target.value); const values = videoDurationOptions(next); setDuration(values.find(value => value >= group.target_duration_seconds) || values.at(-1)); setResolution(preferredVideoResolution(next)); setEstimate(null); }}><option value="" disabled>选择有序多图模型</option>{models.map(item => <option key={item.alias} value={item.alias}>{item.label}</option>)}</select></label>
        <label>生成时长<select value={duration} disabled={pending || Boolean(running)} onChange={event => setDuration(Number(event.target.value))}>{durations.map(value => <option key={value} value={value}>{value} 秒</option>)}</select></label>
        <label>分辨率<select value={resolution} disabled={pending || Boolean(running)} onChange={event => setResolution(event.target.value)}>{(model?.capabilities.supported_resolutions || []).map(value => <option key={value}>{value}</option>)}</select></label>
        <Button type="button" className="primary-button" disabled={!canGenerate} onClick={price}>{pending ? "处理中…" : "预览生成费用"}</Button>
      </div>
      {!model && <p>未配置可用的有序多图模型。请配置模型，或拆组后独立生成再剪辑。</p>}
      {model && (group.input_plan.references.length > model.capabilities.maximum_reference_images || duration < group.target_duration_seconds) && <p className="video-group-error">本组参考数量或总时长超过当前设置，请更换模型、时长或拆组。</p>}
      {estimate?.key === confirmationKey && <div className="video-group-confirm"><p>{estimate.result.estimate_known ? `预计费用 ¥${(estimate.result.estimated_cost_micros / 1000000).toFixed(4)}` : "当前模型无法预估费用，将按供应商实际用量记录"} · 1 段候选视频 · 静音</p>{!estimate.result.estimate_known && <label className="video-group-check"><input type="checkbox" checked={acceptUnknown} onChange={event => setAcceptUnknown(event.target.checked)} />确认接受费用未知</label>}<Button type="button" className="primary-button" disabled={!canGenerate || (!estimate.result.estimate_known && !acceptUnknown)} onClick={generate}>确认费用并生成</Button></div>}
    </>}
    {running && <p role="status">{running.status === "queued" ? "排队中" : "生成中"}，完成后需要核对场景与切点。<Button type="button" variant="warning" size="compact" disabled={pending || disabled || running.status === "cancellation_requested"} onClick={cancel}>{running.status === "cancellation_requested" ? "正在停止…" : "取消任务"}</Button></p>}
    {group.runs?.filter(run => !ACTIVE.has(run.status)).map(run => <details key={run.id}>
      <summary>{run.status === "failed" ? "生成失败" : run.status === "cancelled" ? "已取消" : "生成结果"} · {new Date(run.created_at).toLocaleString("zh-CN")}</summary>
      <p>{run.actual_cost_known ? `已记录费用 ¥${(Number(run.actual_cost_micros || 0) / 1000000).toFixed(4)}` : "实际费用待回传"}</p>
      {run.error_message && <p role="alert">{run.error_message}</p>}
      {(group.error || group.stale_run_ids?.includes(run.id)) && <p className="video-group-error">输入已变化，此历史结果仅供查看，不能按当前分组直接采用。</p>}
      {run.candidates?.filter(candidate => ["ready", "selected"].includes(candidate.status)).map(candidate => group.error
        ? <div className="video-group-review" key={candidate.id}><video controls preload="metadata" src={resolveUrl(candidate.content_url)} aria-label="生成组历史视频（只读）" /></div>
        : <CandidateReview key={candidate.id} candidate={{ ...candidate, content_url: resolveUrl(candidate.content_url) }} group={group} request={request} revision={revision} projectId={projectId} onReload={onReload} disabled={disabled || dirty || Boolean(running) || group.stale_run_ids?.includes(run.id)} />)}
    </details>)}
    {error && <p role="alert" className="video-group-error">{error}</p>}
  </details>;
}

export function VideoGroupsPanel({ project, shots, settings, request, resolveUrl, onChanged, onAdvance, flushRef, beforeGenerate, disabled = false, assets = [], onAddAssets }) {
  const [state, setState] = useState(null), [error, setError] = useState("");
  const [selected, setSelected] = useState([]), [pending, setPending] = useState(false), [suggestions, setSuggestions] = useState([]);
  const [suggested, setSuggested] = useState(false), [dirtyGroups, setDirtyGroups] = useState({});
  const onDirty = useCallback((id, value) => setDirtyGroups(current => current[id] === value ? current : { ...current, [id]: value }), []);
  const unsaved = Object.values(dirtyGroups).some(Boolean);
  const saves = useRef(new Map());
  const registerSave = useCallback((id, save) => { saves.current.set(id, save); return () => saves.current.delete(id); }, []);
  useImperativeHandle(flushRef, () => ({ flush: async () => {
    for (const save of [...saves.current.values()]) if (await save() === false) return false;
    return true;
  } }));
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
    latestState.current = saved; setState(saved); await onChanged();
  }, [project.id, request, state, onChanged]);
  const mutate = async callback => {
    if (operation.current) return;
    if (unsaved) { setError("请先保存已修改的组要求，再合并或拆分。"); return; }
    operation.current = true; setPending(true); setError("");
    try { await callback(); setSelected([]); setSuggestions([]); } catch (failure) { setError(failure.message); }
    finally { operation.current = false; setPending(false); }
  };
  const grouped = new Set(state?.groups.flatMap(group => group.shot_plan_ids) || []);
  const eligible = shots.filter(row => !grouped.has((row.plan || row).id));
  const imageCount = shots.reduce((count, row) => count + ((row.plan || row).visual_beats || []).filter(beat => beat.approved_image_candidate_id).length, 0);
  const addGroups = lists => update([...(state?.groups || []).map(groupDefinition), ...lists.map(ids => ({ id: crypto.randomUUID(), shot_plan_ids: ids, video_prompt: "", transition: "cut" }))]);
  return <section className="video-groups-panel" aria-label="视频生成分组">
    <header><h3>视频生成分组</h3><span>{shots.length} 个成片分镜 · {imageCount} 张已采用图片 · {(state?.groups.length || 0) + eligible.length} 个生成单元</span>{state?.groups.length > 0 && <Button type="button" className="secondary-button" disabled={disabled || pending || running || unsaved} onClick={onAdvance}>进入剪辑</Button>}</header>
    {error && <p role="alert" className="video-group-error">{error}<Button type="button" className="text-button" onClick={load}>重新读取</Button></p>}
    {!state ? <p role="status">正在读取分组…</p> : <>
      <details><summary>合并相邻分镜 / 拆分生成组</summary><p>未分组的镜头仍独立生成。合并不改变成片分镜；拆分保留历史视频。</p>
        <div className="video-group-choices">{eligible.map(row => { const plan = row.plan || row; return <label key={plan.id}><input type="checkbox" disabled={pending || disabled || running} checked={selected.includes(plan.id)} onChange={event => setSelected(ids => event.target.checked ? [...ids, plan.id] : ids.filter(id => id !== plan.id))} />分镜 {plan.index} · {plan.duration_seconds} 秒</label>; })}</div>
        <div className="video-group-actions"><Button type="button" className="secondary-button" disabled={selected.length < 2 || pending || disabled || running} onClick={() => mutate(() => addGroups([eligible.map(row => (row.plan || row).id).filter(id => selected.includes(id))]))}>合并选中分镜</Button><Button type="button" className="text-button" disabled={!models.length || disabled || pending || running} onClick={() => { setSuggestions(suggestedGroups(shots, models[0], grouped)); setSuggested(true); }}>建议短镜头分组</Button></div>
        {suggested && !suggestions.length && <p role="status">没有符合当前模型时长、图片数量限制的相邻短镜头组合，可手动选择或保持独立生成。</p>}
        {suggestions.length > 0 && <div className="video-group-confirm"><p>建议 {suggestions.length} 个生成组：{suggestions.map(ids => ids.map(id => (shots.find(row => (row.plan || row).id === id)?.plan || shots.find(row => row.id === id))?.index).join("、")).join("；")}。确认仅保存分组，不会生成或扣费。</p><Button type="button" className="secondary-button" disabled={pending || disabled || running} onClick={() => mutate(() => addGroups(suggestions))}>确认建议分组</Button></div>}
        {state.groups.map((group, index) => <div className="video-group-actions" key={group.id}><span>生成组 {index + 1} · {group.shot_plan_ids.length} 个分镜</span><Button type="button" className="text-button" disabled={pending || disabled || running} onClick={() => mutate(() => update(state.groups.filter(item => item.id !== group.id).map(groupDefinition)))}>拆为独立生成</Button></div>)}
      </details>
      {state.groups.map((group, index) => <GroupEditor key={group.id} group={group} ordinal={index + 1} models={models} revision={state.expected_revision_id} projectId={project.id} request={request} resolveUrl={resolveUrl} disabled={disabled || pending} assets={assets} onAddAssets={onAddAssets} onReload={reload} onDirty={onDirty} registerSave={registerSave} beforeGenerate={beforeGenerate} onSave={saved => update(latestState.current.groups.map(item => item.id === saved.id ? saved : groupDefinition(item)))} />)}
    </>}
  </section>;
}
