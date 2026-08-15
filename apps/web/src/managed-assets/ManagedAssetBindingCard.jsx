import {
  IdentificationCard,
  PencilSimple,
  Plus,
  Trash,
  UserCircle,
} from "@phosphor-icons/react";

export function ManagedAssetBindingCard({
  binding,
  busy,
  compatible,
  onClear,
  onOpen,
  resolveUrl,
}) {
  const previewUrl = binding?.asset_id
    ? resolveUrl?.(
      `/api/v1/managed-assets/providers/${binding.provider}/assets/${encodeURIComponent(binding.asset_id)}/preview`,
    )
    : "";
  return (
    <section className={`managed-asset-binding-card ${binding ? "bound" : ""}`}>
      <div className="managed-asset-binding-heading">
        <span className="managed-asset-binding-icon">
          <IdentificationCard size={20} weight="duotone" />
        </span>
        <div>
          <strong>演员身份（Provider 托管）</strong>
          <small>
            {binding
              ? "作为本分镜唯一人物身份来源，本地画面只提供动作与构图"
              : "可选；从火山方舟目录绑定虚拟人像或已授权真人"}
          </small>
        </div>
        {binding && (
          <span className={`managed-asset-compatibility ${compatible ? "ready" : "warning"}`}>
            {compatible ? "当前模型可用" : "需切换 Seedance"}
          </span>
        )}
      </div>

      {binding ? (
        <div className="managed-asset-binding-content">
          <div className="managed-asset-binding-preview">
            {previewUrl ? (
              <img alt="" src={previewUrl} />
            ) : (
              <UserCircle size={28} weight="duotone" />
            )}
          </div>
          <div className="managed-asset-binding-copy">
            <strong>{binding.name}</strong>
            <span>{binding.group_name || "未分组"} · {binding.kind === "verified_person" ? "已授权真人" : "虚拟人像"}</span>
            <small>火山方舟 · ProjectName: {binding.project_name}</small>
          </div>
          <div className="managed-asset-binding-actions">
            <button className="secondary-button compact" disabled={busy} onClick={onOpen} type="button">
              <PencilSimple size={15} />更换
            </button>
            <button className="icon-button danger" disabled={busy} onClick={onClear} title="解除演员身份绑定" type="button">
              <Trash size={16} />
            </button>
          </div>
        </div>
      ) : (
        <button className="managed-asset-bind-button" disabled={busy} onClick={onOpen} type="button">
          <Plus size={18} />从 Provider 目录选择演员身份
        </button>
      )}
    </section>
  );
}
