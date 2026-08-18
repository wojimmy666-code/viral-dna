import { useEffect, useState } from "react";
import { CheckCircle, FolderPlus, SpinnerGap } from "@phosphor-icons/react";
import "./generated-assets.css";

export function AddToAssetsButton({
  artifactKind,
  assetType,
  className = "",
  disabled = false,
  label = "加入资产库",
  name,
  onAdded,
  onNotice,
  request,
  shotPlanId,
  sourceEntityId,
}) {
  const [status, setStatus] = useState("idle");
  const [assetId, setAssetId] = useState("");

  useEffect(() => {
    let active = true;
    if (!request || !artifactKind || !sourceEntityId) return undefined;
    request("/assets/generated-artifact-status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: artifactKind, source_entity_id: sourceEntityId }),
    }).then((result) => {
      if (!active || !result?.promoted) return;
      setAssetId(result.asset_id || "");
      setStatus("added");
    }).catch(() => {});
    return () => { active = false; };
  }, [artifactKind, request, sourceEntityId]);

  async function addToAssets(event) {
    event?.stopPropagation?.();
    if (!request || status === "adding" || status === "added") return;
    setStatus("adding");
    try {
      const result = await request("/assets/from-generated-artifact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: artifactKind,
          source_entity_id: sourceEntityId,
          shot_plan_id: shotPlanId || null,
          asset_type: assetType || null,
          name: name || null,
        }),
      });
      setAssetId(result.asset?.id || "");
      setStatus("added");
      onNotice?.(result.already_existed ? "该生成产物已在资产库中" : "已加入资产库");
      onAdded?.(result.asset);
    } catch (error) {
      setStatus("idle");
      onNotice?.(error.message || "加入资产库失败");
    }
  }

  return (
    <button
      className={`generated-asset-button ${className}`.trim()}
      data-asset-id={assetId || undefined}
      disabled={disabled || status === "adding" || status === "added"}
      onClick={addToAssets}
      title={status === "added" ? "已加入资产库" : label}
      type="button"
    >
      {status === "adding" ? (
        <><SpinnerGap className="spin" size={16} />正在加入</>
      ) : status === "added" ? (
        <><CheckCircle size={16} weight="fill" />已在资产库</>
      ) : (
        <><FolderPlus size={16} />{label}</>
      )}
    </button>
  );
}
