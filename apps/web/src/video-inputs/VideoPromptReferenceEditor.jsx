import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  FilmStrip,
  ImageSquare,
  MagnifyingGlass,
  UserCircle,
} from "@phosphor-icons/react";
import {
  buildVideoReferenceOptions,
  buildVideoPromptHighlightSegments,
  deleteVideoMentionAtSelection,
  ensureVideoGenerationReference,
  insertVideoMentionIntoPrompt,
  normalizeVideoPromptMentions,
  requiredSourceForVideoMention,
  selectedVideoReferenceOptions,
  videoMentionToken,
  videoReferenceRoleLabel,
  videoReferenceKey,
} from "./video-prompt-references.js";
import "./video-prompt-reference-editor.css";

function ReferenceThumbnail({ option, resolveUrl }) {
  const source = option.preview_url ? resolveUrl?.(option.preview_url) || option.preview_url : "";
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [source]);
  if (source && !failed) {
    return <img alt="" loading="lazy" onError={() => setFailed(true)} src={source} />;
  }
  if (option.reference_kind === "provider_managed_asset") return <UserCircle size={22} />;
  if (["depth_control", "reference_video"].includes(option.reference_kind)) {
    return <FilmStrip size={22} />;
  }
  return <ImageSquare size={22} />;
}

