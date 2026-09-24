import { Button } from "../ui/system/Button.jsx";
import { cloneElement, forwardRef, useEffect, useId, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, CaretRight, FolderSimple, ImageSquare, Plus, UserCircle, VideoCamera, X } from "@phosphor-icons/react";
import { activeReferences, atomicDeletion, readReferenceDOM, referenceKey, referenceSegments, referenceToken, replaceReference, replacementRange } from "./reference-document.js";
import "./asset-reference-editor.css";

function offsets(root) {
  const selection = window.getSelection();
  if (!selection?.rangeCount || !root.contains(selection.anchorNode) || !root.contains(selection.focusNode)) return null;
  const position = (node, offset) => {
    const range = document.createRange();
    range.selectNodeContents(root); range.setEnd(node, offset);
    return readReferenceDOM(range.cloneContents()).length;
  };
  return { start: position(selection.anchorNode, selection.anchorOffset), end: position(selection.focusNode, selection.focusOffset) };
}

function setSelection(root, start, end = start) {
  if (!root) return;
  function point(offset) {
    let remaining = Math.max(0, offset);
    for (const node of root.childNodes) {
      const token = node.dataset?.referenceToken;
      const length = token ? token.length : node.textContent.length;
      if (remaining <= length) {
        if (!token) return [node, remaining];
        const index = [...root.childNodes].indexOf(node);
        return [root, index + (remaining > 0 ? 1 : 0)];
      }
      remaining -= length;
    }
    return [root, root.childNodes.length];
  }
  const selection = window.getSelection();
  selection.setBaseAndExtent(...point(start), ...point(end));
}

function Thumbnail({ reference, resolveUrl }) {
  const source = reference.thumbnail_url || reference.preview_url;
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [source]);
  return source && !failed ? <img src={resolveUrl?.(source) || source} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} /> : <ImageSquare size={18} />;
}

