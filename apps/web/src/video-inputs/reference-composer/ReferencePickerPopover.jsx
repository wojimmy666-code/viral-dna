import { useMemo, useState } from "react";
import {
  Check,
  IdentificationCard,
  MagnifyingGlass,
  Plus,
  Stack,
} from "@phosphor-icons/react";
import { AnchoredPopover } from "../../video-generation-controls/AnchoredPopover.jsx";
import {
  VIDEO_REFERENCE_CATEGORY_BY_KIND,
  requiredSourceForVideoMention,
  videoReferenceKey,
  videoReferenceSourceSupported,
} from "../video-prompt-references.js";
import { ReferenceThumbnail } from "./ReferenceThumbnail.jsx";

const FILTERS = [
  ["all", "全部"],
  ["image", "图片"],
  ["actor", "角色"],
  ["video", "视频"],
  ["depth", "深度"],
];

export function ReferencePickerPopover({
  anchorRef,
  model,
  onClose,
  onCreateDepth,
  onOpenManagedAssets,
  onToggle,
  open,
  options,
  resolveUrl,
  selectedKeys,
  shotPlanId,
}) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
    return options.filter((option) => {
      const category = VIDEO_REFERENCE_CATEGORY_BY_KIND[option.reference_kind] || "image";
      const matchesFilter = filter === "all" || filter === category;
      const matchesQuery = !normalizedQuery
        || `${option.label} ${option.category} ${option.description} ${option.search_text}`
          .toLocaleLowerCase("zh-CN")
          .includes(normalizedQuery);
      return matchesFilter && matchesQuery;
    });
  }, [filter, options, query]);
  const supportsManagedAssets = videoReferenceSourceSupported(
    model?.capabilities || {},
    "provider_managed_assets",
  );
  const supportsDepthControl = videoReferenceSourceSupported(
    model?.capabilities || {},
    "depth_control",
  );

  return (
    <AnchoredPopover
      anchorRef={anchorRef}
      className="generation-reference-picker"
      labelledBy="generation-reference-picker-title"
      onClose={onClose}
      open={open}
      preferredWidth={480}
    >
      <div className="generation-reference-picker-heading">
        <div><h4 id="generation-reference-picker-title">选择参考</h4><p>只会提交已添加的具体素材</p></div>
        <label><MagnifyingGlass size={17} /><input aria-label="搜索参考" onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称或标签" value={query} /></label>
      </div>
      <div className="generation-reference-filters" role="tablist">
        {FILTERS.map(([value, label]) => (
          <button aria-selected={filter === value} key={value} onClick={() => setFilter(value)} role="tab" type="button">{label}</button>
        ))}
      </div>
      <div className="generation-reference-picker-list">
        {filtered.map((option) => {
          const key = videoReferenceKey(option);
          const selected = selectedKeys.has(key);
          const source = requiredSourceForVideoMention(option);
          const supported = videoReferenceSourceSupported(model?.capabilities || {}, source);
          return (
            <button
              aria-pressed={selected}
              className={selected ? "selected" : ""}
              disabled={!supported && !selected}
              key={key}
              onClick={() => onToggle(option, !selected)}
              title={supported ? option.description : "当前模型不支持此参考类型"}
              type="button"
            >
              <span className="generation-reference-picker-thumb"><ReferenceThumbnail item={option} resolveUrl={resolveUrl} shotPlanId={shotPlanId} /></span>
              <span><strong>{option.label}</strong><small>{supported ? `${option.category} · ${option.description}` : "当前模型不支持"}</small></span>
              {selected ? <Check size={18} weight="bold" /> : <Plus size={18} />}
            </button>
          );
        })}
        {filtered.length === 0 && <p className="generation-reference-picker-empty">没有匹配的参考素材</p>}
      </div>
      <footer>
        <button
          disabled={!supportsManagedAssets}
          onClick={onOpenManagedAssets}
          title={supportsManagedAssets ? "选择 Provider 托管人物" : "当前模型不支持托管人物"}
          type="button"
        >
          <IdentificationCard size={17} />选择托管人物
        </button>
        <button
          disabled={!supportsDepthControl}
          onClick={onCreateDepth}
          title={supportsDepthControl ? "创建或管理深度视频" : "当前模型不支持深度控制"}
          type="button"
        >
          <Stack size={17} />创建或管理深度视频
        </button>
      </footer>
    </AnchoredPopover>
  );
}
