import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowCounterClockwise,
  ArrowDown,
  LockSimple,
  Trash,
  X,
} from "@phosphor-icons/react";
import { formatVideoDuration } from "./production-ui.js";
import { AddToAssetsButton } from "./generated-assets/AddToAssetsButton.jsx";

const HOVER_PREVIEW_DELAY_MS = 180;

function supportsHoverVideoPreview() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return (
    window.matchMedia("(hover: hover) and (pointer: fine)").matches
    && !window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function HoverVideoThumbnail({
  active,
  candidate,
  enabled,
  onPreviewStart,
  onPreviewStop,
  resolveUrl,
}) {
  const hoverTimerRef = useRef(null);
  const videoRef = useRef(null);
  const [ready, setReady] = useState(false);
  const contentUrl = candidate.content_url ? resolveUrl(candidate.content_url) : "";

  const clearHoverTimer = useCallback(() => {
    if (hoverTimerRef.current === null) return;
    window.clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = null;
  }, []);

  function schedulePreview() {
    if (!enabled || !contentUrl || !supportsHoverVideoPreview()) return;
    clearHoverTimer();
    hoverTimerRef.current = window.setTimeout(() => {
      hoverTimerRef.current = null;
      onPreviewStart(candidate.id);
    }, HOVER_PREVIEW_DELAY_MS);
  }

  function stopPreview() {
    clearHoverTimer();
    onPreviewStop(candidate.id);
  }

  useEffect(() => {
    if (!active) {
      setReady(false);
      return undefined;
    }
    return () => {
      const video = videoRef.current;
      if (!video) return;
      video.pause();
      video.removeAttribute("src");
      video.load();
    };
  }, [active]);

  useEffect(() => () => {
    clearHoverTimer();
    const video = videoRef.current;
    if (!video) return;
    video.pause();
    video.removeAttribute("src");
    video.load();
  }, [clearHoverTimer]);

  return (
    <span
      className={`shot-candidate-thumb${ready ? " hover-preview-ready" : ""}`}
      onPointerCancel={stopPreview}
      onPointerEnter={schedulePreview}
      onPointerLeave={stopPreview}
    >
      <img
        alt={`视频 ${candidate.sequence || candidate.ordinal} 缩略图`}
        src={resolveUrl(candidate.thumbnail_url)}
      />
      {active && contentUrl && (
        <video
          aria-hidden="true"
          className="shot-candidate-hover-video"
          loop
          muted
          onCanPlay={(event) => {
            const playResult = event.currentTarget.play();
            if (playResult?.then) {
              playResult.catch(() => onPreviewStop(candidate.id));
            }
          }}
          onError={() => onPreviewStop(candidate.id)}
          onPlaying={() => setReady(true)}
          playsInline
          poster={resolveUrl(candidate.thumbnail_url)}
          preload="auto"
          ref={videoRef}
          src={contentUrl}
          tabIndex={-1}
        />
      )}
      {candidate.status === "rejected" && (
        <span className="shot-candidate-review-state rejected">已退回</span>
      )}
      <small>{formatVideoDuration(candidate.duration_seconds || 0)}s</small>
    </span>
  );
}

function formatCandidateBatchTime(value) {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function generationRunCostLabel(run) {
  if (!run) return "费用未知";
  if (run.actual_cost_known) {
    return `实际 ¥${(Number(run.actual_cost_micros || 0) / 1_000_000).toFixed(2)}`;
  }
  if (run.cost_estimate_known) {
    return `预计 ¥${(Number(run.estimated_cost_micros || 0) / 1_000_000).toFixed(2)}`;
  }
  return "费用待回传";
}

function candidateModelLabel(run) {
  return run?.model_display_name || run?.model_alias || run?.model || "未记录模型";
}

function toggleIds(current, ids, checked) {
  const next = new Set(current);
  ids.forEach((id) => {
    if (checked) next.add(id);
    else next.delete(id);
  });
  return [...next];
}

export function VideoCandidateLibrary({
  archivedCandidateGroups,
  busy,
  candidateGroups,
  displayedCandidate,
  onArchiveCandidates,
  onPreviewCandidate,
  onRestoreCandidates,
  onNotice,
  plan,
  request,
  resolveUrl,
}) {
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const [managing, setManaging] = useState(false);
  const [trashExpanded, setTrashExpanded] = useState(false);
  const [selectedActiveIds, setSelectedActiveIds] = useState([]);
  const [selectedArchivedIds, setSelectedArchivedIds] = useState([]);
  const [pendingAction, setPendingAction] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [hoverPreviewCandidateId, setHoverPreviewCandidateId] = useState("");

  const activeCandidates = useMemo(
    () => candidateGroups.flatMap((group) => group.candidates),
    [candidateGroups],
  );
  const archivedCandidates = useMemo(
    () => archivedCandidateGroups.flatMap((group) => group.candidates),
    [archivedCandidateGroups],
  );
  const latestGroup = candidateGroups[0] || null;
  const historicalGroups = candidateGroups.slice(1);
  const historicalCount = historicalGroups.reduce(
    (total, group) => total + group.candidates.length,
    0,
  );
  const approvedCandidateId = plan?.approved_video_candidate_id || "";
  const oldInput = plan?.video_status === "stale";
  const archivableIds = activeCandidates
    .filter((candidate) => (
      candidate.id !== approvedCandidateId
      && candidate.status !== "archived"
    ))
    .map((candidate) => candidate.id);
  const archivedIds = archivedCandidates.map((candidate) => candidate.id);
  const allArchivableSelected = (
    archivableIds.length > 0
    && archivableIds.every((id) => selectedActiveIds.includes(id))
  );
  const allArchivedSelected = (
    archivedIds.length > 0
    && archivedIds.every((id) => selectedArchivedIds.includes(id))
  );
  const displayedRun = displayedCandidate?.generationRun || null;
  const interactionBusy = busy || submitting;

  useEffect(() => {
    setHistoryExpanded(false);
    setManaging(false);
    setTrashExpanded(false);
    setSelectedActiveIds([]);
    setSelectedArchivedIds([]);
    setPendingAction("");
    setHoverPreviewCandidateId("");
  }, [plan?.id]);

  useEffect(() => {
    const available = new Set(archivableIds);
    setSelectedActiveIds((current) => current.filter((id) => available.has(id)));
  }, [candidateGroups, approvedCandidateId]);

  useEffect(() => {
    const available = new Set(archivedCandidates.map((candidate) => candidate.id));
    setSelectedArchivedIds((current) => current.filter((id) => available.has(id)));
    if (available.size === 0) setTrashExpanded(false);
  }, [archivedCandidateGroups]);

  function enterManagement() {
    setManaging(true);
    setHistoryExpanded(true);
    setTrashExpanded(false);
    setSelectedActiveIds([]);
    setPendingAction("");
    setHoverPreviewCandidateId("");
  }

  function leaveManagement() {
    setManaging(false);
    setSelectedActiveIds([]);
    setPendingAction("");
  }

  const startHoverPreview = useCallback((candidateId) => {
    setHoverPreviewCandidateId(candidateId);
  }, []);

  const stopHoverPreview = useCallback((candidateId) => {
    setHoverPreviewCandidateId((current) => (
      current === candidateId ? "" : current
    ));
  }, []);

  function toggleAllActiveCandidates() {
    setSelectedActiveIds(allArchivableSelected ? [] : archivableIds);
    setPendingAction("");
  }

  function toggleAllArchivedCandidates() {
    setSelectedArchivedIds(allArchivedSelected ? [] : archivedIds);
    setPendingAction("");
  }

  async function submitArchive() {
    if (selectedActiveIds.length === 0 || !onArchiveCandidates) return;
    setSubmitting(true);
    const succeeded = await onArchiveCandidates(selectedActiveIds);
    setSubmitting(false);
    if (succeeded) {
      leaveManagement();
    }
  }

  async function submitRestore() {
    if (selectedArchivedIds.length === 0 || !onRestoreCandidates) return;
    setSubmitting(true);
    const succeeded = await onRestoreCandidates(selectedArchivedIds);
    setSubmitting(false);
    if (succeeded) {
      setSelectedArchivedIds([]);
      setPendingAction("");
    }
  }

  function renderThumbnail(candidate, hoverPreviewEnabled = false) {
    return (
      <HoverVideoThumbnail
        active={hoverPreviewCandidateId === candidate.id}
        candidate={candidate}
        enabled={hoverPreviewEnabled}
        onPreviewStart={startHoverPreview}
        onPreviewStop={stopHoverPreview}
        resolveUrl={resolveUrl}
      />
    );
  }

  function renderBrowseCandidate(candidate, title, batchTime, modelLabel) {
    const isApproved = (
      plan?.video_status === "approved"
      && candidate.id === approvedCandidateId
    );
    const isPreviewing = candidate.id === displayedCandidate?.id;
    const sequence = candidate.sequence || candidate.ordinal;
    const candidateStateLabel = isApproved
      ? "已采用"
      : candidate.status === "rejected"
        ? "已退回"
        : candidate.status === "archived"
          ? "历史候选"
          : "可采用";
    const stateLabel = oldInput && !isApproved
      ? `${candidateStateLabel} · 旧输入`
      : candidateStateLabel;
    return (
      <button
        aria-label={`视频 ${sequence}，${title}，${stateLabel}`}
        aria-pressed={isPreviewing}
        className={[
          "shot-candidate-tile",
          isPreviewing ? "previewing active" : "",
          isApproved ? "approved" : "",
          candidate.status === "rejected" ? "rejected" : "",
        ].filter(Boolean).join(" ")}
        disabled={interactionBusy}
        key={candidate.id}
        onClick={() => onPreviewCandidate(candidate.id)}
        title={`${modelLabel} · ${batchTime} · ${stateLabel} · 悬停静音预览`}
        type="button"
      >
        {renderThumbnail(candidate, !interactionBusy)}
      </button>
    );
  }

  function renderManagedCandidate(candidate, archived = false) {
    const selection = archived ? selectedArchivedIds : selectedActiveIds;
    const setter = archived ? setSelectedArchivedIds : setSelectedActiveIds;
    const locked = !archived && candidate.id === approvedCandidateId;
    const checked = selection.includes(candidate.id);
    if (locked) {
      return (
        <div
          aria-label={`视频 ${candidate.sequence || candidate.ordinal} 已采用，不能移入回收站`}
          className="shot-candidate-tile lifecycle-locked approved"
          key={candidate.id}
          title="已采用，请先取消采用或改用其他视频"
        >
          {renderThumbnail(candidate)}
          <span className="candidate-lifecycle-lock"><LockSimple size={14} weight="fill" /></span>
        </div>
      );
    }
    return (
      <label
        className={`shot-candidate-tile lifecycle-selectable${checked ? " selected-for-lifecycle" : ""}`}
        key={candidate.id}
      >
        <input
          aria-label={`${checked ? "取消选择" : "选择"}视频 ${candidate.sequence || candidate.ordinal}`}
          checked={checked}
          disabled={interactionBusy}
          onChange={(event) => setter((current) => toggleIds(
            current,
            [candidate.id],
            event.target.checked,
          ))}
          type="checkbox"
        />
        {renderThumbnail(candidate)}
      </label>
    );
  }

  function renderGroup(group, title, { historical = false, archived = false } = {}) {
    if (!group) return null;
    const modelLabel = candidateModelLabel(group.run);
    const batchTime = formatCandidateBatchTime(
      group.run.completed_at || group.run.created_at,
    );
    const managementMode = archived || managing;
    return (
      <div
        aria-label={`${title}，${group.candidates.length} 个视频，${modelLabel}，${batchTime}`}
        className={`shot-candidate-strip-group${historical ? " historical" : ""}`}
        key={group.run.id}
        role="group"
      >
        <div className="shot-candidate-batch-label">
          <strong>{title}</strong>
          <small>{batchTime}</small>
        </div>
        <div className="shot-candidate-strip-items">
          {group.candidates.map((candidate) => (
            managementMode
              ? renderManagedCandidate(candidate, archived)
              : renderBrowseCandidate(candidate, title, batchTime, modelLabel)
          ))}
        </div>
      </div>
    );
  }

  if (candidateGroups.length === 0 && archivedCandidateGroups.length === 0) {
    return null;
  }

  return (
    <section
      aria-label="视频候选历史"
      className="shot-candidate-library shot-video-candidate-library"
    >
      <header className="shot-candidate-library-heading">
        <div>
          <strong>视频候选</strong>
          <small>
            可用 {activeCandidates.length} 个 · {candidateGroups.length} 个批次
            {!managing && "，点击缩略图切换预览"}
          </small>
        </div>
        <div className="shot-candidate-library-actions">
          {managing ? (
            <>
              <span>已选 {selectedActiveIds.length} 个</span>
              <button
                disabled={interactionBusy || archivableIds.length === 0}
                onClick={toggleAllActiveCandidates}
                type="button"
              >
                {allArchivableSelected ? "清空选择" : "全选可删除"}
              </button>
              <button disabled={interactionBusy} onClick={leaveManagement} type="button">
                <X size={14} />取消
              </button>
              <button
                className="danger"
                disabled={interactionBusy || selectedActiveIds.length === 0}
                onClick={() => setPendingAction("archive")}
                type="button"
              >
                <Trash size={14} />移入回收站
              </button>
            </>
          ) : (
            <>
              {historicalCount > 0 && (
                <button
                  aria-expanded={historyExpanded}
                  className={historyExpanded ? "expanded" : ""}
                  disabled={interactionBusy}
                  onClick={() => {
                    setHoverPreviewCandidateId("");
                    setHistoryExpanded((value) => !value);
                  }}
                  type="button"
                >
                  历史 {historicalCount} 个
                  <ArrowDown size={14} />
                </button>
              )}
              {archivedCandidates.length > 0 && (
                <button
                  aria-expanded={trashExpanded}
                  className={trashExpanded ? "expanded" : ""}
                  disabled={interactionBusy}
                  onClick={() => {
                    setHoverPreviewCandidateId("");
                    setTrashExpanded((value) => !value);
                    setPendingAction("");
                  }}
                  type="button"
                >
                  回收站 {archivedCandidates.length}
                </button>
              )}
              <button
                disabled={interactionBusy || archivableIds.length === 0}
                onClick={enterManagement}
                title={archivableIds.length === 0 ? "当前只有已采用视频，无法删除" : "管理视频候选"}
                type="button"
              >
                管理
              </button>
            </>
          )}
        </div>
      </header>

      {pendingAction === "archive" && (
        <div className="candidate-lifecycle-confirm" role="status">
          <span>将 {selectedActiveIds.length} 个视频候选移入回收站？候选文件会保留，可随时恢复。</span>
          <div>
            <button disabled={interactionBusy} onClick={() => setPendingAction("")} type="button">取消</button>
            <button className="danger" disabled={interactionBusy} onClick={submitArchive} type="button">
              <Trash size={14} />确认移入
            </button>
          </div>
        </div>
      )}

      {candidateGroups.length > 0 ? (
        <div
          aria-label="视频候选，可横向滚动"
          className="shot-candidate-strip"
          role="region"
          tabIndex={0}
        >
          {renderGroup(latestGroup, "最新")}
          {(historyExpanded || managing) && historicalGroups.map(
            (group, index) => renderGroup(group, `历史 ${index + 1}`, { historical: true }),
          )}
        </div>
      ) : (
        <div className="candidate-library-empty">当前没有可用视频候选，可从回收站恢复或重新生成。</div>
      )}

      {displayedCandidate && !managing && (
        <div className="shot-candidate-current-detail">
          <strong>当前预览</strong>
          <span>
            {candidateModelLabel(displayedRun)}
            {" · "}{formatCandidateBatchTime(displayedRun?.completed_at || displayedRun?.created_at)}
            {" · "}{formatVideoDuration(displayedCandidate.duration_seconds || 0)} 秒
            {" · "}{generationRunCostLabel(displayedRun)}
          </span>
          <em className={
            plan.video_status === "approved"
            && approvedCandidateId === displayedCandidate.id
              ? "approved"
              : displayedCandidate.status === "rejected"
                ? "rejected"
              : oldInput
                ? "old-input"
                : ""
          }>
            {plan.video_status === "approved"
            && approvedCandidateId === displayedCandidate.id
              ? "已采用"
              : displayedCandidate.status === "rejected"
                ? `已退回${oldInput ? " · 旧输入" : ""}`
              : oldInput
                ? "可采用 · 旧输入"
                : "可采用"}
          </em>
          <AddToAssetsButton
            artifactKind="video_candidate"
            assetType="motion_reference"
            disabled={interactionBusy}
            name={`分镜 ${plan.index} 生成视频`}
            onNotice={onNotice}
            request={request}
            shotPlanId={plan.id}
            sourceEntityId={displayedCandidate.id}
          />
        </div>
      )}

      {trashExpanded && archivedCandidates.length > 0 && (
        <section className="candidate-recycle-panel" aria-label="视频候选回收站">
          <header>
            <div><strong>回收站</strong><small>候选文件仍被保留，恢复后回到可采用状态。</small></div>
            <div>
              <span>已选 {selectedArchivedIds.length} 个</span>
              <button
                disabled={interactionBusy || archivedIds.length === 0}
                onClick={toggleAllArchivedCandidates}
                type="button"
              >
                {allArchivedSelected ? "清空选择" : "全选可恢复"}
              </button>
              <button
                disabled={interactionBusy || selectedArchivedIds.length === 0}
                onClick={() => setPendingAction("restore")}
                type="button"
              >
                <ArrowCounterClockwise size={14} />恢复所选
              </button>
            </div>
          </header>
          {pendingAction === "restore" && (
            <div className="candidate-lifecycle-confirm restore" role="status">
              <span>恢复 {selectedArchivedIds.length} 个视频候选？恢复后需要重新选择或采用。</span>
              <div>
                <button disabled={interactionBusy} onClick={() => setPendingAction("")} type="button">取消</button>
                <button disabled={interactionBusy} onClick={submitRestore} type="button">
                  <ArrowCounterClockwise size={14} />确认恢复
                </button>
              </div>
            </div>
          )}
          <div className="shot-candidate-strip" role="region" tabIndex={0} aria-label="已删除视频候选，可横向滚动">
            {archivedCandidateGroups.map((group, index) => renderGroup(
              group,
              `已删除 ${index + 1}`,
              { archived: true, historical: index > 0 },
            ))}
          </div>
        </section>
      )}
    </section>
  );
}