export function VideoPromptReferenceEditor({
  assets,
  depthAssets,
  managedAssetBinding,
  onChange,
  referenceFrames,
  resolveUrl,
  selectedReferences,
  value,
  videoPromptMentions,
  videoReferenceBindings,
}) {
  const editorId = useId();
  const menuId = `${editorId}-mentions`;
  const editorRootRef = useRef(null);
  const highlightRef = useRef(null);
  const promptRef = useRef(null);
  const [mentionMenu, setMentionMenu] = useState(null);
  const [activeOptionIndex, setActiveOptionIndex] = useState(0);
  const [selectionActive, setSelectionActive] = useState(false);
  const options = useMemo(() => buildVideoReferenceOptions({
    assets,
    depthAssets,
    managedAssetBinding,
    referenceFrames,
    videoReferenceBindings,
  }), [assets, depthAssets, managedAssetBinding, referenceFrames, videoReferenceBindings]);
  const selectedOptions = useMemo(
    () => selectedVideoReferenceOptions(options, selectedReferences),
    [options, selectedReferences],
  );
  const selectedKeys = useMemo(
    () => new Set((selectedReferences || []).map(videoReferenceKey)),
    [selectedReferences],
  );
  const quickOptions = useMemo(() => {
    const quickKinds = new Set(["provider_managed_asset", "depth_control"]);
    const quickKeys = new Set();
    return [...selectedOptions, ...options.filter((item) => quickKinds.has(item.reference_kind))]
      .filter((item) => {
        const key = videoReferenceKey(item);
        if (!key || quickKeys.has(key)) return false;
        quickKeys.add(key);
        return true;
      });
  }, [options, selectedOptions]);
  const mentionedKeys = useMemo(
    () => new Set((videoPromptMentions || []).map(videoReferenceKey)),
    [videoPromptMentions],
  );
  const filteredOptions = useMemo(() => {
    if (!mentionMenu) return [];
    const query = mentionMenu.query.trim().toLocaleLowerCase("zh-CN");
    return quickOptions.filter((item) => (
      !mentionedKeys.has(videoReferenceKey(item))
      && (!query || `${item.label} ${item.search_text}`.toLocaleLowerCase("zh-CN").includes(query))
    ));
  }, [mentionMenu, mentionedKeys, quickOptions]);
  const highlightSegments = useMemo(
    () => buildVideoPromptHighlightSegments(value, videoPromptMentions),
    [value, videoPromptMentions],
  );

  useEffect(() => {
    setActiveOptionIndex(0);
  }, [mentionMenu?.query]);

  useEffect(() => {
    if (!mentionMenu) return undefined;
    function dismissIfOutside(event) {
      if (!editorRootRef.current?.contains(event.target)) setMentionMenu(null);
    }
    function dismissOnWindowBlur() {
      setMentionMenu(null);
    }
    document.addEventListener("pointerdown", dismissIfOutside, true);
    document.addEventListener("focusin", dismissIfOutside, true);
    window.addEventListener("blur", dismissOnWindowBlur);
    return () => {
      document.removeEventListener("pointerdown", dismissIfOutside, true);
      document.removeEventListener("focusin", dismissIfOutside, true);
      window.removeEventListener("blur", dismissOnWindowBlur);
    };
  }, [Boolean(mentionMenu)]);

  function syncHighlightViewport(textarea = promptRef.current) {
    const highlight = highlightRef.current;
    if (!textarea || !highlight) return;
    highlight.scrollTop = textarea.scrollTop;
    highlight.scrollLeft = textarea.scrollLeft;
    const styles = window.getComputedStyle(textarea);
    const horizontalBorder = (
      (Number.parseFloat(styles.borderLeftWidth) || 0)
      + (Number.parseFloat(styles.borderRightWidth) || 0)
    );
    highlight.style.width = `${textarea.clientWidth + horizontalBorder}px`;
  }

  useEffect(() => {
    const textarea = promptRef.current;
    if (!textarea) return undefined;
    syncHighlightViewport(textarea);
    if (typeof ResizeObserver === "undefined") {
      const syncOnResize = () => syncHighlightViewport(textarea);
      window.addEventListener("resize", syncOnResize);
      return () => window.removeEventListener("resize", syncOnResize);
    }
    const observer = new ResizeObserver(() => syncHighlightViewport(textarea));
    observer.observe(textarea);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    syncHighlightViewport();
  }, [value]);

  function syncHighlightScroll(event) {
    syncHighlightViewport(event.currentTarget);
  }

  function updateSelectionState(event) {
    setSelectionActive(event.currentTarget.selectionStart !== event.currentTarget.selectionEnd);
  }

  function referenceStateAfterPromptChange(nextValue) {
    const nextMentions = normalizeVideoPromptMentions(
      nextValue,
      videoPromptMentions,
      options,
    );
    const nextMentionKeys = new Set(nextMentions.map(videoReferenceKey));
    const removedMentionKeys = new Set(
      (videoPromptMentions || [])
        .filter((mention) => !nextMentionKeys.has(videoReferenceKey(mention)))
        .map(videoReferenceKey),
    );
    const removedReferences = (selectedReferences || []).filter(
      (reference) => removedMentionKeys.has(videoReferenceKey(reference)),
    );
    return {
      videoPromptMentions: nextMentions,
      selectedReferences: (selectedReferences || []).filter(
        (reference) => !removedMentionKeys.has(videoReferenceKey(reference)),
      ),
      removedReferences,
    };
  }

  function updatePrompt(event) {
    const nextValue = event.target.value;
    const cursor = event.target.selectionStart ?? nextValue.length;
    const match = nextValue.slice(0, cursor).match(/@([^@\n,，。；;]*)$/);
    const matchedFragment = match?.[1] || "";
    const followsCompletedMention = (videoPromptMentions || []).some((mention) => {
      const label = String(mention.label || "").replace(/^@+/, "");
      return matchedFragment === label || matchedFragment.startsWith(`${label} `);
    });
    onChange({ videoPrompt: nextValue, ...referenceStateAfterPromptChange(nextValue) });
    setMentionMenu(match && !followsCompletedMention ? {
      start: cursor - match[1].length - 1,
      end: cursor,
      query: match[1],
    } : null);
  }

  function handlePromptKeyDown(event) {
    if (!event.isComposing && !event.nativeEvent?.isComposing) {
      const deletion = deleteVideoMentionAtSelection(value, videoPromptMentions, {
        key: event.key,
        selectionStart: event.currentTarget.selectionStart,
        selectionEnd: event.currentTarget.selectionEnd,
      });
      if (deletion) {
        event.preventDefault();
        onChange({
          videoPrompt: deletion.value,
          ...referenceStateAfterPromptChange(deletion.value),
        });
        setMentionMenu(null);
        requestAnimationFrame(() => {
          promptRef.current?.focus();
          promptRef.current?.setSelectionRange(deletion.cursor, deletion.cursor);
          setSelectionActive(false);
        });
        return;
      }
    }
    if (event.key === "Escape" && mentionMenu) {
      event.preventDefault();
      setMentionMenu(null);
      return;
    }
    if (!mentionMenu || filteredOptions.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveOptionIndex((current) => (current + 1) % filteredOptions.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveOptionIndex((current) => (
        current <= 0 ? filteredOptions.length - 1 : current - 1
      ));
    } else if (event.key === "Enter") {
      event.preventDefault();
      insertMention(filteredOptions[activeOptionIndex] || filteredOptions[0]);
    }
  }

  function insertMention(option, range = mentionMenu) {
    if (!range) return;
    const insertion = insertVideoMentionIntoPrompt(value, range, option);
    const nextMentions = normalizeVideoPromptMentions(insertion.value, [
      ...(videoPromptMentions || []).filter(
        (item) => videoReferenceKey(item) !== videoReferenceKey(option),
      ),
      {
        reference_kind: option.reference_kind,
        reference_id: option.reference_id,
        label: option.label,
        role: option.role,
        order: (videoPromptMentions || []).length + 1,
      },
    ], options);
    onChange({
      videoPrompt: insertion.value,
      videoPromptMentions: nextMentions,
      requiredInputSource: requiredSourceForVideoMention(option),
      selectedReferences: ensureVideoGenerationReference(selectedReferences, option),
    });
    setMentionMenu(null);
    requestAnimationFrame(() => {
      promptRef.current?.focus();
      promptRef.current?.setSelectionRange(insertion.cursor, insertion.cursor);
      setSelectionActive(false);
    });
  }

  function focusExistingMention(option) {
    const token = videoMentionToken(option);
    const start = String(value || "").indexOf(token);
    if (start < 0) return;
    promptRef.current?.focus();
    promptRef.current?.setSelectionRange(start, start + token.length);
    setSelectionActive(true);
  }

  return (
    <div className="video-prompt-reference-field">
      {quickOptions.length > 0 && (
        <div className="video-prompt-quick-references" aria-label="视频提示词快捷引用">
          <span>快捷引用</span>
          <div>
            {quickOptions.map((option) => {
              const mentioned = mentionedKeys.has(videoReferenceKey(option));
              const selected = selectedKeys.has(videoReferenceKey(option));
              return (
                <button
                  aria-pressed={mentioned}
                  className={`${mentioned ? "active" : ""}${selected ? " selected" : ""}`.trim()}
                  key={videoReferenceKey(option)}
                  onClick={() => {
                    if (mentioned) {
                      focusExistingMention(option);
                    } else {
                      insertMention(option, {
                        start: String(value || "").length,
                        end: String(value || "").length,
                      });
                    }
                  }}
                  title={mentioned
                    ? "已引用，点击定位"
                    : selected
                      ? "插入到提示词末尾"
                      : "加入生成参考并插入提示词"}
                  type="button"
                >
                  <small>{videoReferenceRoleLabel(option)}</small>
                  <strong>@{option.label}</strong>
                  <em>{mentioned ? "已引用" : selected ? "点击插入" : "加入并引用"}</em>
                </button>
              );
            })}
          </div>
        </div>
      )}
      <div
        className={`video-prompt-reference-editor${selectionActive ? " selecting" : ""}`}
        ref={editorRootRef}
      >
        <div aria-hidden="true" className="video-prompt-highlight" ref={highlightRef}>
          {highlightSegments.map((segment, index) => (
            segment.type === "mention"
              ? <mark key={`${segment.referenceKey}-${index}`}>{segment.text}</mark>
              : <span key={`text-${index}`}>{segment.text}</span>
          ))}
          {String(value || "").endsWith("\n") && "\n "}
        </div>
        <textarea
          aria-label="视频提示词"
          aria-activedescendant={mentionMenu && filteredOptions.length
            ? `${menuId}-option-${activeOptionIndex}`
            : undefined}
          aria-autocomplete="list"
          aria-controls={mentionMenu ? menuId : undefined}
          aria-expanded={Boolean(mentionMenu)}
          aria-haspopup="listbox"
          className="prompt-editor-textarea"
          id={editorId}
          maxLength={8000}
          onChange={updatePrompt}
          onKeyDown={handlePromptKeyDown}
          onScroll={syncHighlightScroll}
          onSelect={updateSelectionState}
          placeholder="描述视频；输入 @ 可显式引用图片资产、托管角色或深度视频"
          ref={promptRef}
          rows={7}
          value={value}
        />
        {mentionMenu && (
          <div className="video-prompt-mention-menu" id={menuId} role="listbox">
            <header><MagnifyingGlass size={15} /><span>选择生成输入</span></header>
            <div>
              {filteredOptions.length === 0 ? (
                <p>{quickOptions.length === 0 ? "请先绑定托管角色或通过 +参考 添加素材" : "没有匹配或尚未引用的素材"}</p>
              ) : filteredOptions.map((option, index) => (
                <button
                  aria-selected={activeOptionIndex === index}
                  className={activeOptionIndex === index ? "active" : ""}
                  id={`${menuId}-option-${index}`}
                  key={videoReferenceKey(option)}
                  onClick={() => insertMention(option)}
                  onMouseEnter={() => setActiveOptionIndex(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  role="option"
                  type="button"
                >
                  <span className="video-prompt-mention-thumb">
                    <ReferenceThumbnail option={option} resolveUrl={resolveUrl} />
                  </span>
                  <span><strong>@{option.label}</strong><small>{option.category} · {option.description}</small></span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <small className="video-prompt-reference-help">
        输入 @ 或点击上方快捷引用；系统按对象 ID 绑定素材，并自动附加与其职责对应的生成约束。
      </small>
    </div>
  );
}
