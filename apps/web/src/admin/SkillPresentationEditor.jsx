import { useEffect, useRef, useState } from "react";
import { SkillCover } from "../skill-workflow/SkillCover.jsx";
import { presentationPayload } from "../skill-workflow/skill-presentation-ui.js";

const unresolved = asset => asset && asset.status !== "ready";

export function SkillPresentationEditor({ skill, request, onClose, onSaved }) {
  const storageKey = `viraldna:skill-presentation:${skill.id}`;
  const [draft, setDraft] = useState({ image: null, video: null, revision: 0, itemId: crypto.randomUUID() });
  const [original, setOriginal] = useState({ image: null, video: null });
  const [loaded, setLoaded] = useState(false);
  const [uploading, setUploading] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const controllers = useRef({});
  const discarded = useRef(false);
  const base = `/admin/skills/${encodeURIComponent(skill.id)}`;

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const saved = await request(`${base}/presentation`);
        const item = saved.presentation.items.find(value => value.id === saved.presentation.primary_item_id);
        const originals = { image: saved.assets.find(asset => asset.id === item?.image_asset_id) || null, video: saved.assets.find(asset => asset.id === item?.video_asset_id) || null };
        let cached;
        try { cached = JSON.parse(localStorage.getItem(storageKey)); } catch { /* storage is optional */ }
        const next = { ...originals, revision: saved.presentation.revision, itemId: item?.id || crypto.randomUUID() };
        if (cached) {
          next.revision = cached.revision;
          next.itemId = cached.itemId;
          for (const kind of ["image", "video"]) {
            const id = cached[`${kind}Id`];
            next[kind] = id ? await request(`/admin/skill-media/${id}`).catch(() => ({id, kind, status:"failed", phase:"素材不可用", original_filename:"未保存的素材", error_message:"请重新上传或移除"})) : null;
          }
        }
        if (!live) return;
        setOriginal(originals); setDraft(next); setLoaded(true);
        if (cached) setNotice(cached.revision === saved.presentation.revision ? "已恢复未保存的封面设置" : "封面已被更新，未保存的设置已保留；请核对后重新加载最新配置");
      } catch (failure) { if (live) setError(failure.message); }
    }
    load();
    return () => { live = false; Object.values(controllers.current).forEach(controller => controller.abort()); };
  }, [base, request, storageKey, reloadKey]);

  useEffect(() => {
    if (!loaded || discarded.current) return;
    try { localStorage.setItem(storageKey, JSON.stringify({ revision: draft.revision, itemId: draft.itemId, imageId: draft.image?.id || null, videoId: draft.video?.id || null })); } catch { /* storage is optional */ }
  }, [draft, loaded, storageKey]);

  const pending = [draft.image, draft.video].filter(asset => asset && ["uploaded", "processing"].includes(asset.status));
  const pendingKey = pending.map(asset => asset.id).join(",");
  useEffect(() => {
    if (!pendingKey) return;
    let live = true, timer;
    async function poll() {
      try {
        const assets = await Promise.all(pendingKey.split(",").map(id => request(`/admin/skill-media/${id}`)));
        if (live) setDraft(current => ({ ...current, ...Object.fromEntries(assets.filter(asset => current[asset.kind]?.id === asset.id).map(asset => [asset.kind, asset])) }));
      } catch (failure) { if (live) setError(`状态更新失败：${failure.message}。素材仍在后台处理。`); }
      finally { if (live) timer = setTimeout(poll, 1500); }
    }
    timer = setTimeout(poll, 500);
    return () => { live = false; clearTimeout(timer); };
  }, [pendingKey, request]);

  async function upload(kind, file) {
    if (!file) return;
    const max = (kind === "image" ? 20 : 200) * 1024 * 1024;
    if (file.size > max) { setError(`文件不能超过 ${max / 1024 / 1024}MB`); return; }
    setError(""); setUploading(current => ({ ...current, [kind]: 0 }));
    const controller = new AbortController(); controllers.current[kind] = controller;
    try {
      const body = new FormData(); body.append("kind", kind); body.append("file", file);
      const asset = request.upload
        ? await request.upload(`${base}/media`, body, value => setUploading(current => ({ ...current, [kind]: value })), controller.signal)
        : await request(`${base}/media`, { method: "POST", body, signal: controller.signal });
      if (!controller.signal.aborted) setDraft(current => ({ ...current, [kind]: asset }));
    } catch (failure) { if (failure.name !== "AbortError") setError(failure.message); }
    finally { delete controllers.current[kind]; setUploading(current => { const next = {...current}; delete next[kind]; return next; }); }
  }

  async function retry(asset) {
    setError("");
    try {
      const next = await request(`/admin/skill-media/${asset.id}/retry`, { method: "POST" });
      setDraft(current => current[asset.kind]?.id === asset.id ? { ...current, [asset.kind]: next } : current);
    } catch (failure) { setError(failure.message); }
  }

  function discard() {
    discarded.current = true;
    try { localStorage.removeItem(storageKey); } catch { /* storage is optional */ }
  }

  function reloadSaved() {
    discard();
    setLoaded(false); setError(""); setNotice("");
    discarded.current = false;
    setReloadKey(current => current + 1);
  }

  async function save() {
    setSaving(true); setError("");
    try {
      await request(`${base}/presentation`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(presentationPayload(draft.revision, draft.itemId, draft.image, draft.video)) });
      discard(); onSaved();
    } catch (failure) { setError(failure.message); }
    finally { setSaving(false); }
  }

  const image = draft.image?.status === "ready" ? draft.image : draft.image ? original.image : null;
  const video = draft.video?.status === "ready" ? draft.video : draft.video ? original.video : null;
  const previewSkill = { ...skill, presentation: { cover_url: image?.content_url || video?.poster_url, poster_url: video?.poster_url, video_url: video?.content_url } };
  const canSave = loaded && !saving && !Object.keys(uploading).length && !unresolved(draft.image) && !unresolved(draft.video);
  return <section className="skill-presentation-editor" aria-label={`${skill.name}封面与预览`}>
    <div className="skill-presentation-layout"><div className="skill-presentation-fields">
      {!loaded && !error && <p role="status">正在读取封面设置…</p>}
      {["image", "video"].map(kind => {
        const asset = draft[kind], isUploading = Object.hasOwn(uploading, kind);
        return <div className="skill-presentation-field" key={kind}>
          <label><strong>{kind === "image" ? "封面图片（可选）" : "预览视频（可选）"}</strong><input aria-label={kind === "image" ? "上传封面图片" : "上传预览视频"} type="file" accept={kind === "image" ? "image/jpeg,image/png,image/webp" : "video/mp4,video/quicktime,video/webm"} disabled={!loaded || saving || isUploading} onChange={event => { upload(kind, event.target.files?.[0]); event.target.value = ""; }} /></label>
          <small>{kind === "image" ? "JPG / PNG / WebP，最大 20MB" : "MP4 / MOV / WebM，最大 200MB、120 秒"}</small>
          {isUploading && <div role="status"><small>正在上传{uploading[kind] == null ? "…" : ` ${uploading[kind]}%`}</small><progress aria-label="文件上传进度" max={100} value={uploading[kind] ?? undefined} /></div>}
          {asset && <><small>{asset.original_filename} · {asset.phase}</small>{["uploaded", "processing"].includes(asset.status) && <progress aria-label="素材处理进度" max={100} value={asset.progress || 0} />}<div>
            <button type="button" className="text-button" disabled={saving || isUploading} onClick={() => setDraft(current => ({...current,[kind]:null}))}>移除{kind === "image" ? "图片" : "视频"}</button>
            {asset.status === "failed" && asset.retryable && <button type="button" className="text-button" onClick={() => retry(asset)}>重试处理</button>}
          </div>{asset.error_message && <p role="alert">{asset.error_message}</p>}</>}
        </div>;
      })}
      {!draft.image && draft.video && <small>使用视频第一帧作为封面</small>}
    </div><div className="skill-presentation-preview"><SkillCover skill={previewSkill} /><p>效果预览 · 悬停或点击播放，视频静音循环</p></div></div>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
    {(notice || error) && <button type="button" className="text-button" disabled={saving || !!Object.keys(uploading).length} onClick={reloadSaved}>放弃未保存设置，重新加载</button>}
    <div className="skill-presentation-actions"><button type="button" className="primary-button compact" disabled={!canSave} onClick={save}>{saving ? "正在保存…" : "保存封面"}</button><button type="button" className="secondary-button compact" disabled={saving} onClick={() => { discard(); onClose(); }}>取消</button></div>
  </section>;
}
