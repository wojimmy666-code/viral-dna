import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ImageSquare, Plus, SpinnerGap, X } from "@phosphor-icons/react";
import { ASSET_TYPE_OPTIONS } from "../asset-library-ui.js";
import { folderPreferenceKey, jsonRequest, promotionPayload, recalledFolder, rememberFolder } from "./asset-promotion-ui.js";

export function AddToAssetsDialog({ target, onClose, onAdded, onUncertain }) {
  const dialogRef = useRef(null);
  const nameRef = useRef(null);
  const submitting = useRef(false);
  const alive = useRef(false);
  const headingId = useId();
  const [catalog, setCatalog] = useState(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [newFolder, setNewFolder] = useState(null);
  const [folderSaving, setFolderSaving] = useState(false);
  const [folderError, setFolderError] = useState("");
  const [previewFailed, setPreviewFailed] = useState(false);
  const [draft, setDraft] = useState({
    name: target.name || "生成素材", assetType: target.assetType || "other",
    folderId: "", description: "", tags: "",
  });

  useEffect(() => {
    alive.current = true;
    const dialog = dialogRef.current;
    dialog.showModal();
    nameRef.current?.focus();
    return () => { alive.current = false; dialog.close(); };
  }, []);

  useEffect(() => {
    let active = true;
    setLoadError("");
    async function load() {
      try {
        const context = await target.request("/context");
        if (!context?.active_workspace?.id || !context?.account?.id) throw new Error("当前工作区不可用");
        const folders = await target.request(`/workspaces/${context.active_workspace.id}/asset-folders`);
        if (!Array.isArray(folders)) throw new Error("目录数据不可用，请重试");
        if (!active) return;
        const preferenceKey = folderPreferenceKey(context, target);
        setCatalog({ context, folders, preferenceKey });
        setDraft(current => ({ ...current, folderId: recalledFolder(preferenceKey, folders) }));
      } catch (failure) {
        if (active) setLoadError(failure.message || "无法加载资产目录");
      }
    }
    load();
    return () => { active = false; };
  }, [target, loadAttempt]);

  function close() { if (!submitting.current) onClose(); }
  function change(field, value) { setDraft(current => ({ ...current, [field]: value })); }

  async function verifyWorkspace() {
    const current = await target.request("/context");
    if (current?.account?.id !== catalog.context.account.id
      || current?.active_workspace?.id !== catalog.context.active_workspace.id) {
      throw new Error("当前工作区已切换，请关闭窗口后重新添加");
    }
  }

  async function createFolder() {
    if (submitting.current || !catalog || !newFolder?.trim()) return;
    submitting.current = true;
    setFolderSaving(true); setFolderError("");
    try {
      await verifyWorkspace();
      const folder = await target.request(`/workspaces/${catalog.context.active_workspace.id}/asset-folders`,
        jsonRequest({ name: newFolder.trim() }));
      if (!folder?.id) throw new Error("目录创建结果未确认，请刷新后核对");
      if (!alive.current) return;
      setCatalog(current => ({ ...current, folders: [...current.folders, folder] }));
      change("folderId", folder.id);
      setNewFolder(null);
    } catch (failure) {
      if (alive.current) setFolderError(failure.message || "创建目录失败");
    } finally {
      submitting.current = false;
      if (alive.current) setFolderSaving(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    if (submitting.current || !catalog || newFolder !== null) return;
    submitting.current = true;
    setSaving(true); setError("");
    try {
      const payload = promotionPayload(target, draft);
      await verifyWorkspace();
      const result = await target.request("/assets/from-generated-artifact", jsonRequest(payload));
      if (!result?.asset?.id) throw new Error("入库结果未确认，请重试核对；不会重复创建资产");
      rememberFolder(catalog.preferenceKey, result.asset.folder_id);
      if (alive.current) onAdded(target, result);
    } catch (failure) {
      if (alive.current) {
        setError(failure.message || "加入资产库失败，请重试");
        onUncertain?.(target);
      }
    } finally {
      submitting.current = false;
      if (alive.current) setSaving(false);
    }
  }

  const busy = saving || folderSaving;
  return createPortal(<dialog ref={dialogRef} className="generated-asset-dialog" aria-labelledby={headingId}
    onCancel={event => { event.preventDefault(); close(); }}
    onClick={event => {
      event.stopPropagation();
      if (event.target !== event.currentTarget) return;
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) close();
    }}>
    <form onSubmit={submit}>
      <header><h2 id={headingId}>加入资产库</h2><button className="text-button" aria-label="关闭入库窗口" disabled={busy} onClick={close} type="button"><X size={20} /></button></header>
      <div className="generated-asset-dialog-preview">
        {target.previewUrl && !previewFailed
          ? <img alt="本次加入资产库的素材" src={target.previewUrl} onError={() => setPreviewFailed(true)} />
          : <ImageSquare size={36} aria-label="素材预览不可用" />}
      </div>
      <label><span>资产名称</span><input ref={nameRef} autoFocus required maxLength={120} disabled={busy} value={draft.name} onChange={event => change("name", event.target.value)} /></label>
      <div className="generated-asset-dialog-fields">
        <label><span>保存目录</span><select disabled={!catalog || busy} value={draft.folderId} onChange={event => change("folderId", event.target.value)}>
          <option value="">未分类</option>{catalog?.folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
        </select></label>
        <label><span>资产类型</span><select disabled={busy} value={draft.assetType} onChange={event => change("assetType", event.target.value)}>
          {ASSET_TYPE_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select></label>
      </div>
      {!catalog && <p className="generated-asset-dialog-hint" role={loadError ? "alert" : "status"}>
        {loadError || "正在加载目录…"}{loadError && <button className="text-button" type="button" onClick={() => setLoadAttempt(value => value + 1)}>重试</button>}
      </p>}
      {newFolder === null ? <button className="text-button generated-asset-new-folder" disabled={!catalog || busy} type="button" onClick={() => { setNewFolder(""); setFolderError(""); }}><Plus size={16} />新建目录</button>
        : <div className="generated-asset-create-folder">
          <label><span>新目录名称</span><input autoFocus maxLength={120} disabled={busy} value={newFolder} onChange={event => setNewFolder(event.target.value)} /></label>
          <div><button className="secondary-button compact" type="button" disabled={busy} onClick={() => setNewFolder(null)}>取消新建</button><button className="secondary-button compact" type="button" disabled={busy || !newFolder.trim()} onClick={createFolder}>{folderSaving ? "正在创建…" : "创建目录"}</button></div>
          {folderError && <p className="generated-asset-dialog-error" role="alert">{folderError}</p>}
        </div>}
      <details className="generated-asset-extra"><summary>说明与标签（可选）</summary>
        <label><span>说明</span><textarea maxLength={2000} rows={3} disabled={busy} value={draft.description} onChange={event => change("description", event.target.value)} /></label>
        <label><span>标签</span><input disabled={busy} value={draft.tags} onChange={event => change("tags", event.target.value)} placeholder="用逗号分隔，最多 20 个" /></label>
      </details>
      {error && <p className="generated-asset-dialog-error" role="alert">{error}</p>}
      <footer><button className="secondary-button compact" disabled={busy} type="button" onClick={close}>取消</button><button className="primary-button compact" disabled={busy || !catalog || !draft.name.trim() || newFolder !== null} type="submit">{saving ? <><SpinnerGap className="spin" size={16} />正在加入…</> : "确认加入"}</button></footer>
    </form>
  </dialog>, document.body);
}
