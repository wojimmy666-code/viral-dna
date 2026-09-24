import { useEffect, useId, useRef, useState } from 'react';
import { Check, FolderSimple, ImageSquare, MagnifyingGlass, X } from '@phosphor-icons/react';
import { Button, IconButton } from '../ui/system/Button.jsx';
import { ASSET_TYPE_OPTIONS, buildAssetListQuery } from '../asset-library-ui.js';
import './asset-reference-editor.css';

// Selection stays local until Confirm. selectedIds means referenced by this
// prompt, not just associated with its project. Re-insertion is allowed.
export function PromptAssetPicker({ request, resolveUrl, selectedIds = [], onClose, onSelect,
  initialQuery = '', referenceLimit, reservedReferenceCount = 0, maxSelection }) {
  const dialog = useRef(null);
  const mounted = useRef(true);
  const titleId = useId();
  const [workspaceId, setWorkspaceId] = useState(null);
  const [folders, setFolders] = useState([]);
  const [folderId, setFolderId] = useState('');
  const [items, setItems] = useState([]);
  const [query, setQuery] = useState(initialQuery.slice(0, 120));
  const [type, setType] = useState('');
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [selection, setSelection] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const existing = new Set(selectedIds);
  const newCount = selection.filter((item) => !existing.has(item.id)).length;
  const usedCount = existing.size + reservedReferenceCount;
  const overLimit = Number.isFinite(referenceLimit) && usedCount + newCount > referenceLimit;
  const folder = folders.find((item) => item.id === folderId);
  const home = !folderId && !query.trim() && !type;

  useEffect(() => {
    mounted.current = true;
    const previous = document.activeElement;
    if (!dialog.current.open) dialog.current.showModal();
    dialog.current.querySelector('input')?.focus({ preventScroll: true });
    return () => { mounted.current = false; if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => {
    let active = true;
    if (workspaceId) return undefined;
    setLoading(true); setError('');
    request('/context').then(async (context) => {
      const id = context.active_workspace?.id;
      if (!id) throw new Error('当前账户的资产库不可用，请重新登录后重试。');
      const result = await request(`/workspaces/${id}/asset-folders`);
      if (active) { setFolders(Array.isArray(result) ? result : result.items || []); setWorkspaceId(id); }
    }).catch((failure) => { if (active) { setError(failure.message); setLoading(false); } });
    return () => { active = false; };
  }, [request, workspaceId, retry]);
  useEffect(() => {
    if (!workspaceId) return undefined;
    let active = true;
    setLoading(true); setError('');
    const timer = setTimeout(() => {
      const params = buildAssetListQuery({ page, pageSize: 24, query, type, folderId: home ? 'unfiled' : folderId });
      request(`/workspaces/${workspaceId}/assets?${params}&prompt_images_only=true`)
        .then((result) => {
          if (!active) return;
          setItems((result.items || []).filter((item) => item.media_kind === 'image' && item.type !== 'logo'));
          setPages(Math.max(1, result.total_pages ?? Math.ceil((result.total || 0) / 24)));
          if (result.page && result.page !== page) setPage(result.page);
        })
        .catch((failure) => { if (active) setError(failure.message); })
        .finally(() => { if (active) setLoading(false); });
    }, 200);
    return () => { active = false; clearTimeout(timer); };
  }, [workspaceId, query, type, folderId, home, page, request, retry]);

  function navigate(id) { setFolderId(id); setQuery(''); setPage(1); }
  function toggle(asset) {
    setError('');
    setSelection((current) => current.some((item) => item.id === asset.id)
      ? current.filter((item) => item.id !== asset.id) : [...current, asset]);
  }
  async function confirm() {
    if (busy || !selection.length || overLimit) return;
    setBusy(true); setError('');
    try { await onSelect(selection); }
    catch (failure) { if (mounted.current) setError(failure.message || '引用失败，选择已保留，请重试。'); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <dialog ref={dialog} className="prompt-asset-picker" aria-labelledby={titleId}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><h2 id={titleId}>引用资产</h2><IconButton label="关闭资产库" disabled={busy} onClick={onClose}><X size={20} /></IconButton></header>
    <div className="prompt-asset-picker-body">
      <nav className="prompt-asset-picker-sidebar" aria-label="资产库目录">
        <Button variant="quiet" icon={<FolderSimple size={20} />} aria-current={!folderId ? 'page' : undefined} disabled={busy} onClick={() => navigate('')}>本账户资产库</Button>
        <Button variant="quiet" aria-current={folderId === 'unfiled' ? 'page' : undefined} disabled={busy} onClick={() => navigate('unfiled')}>未分类资产</Button>
      </nav>
      <section className="prompt-asset-picker-main" aria-label="可引用的资产">
        <div className="prompt-asset-picker-toolbar">
          <nav className="prompt-asset-breadcrumb" aria-label="当前目录"><Button variant="quiet" size="compact" disabled={busy} onClick={() => navigate('')}>本账户资产库</Button>{folderId && <span> / {folder?.name || '未分类资产'}</span>}</nav>
          <div className="prompt-asset-picker-filters">
            <div className="prompt-asset-search"><MagnifyingGlass size={18} aria-hidden="true" /><input autoFocus aria-label="搜索资产库" maxLength={120} placeholder="搜索资产名称" disabled={busy} value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} /></div>
            <select aria-label="资产类型" value={type} disabled={busy} onChange={(event) => { setType(event.target.value); setPage(1); }}><option value="">全部类型</option>{ASSET_TYPE_OPTIONS.filter((item) => !['logo', 'motion_reference'].includes(item.value)).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
          </div>
        </div>
        {error && <div className="prompt-asset-picker-error" role="alert"><span>{error}</span>{!busy && <Button variant="quiet" size="compact" onClick={() => setRetry((value) => value + 1)}>重新读取</Button>}</div>}
        <div className="prompt-asset-picker-grid" aria-busy={loading}>
          {home && folders.map((item) => <button data-ui="selection-card" type="button" className="prompt-asset-tile" key={item.id} disabled={busy} onClick={() => navigate(item.id)}>
            <span className="prompt-asset-tile-image folder"><FolderSimple size={64} weight="duotone" /></span><strong>{item.name}</strong><small>文件夹</small>
          </button>)}
          {loading ? <p role="status">正在读取资产…</p> : items.map((asset) => {
            const chosen = selection.some((item) => item.id === asset.id);
            const unavailable = !asset.rights_confirmed || asset.archived_at || asset.sync_state === 'unavailable';
            const limitReached = !chosen && ((maxSelection && selection.length >= maxSelection)
              || (Number.isFinite(referenceLimit) && !existing.has(asset.id) && usedCount + newCount >= referenceLimit));
            return <button data-ui="selection-card" type="button" className="prompt-asset-tile" key={asset.id} aria-pressed={chosen}
              disabled={busy || Boolean(unavailable) || Boolean(limitReached)} onClick={() => toggle(asset)}>
              <span className="prompt-asset-tile-image"><ImageSquare size={32} />{asset.thumbnail_url && <img src={resolveUrl?.(asset.thumbnail_url) || asset.thumbnail_url} loading="lazy" alt="" onError={(event) => { event.currentTarget.hidden = true; }} />}<span className="prompt-asset-check" aria-hidden="true">{chosen && <Check size={16} weight="bold" />}</span></span>
              <strong>{asset.name}</strong><small>{unavailable ? !asset.rights_confirmed ? '尚未确认使用权' : '资产暂不可用' : existing.has(asset.id) ? '已引用 · 可再次插入' : asset.folder_name || '未分类'}</small>
            </button>;
          })}
          {!loading && !items.length && !(home && folders.length) && <p className="prompt-asset-empty">没有可引用的图片资产。可更换目录或搜索词；Logo 请使用专用入口。</p>}
        </div>
        {pages > 1 && <div className="prompt-asset-pagination"><Button size="compact" disabled={loading || busy || page === 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page} / {pages}</span><Button size="compact" disabled={loading || busy || page >= pages} onClick={() => setPage(page + 1)}>下一页</Button></div>}
      </section>
    </div>
    <footer><div role="status"><span>已选择 {selection.length} 项</span><small>{Number.isFinite(referenceLimit) ? `当前已用 ${usedCount} / 上限 ${referenceLimit} 项` : '仅列出可用作图片参考的资产'}{overLimit && ' · 超出当前模型上限'}</small></div><div className="prompt-asset-picker-actions"><Button disabled={busy} onClick={onClose}>取消</Button><Button variant="primary" loading={busy} loadingLabel="正在引用…" disabled={!selection.length || overLimit} onClick={confirm}>确认引用</Button></div></footer>
  </dialog>;
}
