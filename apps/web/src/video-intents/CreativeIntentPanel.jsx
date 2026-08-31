import {
  ArrowCounterClockwise,
  CircleNotch,
  MagicWand,
  PencilSimple,
  Stack,
  WarningCircle,
} from "@phosphor-icons/react";
import { useState } from "react";
import { InlineMessage, StatusBadge } from "../ui/system/index.js";
import { CreativeIntentMentionEditor } from "./CreativeIntentMentionEditor.jsx";
import "./creative-intent.css";

const ASSET_REQUIREMENT_CODES = new Set([
  "asset_ambiguous",
  "asset_not_found",
  "depth_control_not_ready",
  "explicit_reference_manually_removed",
  "explicit_reference_not_resolved",
  "explicit_reference_type_mismatch",
  "explicit_reference_unavailable",
  "managed_asset_ambiguous",
  "managed_asset_not_found",
]);

export function intentRequirementsNeedAssets(requirements = []) {
  return requirements.some((item) => ASSET_REQUIREMENT_CODES.has(item?.code));
}

function intentStatus(status, hasInterpretation, conflicts, errorCode) {
  if (errorCode === "video_intent_model_validation_failed") {
    return { label: "提示词校验失败", tone: "danger" };
  }
  if (conflicts.some((item) => item?.message?.includes("模型输出已降级清理"))) {
    return { label: "提示词校验失败", tone: "danger" };
  }
  if (status === "stale") return { label: "意图已修改", tone: "warning" };
  if (status === "needs_input") {
    return intentRequirementsNeedAssets(conflicts)
      ? { label: "需要补充资产", tone: "warning" }
      : { label: "需要确认意图", tone: "warning" };
  }
  if (status === "failed") return { label: "生成失败", tone: "danger" };
  if (status === "ready" || hasInterpretation) return { label: "已生成", tone: "success" };
  return null;
}

export function CreativeIntentPanel({
  assets,
  busy = false,
  compileResult = null,
  depthAssets,
  draft,
  error = "",
  errorCode = "",
  managedAssetBinding,
  onChange,
  onCompile,
  onOpenPrompt,
  onOpenReferences,
  onRequestManagedAssetMention,
  onRestore,
  referenceFrames,
  resolveUrl,
  videoReferenceBindings,
}) {
  const [mentionsValid, setMentionsValid] = useState(true);
  const interpretation = draft?.intent?.interpretation || null;
  const referenceCount = draft?.selectedReferences?.length || 0;
  const conflicts = draft?.intentConflicts || [];
  const status = intentStatus(
    draft?.intent?.status,
    interpretation,
    conflicts,
    errorCode,
  );
  const unresolved = compileResult?.unresolved_requirements || [];
  const warnings = compileResult?.warnings || [];
  const issues = [
    ...new Map(
      [...unresolved, ...conflicts].map((item) => [
        `${item?.code || "conflict"}:${item?.message || ""}`,
        item,
      ]),
    ).values(),
  ];
  const canGenerate = (
    Boolean(String(draft?.intentText || "").trim())
    && mentionsValid
    && !busy
  );

  return (
    <section className="creative-intent-panel" aria-labelledby="creative-intent-title">
      <header className="creative-intent-heading">
        <div>
          <h4 id="creative-intent-title">创作意图</h4>
        </div>
        {status && <StatusBadge tone={status.tone}>{status.label}</StatusBadge>}
      </header>

      <div className="creative-intent-command">
        <CreativeIntentMentionEditor
          assets={assets}
          depthAssets={depthAssets}
          disabled={busy}
          managedAssetBinding={managedAssetBinding}
          mentions={draft?.intentMentions || []}
          onChange={onChange}
          onRequestManagedAssetMention={onRequestManagedAssetMention}
          onValidityChange={setMentionsValid}
          referenceFrames={referenceFrames}
          resolveUrl={resolveUrl}
          value={draft?.intentText || ""}
          videoReferenceBindings={videoReferenceBindings}
        />
        <button
          className="primary-button creative-intent-generate"
          disabled={!canGenerate}
          onClick={onCompile}
          title={!mentionsValid ? "请先删除失效引用并重新选择资产" : undefined}
          type="button"
        >
          {busy
            ? <CircleNotch className="spin" size={17} />
            : <MagicWand size={17} weight="fill" />}
          {busy ? "正在理解意图" : "生成引用与提示词"}
        </button>
      </div>

      {error && (
        <InlineMessage tone="danger">
          <WarningCircle aria-hidden="true" size={17} />
          <span>{error}</span>
        </InlineMessage>
      )}

      {interpretation && (
        <div className="creative-intent-result-actions" aria-label="生成结果操作">
          <button className="text-button" onClick={onOpenReferences} type="button">
            <Stack size={16} />查看引用（{referenceCount}）
          </button>
          <button className="text-button" onClick={onOpenPrompt} type="button">
            <PencilSimple size={16} />编辑提示词
          </button>
        </div>
      )}

      {issues.map((item, index) => (
        <InlineMessage key={`${item.code || "conflict"}:${index}`} tone="warning">
          <WarningCircle aria-hidden="true" size={17} />
          <span>{item.message}</span>
        </InlineMessage>
      ))}

      {warnings.length > 0 && (
        <InlineMessage>
          <WarningCircle aria-hidden="true" size={17} />
          <span>{warnings.join("；")}</span>
        </InlineMessage>
      )}

      {draft?.autoBaseline && draft?.promptManuallyModified && (
        <div className="creative-intent-restore">
          <span>当前提示词含人工修改，重新生成时不会自动覆盖。</span>
          <button className="text-button" onClick={onRestore} type="button">
            <ArrowCounterClockwise size={15} />恢复最近自动版本
          </button>
        </div>
      )}

    </section>
  );
}
