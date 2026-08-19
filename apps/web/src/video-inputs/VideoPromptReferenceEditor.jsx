import { useMemo, useRef, useState } from "react";
import {
  FilmStrip,
  ImageSquare,
  MagnifyingGlass,
  UserCircle,
  X,
} from "@phosphor-icons/react";
import {
  buildVideoReferenceOptions,
  normalizeVideoPromptMentions,
  removeVideoMentionFromPrompt,
  requiredSourceForVideoMention,
  videoMentionToken,
  videoReferenceKey,
} from "./video-prompt-references.js";
import "./video-prompt-reference-editor.css";

function ReferenceThumbnail({ option, resolveUrl }) {
  const source = option.preview_url ? resolveUrl?.(option.preview_url) || option.preview_url : "";
  if (source) return <img alt="" loading="lazy" src={source} />;
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
  value,
  videoPromptMentions,
  videoReferenceBindings,
}) {
  const promptRef = useRef(null);
  const [mentionMenu, setMentionMenu] = useState(null);
  const options = useMemo(() => buildVideoReferenceOptions({
    assets,
    depthAssets,
    managedAssetBinding,
    referenceFrames,
    videoReferenceBindings,
  }), [assets, depthAssets, managedAssetBinding, referenceFrames, videoReferenceBindings]);
  const selectedKeys = useMemo(
    () => new Set((videoPromptMentions || []).map(videoReferenceKey)),
    [videoPromptMentions],
  );
  const filteredOptions = useMemo(() => {
    if (!mentionMenu) return [];
    const query = mentionMenu.query.trim().toLocaleLowerCase("zh-CN");
    return options.filter((item) => (
      !selectedKeys.has(videoReferenceKey(item))
      && (!query || `${item.label} ${item.search_text}`.toLocaleLowerCase("zh-CN").includes(query))
    ));
  }, [mentionMenu, options, selectedKeys]);

  function updatePrompt(event) {
    const nextValue = event.target.value;
    const cursor = event.target.selectionStart ?? nextValue.length;
    const match = nextValue.slice(0, cursor).match(/@([^@\n,，。；;]*)$/);
    const matchedFragment = match?.[1] || "";
    const followsCompletedMention = (videoPromptMentions || []).some((mention) => {
      const label = String(mention.label || "").replace(/^@+/, "");
      return matchedFragment === label || matchedFragment.startsWith(`${label} `);
    });
    onChange({
      videoPrompt: nextValue,
      videoPromptMentions: normalizeVideoPromptMentions(
        nextValue,
        videoPromptMentions,
        options,
      ),
    });
    setMentionMenu(match && !followsCompletedMention ? {
      start: cursor - match[1].length - 1,
      end: cursor,
      query: match[1],
    } : null);
  }

  function handlePromptKeyDown(event) {
    if (event.key === "Escape" && mentionMenu) {
      event.preventDefault();
      setMentionMenu(null);
    }
  }

  function insertMention(option) {
    if (!mentionMenu) return;
    const token = videoMentionToken(option);
    const nextPrompt = `${value.slice(0, mentionMenu.start)}${token} ${value.slice(mentionMenu.end)}`;
    const nextMentions = [
      ...(videoPromptMentions || []),
      {
        reference_kind: option.reference_kind,
        reference_id: option.reference_id,
        label: option.label,
        role: option.role,
        order: (videoPromptMentions || []).length + 1,
      },
    ];
    onChange({
      videoPrompt: nextPrompt,
      videoPromptMentions: nextMentions,
      requiredInputSource: requiredSourceForVideoMention(option),
    });
    setMentionMenu(null);
    requestAnimationFrame(() => promptRef.current?.focus());
  }

  function removeMention(mention) {
    const remaining = (videoPromptMentions || [])
      .filter((item) => videoReferenceKey(item) !== videoReferenceKey(mention))
      .map((item, index) => ({ ...item, order: index + 1 }));
    onChange({
      videoPrompt: removeVideoMentionFromPrompt(value, mention),
      videoPromptMentions: remaining,
    });
  }

  return (
    <label className="video-prompt-reference-field">
      <span>视频提示词</span>
      <div className="video-prompt-reference-editor">
        <textarea
          className="prompt-editor-textarea"
          maxLength={8000}
          onChange={updatePrompt}
          onKeyDown={handlePromptKeyDown}
          placeholder="描述视频；输入 @ 可显式引用图片资产、托管角色或深度视频"
          ref={promptRef}
          rows={7}
          value={value}
        />
        {mentionMenu && (
          <div className="video-prompt-mention-menu" role="listbox">
            <header><MagnifyingGlass size={15} /><span>选择生成输入</span></header>
            <div>
              {filteredOptions.length === 0 ? (
                <p>{options.length === 0 ? "当前分镜还没有可引用的素材" : "没有匹配的素材"}</p>
              ) : filteredOptions.map((option) => (
                <button
                  key={videoReferenceKey(option)}
                  onClick={() => insertMention(option)}
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
        输入 @ 选择具体素材；名称用于阅读，系统会保存对象 ID，并按当前模型编译成真实输入参数。
      </small>
      {(videoPromptMentions || []).length > 0 && (
        <span className="video-prompt-reference-chips" aria-label="已关联生成输入">
          {videoPromptMentions.map((mention) => (
            <button key={videoReferenceKey(mention)} onClick={() => removeMention(mention)} type="button">
              {videoMentionToken(mention)}<X size={12} />
            </button>
          ))}
        </span>
      )}
    </label>
  );
}