export const AssetReferenceEditor = forwardRef(function AssetReferenceEditor({
  value = "", references = [], options = [], onChange, onBlur, onAddAssets, onAddManagedAssets, resolveUrl,
  disabled = false, label = "提示词", placeholder = "描述画面；输入 @ 引用项目已选资产", rows = 8,
  maxLength = 8000, indexOffset = 0, labelledBy, styleControl,
  referenceLimit, reservedReferenceCount = 0, reservedReferenceIds = [],
}, forwardedRef) {
  const editorRef = useRef(null);
  const readOnlyRef = useRef(disabled);
  readOnlyRef.current = disabled;
  const wrapperRef = useRef(null);
  const popupRef = useRef(null);
  const composing = useRef(false);
  const local = useRef({ value, references });
  const history = useRef([{ value, references }]);
  const historyIndex = useRef(0);
  const caret = useRef(null);
  const renderedReferences = useRef(null);
  const lastTyping = useRef(0);
  const dismissTimer = useRef(null);
  const [popup, setPopup] = useState(null);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [menuSection, setMenuSection] = useState(null);
  const [selected, setSelected] = useState(null);
  const [renderTick, setRenderTick] = useState(0);
  const popupId = useId();
  const optionMap = useMemo(() => new Map(options.map((item) => [referenceKey(item), item])), [options]);
  const visible = activeReferences(value, references).map((item, index) => ({
    ...optionMap.get(referenceKey(item)), ...item,
    number: item.number ?? indexOffset + index + 1,
  }));
  const visibleKey = JSON.stringify(visible);
  const matching = [...optionMap.values()].filter((item) => item.available !== false && (!query ||
    `${item.label} ${item.description || ""}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())));
  const isVideo = (item) => ['reference_video', 'video'].includes(item.reference_kind || item.media_kind);
  const menuReferences = menuSection ? matching.filter((item) => menuSection === 'video' ? isVideo(item) : !isVideo(item))
    : matching.filter((item) => visible.some((reference) => referenceKey(reference) === referenceKey(item)));
  const categories = menuSection ? [] : [
    { key: 'image', label: '图片', icon: ImageSquare },
    ...(options.some(isVideo) ? [{ key: 'video', label: '视频', icon: VideoCamera }] : []),
    ...(onAddAssets ? [{ key: 'library', label: '资产', icon: FolderSimple }] : []),
    ...(onAddManagedAssets ? [{ key: 'managed', label: '从托管资产目录选择', icon: UserCircle }] : []),
  ];
  const menuCount = menuReferences.length + categories.length;

  useImperativeHandle(forwardedRef, () => ({
    focus: () => editorRef.current?.focus(),
    setSelectionRange: (start, end) => setSelection(editorRef.current, start, end),
    get selectionStart() { return offsets(editorRef.current)?.start ?? 0; },
    get selectionEnd() { return offsets(editorRef.current)?.end ?? 0; },
  }));

  useLayoutEffect(() => {
    if (composing.current) return;
    const root = editorRef.current;
    const focused = document.activeElement === root;
    const selection = caret.current || (focused ? offsets(root) : null);
    if (local.current.value !== value) {
      history.current = [{ value, references }]; historyIndex.current = 0;
    }
    local.current = { value, references };
    // Ordinary typing already updated the DOM. Rebuilding it here scrolls long
    // editors and can displace the caret/IME while parent autosave echoes input.
    if (renderedReferences.current === visibleKey && readReferenceDOM(root) === value) {
      const currentSelection = focused ? offsets(root) : null;
      if (focused && caret.current && (currentSelection?.start !== caret.current.start || currentSelection?.end !== caret.current.end)) {
        setSelection(root, Math.min(caret.current.start, value.length), Math.min(caret.current.end, value.length));
      }
      caret.current = null;
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const segment of referenceSegments(value, visible)) {
      if (!segment.reference) { fragment.append(document.createTextNode(segment.text)); continue; }
      const reference = segment.reference;
      const token = document.createElement("span");
      token.contentEditable = "false"; token.className = "asset-reference-token";
      token.dataset.referenceToken = segment.text;
      token.dataset.referenceKey = referenceKey(reference);
      token.tabIndex = 0; token.setAttribute("role", "button");
      token.setAttribute("aria-label", `图片 ${reference.number}，${reference.label}，查看引用`);
      token.title = reference.label;
      if (reference.available === false) token.classList.add("unavailable");
      const source = reference.thumbnail_url || reference.preview_url;
      if (source) {
        const img = document.createElement("img"); img.alt = ""; img.loading = "lazy"; img.decoding = "async";
        img.src = resolveUrl?.(source) || source; img.onerror = () => { img.hidden = true; };
        token.append(img);
      }
      const text = document.createElement("span");
      text.textContent = `图片${reference.number}`;
      token.append(text); fragment.append(token);
    }
    if (!fragment.childNodes.length) fragment.append(document.createTextNode(""));
    root.replaceChildren(fragment);
    renderedReferences.current = visibleKey;
    if (focused && selection) setSelection(root, Math.min(selection.start, value.length), Math.min(selection.end, value.length));
    caret.current = null;
  }, [value, visibleKey, renderTick, resolveUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!popup) return undefined;
    function outside(event) {
      if (!wrapperRef.current?.contains(event.target) && !popupRef.current?.contains(event.target)) setPopup(null);
    }
    document.addEventListener("pointerdown", outside);
    const reposition = (event) => {
      if (popup.kind === 'menu') positionPopup();
      else if (!popupRef.current?.contains(event.target)) setPopup(null);
    };
    window.addEventListener('resize', reposition);
    document.addEventListener('scroll', reposition, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener('resize', reposition);
      document.removeEventListener('scroll', reposition, true);
    };
  }, [popup]);

  useEffect(() => () => clearTimeout(dismissTimer.current), []);
  useEffect(() => {
    if (popup?.kind !== 'menu') return;
    const list = document.getElementById(popupId);
    const option = document.getElementById(`${popupId}-${activeIndex}`);
    if (!list || !option) return;
    const viewport = list.getBoundingClientRect(), item = option.getBoundingClientRect();
    // Never scroll ancestors: scrollIntoView can move the page and used to
    // immediately trigger the document-level popup dismissal listener.
    if (item.top < viewport.top) list.scrollTop += item.top - viewport.top;
    else if (item.bottom > viewport.bottom) list.scrollTop += item.bottom - viewport.bottom;
  }, [activeIndex, popup?.kind, popupId, menuCount]);
  function caretRect() {
    const selection = window.getSelection();
    if (selection?.rangeCount && editorRef.current?.contains(selection.focusNode)) {
      const range = selection.getRangeAt(0).cloneRange();
      range.collapse(false);
      const rect = range.getBoundingClientRect();
      if (rect.height) return rect;
    }
    return null;
  }
  function positionPopup() {
    if (!popup || !popupRef.current) return;
    const panel = popupRef.current;
    const box = panel.getBoundingClientRect();
    const anchor = popup.kind === 'menu' ? (caretRect() || popup.anchor || editorRef.current?.getBoundingClientRect()) : null;
    const desiredLeft = anchor?.left ?? popup.left;
    let desiredTop = anchor ? anchor.bottom + 4 : popup.top;
    if (anchor && desiredTop + box.height > window.innerHeight - 8) desiredTop = anchor.top - box.height - 4;
    const left = Math.max(8, Math.min(desiredLeft, window.innerWidth - box.width - 8));
    const top = Math.max(8, Math.min(desiredTop, window.innerHeight - box.height - 8));
    panel.style.left = `${left}px`; panel.style.top = `${top}px`;
  }
  useLayoutEffect(() => {
    positionPopup();
    if (popup?.kind === 'menu' && popup.replacing) popupRef.current?.querySelector('input')?.focus({ preventScroll: true });
  }, [popup, menuCount, menuSection]);

  function commit(nextValue, nextReferences = local.current.references, position, typing = false) {
    if (disabled || nextValue.length > maxLength) { setRenderTick((tick) => tick + 1); return; }
    const next = { value: nextValue, references: activeReferences(nextValue, nextReferences) };
    const now = Date.now();
    const merging = typing && now - lastTyping.current < 600 && historyIndex.current > 0
      && JSON.stringify(next.references) === JSON.stringify(local.current.references);
    history.current = history.current.slice(0, historyIndex.current + 1);
    if (merging) history.current[historyIndex.current] = next;
    else { history.current.push(next); historyIndex.current += 1; }
    if (history.current.length > 100) { history.current.shift(); historyIndex.current -= 1; }
    lastTyping.current = typing ? now : 0;
    local.current = next; caret.current = position;
    onChange(nextValue, next.references);
    setRenderTick((tick) => tick + 1);
  }

  function open(reference, target, hover = false) {
    if (!reference) return;
    clearTimeout(dismissTimer.current);
    const rect = (target || wrapperRef.current).getBoundingClientRect();
    setPopup((current) => current?.kind === 'reference' && referenceKey(current.reference) === referenceKey(reference) && (hover || !current.hover)
      ? current : { kind: "reference", reference, hover, left: rect.left, top: rect.bottom + 4 });
    setSelected(referenceKey(reference));
  }

  function dismissPreview() {
    clearTimeout(dismissTimer.current);
    dismissTimer.current = setTimeout(() => setPopup((current) => current?.hover ? null : current), 180);
  }

  function dismissReference() {
    clearTimeout(dismissTimer.current);
    setPopup((current) => current?.kind === 'reference' ? null : current);
  }

  function inputReference(target) {
    const token = target.closest?.('[data-reference-key]');
    return token && editorRef.current?.contains(token) ? token : null;
  }

  function menu(range, replacing = null) {
    const rect = caretRect() || editorRef.current.getBoundingClientRect();
    setQuery(""); setActiveIndex(0); setMenuSection(replacing ? 'image' : popup?.kind === 'menu' ? menuSection : null);
    setPopup({ kind: "menu", range, replacing, anchor: rect, left: rect.left, top: rect.bottom + 4 });
  }

  function insert(reference) {
    if (atReferenceLimit(reference)) return;
    const current = local.current;
    if (popup.replacing) {
      const next = replaceReference(current.value, current.references, popup.replacing, reference);
      commit(next.value, next.references);
    } else {
      const range = popup.range || { start: current.value.length, end: current.value.length };
      const token = referenceToken(reference);
      commit(current.value.slice(0, range.start) + token + " " + current.value.slice(range.end),
        [...current.references, reference], { start: range.start + token.length + 1, end: range.start + token.length + 1 });
    }
    setPopup(null); editorRef.current.focus({ preventScroll: true });
  }

  function atReferenceLimit(reference) {
    if (!Number.isFinite(referenceLimit) || reference.reference_kind === 'reference_video') return false;
    const keys = new Set([...reservedReferenceIds, ...visible.filter(item => item.reference_kind !== 'reference_video' && referenceKey(item) !== referenceKey(popup?.replacing || {})).map(item => item.reference_asset_id || item.reference_id)]);
    keys.add(reference.reference_asset_id || reference.reference_id);
    return keys.size + reservedReferenceCount > referenceLimit;
  }

  function addAsset(handler = onAddAssets) {
    const position = popup?.kind === 'menu' ? popup.range : offsets(editorRef.current);
    const range = position || { start: local.current.value.length, end: local.current.value.length };
    const capturedValue = local.current.value;
    const replacing = popup?.replacing;
    const restore = () => {
      if (!editorRef.current) return;
      editorRef.current.focus({ preventScroll: true });
      setSelection(editorRef.current, range.end);
    };
    setPopup(null);
    handler?.((selection) => {
      if (!editorRef.current) throw new Error('编辑位置已关闭，请重新选择提示词。');
      if (readOnlyRef.current) throw new Error('当前已变为只读，请取得编辑权限后重新引用。');
      const additions = (Array.isArray(selection) ? selection : [selection]).filter(Boolean);
      if (!additions.length) return;
      const current = local.current;
      if (current.value !== capturedValue) throw new Error('提示词已变化，请关闭资产库后重新选择插入位置。');
      const start = Math.min(range.start, range.end), end = Math.max(range.start, range.end);
      const token = additions.map(referenceToken).join(' ') + ' ';
      const next = replacing ? replaceReference(current.value, current.references, replacing, additions[0])
        : { value: current.value.slice(0, start) + token + current.value.slice(end), references: [...current.references, ...additions] };
      if (next.value.length > maxLength) throw new Error(`加入引用后超过 ${maxLength} 字，请减少选择或缩短提示词。`);
      editorRef.current.focus({ preventScroll: true });
      commit(next.value, next.references, replacing ? undefined : { start: start + token.length, end: start + token.length });
      setTimeout(() => {
        if (!editorRef.current) return;
        editorRef.current.focus({ preventScroll: true });
        if (!replacing) setSelection(editorRef.current, start + token.length);
      }, 0);
    }, {
      query: popup?.kind === 'menu' ? query : '', selectedIds: [...new Set([...reservedReferenceIds, ...visible.filter(item => item.reference_kind !== 'reference_video' && referenceKey(item) !== referenceKey(replacing || {})).map((item) => item.reference_asset_id || item.reference_id)])],
      referenceLimit, reservedReferenceCount, maxSelection: replacing ? 1 : undefined, onCancel: restore,
    });
  }

  function input() {
    if (composing.current) return;
    const text = readReferenceDOM(editorRef.current);
    const position = offsets(editorRef.current);
    commit(text, local.current.references, position, true);
    const start = position?.start ?? text.length;
    const match = text.slice(0, start).match(/@([^@\n，。,；;]*)$/);
    const insideReference = referenceSegments(text, local.current.references).some((item) => item.reference && start > item.start && start <= item.start + item.text.length);
    if (match && !insideReference) { menu({ start: start - match[0].length, end: start }); setQuery(match[1]); }
    else if (popup?.kind === "menu") setPopup(null);
  }

  function editSelection(text) {
    const current = local.current;
    const position = offsets(editorRef.current) || { start: current.value.length, end: current.value.length };
    const start = Math.min(position.start, position.end), end = Math.max(position.start, position.end);
    const range = replacementRange(current.value, current.references, start, end);
    commit(current.value.slice(0, range.start) + text + current.value.slice(range.end), current.references,
      { start: range.start + text.length, end: range.start + text.length });
  }

  function keyDown(event) {
    if (event.isComposing || composing.current) return;
    const token = event.target.closest?.('[data-reference-key]');
    if (token && ['Enter', ' '].includes(event.key)) {
      event.preventDefault(); open(visible.find((item) => referenceKey(item) === token.dataset.referenceKey), token); return;
    }
    if (disabled) return;
    if ((event.ctrlKey || event.metaKey) && ['z', 'y'].includes(event.key.toLowerCase())) {
      event.preventDefault();
      const direction = event.shiftKey || event.key.toLowerCase() === 'y' ? 1 : -1;
      const index = Math.max(0, Math.min(history.current.length - 1, historyIndex.current + direction));
      historyIndex.current = index; const next = history.current[index]; local.current = next;
      onChange(next.value, next.references); setRenderTick((tick) => tick + 1); setPopup(null); return;
    }
    if (event.key === 'Escape') { setPopup(null); return; }
    if (menuKeyDown(event)) return;
    if (event.key === 'Enter') { event.preventDefault(); editSelection('\n'); return; }
    if (['Backspace', 'Delete'].includes(event.key)) {
      const position = offsets(editorRef.current);
      if (!position) return;
      const start = Math.min(position.start, position.end), end = Math.max(position.start, position.end);
      const range = atomicDeletion(value, references, start, end, event.key === 'Backspace');
      if (range.start !== start || range.end !== end) {
        event.preventDefault(); commit(value.slice(0, range.start) + value.slice(range.end), references, { start: range.start, end: range.start });
      }
    }
  }

  function menuKeyDown(event) {
    if (event.isComposing || composing.current || popup?.kind !== 'menu' || !['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) return false;
    event.preventDefault();
    if (event.key === 'Enter') {
      if (menuReferences[activeIndex]) insert(menuReferences[activeIndex]);
      else if (categories[activeIndex - menuReferences.length]) chooseCategory(categories[activeIndex - menuReferences.length].key);
    }
    else setActiveIndex((index) => Math.max(0, Math.min(menuCount - 1, index + (event.key === 'ArrowDown' ? 1 : -1))));
    return true;
  }
  function chooseCategory(key) {
    if (key === 'library') addAsset();
    else if (key === 'managed') addAsset(onAddManagedAssets);
    else { setMenuSection(key); setActiveIndex(0); }
  }

  function copy(event, cut = false) {
    const position = offsets(editorRef.current); if (!position || position.start === position.end) return;
    const range = replacementRange(value, references, position.start, position.end);
    event.preventDefault();
    event.clipboardData.setData('text/plain', value.slice(range.start, range.end));
    if (cut && !disabled) commit(value.slice(0, range.start) + value.slice(range.end), references, { start: range.start, end: range.start });
  }

  const referenceThumbnails = visible.map((reference) => <button type="button" key={referenceKey(reference)}
    className={`asset-reference-thumbnail${selected === referenceKey(reference) ? ' active' : ''}`}
    aria-label={`图片 ${reference.number}，${reference.label}`} onClick={(event) => open(reference, event.currentTarget)}
    onFocus={(event) => open(reference, event.currentTarget, true)} onBlur={dismissPreview}
    onMouseLeave={dismissPreview} onMouseEnter={(event) => open(reference, event.currentTarget, true)}>
    <Thumbnail reference={reference} resolveUrl={resolveUrl} /><span>{reference.number}</span>
  </button>);
  // Keep one mounted style control; only compose its display slots around the asset rail.
  // Style covers remain prompt metadata, never numbered generation references.
  const renderReferenceLayout = ({ trigger, thumbnail, status }) => <>
    <div className="prompt-style-tools">
      {onAddAssets && <Button variant="quiet" size="compact" disabled={disabled} onClick={() => addAsset()} icon={<Plus size={16} />}>添加参考</Button>}
      {trigger}{status}
    </div>
    {(thumbnail || visible.length > 0) && <div className="asset-reference-rail" aria-label={`${label}风格与引用图片`}>
      {thumbnail}{referenceThumbnails}
    </div>}
  </>;

  return <div className={`asset-reference-editor${disabled ? ' disabled' : ''}`} ref={wrapperRef}
    onKeyDownCapture={(event) => {
      if (event.key === 'Escape' && popup) {
        event.preventDefault(); event.stopPropagation(); clearTimeout(dismissTimer.current);
        setPopup(null); editorRef.current?.focus({ preventScroll: true });
      }
    }}>
    {styleControl ? cloneElement(styleControl, { renderLayout: renderReferenceLayout }) : renderReferenceLayout({})}
    <div ref={editorRef} className="asset-reference-input" role="textbox" aria-label={label} aria-labelledby={labelledBy} aria-multiline="true"
      aria-disabled={disabled} contentEditable={!disabled} suppressContentEditableWarning tabIndex={0}
      aria-controls={popup?.kind === 'menu' ? popupId : undefined} aria-autocomplete="list"
      aria-activedescendant={popup?.kind === 'menu' && menuCount > activeIndex ? `${popupId}-${activeIndex}` : undefined}
      data-placeholder={placeholder} data-empty={!value} style={{ '--editor-rows': rows }}
      onInput={input} onKeyDown={keyDown}
      onCompositionStart={() => { composing.current = true; }}
      onCompositionEnd={() => { composing.current = false; input(); }}
      onBlur={(event) => { if (!composing.current && !popupRef.current?.contains(event.relatedTarget)) { onBlur?.(); dismissPreview(); } }}
      onPaste={(event) => { event.preventDefault(); editSelection(event.clipboardData.getData('text/plain')); }}
      onCopy={(event) => copy(event)} onCut={(event) => copy(event, true)}
      onDrop={(event) => event.preventDefault()}
      onPointerDown={(event) => { if (!inputReference(event.target)) dismissReference(); }}
      onFocus={(event) => { const token = inputReference(event.target); if (token) open(visible.find((item) => referenceKey(item) === token.dataset.referenceKey), token, true); else dismissReference(); }}
      onClick={(event) => { const token = inputReference(event.target); if (token) open(visible.find((item) => referenceKey(item) === token.dataset.referenceKey), token); else dismissReference(); }}
      onMouseOver={(event) => { const token = inputReference(event.target); if (token) open(visible.find((item) => referenceKey(item) === token.dataset.referenceKey), token, true); }}
      onMouseOut={(event) => { if (inputReference(event.target) && !event.relatedTarget?.closest?.('[data-reference-key]')) dismissPreview(); }}
    />
    {popup && createPortal(<div className="asset-reference-popover" ref={popupRef} style={{ left: popup.left, top: popup.top }}
      onMouseEnter={() => clearTimeout(dismissTimer.current)} onMouseLeave={dismissPreview}
      onFocus={() => clearTimeout(dismissTimer.current)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) dismissPreview(); }}
      onKeyDown={(event) => { if (event.key === 'Escape') { setPopup(null); editorRef.current?.focus(); } else menuKeyDown(event); }}>
      {popup.kind === 'reference' ? <>
        <button className="asset-reference-close" aria-label="关闭引用预览" type="button" onClick={() => { setPopup(null); editorRef.current?.focus({ preventScroll: true }); }}><X size={16} /></button>
        <div className="asset-reference-preview"><Thumbnail reference={popup.reference} resolveUrl={resolveUrl} /></div>
        <strong>{popup.reference.label}</strong>
        {popup.reference.description && <p>{popup.reference.description}</p>}
        {popup.reference.available === false && <p role="status">此引用暂不可用，请重新选择</p>}
        <div className="asset-reference-actions">
          <Button className="secondary-button compact" type="button" onClick={() => {
            const start = value.indexOf(referenceToken(popup.reference)); setPopup(null); editorRef.current.focus();
            setSelection(editorRef.current, start, start + referenceToken(popup.reference).length);
          }}>定位</Button>
          <Button className="secondary-button compact" disabled={disabled} type="button" onClick={() => menu(null, popup.reference)}>替换</Button>
          <Button className="secondary-button compact" disabled={disabled} type="button" onClick={() => {
            const next = replaceReference(value, references, popup.reference, null); commit(next.value, next.references); setPopup(null);
          }}>移除</Button>
        </div>
      </> : <>
        <input aria-label="搜索项目已选资产" placeholder="搜索引用，或打开资产库" value={query} onChange={(event) => { setQuery(event.target.value); setActiveIndex(0); }} />
        {menuSection && <Button variant="quiet" size="compact" icon={<ArrowLeft size={16} />} onClick={() => { setMenuSection(null); setActiveIndex(0); }}>返回素材引用</Button>}
        <div role="listbox" id={popupId} aria-label="项目已选资产">
          {!menuSection && menuReferences.length > 0 && <p className="reference-menu-heading">已引用</p>}
          {menuSection && !menuReferences.length && <p>没有匹配的项目素材，可到资产库中选择。</p>}
          {menuReferences.map((reference, index) => <button data-ui="selection-card" id={`${popupId}-${index}`} type="button" role="option" aria-selected={activeIndex === index}
            key={referenceKey(reference)} disabled={atReferenceLimit(reference)} title={atReferenceLimit(reference) ? '已达到当前模型的参考图数量上限' : undefined} onMouseDown={(event) => event.preventDefault()} onClick={() => insert(reference)} onMouseEnter={() => setActiveIndex(index)}>
            <span className="asset-reference-option-image"><Thumbnail reference={reference} resolveUrl={resolveUrl} /></span>
            <span><strong>{reference.label}</strong>{reference.description && <small>{reference.description}</small>}</span>
          </button>)}
          {!menuSection && <p className="reference-menu-heading">素材引用</p>}
          {categories.map(({ key, label: name, icon: Icon }, index) => <button data-ui="selection-card" type="button" role="option"
            id={`${popupId}-${menuReferences.length + index}`} key={key} aria-selected={activeIndex === menuReferences.length + index}
            onMouseDown={(event) => event.preventDefault()} onClick={() => chooseCategory(key)} onMouseEnter={() => setActiveIndex(menuReferences.length + index)}>
            <Icon size={20} /><span>{name}</span><CaretRight size={16} className="reference-menu-chevron" />
          </button>)}
        </div>
        {onAddAssets && menuSection && <Button variant="quiet" type="button" onClick={() => addAsset()}>打开资产库</Button>}
      </>}
    </div>, editorRef.current?.closest('dialog') || document.body)}
  </div>;
});
