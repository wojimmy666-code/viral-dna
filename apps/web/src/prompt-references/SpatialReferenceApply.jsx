import { useEffect, useId, useRef, useState } from 'react';
import { X } from '@phosphor-icons/react';
import { Button, IconButton } from '../ui/system/Button.jsx';

export function SpatialReferenceApply({ projectId, beatId, reference, request, beforeLoad, onSaved, onClose, disabled }) {
  const dialog = useRef(null), mounted = useRef(false), pending = useRef(false);
  const titleId = useId();
  const [state, setState] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [scope, setScope] = useState('current'), [selected, setSelected] = useState([beatId]), [replace, setReplace] = useState(false);
  const id = reference.reference_asset_id;
  const targets = (state?.targets || []).filter(item => scope === 'all' || (scope === 'current' ? item.id === beatId : selected.includes(item.id)));
  const conflicts = targets.filter(item => item.spatial_reference_ids.some(value => value !== id));
  const guided = targets.filter(item => item.has_composition);
  async function load() {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError('');
    try {
      if (await beforeLoad?.() === false) throw new Error('请先保存当前提示词，再应用空间参考。');
      const result = await request(`/productions/${projectId}/spatial-references`);
      if (mounted.current) { setState(result); setReplace(false); }
    } catch (failure) { if (mounted.current) setError(failure.message); }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  }
  useEffect(() => {
    mounted.current = true; const previous = document.activeElement;
    dialog.current.showModal(); void load();
    return () => { mounted.current = false; if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, []);
  async function apply() {
    if (pending.current || disabled || !state || !targets.length || guided.length || (conflicts.length && !replace)) return;
    pending.current = true; setBusy(true); setError('');
    try {
      await request(`/productions/${projectId}/spatial-references`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        expected_revision_id: state.revision_id, expected_context_id: state.context_id,
        reference_asset_id: id, visual_beat_ids: targets.map(item => item.id), replace_existing: replace,
      }) });
      if (!mounted.current) return;
      await onSaved([...new Set(targets.map(item => item.shot_id))]);
      onClose();
    } catch (failure) { if (mounted.current) setError(`${failure.message} 请重新读取状态后核对，不会自动重试。`); }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  }
  return <dialog ref={dialog} className="spatial-reference-dialog" aria-labelledby={titleId} onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><h2 id={titleId}>应用空间参考</h2><IconButton label="关闭空间参考应用" disabled={busy} onClick={onClose}><X size={20} /></IconButton></header>
    <div className="spatial-reference-dialog-body">
      <p>{reference.label}</p><p>只更新参考配置，不生成图片，不覆盖素材，也不改变采用状态。</p>
      {error && <div role="alert"><p>{error}</p><Button variant="quiet" disabled={busy} onClick={load}>重新读取状态</Button></div>}
      {!state && busy && <p role="status">正在读取画面…</p>}
      {state && <>
        <label className="reference-purpose-field">应用范围<select aria-label="空间参考应用范围" disabled={busy || disabled} value={scope} onChange={event => { setScope(event.target.value); setReplace(false); }}><option value="current">仅当前画面</option><option value="selected">指定画面</option><option value="all">全部现有画面</option></select></label>
        {scope === 'selected' && <fieldset className="spatial-reference-targets" disabled={busy || disabled}><legend>选择画面</legend>{state.targets.map(item => <label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} onChange={event => { setSelected(current => event.target.checked ? [...current, item.id] : current.filter(id => id !== item.id)); setReplace(false); }} /><span>{item.label}{item.spatial_reference_ids.length ? ' · 已有空间参考' : ''}</span></label>)}</fieldset>}
        <p role="status">将更新 {targets.length} 个画面</p>
        {guided.length > 0 && <p role="alert">{guided.map(item => item.label).join('、')} 已启用构图引导。请先关闭该窗口并停用对应构图，再应用空间参考。</p>}
        {conflicts.length > 0 && <label className="spatial-reference-confirm"><input type="checkbox" disabled={busy || disabled} checked={replace} onChange={event => setReplace(event.target.checked)} /><span>确认替换 {conflicts.length} 个画面已有的空间参考，仅移除旧引用，原资产保留。</span></label>}
      </>}
    </div>
    <footer><Button disabled={busy} onClick={onClose}>取消</Button><Button variant="primary" loading={busy} loadingLabel="处理中…" disabled={disabled || !state || !targets.length || Boolean(guided.length) || (Boolean(conflicts.length) && !replace)} onClick={apply}>应用到 {targets.length} 个画面</Button></footer>
  </dialog>;
}
