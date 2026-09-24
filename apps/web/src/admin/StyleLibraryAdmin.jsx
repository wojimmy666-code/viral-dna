import { useEffect, useRef, useState } from "react";
import { Plus, UploadSimple, X } from "@phosphor-icons/react";
import { Button, IconButton } from "../ui/system/Button.jsx";
import { StyleCover } from "../visual-styles/VisualStyleControl.jsx";
import { registerAccountFlusher } from "../accounts/account-client.js";
import "./style-library-admin.css";

const BASE = "/admin/visual-styles";
const EMPTY = { name: "", category: "写实摄影", tags: [], description: "", cover_id: null, sample_ids: [], applies_to: ["image", "video"], image_prompt: "", video_prompt: "", image_negative: "", video_negative: "", sort_order: 0 };
const definition = item => ({ ...Object.fromEntries(Object.keys(EMPTY).map(key => [key, item[key] ?? EMPTY[key]])), tags: (item.tags || []).map(tag => tag.trim()).filter(Boolean) });
const json = (body, method = "POST") => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export function StyleLibraryAdmin({ request, onUnsavedChange }) {
  const [items, setItems] = useState([]), [selected, setSelected] = useState(null), [draft, setDraft] = useState(null);
  const [query, setQuery] = useState(""), [loading, setLoading] = useState(true), [busy, setBusy] = useState("");
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const alive = useRef(false), operation = useRef(false);
  const dirty = draft && JSON.stringify(definition(draft)) !== JSON.stringify(definition(selected || EMPTY));
  useEffect(() => { onUnsavedChange?.(Boolean(dirty || busy)); return () => onUnsavedChange?.(false); }, [dirty, busy, onUnsavedChange]);
  useEffect(() => registerAccountFlusher(() => {
    if (!dirty && !operation.current) return true;
    setError("当前风格有未保存修改，请先保存草稿或取消修改。");
    return false;
  }), [dirty]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function load() {
    setLoading(true); setError("");
    try {
      const result = await request(BASE);
      if (alive.current) setItems(result.items);
    } catch (failure) { if (alive.current) setError(failure.message); }
    finally { if (alive.current) setLoading(false); }
  }
  useEffect(() => { void load(); }, [request]);
  useEffect(() => {
    const handler = event => { if (dirty || operation.current) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
  function choose(item) {
    if (operation.current) return;
    if (dirty) { setError("当前风格有未保存修改，请先保存草稿或取消修改。"); return; }
    setSelected(item); setDraft(item ? { ...item } : { ...EMPTY }); setError(""); setNotice("");
  }
  function change(key, value) { setDraft(current => ({ ...current, [key]: value })); setNotice(""); }
  function accept(item) { setItems(current => [...current.filter(value => value.id !== item.id), item].sort((a, b) => a.sort_order - b.sort_order)); setSelected(item); setDraft({ ...item }); }
  async function save(event) {
    event.preventDefault();
    if (operation.current) return;
    operation.current = true; setBusy("save"); setError(""); setNotice("");
    try {
      const item = await request(selected ? `${BASE}/${selected.id}` : BASE, json({ expected_revision: selected?.revision || 0, style: definition(draft) }, selected ? "PUT" : "POST"));
      if (alive.current) { accept(item); setNotice("草稿已保存，发布后用户可选择。"); }
    } catch (failure) { if (alive.current) setError(failure.message); }
    finally { operation.current = false; if (alive.current) setBusy(""); }
  }
  async function action(kind) {
    if (operation.current || dirty || !selected) return;
    operation.current = true; setBusy(kind); setError(""); setNotice("");
    try {
      const item = await request(`${BASE}/${selected.id}/${kind}`, json({ expected_revision: selected.revision }));
      if (alive.current) { accept(item); setNotice(kind === "publish" ? `版本 ${item.version} 已发布` : "已停用，历史任务和已有选择保留。"); }
    } catch (failure) { if (alive.current) setError(failure.message); }
    finally { operation.current = false; if (alive.current) setBusy(""); }
  }
  async function upload(event, sample = false) {
    const file = event.target.files?.[0]; event.target.value = "";
    if (!file || operation.current) return;
    operation.current = true; setBusy("upload"); setError("");
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error("请选择不超过 10 MB 的图片");
      const body = new FormData(); body.append("file", file);
      const media = await request(`${BASE}/media`, { method: "POST", body });
      if (alive.current) setDraft(current => sample
        ? { ...current, sample_ids: [...current.sample_ids, media.id], sample_urls: [...(current.sample_urls || []), media.url] }
        : { ...current, cover_id: media.id, cover_url: media.url });
    } catch (failure) { if (alive.current) setError(failure.message || "上传失败，请重试"); }
    finally { operation.current = false; if (alive.current) setBusy(""); }
  }
  return <section className="style-admin" aria-label="管理员风格库">
    <div className="style-admin-toolbar"><p>维护用户可选的风格与图片、视频提示词。</p><Button icon={<Plus />} disabled={Boolean(busy)} onClick={() => choose(null)}>新建风格</Button></div>
    {error && <div role="alert" className="visual-style-error">{error}<Button variant="text" size="compact" disabled={Boolean(busy)} onClick={() => void load()}>重新读取列表</Button></div>}
    {notice && <p role="status">{notice}</p>}
    <div className="style-admin-columns">
      <aside className="style-admin-list"><input type="search" aria-label="搜索管理员风格" placeholder="搜索风格" value={query} onChange={event => setQuery(event.target.value)} />
        {loading && <p role="status">正在读取…</p>}
        {items.filter(item => item.name.includes(query) || item.category.includes(query)).map(item => <button data-ui="navigation-item" type="button" className={selected?.id === item.id ? "is-selected" : ""} key={item.id} onClick={() => choose(item)} disabled={Boolean(busy)}>
          <StyleCover src={item.cover_url} /><span><strong>{item.name}</strong><small>{item.enabled ? `已发布 · v${item.version}` : item.version ? "已停用" : "草稿"}{item.has_unpublished_changes && item.version ? " · 有新草稿" : ""}</small></span>
        </button>)}
      </aside>
      {draft ? <form className="style-admin-editor" onSubmit={save}>
        <header><h2>{selected ? selected.name : "新建风格"}</h2><span>{selected?.version ? `当前发布版本 ${selected.version}` : "尚未发布"}</span></header>
        <fieldset disabled={Boolean(busy)}>
          <div className="style-admin-fields"><label>风格名称<input required maxLength={60} value={draft.name} onChange={event => change("name", event.target.value)} /></label><label>分类<input required list="style-admin-categories" maxLength={40} value={draft.category} onChange={event => change("category", event.target.value)} /><datalist id="style-admin-categories">{[...new Set(items.map(item => item.category))].map(name => <option key={name} value={name} />)}</datalist></label>
            <label>标签（逗号分隔）<input value={draft.tags.join("，")} onChange={event => change("tags", event.target.value.split(/[,，]/).slice(0, 12))} /></label><label>排序<input type="number" min={0} max={10000} value={draft.sort_order} onChange={event => change("sort_order", Number(event.target.value))} /></label></div>
          <label>简短说明<textarea rows={2} maxLength={400} value={draft.description} onChange={event => change("description", event.target.value)} /></label>
          <div className="style-admin-media"><StyleCover src={draft.cover_url} name="风格封面" /><div><label className="style-upload"><UploadSimple size={18} />{busy === "upload" ? "正在上传并处理…" : "上传封面"}<input type="file" accept="image/jpeg,image/png,image/webp" onChange={event => void upload(event)} /></label><p>JPG / PNG / WebP，最大 10 MB。封面仅展示，不传给生成模型。</p></div></div>
          <details><summary>效果示例（最多 4 张）</summary><div className="style-samples">{draft.sample_ids.map((id, index) => <div key={id}><StyleCover src={draft.sample_urls?.[index] || `/api/v1/admin/visual-styles/media/${id}`} /><IconButton label={`移除示例 ${index + 1}`} onClick={() => setDraft(current => ({ ...current, sample_ids: current.sample_ids.filter(value => value !== id), sample_urls: (current.sample_urls || []).filter((_, number) => number !== index) }))}><X /></IconButton></div>)}</div>{draft.sample_ids.length < 4 && <label className="style-upload">上传示例<input type="file" accept="image/jpeg,image/png,image/webp" onChange={event => void upload(event, true)} /></label>}</details>
          <div className="style-admin-types"><span>适用于</span>{[["image", "图片"], ["video", "视频"]].map(([key, name]) => <label key={key}><input type="checkbox" checked={draft.applies_to.includes(key)} onChange={event => change("applies_to", event.target.checked ? [...draft.applies_to, key] : draft.applies_to.filter(part => part !== key))} />{name}</label>)}</div>
          <div className="style-admin-fields">{[["image", "图片"], ["video", "视频"]].filter(([key]) => draft.applies_to.includes(key)).map(([key, name]) => <div key={key} className="style-admin-prompt"><label>{name}风格提示词<textarea required rows={8} maxLength={6000} value={draft[`${key}_prompt`]} placeholder={key === "image" ? "用中文描述光照、色彩、材质与摄影表现" : "用中文描述视觉表现与运动质感，不改变镜头要求"} onChange={event => change(`${key}_prompt`, event.target.value)} /></label><label>{name}避免项<textarea rows={3} maxLength={2000} value={draft[`${key}_negative`]} onChange={event => change(`${key}_negative`, event.target.value)} /></label></div>)}</div>
        </fieldset>
        <footer className="style-admin-actions"><Button type="submit" loading={busy === "save"} disabled={Boolean(busy) || !draft.applies_to.length}>保存草稿</Button><Button variant="quiet" disabled={Boolean(busy)} onClick={() => { setDraft(selected ? { ...selected } : null); setError(""); }}>取消修改</Button><Button variant="primary" loading={busy === "publish"} disabled={Boolean(busy) || dirty || !selected || !draft.cover_id} onClick={() => void action("publish")}>发布新版本</Button>{selected?.enabled && <Button variant="warning" loading={busy === "disable"} disabled={Boolean(busy) || dirty} onClick={() => void action("disable")}>停用</Button>}</footer>
      </form> : <p className="style-admin-empty">选择一个风格进行编辑，或新建风格。</p>}
    </div>
  </section>;
}
