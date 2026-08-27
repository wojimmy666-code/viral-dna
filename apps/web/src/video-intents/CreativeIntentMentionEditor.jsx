import {
  FilmStrip,
  ImageSquare,
  MagnifyingGlass,
  UserCircle,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import {
  buildVideoPromptHighlightSegments,
  buildVideoReferenceOptions,
  deleteVideoMentionAtSelection,
  insertVideoMentionIntoPrompt,
  normalizeVideoPromptMentions,
  videoMentionToken,
  videoReferenceKey,
} from "../video-inputs/video-prompt-references.js";
import "../video-inputs/video-prompt-reference-editor.css";

const CONTEXT_ROLE_HINTS = Object.freeze([
  { pattern: /人物|角色|身份|面部|脸|发型/u, roles: ["actor_identity"] },
  { pattern: /服装|衣服|穿搭|上衣|裤|裙|鞋/u, roles: ["wardrobe"] },
  { pattern: /产品|商品|配件|包装/u, roles: ["product"] },
  { pattern: /场景|背景|环境|地点/u, roles: ["scene"] },
  { pattern: /动作|姿态|节奏|运镜|镜头|复刻/u, roles: ["depth", "motion", "camera"] },
  { pattern: /转场|遮挡|切换/u, roles: ["transition", "motion"] },
  { pattern: /分镜|画面|构图/u, roles: ["composition"] },
  { pattern: /风格|光线|色彩/u, roles: ["style", "composition"] },
]);

function ReferenceThumbnail({ option, resolveUrl }) {
  const source = option.preview_url
    ? resolveUrl?.(option.preview_url) || option.preview_url
    : "";
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

function contextScore(option, context) {
  const match = CONTEXT_ROLE_HINTS.find((item) => item.pattern.test(context));
  if (!match) return 0;
  return match.roles.includes(option.role) ? 20 : 0;
}

export function CreativeIntentMentionEditor({
  assets,
  depthAssets,
  disabled = false,
  managedAssetBinding,
  mentions,
  onChange,
  onValidityChange,
  referenceFrames,
  resolveUrl,
  value,
  videoReferenceBindings,
}) {
  const editorId = useId();
  const menuId = `${editorId}-mentions`;
  const editorRootRef = useRef(null);
  const highlightRef = useRef(null);
  const menuRef = useRef(null);
  const promptRef = useRef(null);
  const [mentionMenu, setMentionMenu] = useState(null);
  const [menuStyle, setMenuStyle] = useState(null);
  const [activeOptionIndex, setActiveOptionIndex] = useState(0);
  const [selectionActive, setSelectionActive] = useState(false);
  const options = useMemo(() => buildVideoReferenceOptions({
    assets,
    depthAssets,
    managedAssetBinding,
    referenceFrames,
    videoReferenceBindings,
  }), [assets, depthAssets, managedAssetBinding, referenceFrames, videoReferenceBindings]);
  const optionKeys = useMemo(
    () => new Set(options.map(videoReferenceKey)),
    [options],
  );
  const mentionedKeys = useMemo(
    () => new Set((mentions || []).map(videoReferenceKey)),
    [mentions],
  );
  const invalidMentions = useMemo(
    () => (mentions || []).filter((item) => !optionKeys.has(videoReferenceKey(item))),
    [mentions, optionKeys],
  );
  const hasUnboundMention = useMemo(() => {
    const source = String(value || "");
    const boundRanges = [];
    for (const mention of mentions || []) {
      const token = videoMentionToken(mention);
      if (!token) continue;
      let cursor = 0;
      while (cursor < source.length) {
        const start = source.indexOf(token, cursor);
        if (start < 0) break;
        boundRanges.push({ start, end: start + token.length });
        cursor = start + token.length;
      }
    }
    for (let index = source.indexOf("@"); index >= 0; index = source.indexOf("@", index + 1)) {
      if (!boundRanges.some((range) => index >= range.start && index < range.end)) return true;
    }
    return false;
  }, [mentions, value]);

  useEffect(() => {
    onValidityChange?.(invalidMentions.length === 0 && !hasUnboundMention);
  }, [hasUnboundMention, invalidMentions.length, onValidityChange]);
  const highlightSegments = useMemo(
    () => buildVideoPromptHighlightSegments(value, mentions),
    [value, mentions],
  );
  const filteredOptions = useMemo(() => {
    if (!mentionMenu) return [];
    const query = mentionMenu.query.trim().toLocaleLowerCase("zh-CN");
    const context = String(value || "").slice(
      Math.max(0, mentionMenu.start - 36),
      mentionMenu.start,
    );
    return options
      .filter((item) => (
        !mentionedKeys.has(videoReferenceKey(item))
        && (!query || `${item.label} ${item.search_text}`
          .toLocaleLowerCase("zh-CN")
          .includes(query))
      ))
      .map((item, index) => ({ item, index, score: contextScore(item, context) }))
      .sort((left, right) => (
        right.score - left.score
        || left.index - right.index
      ))
      .map(({ item }) => item)
      .slice(0, 30);
  }, [mentionMenu, mentionedKeys, options, value]);

  useEffect(() => setActiveOptionIndex(0), [mentionMenu?.query]);

  useEffect(() => {
    if (!mentionMenu) return undefined;
    function dismissIfOutside(event) {
      if (
        !editorRootRef.current?.contains(event.target)
        && !menuRef.current?.contains(event.target)
      ) {
        setMentionMenu(null);
      }
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

  useEffect(() => {
    if (disabled) setMentionMenu(null);
  }, [disabled]);

  function updateMenuPosition() {
    const root = editorRootRef.current;
    if (!root || !mentionMenu) return;
    const rect = root.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const width = Math.max(
      160,
      Math.min(520, Math.max(260, rect.width - 16), viewportWidth - 16),
    );
    const left = Math.min(
      Math.max(8, rect.left + 8),
      Math.max(8, viewportWidth - width - 8),
    );
    const below = viewportHeight - rect.bottom - 12;
    const openAbove = below < 220 && rect.top > below;
    const maxHeight = Math.max(
      160,
      Math.min(320, openAbove ? rect.top - 16 : below),
    );
    setMenuStyle({
      position: "fixed",
      width: `${width}px`,
      maxHeight: `${maxHeight}px`,
      left: `${left}px`,
      bottom: "auto",
      top: `${openAbove
        ? Math.max(8, rect.top - maxHeight - 6)
        : Math.min(viewportHeight - 8, rect.bottom + 6)}px`,
      zIndex: "var(--z-dropdown)",
    });
  }

  useLayoutEffect(() => {
    if (!mentionMenu) {
      setMenuStyle(null);
      return undefined;
    }
    updateMenuPosition();
    window.addEventListener("resize", updateMenuPosition);
    window.addEventListener("scroll", updateMenuPosition, true);
    return () => {
      window.removeEventListener("resize", updateMenuPosition);
      window.removeEventListener("scroll", updateMenuPosition, true);
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

  useEffect(() => syncHighlightViewport(), [value]);

  function nextMentionState(nextValue) {
    const nextMentions = normalizeVideoPromptMentions(nextValue, mentions, options);
    const nextKeys = new Set(nextMentions.map(videoReferenceKey));
    return {
      intentMentions: nextMentions,
      removedMentions: (mentions || []).filter(
        (item) => !nextKeys.has(videoReferenceKey(item)),
      ),
    };
  }

  function updateIntent(event) {
    const nextValue = event.target.value;
    const cursor = event.target.selectionStart ?? nextValue.length;
    const match = nextValue.slice(0, cursor).match(/@([^@\n,，。；;]*)$/u);
    const matchedFragment = match?.[1] || "";
    const followsCompletedMention = (mentions || []).some((mention) => {
      const label = String(mention.label || "").replace(/^@+/u, "");
      return matchedFragment === label || matchedFragment.startsWith(`${label} `);
    });
    onChange?.({
      intentText: nextValue,
      ...nextMentionState(nextValue),
    });
    setMentionMenu(match && !followsCompletedMention ? {
      start: cursor - match[1].length - 1,
      end: cursor,
      query: match[1],
    } : null);
  }

  function insertMention(option, range = mentionMenu) {
    if (!range) return;
    const insertion = insertVideoMentionIntoPrompt(value, range, option);
    const intentMentions = normalizeVideoPromptMentions(insertion.value, [
      ...(mentions || []).filter(
        (item) => videoReferenceKey(item) !== videoReferenceKey(option),
      ),
      {
        reference_kind: option.reference_kind,
        reference_id: option.reference_id,
        label: option.label,
        role: option.role,
        order: (mentions || []).length + 1,
      },
    ], options);
    onChange?.({
      intentText: insertion.value,
      intentMentions,
      addedReference: option,
      removedMentions: [],
    });
    setMentionMenu(null);
    requestAnimationFrame(() => {
      promptRef.current?.focus();
      promptRef.current?.setSelectionRange(insertion.cursor, insertion.cursor);
      setSelectionActive(false);
    });
  }

  function handleKeyDown(event) {
    if (!event.isComposing && !event.nativeEvent?.isComposing) {
      const deletion = deleteVideoMentionAtSelection(value, mentions, {
        key: event.key,
        selectionStart: event.currentTarget.selectionStart,
        selectionEnd: event.currentTarget.selectionEnd,
      });
      if (deletion) {
        event.preventDefault();
        onChange?.({
          intentText: deletion.value,
          ...nextMentionState(deletion.value),
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

  const menu = mentionMenu && menuStyle ? (
    <div
      className="video-prompt-mention-menu creative-intent-mention-menu"
      id={menuId}
      ref={menuRef}
      role="listbox"
      style={menuStyle}
    >
      <header><MagnifyingGlass size={15} /><span>选择创作资产</span></header>
      <div>
        {filteredOptions.length === 0 ? (
          <p>{options.length === 0 ? "当前分镜还没有可用资产" : "没有匹配的资产"}</p>
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
            <span>
              <strong>@{option.label}</strong>
              <small>{option.category} · {option.description}</small>
            </span>
          </button>
        ))}
      </div>
    </div>
  ) : null;

  return (
    <div className="creative-intent-reference-field">
      <div
        className={`video-prompt-reference-editor${selectionActive ? " selecting" : ""}`}
        ref={editorRootRef}
      >
        <div aria-hidden="true" className="video-prompt-highlight" ref={highlightRef}>
          {highlightSegments.map((segment, index) => (
            segment.type === "mention"
              ? (
                <mark
                  className={optionKeys.has(segment.referenceKey) ? "" : "invalid"}
                  key={`${segment.referenceKey}-${index}`}
                >
                  {segment.text}
                </mark>
              )
              : <span key={`text-${index}`}>{segment.text}</span>
          ))}
          {String(value || "").endsWith("\n") && "\n "}
        </div>
        <textarea
          aria-activedescendant={mentionMenu && filteredOptions.length
            ? `${menuId}-option-${activeOptionIndex}`
            : undefined}
          aria-autocomplete="list"
          aria-controls={mentionMenu ? menuId : undefined}
          aria-expanded={Boolean(mentionMenu)}
          aria-haspopup="listbox"
          aria-invalid={invalidMentions.length > 0 || hasUnboundMention || undefined}
          aria-label="创作意图"
          className="prompt-editor-textarea"
          disabled={disabled}
          id={editorId}
          maxLength={4000}
          onChange={updateIntent}
          onKeyDown={handleKeyDown}
          onScroll={(event) => syncHighlightViewport(event.currentTarget)}
          onSelect={(event) => setSelectionActive(
            event.currentTarget.selectionStart !== event.currentTarget.selectionEnd,
          )}
          placeholder="例如：将人物换成 @托管角色/小喵酱，服装换成 @资产/服装/白色睡衣；参考原动作但允许自然调整，保留原转场。"
          ref={promptRef}
          rows={3}
          value={value}
        />
      </div>
      {invalidMentions.length > 0 && (
        <p className="creative-intent-invalid-mentions" role="alert">
          <WarningCircle aria-hidden="true" size={15} />
          {invalidMentions.map((item) => `@${item.label}`).join("、")} 已失效，请删除后重新选择
        </p>
      )}
      {hasUnboundMention && invalidMentions.length === 0 && (
        <p className="creative-intent-invalid-mentions" role="status">
          <WarningCircle aria-hidden="true" size={15} />
          存在尚未选择完成的 @ 引用，请从资产列表中选择
        </p>
      )}
      {menu && createPortal(menu, document.body)}
    </div>
  );
}
