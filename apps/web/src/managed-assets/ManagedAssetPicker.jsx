import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  FolderOpen,
  Gear,
  MagnifyingGlass,
  UserCircle,
  WarningCircle,
  X,
} from "@phosphor-icons/react";

const KIND_OPTIONS = [
  { id: "virtual_person", label: "虚拟人像" },
  { id: "verified_person", label: "已授权真人" },
];

function buildCatalogPath({ kind, groupId, page, query }) {
  const params = new URLSearchParams({
    kind,
    page: String(page),
    page_size: "24",
  });
  if (groupId) params.set("group_id", groupId);
  if (query) params.set("query", query);
  return `/managed-assets/providers/volc_ark/catalog?${params.toString()}`;
}

function assetBinding(asset) {
  return {
    provider: asset.provider,
    asset_id: asset.id,
    group_id: asset.group_id || null,
    kind: asset.kind,
    role: "actor_identity",
    name: asset.name,
    group_name: asset.group_name || null,
    media_type: asset.media_type,
    project_name: asset.project_name,
    status: "active",
    preview_url: asset.preview_url || null,
  };
}

export function ManagedAssetPicker({
  currentBinding,
  initialQuery = "",
  onClose,
  onOpenModelSettings,
  onSelect,
  request,
}) {
  const [kind, setKind] = useState(currentBinding?.kind || "virtual_person");
  const [queryDraft, setQueryDraft] = useState(initialQuery);
  const [query, setQuery] = useState(initialQuery);
  const [groupId, setGroupId] = useState("");
  const [page, setPage] = useState(1);
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    request(buildCatalogPath({ kind, groupId, page, query }))
      .then((payload) => {
        if (!cancelled) setCatalog(payload);
      })
      .catch((requestError) => {
        if (!cancelled) setError(requestError);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [groupId, kind, page, query, request]);

  const totalPages = Math.max(1, Math.ceil(Number(catalog?.total || 0) / 24));
  const assets = catalog?.assets || [];
  const selectedId = currentBinding?.asset_id || "";
  const title = useMemo(
    () => KIND_OPTIONS.find((item) => item.id === kind)?.label || "人物资产",
    [kind],
  );

  function changeKind(nextKind) {
    setKind(nextKind);
    setGroupId("");
    setPage(1);
  }

  function submitSearch(event) {
    event.preventDefault();
    setQuery(queryDraft.trim());
    setPage(1);
  }

  return (
    <div className="managed-asset-picker-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <aside aria-labelledby="managed-asset-picker-title" aria-modal="true" className="managed-asset-picker" role="dialog">
        <header className="managed-asset-picker-header">
          <div>
            <span>火山方舟资产目录</span>
            <h3 id="managed-asset-picker-title">选择演员身份</h3>
            <p>目录由 Provider 返回；ViralDNA 不要求手动输入资产 ID。</p>
          </div>
          <button aria-label="关闭" className="icon-button" onClick={onClose} type="button"><X size={20} /></button>
        </header>

        <div className="managed-asset-kind-tabs" role="tablist" aria-label="资产类型">
          {KIND_OPTIONS.map((item) => (
            <button
              aria-selected={kind === item.id}
              className={kind === item.id ? "active" : ""}
              key={item.id}
              onClick={() => changeKind(item.id)}
              role="tab"
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>

        <form className="managed-asset-search" onSubmit={submitSearch}>
          <MagnifyingGlass size={18} />
          <input
            aria-label="搜索 Provider 资产"
            onChange={(event) => setQueryDraft(event.target.value)}
            placeholder={`搜索${title}名称`}
            value={queryDraft}
          />
          <button className="secondary-button compact" type="submit">搜索</button>
        </form>

        <div className="managed-asset-picker-body">
          <nav aria-label="Provider 资产目录" className="managed-asset-group-list">
            <button className={!groupId ? "active" : ""} onClick={() => { setGroupId(""); setPage(1); }} type="button">
              <FolderOpen size={17} />全部
              <span>{catalog?.total ?? "—"}</span>
            </button>
            {(catalog?.groups || []).map((group) => (
              <button className={groupId === group.id ? "active" : ""} key={group.id} onClick={() => { setGroupId(group.id); setPage(1); }} type="button">
                <FolderOpen size={17} />
                <span className="managed-asset-group-name">{group.name}</span>
              </button>
            ))}
          </nav>

          <section className="managed-asset-catalog-results" aria-live="polite">
            {loading ? (
              <div className="managed-asset-loading-grid" aria-label="正在加载资产目录">
                {Array.from({ length: 8 }, (_, index) => <span key={index} />)}
              </div>
            ) : error ? (
              <div className="managed-asset-picker-state error" role="alert">
                <WarningCircle size={28} weight="duotone" />
                <strong>无法读取火山方舟资产目录</strong>
                <p>{error.message}</p>
                <button className="secondary-button compact" onClick={() => { onClose(); onOpenModelSettings?.(); }} type="button">
                  <Gear size={16} />打开模型与设置
                </button>
              </div>
            ) : assets.length === 0 ? (
              <div className="managed-asset-picker-state">
                <UserCircle size={30} weight="duotone" />
                <strong>当前目录没有可用的{title}</strong>
                <p>请在火山方舟控制台创建资产，并等待状态变为 Active。</p>
              </div>
            ) : (
              <div className="managed-asset-grid">
                {assets.map((asset) => (
                  <button
                    aria-pressed={selectedId === asset.id}
                    className={selectedId === asset.id ? "selected" : ""}
                    key={asset.id}
                    onClick={() => onSelect(assetBinding(asset))}
                    type="button"
                  >
                    <span className="managed-asset-grid-preview">
                      {asset.preview_url ? <img alt="" loading="lazy" src={asset.preview_url} /> : <UserCircle size={32} weight="duotone" />}
                      {selectedId === asset.id && <i><Check size={14} weight="bold" /></i>}
                    </span>
                    <strong>{asset.name}</strong>
                    <small>{asset.group_name || "未分组"} · {asset.media_type === "video" ? "视频" : "图片"}</small>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>

        {!loading && !error && totalPages > 1 && (
          <footer className="managed-asset-picker-pagination">
            <span>第 {page} / {totalPages} 页 · 共 {catalog?.total || 0} 个</span>
            <div>
              <button aria-label="上一页" className="icon-button" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))} type="button"><ArrowLeft size={17} /></button>
              <button aria-label="下一页" className="icon-button" disabled={page >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))} type="button"><ArrowRight size={17} /></button>
            </div>
          </footer>
        )}
      </aside>
    </div>
  );
}
