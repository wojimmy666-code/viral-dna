import { useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ArrowClockwise,
  CaretLeft,
  CaretRight,
  Check,
  CircleNotch,
  DotsThree,
  DownloadSimple,
  Folder,
  FolderOpen,
  FolderPlus,
  HardDrive,
  ImageSquare,
  MagnifyingGlass,
  PencilSimple,
  Plus,
  ShieldCheck,
  Trash,
  UploadSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  ASSET_PAGE_SIZES,
  ASSET_TYPE_LABELS,
  ASSET_TYPE_OPTIONS,
  STORAGE_STATE_LABELS,
  assetLibraryView,
  assetListFolderForView,
  buildAssetListQuery,
  buildAssetPaginationItems,
  buildPostUploadView,
  formatAssetDate,
  formatAssetSize,
  normalizeAssetTags,
} from "./asset-library-ui.js";
import "./asset-library.css";

const EMPTY_LIST = Object.freeze({ items: [], page: 1, page_size: 20, total: 0, total_pages: 0 });
const EMPTY_UPLOAD = Object.freeze({
  name: "",
  type: "person",
  folderId: "",
  description: "",
  tags: "",
  rightsNote: "",
  rightsConfirmed: false,
});

function useObjectUrl(file) {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : ""), [file]);
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);
  return url;
}

function AssetThumbnail({ asset, resolveUrl, eager = false, useOriginal = false, alt = "" }) {
  const [failed, setFailed] = useState(false);
  const source = resolveUrl(useOriginal ? asset.content_url : asset.thumbnail_url);

  useEffect(() => setFailed(false), [source]);

  return (
    <span className={`asset-thumbnail ${failed ? "failed" : ""}`}>
      {!failed && source ? (
        <img
          alt={alt}
          decoding="async"
          loading={eager ? "eager" : "lazy"}
          onError={() => setFailed(true)}
          src={source}
        />
      ) : (
        <span className="asset-thumbnail-fallback" aria-hidden="true">
          <ImageSquare size={28} />
        </span>
      )}
    </span>
  );
}

function StorageBadge({ asset, compact = false }) {
  const state = asset.sync_state || "unavailable";
  return (
    <span className={`asset-storage-badge ${state} ${compact ? "compact" : ""}`}>
      <HardDrive size={compact ? 11 : 13} weight="fill" />
      {STORAGE_STATE_LABELS[state] || state}
    </span>
  );
}

function FolderCover({ cover, resolveUrl }) {
  const [failed, setFailed] = useState(false);
  const source = cover?.thumbnail_url ? resolveUrl(cover.thumbnail_url) : "";

  useEffect(() => setFailed(false), [source]);

  if (!source || failed) {
    return (
      <span className="asset-folder-card-placeholder" aria-hidden="true">
        <FolderOpen size={30} />
      </span>
    );
  }
  return <img alt="" decoding="async" loading="lazy" onError={() => setFailed(true)} src={source} />;
}

function Modal({ children, label, onClose, size = "default" }) {
  return (
    <div
      className="asset-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        aria-label={label}
        aria-modal="true"
        className={`asset-modal ${size === "compact" ? "compact" : ""}`}
        role="dialog"
      >
        {children}
      </section>
    </div>
  );
}

