import { useEffect, useRef, useState } from 'react';

// Only mounted after the user explicitly opens the library. Automatic matching
// never calls this list endpoint; it receives the selected-ID endpoint instead.
export function PromptAssetPicker({ request, resolveUrl, selectedIds = [], onClose, onSelect }) {
  const dialog = useRef(null);
  const [workspaceId, setWorkspaceId] = useState(null);
  const [items, setItems] = useState([]);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const displayedItems = items.filter((item) => item.media_kind === 'image' && item.type !== 'logo');
  useEffect(() => {
    dialog.current.showModal();
    request('/context').then((context) => setWorkspaceId(context.active_workspace.id))
      .catch((failure) => { setError(failure.message); setLoading(false); });
  }, [request]);
  useEffect(() => {
    if (!workspaceId) return undefined;
    let current = true;
    setLoading(true);
    const timer = setTimeout(() => {
      request(`/workspaces/${workspaceId}/assets?page=${page}&page_size=30&query=${encodeURIComponent(query)}`)
        .then((result) => { if (current) { setItems(result.items || []); setTotal(result.total || 0); setError(''); } })
        .catch((failure) => { if (current) setError(failure.message); })
        .finally(() => { if (current) setLoading(false); });
    }, 250);
    return () => { current = false; clearTimeout(timer); };
  }, [workspaceId, query, page, request]);
  return <dialog ref={dialog} className="prompt-asset-picker" onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><h3>添加项目资产</h3><button className="secondary-button compact" type="button" disabled={busy} onClick={onClose}>关闭</button></header>
    <input aria-label="搜索资产库" placeholder="搜索资产名称" value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} />
    {error && <p role="alert">{error}</p>}
    {loading ? <p role="status">正在读取资产…</p> : <div className="prompt-asset-picker-list">
      {displayedItems.map((asset) => <button type="button" key={asset.id}
        disabled={busy || selectedIds.includes(asset.id) || !asset.rights_confirmed}
        onClick={async () => { setBusy(true); try { await onSelect(asset); } catch (failure) { setError(failure.message); } finally { setBusy(false); } }}>
        <img src={resolveUrl?.(asset.thumbnail_url) || asset.thumbnail_url} loading="lazy" alt="" onError={(event) => { event.currentTarget.hidden = true; }} />
        <span><strong>{asset.name}</strong><small>{asset.folder_name || '未分类'}{selectedIds.includes(asset.id) ? ' · 已加入项目' : ''}</small></span>
      </button>)}
      {!displayedItems.length && <p>本页没有可引用的图片资产，可更换搜索词或翻页。</p>}
    </div>}
    <footer><button className="secondary-button compact" disabled={page === 1 || busy} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} 页</span><button className="secondary-button compact" disabled={page * 30 >= total || busy} onClick={() => setPage(page + 1)}>下一页</button></footer>
  </dialog>;
}
