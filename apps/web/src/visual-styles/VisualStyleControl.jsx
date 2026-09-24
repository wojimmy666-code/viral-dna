import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle, Heart, ImageSquare, MagnifyingGlass, Palette, X } from "@phosphor-icons/react";
import { Button, IconButton } from "../ui/system/Button.jsx";
import { mediaUrl } from "../accounts/account-client.js";
import { ORIGINAL_STYLE, hasVisualStyle, filterStyles, visualStyleKey } from "./visual-style.js";
import "./visual-style.css";

const BASE = "/me/settings/visual-styles";
const json = body => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(15000) });

export function StyleCover({ src, name = "", className = "" }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return <span className={`style-cover ${className}`}>
    {src && !failed ? <img src={mediaUrl(src)} alt={name} loading="lazy" decoding="async" onError={() => setFailed(true)} />
      : <span className="style-cover-missing"><ImageSquare size={24} /><span>待添加预览</span></span>}
  </span>;
}

function StylePicker({ catalog, loading, error: loadError, onReload, initial, allowInherit, inheritedSnapshot, part, onApply, onClose, request, onCatalogChange }) {
  const ref = useRef(null), submitting = useRef(false), mounted = useRef(false);
  const titleId = useId();
  const [query, setQuery] = useState(""), [tab, setTab] = useState("all"), [category, setCategory] = useState("");
  const [selected, setSelected] = useState(initial);
  const [saving, setSaving] = useState(false), [error, setError] = useState("");
  const [favoriteBusy, setFavoriteBusy] = useState("");
  const items = catalog?.items || [];
  const selectedItem = items.find(item => item.id === selected?.catalog_id);
  const visible = filterStyles(items, { query, tab, category, part });
  const selectedKey = visualStyleKey(selected);
  const validSelection = !selected?.catalog_id || Boolean(selectedItem);
  useEffect(() => {
    mounted.current = true;
    const opener = document.activeElement, dialog = ref.current;
    const overflow = document.body.style.overflow;
    dialog.showModal(); document.body.style.overflow = "hidden";
    return () => { mounted.current = false; dialog.close(); document.body.style.overflow = overflow; opener?.focus?.(); };
  }, []);
  async function apply() {
    if (submitting.current || !validSelection) return;
    submitting.current = true; setSaving(true); setError("");
    try {
      const compiled = selected === null ? {} : await request(`${BASE}/preview`, json(selected));
      if (!mounted.current) return;
      if (hasVisualStyle(selected) && !compiled?.selection) throw new Error("风格结果无效，请重新读取后选择");
      await onApply(selected, compiled);
      if (!mounted.current) return;
      if (selected?.catalog_id) void request(`${BASE}/${selected.catalog_id}/used`, { method: "POST" }).catch(() => {});
      onClose();
    } catch (failure) { if (mounted.current) setError(failure.message || "风格应用失败，请重试"); }
    finally { submitting.current = false; if (mounted.current) setSaving(false); }
  }
  async function favorite(item) {
    if (favoriteBusy) return;
    setFavoriteBusy(item.id); setError("");
    try {
      await request(`${BASE}/${item.id}/favorite`, { ...json({ favorite: !item.favorite }), method: "PUT" });
      if (mounted.current) onCatalogChange(current => ({ ...current, items: current.items.map(value => value.id === item.id ? { ...value, favorite: !item.favorite } : value) }));
    } catch (failure) { if (mounted.current) setError(failure.message || "收藏失败，请重试"); }
    finally { if (mounted.current) setFavoriteBusy(""); }
  }
  const close = () => { if (!submitting.current) onClose(); };
  return createPortal(<dialog ref={ref} className="style-picker-dialog" aria-labelledby={titleId}
    onCancel={event => { event.preventDefault(); close(); }} onClick={event => { if (event.target === ref.current) close(); }}>
    <div className="style-picker-layout">
      <header className="style-picker-header"><h2 id={titleId}>选择风格</h2><IconButton label="关闭风格选择" onClick={close} disabled={saving}><X /></IconButton></header>
      <div className="style-picker-tools">
        <div className="style-picker-tabs" role="group" aria-label="风格范围">{[["all", "全部风格"], ["favorites", "我的收藏"], ["recent", "最近使用"]].map(([key, name]) => <button data-ui="tab" type="button" key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{name}</button>)}</div>
        <label className="style-picker-search"><MagnifyingGlass size={18} /><input autoFocus type="search" aria-label="搜索风格名称或标签" placeholder="搜索风格名称、标签" value={query} onChange={event => setQuery(event.target.value)} /></label>
      </div>
      <div className="style-picker-categories" role="group" aria-label="风格分类">{["", ...new Set(items.map(item => item.category))].map(name => <button key={name} data-ui="filter" type="button" aria-pressed={category === name} onClick={() => setCategory(name)}>{name || "全部"}</button>)}</div>
      <div className="style-picker-content" aria-busy={loading}>
        {loading ? <p role="status">正在读取风格库…</p> : loadError ? <div role="alert" className="style-picker-empty"><p>{loadError}</p><Button onClick={onReload}>重新读取</Button></div> : <>
          {!visible.length && <p className="style-picker-empty">{query || category ? "没有找到匹配的风格" : tab === "favorites" ? "还没有收藏风格" : tab === "recent" ? "还没有使用记录" : "管理员尚未发布风格"}</p>}
          <div className="style-picker-grid">{visible.map(item => {
            const checked = selected?.catalog_id === item.id && selected?.catalog_version === item.version;
            return <article key={item.id} className={`style-picker-card${checked ? " is-selected" : ""}`}>
              <button type="button" data-ui="selection-card" className="style-card-choice" aria-label={`选择${item.name}`} aria-pressed={checked} disabled={saving} onClick={() => { setSelected(item.selection); setError(""); }}>
                <StyleCover src={item.cover_url} name={`${item.name}风格示例`} />
                <span className="style-card-name">{item.name}{checked && <CheckCircle size={18} weight="fill" />}</span>
                <span className="style-card-scope">{item.applies_to.map(value => value === "image" ? "图片" : "视频").join(" / ")}</span>
              </button>
              <IconButton className="style-card-favorite" label={`${item.favorite ? "取消收藏" : "收藏"}${item.name}`} aria-pressed={item.favorite} disabled={Boolean(favoriteBusy) || saving} onClick={() => void favorite(item)}><Heart weight={item.favorite ? "fill" : "regular"} /></IconButton>
            </article>;
          })}</div>
        </>}
      </div>
      <footer className="style-picker-footer">
        <p className="visual-style-status">封面为风格示意，不作为生成参考图。</p>
        {error && <p className="visual-style-error" role="alert">{error}</p>}
        <div className="style-picker-selection">
          <div className="style-picker-reset">
            {allowInherit && <Button variant="quiet" size="compact" disabled={saving} aria-pressed={selected === null} onClick={() => setSelected(null)}>继承整片{inheritedSnapshot?.label ? ` · ${inheritedSnapshot.label}` : ""}</Button>}
            <Button variant="quiet" size="compact" disabled={saving} aria-pressed={selectedKey === visualStyleKey(ORIGINAL_STYLE)} onClick={() => setSelected(ORIGINAL_STYLE)}>不附加风格</Button>
          </div>
          <div className="style-picker-actions"><Button disabled={saving} onClick={close}>取消</Button><Button variant="primary" loading={saving} loadingLabel="正在应用…" disabled={!validSelection || loading || Boolean(loadError)} onClick={() => void apply()}>使用此风格</Button></div>
        </div>
        {selectedItem && <details className="style-picker-description"><summary>{selectedItem.name} · 查看风格说明</summary><p>{selectedItem.description}</p>{selectedItem.sample_urls?.length > 0 && <div className="style-samples">{selectedItem.sample_urls.map(src => <StyleCover key={src} src={src} name="风格效果示例" />)}</div>}<p className="visual-style-rules">{part === "video" ? selectedItem.video_prompt : selectedItem.image_prompt}</p></details>}
      </footer>
    </div>
  </dialog>, document.body);
}