export function AssetLibrary({ request, resolveUrl, onNotice }) {
  const [context, setContext] = useState(null);
  const [folders, setFolders] = useState([]);
  const [assetList, setAssetList] = useState(EMPTY_LIST);
  const [selectedFolder, setSelectedFolder] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [storageFilter, setStorageFilter] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedAsset, setSelectedAsset] = useState(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadDraft, setUploadDraft] = useState(EMPTY_UPLOAD);
  const [uploading, setUploading] = useState(false);
  const [folderDialog, setFolderDialog] = useState(null);
  const [folderSaving, setFolderSaving] = useState(false);
  const [coverDialog, setCoverDialog] = useState(null);
  const [coverSaving, setCoverSaving] = useState(false);
  const [detailDraft, setDetailDraft] = useState(null);
  const [detailSaving, setDetailSaving] = useState(false);
  const [listRefreshToken, setListRefreshToken] = useState(0);
  const [justCreatedAssetId, setJustCreatedAssetId] = useState(null);
  const listRequestRef = useRef(0);
  const assetCardRefs = useRef(new Map());
  const uploadPreview = useObjectUrl(uploadFile);
  const workspaceId = context?.active_workspace?.id || "";
  const workspaceName = context?.active_workspace?.name || "主工作区";
  const localLocation = context?.storage_locations?.find(
    (item) => item.provider_type === "local_filesystem",
  );
  const browserView = assetLibraryView({
    folderId: selectedFolder,
    type: typeFilter,
    query,
    storageState: storageFilter,
    includeArchived,
  });
  const listFolderId = assetListFolderForView({
    folderId: selectedFolder,
    type: typeFilter,
    query,
    storageState: storageFilter,
    includeArchived,
  });
  const homeMode = browserView === "home";

  useEffect(() => {
    let active = true;
    setLoading(true);
    request("/context")
      .then((payload) => {
        if (active) setContext(payload);
      })
      .catch((requestError) => {
        if (active) setError(requestError.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [request]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPage(1);
      setQuery(searchInput);
    }, 240);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    if (!workspaceId) return undefined;
    let active = true;
    request(`/workspaces/${workspaceId}/asset-folders`)
      .then((payload) => {
        if (active) setFolders(payload || []);
      })
      .catch((requestError) => {
        if (active) setError(requestError.message);
      });
    return () => {
      active = false;
    };
  }, [request, workspaceId]);

  useEffect(() => {
    if (!workspaceId) return undefined;
    const requestId = ++listRequestRef.current;
    const parameters = buildAssetListQuery({
      page,
      pageSize,
      folderId: listFolderId,
      type: typeFilter,
      query,
      storageState: storageFilter,
      includeArchived,
    });
    setLoading(true);
    setError("");
    request(`/workspaces/${workspaceId}/assets?${parameters}`)
      .then((payload) => {
        if (requestId !== listRequestRef.current) return;
        setAssetList(payload);
        if (payload.page !== page) setPage(payload.page);
        setSelectedAsset((current) => {
          if (!current) return current;
          return payload.items.find((item) => item.id === current.id) || current;
        });
      })
      .catch((requestError) => {
        if (requestId === listRequestRef.current) setError(requestError.message);
      })
      .finally(() => {
        if (requestId === listRequestRef.current) setLoading(false);
      });
    return undefined;
  }, [
    request,
    workspaceId,
    page,
    pageSize,
    listFolderId,
    typeFilter,
    query,
    storageFilter,
    includeArchived,
    listRefreshToken,
  ]);

  useEffect(() => {
    if (!justCreatedAssetId) return undefined;
    const card = assetCardRefs.current.get(justCreatedAssetId);
    if (!card) return undefined;
    card.focus({ preventScroll: true });
    card.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
    const timer = window.setTimeout(() => setJustCreatedAssetId(null), 2400);
    return () => window.clearTimeout(timer);
  }, [assetList.items, justCreatedAssetId]);

  useEffect(() => {
    if (!selectedAsset) {
      setDetailDraft(null);
      return;
    }
    setDetailDraft({
      name: selectedAsset.name,
      type: selectedAsset.type,
      folderId: selectedAsset.folder_id || "",
      description: selectedAsset.description || "",
      tags: (selectedAsset.tags || []).join("，"),
      rightsConfirmed: selectedAsset.rights_confirmed,
      rightsNote: selectedAsset.rights_note || "",
    });
  }, [selectedAsset]);

  async function refreshFolders() {
    if (!workspaceId) return;
    const payload = await request(`/workspaces/${workspaceId}/asset-folders`);
    setFolders(payload || []);
  }

  async function refreshAssets({ selectId = null } = {}) {
    if (!workspaceId) return;
    const parameters = buildAssetListQuery({
      page,
      pageSize,
      folderId: listFolderId,
      type: typeFilter,
      query,
      storageState: storageFilter,
      includeArchived,
    });
    const payload = await request(`/workspaces/${workspaceId}/assets?${parameters}`);
    setAssetList(payload);
    if (payload.page !== page) setPage(payload.page);
    if (selectId) {
      const fresh = payload.items.find((item) => item.id === selectId)
        || await request(`/assets/${selectId}`);
      setSelectedAsset(fresh);
    } else if (selectedAsset) {
      const fresh = payload.items.find((item) => item.id === selectedAsset.id);
      if (fresh) setSelectedAsset(fresh);
    }
  }

  function changeFolder(folderId) {
    setSelectedFolder(folderId);
    setSelectedAsset(null);
    setPage(1);
  }

  function changeFilter(setter, value) {
    setter(value);
    setPage(1);
  }

  function openUpload() {
    setUploadFile(null);
    setUploadDraft({
      ...EMPTY_UPLOAD,
      folderId: selectedFolder && selectedFolder !== "unfiled" ? selectedFolder : "",
    });
    setError("");
    setUploadOpen(true);
  }

  function chooseUploadFile(file) {
    setUploadFile(file || null);
    if (file && !uploadDraft.name) {
      setUploadDraft((current) => ({
        ...current,
        name: file.name.replace(/\.[^.]+$/, "").slice(0, 120),
      }));
    }
  }

  async function submitUpload(event) {
    event.preventDefault();
    if (!uploadFile) {
      setError("请选择一张资产图片");
      return;
    }
    if (!uploadDraft.rightsConfirmed) {
      setError("请先确认拥有该资产的使用权");
      return;
    }
    setUploading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", uploadFile);
      form.append("type", uploadDraft.type);
      form.append("name", uploadDraft.name.trim());
      if (uploadDraft.folderId) form.append("folder_id", uploadDraft.folderId);
      form.append("description", uploadDraft.description.trim());
      form.append("tags", normalizeAssetTags(uploadDraft.tags).join(","));
      form.append("rights_confirmed", "true");
      form.append("rights_note", uploadDraft.rightsNote.trim());
      form.append("storage_policy", "local_only");
      if (localLocation?.id) form.append("target_location_id", localLocation.id);
      const created = await request(`/workspaces/${workspaceId}/assets`, {
        method: "POST",
        body: form,
      });
      const nextView = buildPostUploadView(created);
      setUploadOpen(false);
      setUploadFile(null);
      setSelectedAsset(null);
      setSelectedFolder(nextView.folderId);
      setSearchInput(nextView.query);
      setQuery(nextView.query);
      setTypeFilter(nextView.type);
      setStorageFilter(nextView.storageState);
      setIncludeArchived(nextView.includeArchived);
      setPage(nextView.page);
      setJustCreatedAssetId(created.id);
      setListRefreshToken((current) => current + 1);
      await refreshFolders();
      onNotice?.("资产已上传，并显示在列表中");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setUploading(false);
    }
  }

  async function saveFolder(event) {
    event.preventDefault();
    const name = folderDialog?.name.trim();
    if (!name) return;
    setFolderSaving(true);
    setError("");
    try {
      if (folderDialog.folder) {
        await request(`/asset-folders/${folderDialog.folder.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_version: folderDialog.folder.version,
            name,
          }),
        });
        onNotice?.("目录名称已更新");
      } else {
        await request(`/workspaces/${workspaceId}/asset-folders`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
        onNotice?.("资产目录已创建");
      }
      setFolderDialog(null);
      await refreshFolders();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setFolderSaving(false);
    }
  }

  async function openCoverPicker(folder) {
    setCoverDialog({
      folder,
      items: [],
      loading: true,
      selectedAssetId: folder.cover?.source === "manual"
        ? folder.cover.asset_id || ""
        : "",
      error: "",
    });
    try {
      const parameters = buildAssetListQuery({
        page: 1,
        pageSize: 100,
        folderId: folder.id,
      });
      const payload = await request(`/workspaces/${workspaceId}/assets?${parameters}`);
      let items = payload.items || [];
      const manualCoverId = folder.cover?.source === "manual" ? folder.cover.asset_id : "";
      if (manualCoverId && !items.some((item) => item.id === manualCoverId)) {
        const manualCover = await request(`/assets/${manualCoverId}`);
        items = [manualCover, ...items];
      }
      setCoverDialog((current) => (
        current?.folder.id === folder.id
          ? { ...current, items, loading: false }
          : current
      ));
    } catch (requestError) {
      setCoverDialog((current) => (
        current?.folder.id === folder.id
          ? { ...current, error: requestError.message, loading: false }
          : current
      ));
    }
  }

  async function updateFolderCover(folder, coverAssetId) {
    setCoverSaving(true);
    try {
      const updated = await request(`/asset-folders/${folder.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_version: folder.version,
          cover_asset_id: coverAssetId || null,
        }),
      });
      setFolders((current) => current.map((item) => (
        item.id === updated.id ? updated : item
      )));
      return updated;
    } finally {
      setCoverSaving(false);
    }
  }

  async function saveFolderCover(event) {
    event.preventDefault();
    if (!coverDialog) return;
    setCoverDialog((current) => ({ ...current, error: "" }));
    try {
      await updateFolderCover(coverDialog.folder, coverDialog.selectedAssetId);
      setCoverDialog(null);
      onNotice?.(coverDialog.selectedAssetId ? "目录封面已更新" : "目录已恢复自动封面");
    } catch (requestError) {
      setCoverDialog((current) => ({ ...current, error: requestError.message }));
    }
  }

  async function setSelectedAssetAsCover() {
    if (!selectedAsset?.folder_id) return;
    const folder = folders.find((item) => item.id === selectedAsset.folder_id);
    if (!folder) return;
    setError("");
    try {
      await updateFolderCover(folder, selectedAsset.id);
      onNotice?.("已设为目录封面");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function restoreAutomaticCover(folder) {
    setError("");
    try {
      await updateFolderCover(folder, "");
      onNotice?.("目录已恢复自动封面");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function deleteFolder(folder) {
    const hasAssets = folder.asset_count > 0;
    const accepted = window.confirm(
      hasAssets
        ? `“${folder.name}”中有 ${folder.asset_count} 个资产。删除目录并将资产移到未分类吗？`
        : `确定删除目录“${folder.name}”吗？`,
    );
    if (!accepted) return;
    setError("");
    try {
      await request(
        `/asset-folders/${folder.id}?move_assets_to_unfiled=${hasAssets ? "true" : "false"}`,
        { method: "DELETE" },
      );
      if (selectedFolder === folder.id) changeFolder("unfiled");
      if (selectedAsset?.folder_id === folder.id) {
        setSelectedAsset((current) => ({ ...current, folder_id: null, folder_name: null }));
      }
      await Promise.all([refreshFolders(), refreshAssets()]);
      onNotice?.(hasAssets ? "目录已删除，资产已移到未分类" : "目录已删除");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function saveAssetDetail(event) {
    event.preventDefault();
    if (!selectedAsset || !detailDraft) return;
    setDetailSaving(true);
    setError("");
    try {
      const updated = await request(`/assets/${selectedAsset.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_version: selectedAsset.version,
          name: detailDraft.name.trim(),
          type: detailDraft.type,
          folder_id: detailDraft.folderId || null,
          description: detailDraft.description.trim(),
          tags: normalizeAssetTags(detailDraft.tags),
          rights_confirmed: detailDraft.rightsConfirmed,
          rights_note: detailDraft.rightsNote.trim() || null,
        }),
      });
      setSelectedAsset(updated);
      await Promise.all([refreshFolders(), refreshAssets()]);
      onNotice?.("资产信息已更新");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setDetailSaving(false);
    }
  }

  async function toggleArchive() {
    if (!selectedAsset) return;
    const restoring = Boolean(selectedAsset.archived_at);
    if (!restoring && !window.confirm(`确定归档资产“${selectedAsset.name}”吗？`)) return;
    setDetailSaving(true);
    setError("");
    try {
      const updated = await request(
        restoring ? `/assets/${selectedAsset.id}/restore` : `/assets/${selectedAsset.id}`,
        { method: restoring ? "POST" : "DELETE" },
      );
      await Promise.all([refreshFolders(), refreshAssets()]);
      setSelectedAsset(restoring || includeArchived ? updated : null);
      onNotice?.(restoring ? "资产已恢复" : "资产已归档");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setDetailSaving(false);
    }
  }

  const paginationItems = buildAssetPaginationItems(assetList.page, assetList.total_pages);
  const activeFolderName = selectedFolder === "unfiled"
    ? "未分类"
    : selectedFolder
      ? folders.find((item) => item.id === selectedFolder)?.name || "资产目录"
      : browserView === "search"
        ? "搜索结果"
        : "全部资产";
  const resultStart = assetList.total ? (assetList.page - 1) * assetList.page_size + 1 : 0;
  const resultEnd = Math.min(assetList.page * assetList.page_size, assetList.total);

  function renderAssetGrid() {
    return (
      <div className="asset-grid" aria-busy={loading}>
        {assetList.items.map((asset, index) => (
          <button
            className={`asset-card ${selectedAsset?.id === asset.id ? "selected" : ""} ${justCreatedAssetId === asset.id ? "just-created" : ""} ${asset.archived_at ? "archived" : ""}`}
            key={asset.id}
            onClick={() => setSelectedAsset(asset)}
            ref={(node) => {
              if (node) assetCardRefs.current.set(asset.id, node);
              else assetCardRefs.current.delete(asset.id);
            }}
            type="button"
          >
            <span className="asset-card-visual">
              <AssetThumbnail asset={asset} eager={index < 6} resolveUrl={resolveUrl} />
              <StorageBadge asset={asset} compact />
              {asset.archived_at && <span className="asset-archived-label"><Archive size={12} />已归档</span>}
            </span>
            <span className="asset-card-copy">
              <span className="asset-card-name">{asset.name}</span>
              <span className="asset-card-meta">
                <span>{ASSET_TYPE_LABELS[asset.type] || asset.type}</span>
                <i />
                <span>{asset.width} × {asset.height}</span>
              </span>
              <span className="asset-card-tags">
                {(asset.tags || []).slice(0, 2).map((tag) => <small key={tag}>{tag}</small>)}
                {!asset.tags?.length && <small className="muted">未添加标签</small>}
              </span>
            </span>
          </button>
        ))}
      </div>
    );
  }

  function renderPagination() {
    return (
      <nav className="asset-pagination" aria-label="资产分页">
        <div>
          <span>显示 {resultStart}–{resultEnd} 个，共 {assetList.total} 个</span>
          <label>
            每页
            <select
              aria-label="每页资产数"
              onChange={(event) => {
                setPageSize(Number(event.target.value));
                setPage(1);
              }}
              value={pageSize}
            >
              {ASSET_PAGE_SIZES.map((size) => <option key={size} value={size}>{size} 个</option>)}
            </select>
          </label>
        </div>
        <div>
          <button aria-label="上一页" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)} type="button">
            <CaretLeft size={15} />
          </button>
          {paginationItems.map((item) => typeof item === "number" ? (
            <button
              aria-current={item === page ? "page" : undefined}
              className={item === page ? "active" : ""}
              disabled={loading}
              key={item}
              onClick={() => setPage(item)}
              type="button"
            >
              {item}
            </button>
          ) : <span aria-hidden="true" key={item}>…</span>)}
          <button
            aria-label="下一页"
            disabled={page >= assetList.total_pages || loading}
            onClick={() => setPage(page + 1)}
            type="button"
          >
            <CaretRight size={15} />
          </button>
        </div>
      </nav>
    );
  }

  function renderAssetCollection({ compactEmpty = false } = {}) {
    if (loading && !assetList.items.length) {
      return (
        <div className={`asset-loading ${compactEmpty ? "compact" : ""}`} role="status">
          <CircleNotch className="spin" size={21} />
          正在读取工作区资产…
        </div>
      );
    }
    if (!assetList.items.length) {
      if (compactEmpty) {
        return (
          <div className="asset-home-empty">
            <span><ImageSquare size={24} /></span>
            <div>
              <strong>未分类中还没有资产</strong>
              <p>上传时不选择目录的资产会显示在这里。</p>
            </div>
            <button className="secondary-button compact" onClick={openUpload} type="button">
              <Plus size={15} />上传资产
            </button>
          </div>
        );
      }
      const filtered = query || selectedFolder || typeFilter || storageFilter || includeArchived;
      return (
        <div className="asset-empty">
          <span><ImageSquare size={30} /></span>
          <h2>{filtered ? "没有匹配的资产" : "工作区还没有资产"}</h2>
          <p>{filtered ? "调整目录或筛选条件后再试。" : "上传人物、产品、服装或场景图片，供后续分镜生图复用。"}</p>
          {!filtered && (
            <button className="primary-button compact" onClick={openUpload} type="button">
              <Plus size={16} />上传第一个资产
            </button>
          )}
        </div>
      );
    }
    return (
      <>
        {renderAssetGrid()}
        {renderPagination()}
      </>
    );
  }

  function renderFolderCard(folder) {
    return (
      <article className="asset-folder-card" key={folder.id}>
        <button
          aria-label={`打开目录${folder.name}`}
          className="asset-folder-card-open"
          onClick={() => changeFolder(folder.id)}
          type="button"
        >
          <span className="asset-folder-card-cover">
            <FolderCover cover={folder.cover} resolveUrl={resolveUrl} />
          </span>
          <span className="asset-folder-card-copy">
            <strong title={folder.name}>{folder.name}</strong>
            <small>{folder.asset_count} 个资产</small>
          </span>
        </button>
        <details className="asset-folder-card-menu">
          <summary aria-label={`管理目录${folder.name}`} title="管理目录">
            <DotsThree size={18} weight="bold" />
          </summary>
          <div>
            <button
              disabled={!folder.asset_count}
              onClick={(event) => {
                event.currentTarget.closest("details")?.removeAttribute("open");
                openCoverPicker(folder);
              }}
              type="button"
            >
              <ImageSquare size={15} />设置封面
            </button>
            {folder.cover?.source === "manual" && (
              <button
                disabled={coverSaving}
                onClick={(event) => {
                  event.currentTarget.closest("details")?.removeAttribute("open");
                  restoreAutomaticCover(folder);
                }}
                type="button"
              >
                <ArrowClockwise size={15} />恢复自动封面
              </button>
            )}
            <button
              onClick={(event) => {
                event.currentTarget.closest("details")?.removeAttribute("open");
                setFolderDialog({ folder, name: folder.name });
              }}
              type="button"
            >
              <PencilSimple size={15} />重命名
            </button>
            <button
              className="danger"
              onClick={(event) => {
                event.currentTarget.closest("details")?.removeAttribute("open");
                deleteFolder(folder);
              }}
              type="button"
            >
              <Trash size={15} />删除目录
            </button>
          </div>
        </details>
      </article>
    );
  }

  return (
    <main className={`asset-library-page ${selectedAsset ? "has-detail" : ""}`}>
      <section className="asset-page-heading">
        <div>
          <div className="breadcrumb">
            <span>{workspaceName}</span>
            <CaretRight size={14} />
            <span className="breadcrumb-current">资产库</span>
          </div>
          <div className="asset-title-row">
            <h1>资产库</h1>
            <span className="asset-local-status"><HardDrive size={14} weight="fill" /> 当前仅本地</span>
          </div>
          <p>集中管理人物、产品、服装和场景参考；后续可无缝扩展云端副本。</p>
        </div>
        <button className="primary-button compact" onClick={openUpload} type="button">
          <UploadSimple size={17} weight="bold" />
          上传资产
        </button>
      </section>

      <section className="asset-library-shell">
        <aside className="asset-folder-rail" aria-label="资产目录">
          <div className="asset-rail-heading">
            <div>
              <span>一级目录</span>
              <strong>资产分类</strong>
            </div>
            <button
              aria-label="新建资产目录"
              onClick={() => setFolderDialog({ folder: null, name: "" })}
              type="button"
            >
              <FolderPlus size={18} />
            </button>
          </div>
          <button
            className={`asset-folder-item ${selectedFolder === "" ? "active" : ""}`}
            onClick={() => changeFolder("")}
            type="button"
          >
            <FolderOpen size={17} weight={selectedFolder === "" ? "fill" : "regular"} />
            <span>全部资产</span>
          </button>
          <button
            className={`asset-folder-item ${selectedFolder === "unfiled" ? "active" : ""}`}
            onClick={() => changeFolder("unfiled")}
            type="button"
          >
            <Folder size={17} weight={selectedFolder === "unfiled" ? "fill" : "regular"} />
            <span>未分类</span>
          </button>
          <div className="asset-folder-list">
            {folders.map((folder) => (
              <div className={`asset-folder-row ${selectedFolder === folder.id ? "active" : ""}`} key={folder.id}>
                <button onClick={() => changeFolder(folder.id)} type="button">
                  <Folder size={17} weight={selectedFolder === folder.id ? "fill" : "regular"} />
                  <span>{folder.name}</span>
                  <small>{folder.asset_count}</small>
                </button>
                <span className="asset-folder-actions">
                  <button
                    aria-label={`重命名${folder.name}`}
                    onClick={() => setFolderDialog({ folder, name: folder.name })}
                    type="button"
                  >
                    <PencilSimple size={13} />
                  </button>
                  <button aria-label={`删除${folder.name}`} onClick={() => deleteFolder(folder)} type="button">
                    <Trash size={13} />
                  </button>
                </span>
              </div>
            ))}
          </div>
          <div className="asset-storage-note">
            <span><HardDrive size={17} weight="fill" /></span>
            <div>
              <strong>{localLocation?.name || "本机工作区"}</strong>
              <p>原图与缩略图均保存在工作区对象存储中。</p>
            </div>
          </div>
        </aside>

        <section className="asset-browser">
          <div className="asset-toolbar" aria-label="资产筛选">
            <label className="asset-search">
              <MagnifyingGlass size={18} />
              <input
                aria-label="搜索资产"
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="搜索名称、说明或标签"
                value={searchInput}
              />
              {searchInput && (
                <button aria-label="清空资产搜索" onClick={() => setSearchInput("")} type="button">
                  <X size={14} />
                </button>
              )}
            </label>
            <select
              aria-label="按资产类型筛选"
              onChange={(event) => changeFilter(setTypeFilter, event.target.value)}
              value={typeFilter}
            >
              <option value="">全部类型</option>
              {ASSET_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
            <select
              aria-label="按存储状态筛选"
              onChange={(event) => changeFilter(setStorageFilter, event.target.value)}
              value={storageFilter}
            >
              <option value="">全部存储状态</option>
              <option value="local_only">仅本地</option>
              <option value="synced">已同步</option>
              <option value="unavailable">不可用</option>
            </select>
            <label className="asset-archive-toggle">
              <input
                checked={includeArchived}
                onChange={(event) => changeFilter(setIncludeArchived, event.target.checked)}
                type="checkbox"
              />
              <span>包含已归档</span>
            </label>
          </div>

          {error && (
            <div className="asset-error" role="alert">
              <WarningCircle size={17} weight="fill" />
              <span>{error}</span>
              <button aria-label="关闭错误提示" onClick={() => setError("")} type="button"><X size={14} /></button>
            </div>
          )}

          {homeMode ? (
            <div className="asset-home">
              <section className="asset-home-section" aria-labelledby="asset-folder-heading">
                <header className="asset-home-heading">
                  <div>
                    <h2 id="asset-folder-heading">目录</h2>
                    <span>{folders.length} 个目录</span>
                  </div>
                  <div className="asset-home-heading-actions">
                    <button
                      aria-label="刷新资产目录"
                      className="asset-refresh-button"
                      disabled={loading}
                      onClick={() => Promise.all([refreshFolders(), refreshAssets()]).catch((requestError) => setError(requestError.message))}
                      type="button"
                    >
                      <ArrowClockwise className={loading ? "spin" : ""} size={16} />
                      刷新
                    </button>
                    <button
                      className="secondary-button compact"
                      onClick={() => setFolderDialog({ folder: null, name: "" })}
                      type="button"
                    >
                      <FolderPlus size={16} />新建目录
                    </button>
                  </div>
                </header>
                {folders.length ? (
                  <div className="asset-folder-card-grid">
                    {folders.map(renderFolderCard)}
                  </div>
                ) : (
                  <div className="asset-home-empty directory">
                    <span><FolderPlus size={24} /></span>
                    <div>
                      <strong>还没有资产目录</strong>
                      <p>按人物、产品或场景创建一级目录，之后查找会更快。</p>
                    </div>
                    <button className="secondary-button compact" onClick={() => setFolderDialog({ folder: null, name: "" })} type="button">
                      <Plus size={15} />新建目录
                    </button>
                  </div>
                )}
              </section>

              <section className="asset-home-section" aria-labelledby="asset-unfiled-heading">
                <header className="asset-home-heading">
                  <div>
                    <h2 id="asset-unfiled-heading">未分类资产</h2>
                    <span>{assetList.total} 个资产</span>
                  </div>
                  {assetList.total > 0 && (
                    <button className="asset-section-link" onClick={() => changeFolder("unfiled")} type="button">
                      查看全部<CaretRight size={15} />
                    </button>
                  )}
                </header>
                {renderAssetCollection({ compactEmpty: true })}
              </section>
            </div>
          ) : (
            <>
              <div className="asset-result-heading">
                <div>
                  <strong>{activeFolderName}</strong>
                  <span>{assetList.total} 个资产</span>
                </div>
                <button
                  aria-label="刷新资产列表"
                  className="asset-refresh-button"
                  disabled={loading}
                  onClick={() => Promise.all([refreshFolders(), refreshAssets()]).catch((requestError) => setError(requestError.message))}
                  type="button"
                >
                  <ArrowClockwise className={loading ? "spin" : ""} size={16} />
                  刷新
                </button>
              </div>
              {renderAssetCollection()}
            </>
          )}
        </section>

        {selectedAsset && detailDraft && (
          <aside className="asset-detail-panel" aria-label="资产详情">
            <header>
              <div>
                <span>资产详情</span>
                <strong>{selectedAsset.name}</strong>
              </div>
              <button aria-label="关闭资产详情" onClick={() => setSelectedAsset(null)} type="button"><X size={17} /></button>
            </header>
            <div
              className="asset-detail-preview"
              style={{ "--asset-aspect-ratio": `${selectedAsset.width || 4} / ${selectedAsset.height || 3}` }}
            >
              <AssetThumbnail
                alt={`${selectedAsset.name} 原图`}
                asset={selectedAsset}
                eager
                resolveUrl={resolveUrl}
                useOriginal
              />
              <StorageBadge asset={selectedAsset} />
            </div>
            <form className="asset-detail-form" onSubmit={saveAssetDetail}>
              <label>
                <span>资产名称</span>
                <input
                  maxLength={120}
                  onChange={(event) => setDetailDraft((current) => ({ ...current, name: event.target.value }))}
                  required
                  value={detailDraft.name}
                />
              </label>
              <div className="asset-detail-columns">
                <label>
                  <span>类型</span>
                  <select onChange={(event) => setDetailDraft((current) => ({ ...current, type: event.target.value }))} value={detailDraft.type}>
                    {ASSET_TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                </label>
                <label>
                  <span>目录</span>
                  <select onChange={(event) => setDetailDraft((current) => ({ ...current, folderId: event.target.value }))} value={detailDraft.folderId}>
                    <option value="">未分类</option>
                    {folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
                  </select>
                </label>
              </div>
              <label>
                <span>说明</span>
                <textarea
                  maxLength={2000}
                  onChange={(event) => setDetailDraft((current) => ({ ...current, description: event.target.value }))}
                  placeholder="人物身份、产品卖点或场景使用说明"
                  rows={3}
                  value={detailDraft.description}
                />
              </label>
              <label>
                <span>标签</span>
                <input
                  onChange={(event) => setDetailDraft((current) => ({ ...current, tags: event.target.value }))}
                  placeholder="用逗号分隔"
                  value={detailDraft.tags}
                />
              </label>
              <label>
                <span>权利说明</span>
                <textarea
                  maxLength={1000}
                  onChange={(event) => setDetailDraft((current) => ({ ...current, rightsNote: event.target.value }))}
                  placeholder="可选：授权来源或内部备注"
                  rows={2}
                  value={detailDraft.rightsNote}
                />
              </label>
              <label className="asset-rights-check">
                <input
                  checked={detailDraft.rightsConfirmed}
                  onChange={(event) => setDetailDraft((current) => ({ ...current, rightsConfirmed: event.target.checked }))}
                  type="checkbox"
                />
                <span>已确认拥有使用权</span>
              </label>
              <dl className="asset-file-facts">
                <div><dt>尺寸</dt><dd>{selectedAsset.width} × {selectedAsset.height}</dd></div>
                <div><dt>文件</dt><dd>{formatAssetSize(selectedAsset.size_bytes)} · {selectedAsset.mime_type}</dd></div>
                <div><dt>更新</dt><dd>{formatAssetDate(selectedAsset.updated_at)}</dd></div>
                <div><dt>校验</dt><dd title={selectedAsset.sha256}>{selectedAsset.sha256.slice(0, 12)}…</dd></div>
              </dl>
              {selectedAsset.folder_id && !selectedAsset.archived_at && (
                <button
                  className="asset-set-cover-action"
                  disabled={coverSaving || detailSaving}
                  onClick={setSelectedAssetAsCover}
                  type="button"
                >
                  {coverSaving ? <CircleNotch className="spin" size={16} /> : <ImageSquare size={16} />}
                  设为所在目录封面
                </button>
              )}
              <div className="asset-detail-primary-actions">
                <button className="primary-button compact" disabled={detailSaving || Boolean(selectedAsset.archived_at)} type="submit">
                  {detailSaving ? <CircleNotch className="spin" size={16} /> : <Check size={16} weight="bold" />}
                  保存修改
                </button>
                <a className="secondary-button compact" download href={resolveUrl(selectedAsset.content_url)}>
                  <DownloadSimple size={16} />原图
                </a>
              </div>
            </form>
            <button className={`asset-archive-action ${selectedAsset.archived_at ? "restore" : ""}`} disabled={detailSaving} onClick={toggleArchive} type="button">
              {selectedAsset.archived_at ? <ArrowClockwise size={16} /> : <Archive size={16} />}
              {selectedAsset.archived_at ? "恢复资产" : "归档资产"}
            </button>
          </aside>
        )}
      </section>

      {uploadOpen && (
        <Modal label="上传资产" onClose={() => !uploading && setUploadOpen(false)}>
          <form onSubmit={submitUpload}>
            <header className="asset-modal-header">
              <div><span>工作区资产</span><h2>上传新资产</h2><p>当前版本保存在本机工作区，单张图片不超过 15 MB。</p></div>
              <button aria-label="关闭上传资产" disabled={uploading} onClick={() => setUploadOpen(false)} type="button"><X size={18} /></button>
            </header>
            <div className="asset-upload-body">
              <label className={`asset-file-drop ${uploadPreview ? "has-preview" : ""}`}>
                {uploadPreview ? <img alt="待上传资产预览" src={uploadPreview} /> : <span><UploadSimple size={26} /><strong>选择资产图片</strong><small>PNG、JPG、WebP · 最大 15 MB</small></span>}
                <input accept="image/png,image/jpeg,image/webp" onChange={(event) => chooseUploadFile(event.target.files?.[0])} type="file" />
              </label>
              <div className="asset-upload-fields">
                <label><span>资产名称</span><input maxLength={120} onChange={(event) => setUploadDraft((current) => ({ ...current, name: event.target.value }))} required value={uploadDraft.name} /></label>
                <div className="asset-detail-columns">
                  <label><span>类型</span><select onChange={(event) => setUploadDraft((current) => ({ ...current, type: event.target.value }))} value={uploadDraft.type}>{ASSET_TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                  <label><span>目录</span><select onChange={(event) => setUploadDraft((current) => ({ ...current, folderId: event.target.value }))} value={uploadDraft.folderId}><option value="">未分类</option>{folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label>
                </div>
                <label><span>说明</span><textarea maxLength={2000} onChange={(event) => setUploadDraft((current) => ({ ...current, description: event.target.value }))} placeholder="说明这个资产适合用于哪些镜头" rows={3} value={uploadDraft.description} /></label>
                <label><span>标签</span><input onChange={(event) => setUploadDraft((current) => ({ ...current, tags: event.target.value }))} placeholder="例如：女主播，白色连衣裙，户外" value={uploadDraft.tags} /></label>
                <label><span>权利说明</span><input maxLength={1000} onChange={(event) => setUploadDraft((current) => ({ ...current, rightsNote: event.target.value }))} placeholder="可选：授权来源或内部备注" value={uploadDraft.rightsNote} /></label>
                <label className="asset-rights-check prominent"><input checked={uploadDraft.rightsConfirmed} onChange={(event) => setUploadDraft((current) => ({ ...current, rightsConfirmed: event.target.checked }))} type="checkbox" /><ShieldCheck size={17} /><span>我确认拥有该图片的使用权</span></label>
              </div>
            </div>
            <footer className="asset-modal-footer">
              <span><HardDrive size={15} weight="fill" />存储策略：仅本地</span>
              <button className="secondary-button compact" disabled={uploading} onClick={() => setUploadOpen(false)} type="button">取消</button>
              <button className="primary-button compact" disabled={uploading || !uploadFile || !uploadDraft.rightsConfirmed} type="submit">
                {uploading ? <CircleNotch className="spin" size={16} /> : <UploadSimple size={16} weight="bold" />}
                {uploading ? "正在保存…" : "上传资产"}
              </button>
            </footer>
          </form>
        </Modal>
      )}

      {folderDialog && (
        <Modal label={folderDialog.folder ? "重命名资产目录" : "新建资产目录"} onClose={() => !folderSaving && setFolderDialog(null)} size="compact">
          <form className="asset-folder-dialog" onSubmit={saveFolder}>
            <header className="asset-modal-header">
              <div><span>一级目录</span><h2>{folderDialog.folder ? "重命名目录" : "新建目录"}</h2><p>资产目录暂时只支持一级分类。</p></div>
              <button aria-label="关闭目录设置" disabled={folderSaving} onClick={() => setFolderDialog(null)} type="button"><X size={18} /></button>
            </header>
            <label><span>目录名称</span><input autoFocus maxLength={120} onChange={(event) => setFolderDialog((current) => ({ ...current, name: event.target.value }))} placeholder="例如：主播人物" required value={folderDialog.name} /></label>
            <footer className="asset-modal-footer">
              <span />
              <button className="secondary-button compact" disabled={folderSaving} onClick={() => setFolderDialog(null)} type="button">取消</button>
              <button className="primary-button compact" disabled={folderSaving || !folderDialog.name.trim()} type="submit">{folderSaving ? <CircleNotch className="spin" size={16} /> : <Check size={16} />}{folderDialog.folder ? "保存" : "创建目录"}</button>
            </footer>
          </form>
        </Modal>
      )}

      {coverDialog && (
        <Modal
          label={`设置${coverDialog.folder.name}目录封面`}
          onClose={() => !coverSaving && setCoverDialog(null)}
        >
          <form className="asset-cover-dialog" onSubmit={saveFolderCover}>
            <header className="asset-modal-header">
              <div>
                <span>目录封面</span>
                <h2>设置“{coverDialog.folder.name}”封面</h2>
                <p>选择目录中的一张资产，或由系统自动使用最近更新的有效资产。</p>
              </div>
              <button aria-label="关闭目录封面设置" disabled={coverSaving} onClick={() => setCoverDialog(null)} type="button">
                <X size={18} />
              </button>
            </header>
            <div className="asset-cover-dialog-body">
              {coverDialog.error && (
                <div className="asset-error" role="alert">
                  <WarningCircle size={17} weight="fill" />
                  <span>{coverDialog.error}</span>
                </div>
              )}
              {coverDialog.loading ? (
                <div className="asset-cover-loading" role="status">
                  <CircleNotch className="spin" size={20} />正在读取目录资产…
                </div>
              ) : (
                <div className="asset-cover-options" role="radiogroup" aria-label="目录封面选项">
                  <button
                    aria-checked={!coverDialog.selectedAssetId}
                    className="asset-cover-option automatic"
                    onClick={() => setCoverDialog((current) => ({ ...current, selectedAssetId: "" }))}
                    role="radio"
                    type="button"
                  >
                    <span className="asset-cover-option-visual"><FolderOpen size={32} /></span>
                    <span><strong>自动选择</strong><small>使用最近更新的有效资产</small></span>
                  </button>
                  {coverDialog.items.map((asset) => (
                    <button
                      aria-checked={coverDialog.selectedAssetId === asset.id}
                      className="asset-cover-option"
                      key={asset.id}
                      onClick={() => setCoverDialog((current) => ({ ...current, selectedAssetId: asset.id }))}
                      role="radio"
                      type="button"
                    >
                      <span className="asset-cover-option-visual">
                        <AssetThumbnail asset={asset} alt="" resolveUrl={resolveUrl} />
                      </span>
                      <span><strong title={asset.name}>{asset.name}</strong><small>{ASSET_TYPE_LABELS[asset.type] || asset.type}</small></span>
                    </button>
                  ))}
                </div>
              )}
              {!coverDialog.loading && coverDialog.items.length >= 100 && (
                <p className="asset-cover-limit-note">当前显示最近 100 个有效资产。</p>
              )}
            </div>
            <footer className="asset-modal-footer">
              <span>{coverDialog.selectedAssetId ? "将使用所选资产作为固定封面" : "目录内容变化时，自动封面会同步更新"}</span>
              <button className="secondary-button compact" disabled={coverSaving} onClick={() => setCoverDialog(null)} type="button">取消</button>
              <button className="primary-button compact" disabled={coverSaving || coverDialog.loading} type="submit">
                {coverSaving ? <CircleNotch className="spin" size={16} /> : <Check size={16} />}
                保存封面
              </button>
            </footer>
          </form>
        </Modal>
      )}
    </main>
  );
}
