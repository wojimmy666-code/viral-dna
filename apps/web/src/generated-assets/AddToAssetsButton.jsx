import { useEffect, useRef, useState } from "react";
import { FolderPlus } from "@phosphor-icons/react";
import { AddToAssetsDialog } from "./AddToAssetsDialog.jsx";
import { artifactKey, jsonRequest } from "./asset-promotion-ui.js";
import "./generated-assets.css";

const ADDED_EVENT = "viraldna:generated-asset-added";
const REFRESH_EVENT = "viraldna:generated-asset-refresh";

export function AddToAssetsButton({
  artifactKind,
  assetType,
  className = "",
  disabled = false,
  label = "加入资产库",
  name,
  onAdded,
  onNotice,
  previewUrl,
  projectId,
  request,
  shotPlanId,
  sourceEntityId,
}) {
  const identity = artifactKey(artifactKind, sourceEntityId);
  const [lookup, setLookup] = useState(null);
  const [dialog, setDialog] = useState(null);
  const sequence = useRef(0);
  const buttonRef = useRef(null);
  const restoreFocus = useRef(false);

  useEffect(() => {
    if (!dialog && restoreFocus.current) {
      restoreFocus.current = false;
      buttonRef.current?.focus();
    }
  }, [dialog]);

  useEffect(() => {
    if (!request || !artifactKind || !sourceEntityId) return undefined;
    let active = true;
    let retryTimer;
    async function check(attempt = 0) {
      window.clearTimeout(retryTimer);
      const token = ++sequence.current;
      setLookup(null);
      try {
        const result = await request("/assets/generated-artifact-status", jsonRequest({
          kind: artifactKind, source_entity_id: sourceEntityId,
        }));
        if (typeof result?.promoted !== "boolean") throw new Error("Invalid asset status");
        if (active && token === sequence.current) {
          setLookup({ identity, request, absent: !result.promoted });
        }
      } catch {
        // Unknown is never treated as absent. Recheck quietly after a transient
        // error or returning from the asset library; never show a stale label.
        if (active && token === sequence.current && attempt < 2) {
          retryTimer = window.setTimeout(() => check(attempt + 1), 2000 * (attempt + 1));
        }
      }
    }
    const refresh = () => { if (!document.hidden) check(); };
    const promoted = event => {
      if (event.detail?.identity !== identity || event.detail?.request !== request) return;
      ++sequence.current;
      window.clearTimeout(retryTimer);
      setLookup({ identity, request, absent: false });
    };
    const recheck = event => {
      if (event.detail?.identity === identity && event.detail?.request === request) check();
    };
    check();
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener(ADDED_EVENT, promoted);
    window.addEventListener(REFRESH_EVENT, recheck);
    return () => {
      active = false;
      window.clearTimeout(retryTimer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener(ADDED_EVENT, promoted);
      window.removeEventListener(REFRESH_EVENT, recheck);
    };
  }, [artifactKind, identity, request, sourceEntityId]);

  function openDialog(event) {
    event.stopPropagation();
    if (disabled || dialog || !lookup?.absent || lookup.identity !== identity || lookup.request !== request) return;
    // Capture the target so changing the preview cannot save a different image.
    setDialog({ identity, artifactKind, sourceEntityId, shotPlanId, projectId,
      assetType, name, previewUrl, request, onAdded, onNotice });
  }

  function added(target, result) {
    window.dispatchEvent(new CustomEvent(ADDED_EVENT, {
      detail: { identity: target.identity, request: target.request },
    }));
    setDialog(null);
    target.onNotice?.(result.already_existed ? "已完成入库核对，未重复添加" : "已加入资产库");
    target.onAdded?.(result.asset);
  }

  function refreshTarget(target) {
    window.dispatchEvent(new CustomEvent(REFRESH_EVENT, {
      detail: { identity: target.identity, request: target.request },
    }));
  }

  function closeDialog() {
    restoreFocus.current = true;
    setDialog(null);
  }

  return <>
    {lookup?.identity === identity && lookup.request === request && lookup.absent && (
      <button ref={buttonRef} className={`secondary-button compact generated-asset-button ${className}`.trim()}
        disabled={disabled || Boolean(dialog)} onClick={openDialog} type="button">
        <FolderPlus size={16} />{label}
      </button>
    )}
    {dialog && <AddToAssetsDialog target={dialog} onClose={closeDialog} onAdded={added} onUncertain={refreshTarget} />}
  </>;
}
