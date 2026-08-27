import { ArrowCounterClockwise, Plus, WarningCircle, X } from "@phosphor-icons/react";
import { useMemo, useRef, useState } from "react";
import {
  buildVideoReferenceOptions,
  requiredSourceForVideoMention,
  videoReferenceKey,
  videoReferenceStableKey,
  videoReferenceSourceSupported,
} from "../video-prompt-references.js";
import { ReferencePickerPopover } from "./ReferencePickerPopover.jsx";
import { ReferencePreviewDialog } from "./ReferencePreviewDialog.jsx";
import { ReferenceThumbnail } from "./ReferenceThumbnail.jsx";
import {
  referenceSource,
  selectedReferenceItems,
} from "./reference-composer-ui.js";
import "./reference-composer.css";

export function GenerationReferenceComposer({
  assets,
  autoReferenceExclusions,
  depthAssets,
  managedAssetBinding,
  model,
  onChange,
  onCreateDepth,
  onOpenManagedAssets,
  onRestoreAutomaticReferences,
  referenceFrames,
  resolveUrl,
  selectedReferences,
  selectedSources,
  shotPlanId,
  videoReferenceBindings,
}) {
  const anchorRef = useRef(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [previewItem, setPreviewItem] = useState(null);
  const options = useMemo(() => buildVideoReferenceOptions({
    assets,
    depthAssets,
    managedAssetBinding,
    referenceFrames,
    videoReferenceBindings,
  }), [assets, depthAssets, managedAssetBinding, referenceFrames, videoReferenceBindings]);
  const items = useMemo(() => selectedReferenceItems({
    references: selectedReferences,
    options,
    selectedSources,
  }), [options, selectedReferences, selectedSources]);
  const selectedKeys = useMemo(
    () => new Set((selectedReferences || []).map(videoReferenceKey)),
    [selectedReferences],
  );

  function toggleReference(option, enabled) {
    const key = videoReferenceKey(option);
    const source = requiredSourceForVideoMention(option);
    const existingReference = (selectedReferences || [])
      .find((item) => videoReferenceKey(item) === key);
    let references = (selectedReferences || []).filter((item) => videoReferenceKey(item) !== key);
    let addedReference = null;
    if (enabled) {
      const nextReference = {
        reference_kind: option.reference_kind,
        reference_id: option.reference_id,
        label: option.label,
        role: option.role,
        order: references.length + 1,
      };
      if (option.visual_beat_id) nextReference.visual_beat_id = option.visual_beat_id;
      if (option.automatic) nextReference.automatic = true;
      if (option.scope) nextReference.scope = option.scope;
      if (option.origin) nextReference.origin = option.origin;
      if (option.locked) nextReference.locked = true;
      references.push(nextReference);
      addedReference = nextReference;
    }
    references = references.map((item, index) => ({ ...item, order: index + 1 }));
    const sources = new Set(selectedSources || []);
    if (enabled && source) sources.add(source);
    if (!enabled && source && !references.some((item) => requiredSourceForVideoMention(item) === source)) {
      sources.delete(source);
    }
    onChange?.({
      selectedReferences: references,
      inputSources: [...sources],
      addedReference,
      removedReference: enabled ? null : (existingReference || option),
    });
  }

  function removeItem(item) {
    if (item.explicit) {
      const option = options.find((candidate) => videoReferenceKey(candidate) === videoReferenceKey(item)) || item;
      toggleReference(option, false);
      return;
    }
    const source = referenceSource(item);
    onChange?.({
      selectedReferences,
      inputSources: (selectedSources || []).filter((value) => value !== source),
    });
  }

  function reorderItem(draggedKey, targetKey) {
    const references = [...(selectedReferences || [])];
    const from = references.findIndex((item) => videoReferenceKey(item) === draggedKey);
    const to = references.findIndex((item) => videoReferenceKey(item) === targetKey);
    if (from < 0 || to < 0 || from === to) return;
    const [moved] = references.splice(from, 1);
    references.splice(to, 0, moved);
    const orderedReferences = references.map((item, index) => ({ ...item, order: index + 1 }));
    onChange?.({
      selectedReferences: orderedReferences,
      inputSources: selectedSources,
      referenceOrderOverride: orderedReferences.map(videoReferenceStableKey),
    });
  }

  const incompatibleCount = items.filter((item) => !videoReferenceSourceSupported(
    model?.capabilities || {},
    referenceSource(item),
  )).length;
  const automaticCount = items.filter((item) => item.automatic).length;
  const excludedAutomaticCount = (autoReferenceExclusions || []).length;

  return (
    <section className="generation-reference-composer" aria-label="生成参考">
      <div className="generation-reference-rail">
        <div className="generation-reference-summary">
          <div>
            <strong>生成参考</strong>
            <small>
              {automaticCount > 0
                ? `已自动加入 ${automaticCount} 张分镜图 · 与画面轨道同步`
                : excludedAutomaticCount > 0
                  ? "自动分镜图已手动移除"
                  : "分镜图将在采用后自动加入"}
            </small>
          </div>
          {excludedAutomaticCount > 0 && (
            <button onClick={onRestoreAutomaticReferences} type="button">
              <ArrowCounterClockwise size={14} />恢复默认
            </button>
          )}
        </div>
        <div className="generation-reference-content">
          <div className="generation-reference-items" aria-label={`${items.length} 项生成参考`}>
            {items.map((item) => {
              const key = videoReferenceKey(item);
              const supported = videoReferenceSourceSupported(model?.capabilities || {}, referenceSource(item));
              return (
                <article
                  className={`generation-reference-item${supported ? "" : " incompatible"}${item.automatic ? " automatic" : ""}`}
                  draggable={item.explicit && items.length > 1}
                  key={`${key}:${item.explicit ? "explicit" : "implicit"}`}
                  onDragOver={(event) => event.preventDefault()}
                  onDragStart={(event) => event.dataTransfer.setData("text/reference-key", key)}
                  onDrop={(event) => reorderItem(event.dataTransfer.getData("text/reference-key"), key)}
                >
                  <button aria-label={`预览${item.label}`} className="generation-reference-media" onClick={() => setPreviewItem(item)} type="button">
                    <ReferenceThumbnail item={item} previewOnHover resolveUrl={resolveUrl} shotPlanId={shotPlanId} />
                    <b>{item.display_order}</b>
                    {item.automatic && <span className="generation-reference-auto-badge">自动</span>}
                    {["reference_video", "depth_control"].includes(item.reference_kind) && <span>视频</span>}
                  </button>
                  <button aria-label={`移除${item.label}`} className="generation-reference-remove" onClick={() => removeItem(item)} type="button"><X size={13} /></button>
                  <small title={item.label}>{item.display_alias}</small>
                </article>
              );
            })}
            {items.length === 0 && <span className="generation-reference-empty">尚无生成参考</span>}
          </div>
          <button
            aria-expanded={pickerOpen}
            className="generation-reference-add"
            onClick={() => setPickerOpen((current) => !current)}
            ref={anchorRef}
            type="button"
          >
            <Plus size={18} />参考
          </button>
          <span className="generation-reference-count">{items.length} 项</span>
        </div>
      </div>
      {incompatibleCount > 0 && (
        <p className="generation-reference-warning"><WarningCircle size={16} />{incompatibleCount} 项参考与当前模型不兼容</p>
      )}
      <ReferencePickerPopover
        anchorRef={anchorRef}
        model={model}
        onClose={() => setPickerOpen(false)}
        onCreateDepth={() => {
          setPickerOpen(false);
          onCreateDepth?.();
        }}
        onOpenManagedAssets={() => {
          setPickerOpen(false);
          onOpenManagedAssets?.();
        }}
        onToggle={toggleReference}
        open={pickerOpen}
        options={options}
        resolveUrl={resolveUrl}
        selectedKeys={selectedKeys}
        shotPlanId={shotPlanId}
      />
      <ReferencePreviewDialog item={previewItem} onClose={() => setPreviewItem(null)} resolveUrl={resolveUrl} shotPlanId={shotPlanId} />
    </section>
  );
}