export function VisualStyleControl({ value = ORIGINAL_STYLE, snapshot, inheritedSnapshot, request, onChange, onPending, onAvailable, disabled = false, label = "风格", allowInherit = false, part }) {
  const callbacks = useRef({ onChange, onPending, onAvailable });
  callbacks.current = { onChange, onPending, onAvailable };
  const [catalog, setCatalog] = useState(null), [error, setError] = useState("");
  const [loading, setLoading] = useState(true), [reload, setReload] = useState(0), [open, setOpen] = useState(false), [pending, setPending] = useState(false);
  const alive = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; callbacks.current.onPending?.(false); }; }, []);
  useEffect(() => {
    let active = true;
    setLoading(true); setError("");
    request(BASE).then(result => {
      if (!active) return;
      if (result?.version !== "visual-style-library-v1" || !Array.isArray(result.items)) throw new Error("请更新并重启服务后重新读取风格库");
      setCatalog(result); callbacks.current.onAvailable?.(true);
    }).catch(failure => { if (active) { setError(failure.message || "风格库读取失败"); callbacks.current.onAvailable?.(false); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [request, reload]);
  async function apply(next, compiled) {
    setPending(true); callbacks.current.onPending?.(true);
    try { await callbacks.current.onChange?.(next, compiled); }
    finally { if (alive.current) { setPending(false); callbacks.current.onPending?.(false); } }
  }
  const effective = value === null ? inheritedSnapshot : snapshot;
  const known = catalog?.items.find(item => item.id === value?.catalog_id && item.version === value?.catalog_version);
  const selected = hasVisualStyle(value) || (value === null && effective?.label);
  const name = effective?.label || known?.name || (value?.catalog_id ? "已选风格" : "原有风格");
  const showPicker = () => { setOpen(true); setReload(count => count + 1); };
  return <div className="visual-style-control" aria-label={label}>
    <div className="visual-style-row">
      <Button variant="quiet" size="compact" icon={<Palette size={18} />} disabled={disabled || pending} onClick={showPicker} aria-haspopup="dialog">{label}</Button>
      {selected && <div className="style-selected">
        <button data-ui="style-thumbnail" className="style-selected-choice" type="button" disabled={disabled || pending} onClick={showPicker} aria-label={`更换${label}：${name}`} title={name}>
          <StyleCover src={effective?.cover_url || known?.cover_url} name="" /><span className="style-selected-kind">风格</span>
        </button>
        <span className="style-selected-name">{name}{value === null && <small>继承整片</small>}</span>
        <IconButton label={`移除${label}`} size="compact" disabled={disabled || pending} onClick={() => { void apply(ORIGINAL_STYLE, {}).catch(failure => setError(failure.message)); }}><X size={16} /></IconButton>
      </div>}
      {!selected && allowInherit && value === null && <span className="visual-style-status">继承整片</span>}
      {pending && <span className="visual-style-status" role="status">正在保存风格…</span>}
    </div>
    {error && !open && <p role="alert" className="visual-style-error">{error}<Button variant="text" size="compact" onClick={showPicker}>重新读取</Button></p>}
    {open && <StylePicker catalog={catalog} loading={loading} error={error} onReload={() => setReload(count => count + 1)} initial={value}
      allowInherit={allowInherit} inheritedSnapshot={inheritedSnapshot} part={part} onApply={apply} onClose={() => setOpen(false)} request={request} onCatalogChange={setCatalog} />}
  </div>;
}
