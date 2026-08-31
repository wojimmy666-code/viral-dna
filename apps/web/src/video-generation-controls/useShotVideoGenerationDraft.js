import { useCallback, useEffect, useRef, useState } from "react";
import { normalizeVideoDuration } from "../production-ui.js";
import {
  approvedVisualBeatFramesFromDetail,
  normalizeVideoGenerationReferences,
  requiredSourceForVideoMention,
  stripLegacyVideoReferencePolicies,
  synchronizeAutomaticVideoPrompt,
  synchronizeAutomaticVideoReferences,
  videoReferenceStableKey,
} from "../video-inputs/video-prompt-references.js";

export const EMPTY_VIDEO_DRAFT = Object.freeze({
  videoPrompt: "",
  videoPromptMentions: [],
  selectedReferences: [],
  negativeConstraints: "",
  durationSeconds: "",
  candidateCount: 1,
  modelAlias: "",
  resolution: "720P",
  inputSources: [],
  referenceSyncMode: "auto",
  autoReferenceExclusions: [],
  referenceOrderOverride: [],
  draftVersion: 0,
  intentText: "",
  intentMentions: [],
  intent: null,
  autoBaseline: null,
  intentConflicts: [],
  promptManuallyModified: false,
  lockedReferenceKeys: [],
  removedIntentReferenceKeys: [],
});

function normalizedCandidateCount(value) {
  return Math.min(4, Math.max(1, Math.trunc(Number(value) || 1)));
}

function normalizedDuration(value, fallback = 3) {
  const duration = Number(value);
  return Number.isFinite(duration)
    ? Math.min(60, Math.max(0.1, duration))
    : fallback;
}

function negativeConstraintLines(value) {
  return Array.from(new Set(
    String(value || "")
      .split(/\r?\n/u)
      .map((item) => item.trim())
      .filter(Boolean),
  ));
}

export function videoDraftParameters(draft) {
  return {
    model_alias: String(draft?.modelAlias || "").trim(),
    resolution: String(draft?.resolution || "720P").trim().toUpperCase(),
    duration_seconds: normalizedDuration(draft?.durationSeconds),
    candidate_count: normalizedCandidateCount(draft?.candidateCount),
    input_plan: {
      schema_version: "viral-dna-video-input-plan/v1",
      sources: Array.from(new Set(draft?.inputSources || [])),
      references: normalizeVideoGenerationReferences(draft?.selectedReferences || []),
    },
    video_prompt: String(draft?.videoPrompt || ""),
    video_prompt_mentions: normalizeVideoGenerationReferences(
      draft?.videoPromptMentions || [],
    ),
    video_negative_constraints: negativeConstraintLines(draft?.negativeConstraints),
    intent_text: String(draft?.intentText || ""),
    intent_mentions: normalizeVideoGenerationReferences(
      draft?.intentMentions || [],
    ),
    locked_reference_keys: Array.from(new Set(
      (draft?.lockedReferenceKeys || []).map(String),
    )),
    removed_intent_reference_keys: Array.from(new Set(
      (draft?.removedIntentReferenceKeys || []).map(String),
    )),
    prompt_manually_modified: Boolean(draft?.promptManuallyModified),
    reference_sync_mode: draft?.referenceSyncMode || "auto",
    auto_reference_exclusions: Array.from(new Set(
      (draft?.autoReferenceExclusions || []).map(String),
    )),
    reference_order_override: Array.from(new Set(
      (draft?.referenceOrderOverride || []).map(String),
    )),
  };
}

function sameParameters(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function localVideoDraftParameters(draft) {
  return {
    modelAlias: draft.modelAlias,
    resolution: draft.resolution,
    durationSeconds: draft.durationSeconds,
    candidateCount: draft.candidateCount,
    inputSources: [...(draft.inputSources || [])],
    selectedReferences: (draft.selectedReferences || []).map((item) => ({ ...item })),
    referenceSyncMode: draft.referenceSyncMode || "auto",
    autoReferenceExclusions: [...(draft.autoReferenceExclusions || [])],
    referenceOrderOverride: [...(draft.referenceOrderOverride || [])],
    draftVersion: Number(draft.draftVersion || 0),
    intentText: draft.intentText || "",
    intentMentions: (draft.intentMentions || []).map((item) => ({ ...item })),
    intent: draft.intent || null,
    autoBaseline: draft.autoBaseline || null,
    intentConflicts: [...(draft.intentConflicts || [])],
    promptManuallyModified: Boolean(draft.promptManuallyModified),
    lockedReferenceKeys: [...(draft.lockedReferenceKeys || [])],
    removedIntentReferenceKeys: [...(draft.removedIntentReferenceKeys || [])],
  };
}

export function videoDraftFromDetail(detail, settings, persistedDraft = null) {
  const modelAlias = (
    persistedDraft?.model_alias
    || settings?.default_model_alias
    || ""
  );
  const selectedModel = (settings?.models || []).find(
    (item) => item.alias === modelAlias,
  );
  const rawDuration = (
    persistedDraft?.duration_seconds
    ?? detail?.plan?.duration_seconds
    ?? 3
  );
  const durationSeconds = selectedModel
    ? normalizeVideoDuration(rawDuration, selectedModel)
    : normalizedDuration(rawDuration);
  const persistedV2 = persistedDraft?.schema_version === "viral-dna-shot-video-draft/v2";
  const videoPrompt = stripLegacyVideoReferencePolicies(
    persistedV2 ? persistedDraft?.video_prompt : detail?.plan?.video_prompt || "",
  );
  const legacyMentions = persistedV2
    ? persistedDraft?.video_prompt_mentions || []
    : detail?.plan?.video_prompt_mentions || [];
  const persistedReferences = persistedDraft?.input_plan?.references;
  const shouldRespectEmptyPersistedReferences = (
    persistedV2
    || ["user", "intent_generated"].includes(persistedDraft?.origin)
  );
  const baseReferences = (
    Array.isArray(persistedReferences)
    && (persistedReferences.length > 0 || shouldRespectEmptyPersistedReferences)
  ) ? persistedReferences : legacyMentions;
  const referenceFrames = approvedVisualBeatFramesFromDetail(detail);
  const currentVisualBeatIds = new Set(
    referenceFrames.map(({ beat }) => String(beat.id)),
  );
  const autoReferenceExclusions = (
    persistedDraft?.auto_reference_exclusions || []
  ).map(String).filter((id) => currentVisualBeatIds.size === 0 || currentVisualBeatIds.has(id));
  const referenceOrderOverride = (
    persistedDraft?.reference_order_override || []
  ).map(String);
  const selectedReferences = synchronizeAutomaticVideoReferences({
    selectedReferences: baseReferences,
    referenceFrames,
    excludedVisualBeatIds: autoReferenceExclusions,
    orderOverride: referenceOrderOverride,
  });
  const selectedStableKeys = new Set(selectedReferences.map(videoReferenceStableKey));
  const effectiveReferenceOrderOverride = referenceOrderOverride.filter(
    (key) => selectedStableKeys.has(key),
  );
  const synchronizedPrompt = synchronizeAutomaticVideoPrompt({
    prompt: videoPrompt,
    mentions: legacyMentions,
    selectedReferences,
  });
  const inferredSources = selectedReferences
    .map(requiredSourceForVideoMention)
    .filter(Boolean);
  return {
    ...EMPTY_VIDEO_DRAFT,
    videoPrompt: synchronizedPrompt.videoPrompt,
    videoPromptMentions: synchronizedPrompt.videoPromptMentions,
    selectedReferences,
    negativeConstraints: (
      (
        persistedV2
          ? persistedDraft?.video_negative_constraints
          : detail?.plan?.video_negative_constraints
      ) || []
    ).join("\n"),
    durationSeconds: String(durationSeconds),
    candidateCount: normalizedCandidateCount(
      persistedDraft?.candidate_count,
    ),
    modelAlias,
    resolution: (
      persistedDraft?.resolution
      || settings?.default_resolution
      || "720P"
    ).toUpperCase(),
    inputSources: Array.from(new Set([
      ...(persistedDraft?.input_plan?.sources || []),
      ...inferredSources,
    ])),
    referenceSyncMode: persistedDraft?.reference_sync_mode || "auto",
    autoReferenceExclusions,
    referenceOrderOverride: effectiveReferenceOrderOverride,
    draftVersion: Number(persistedDraft?.draft_version || 0),
    intentText: persistedDraft?.intent?.text || "",
    intentMentions: normalizeVideoGenerationReferences(
      persistedDraft?.intent?.mentions || [],
    ),
    intent: persistedDraft?.intent || null,
    autoBaseline: persistedDraft?.auto_baseline || null,
    intentConflicts: persistedDraft?.intent_conflicts || [],
    promptManuallyModified: Boolean(persistedDraft?.prompt_manually_modified),
    lockedReferenceKeys: (persistedDraft?.locked_reference_keys || []).map(String),
    removedIntentReferenceKeys: (
      persistedDraft?.removed_intent_reference_keys || []
    ).map(String),
  };
}

export function useShotVideoGenerationDraft({ request, onNotice }) {
  const [videoDraft, setVideoDraftState] = useState({ ...EMPTY_VIDEO_DRAFT });
  const [saveState, setSaveState] = useState("idle");
  const activeShotIdRef = useRef(null);
  const currentDraftRef = useRef({ ...EMPTY_VIDEO_DRAFT });
  const localDraftsRef = useRef(new Map());
  const promptBaselinesRef = useRef(new Map());
  const promptDirtyRef = useRef(new Set());
  const recordsRef = useRef(new Map());
  const pendingRef = useRef(new Map());
  const saveTimerRef = useRef(null);
  const saveChainRef = useRef(Promise.resolve());
  const lastNotifiedErrorRef = useRef("");

  const applyLocalDraft = useCallback((next, shotPlanId = activeShotIdRef.current) => {
    currentDraftRef.current = next;
    if (shotPlanId) localDraftsRef.current.set(shotPlanId, next);
    setVideoDraftState(next);
  }, []);

  const persistPending = useCallback((shotPlanId) => {
    const operation = saveChainRef.current
      .catch(() => undefined)
      .then(async () => {
        let pending = pendingRef.current.get(shotPlanId);
        if (!pending) return recordsRef.current.get(shotPlanId) || null;
        let record = recordsRef.current.get(shotPlanId);
        if (!record) {
          record = await request(
            `/production-shots/${shotPlanId}/video-generation-draft`,
          );
          recordsRef.current.set(shotPlanId, record);
        }
        setSaveState("saving");
        try {
          const save = (currentRecord, parameters) => request(
            `/production-shots/${shotPlanId}/video-generation-draft`,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                expected_draft_version: currentRecord.draft_version,
                ...parameters,
              }),
            },
          );
          let saved;
          try {
            saved = await save(record, pending);
          } catch (error) {
            if (error?.status !== 409) throw error;
            record = await request(
              `/production-shots/${shotPlanId}/video-generation-draft`,
            );
            recordsRef.current.set(shotPlanId, record);
            pending = pendingRef.current.get(shotPlanId);
            if (!pending) {
              setSaveState("saved");
              return record;
            }
            saved = await save(record, pending);
          }
          recordsRef.current.set(shotPlanId, saved);
          const savedLatestPending = sameParameters(
            pendingRef.current.get(shotPlanId),
            pending,
          );
          if (savedLatestPending) {
            pendingRef.current.delete(shotPlanId);
          }
          lastNotifiedErrorRef.current = "";
          setSaveState(savedLatestPending ? "saved" : "dirty");
          return saved;
        } catch (error) {
          setSaveState("error");
          const message = error?.message || "视频生成设置暂时无法保存";
          if (lastNotifiedErrorRef.current !== message) {
            lastNotifiedErrorRef.current = message;
            onNotice?.({
              type: "error",
              title: "视频生成设置未保存",
              message: `${message}；当前选择已在本页保留，请稍后重试。`,
            });
          }
          throw error;
        }
      });
    saveChainRef.current = operation.catch(() => undefined);
    return operation;
  }, [onNotice, request]);

  const scheduleSave = useCallback((shotPlanId, immediate) => {
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    if (immediate) {
      persistPending(shotPlanId).catch(() => undefined);
      return;
    }
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null;
      persistPending(shotPlanId).catch(() => undefined);
    }, 400);
  }, [persistPending]);

  const setVideoDraft = useCallback((updater) => {
    const current = currentDraftRef.current;
    const proposed = typeof updater === "function" ? updater(current) : updater;
    const promptChanged = (
      proposed.videoPrompt !== current.videoPrompt
      || JSON.stringify(proposed.videoPromptMentions || [])
        !== JSON.stringify(current.videoPromptMentions || [])
      || proposed.negativeConstraints !== current.negativeConstraints
    );
    const next = promptChanged
      ? { ...proposed, promptManuallyModified: true }
      : proposed;
    const shotPlanId = activeShotIdRef.current;
    applyLocalDraft(next, shotPlanId);
    if (!shotPlanId) return;
    const promptBaseline = promptBaselinesRef.current.get(shotPlanId);
    if (
      promptBaseline
      && next.videoPrompt === promptBaseline.videoPrompt
      && JSON.stringify(next.videoPromptMentions || [])
        === JSON.stringify(promptBaseline.videoPromptMentions || [])
      && next.negativeConstraints === promptBaseline.negativeConstraints
    ) {
      promptDirtyRef.current.delete(shotPlanId);
    } else if (
      next.videoPrompt !== current.videoPrompt
      || JSON.stringify(next.videoPromptMentions || [])
        !== JSON.stringify(current.videoPromptMentions || [])
      || next.negativeConstraints !== current.negativeConstraints
    ) {
      promptDirtyRef.current.add(shotPlanId);
    }
    const currentParameters = videoDraftParameters(current);
    const nextParameters = videoDraftParameters(next);
    if (sameParameters(currentParameters, nextParameters)) return;
    pendingRef.current.set(shotPlanId, nextParameters);
    setSaveState("dirty");
    scheduleSave(
      shotPlanId,
      currentParameters.model_alias !== nextParameters.model_alias,
    );
  }, [applyLocalDraft, scheduleSave]);

  const hydrateVideoDraft = useCallback(({
    shotPlanId,
    detail,
    settings,
    persistedDraft,
  }) => {
    const knownRecord = recordsRef.current.get(shotPlanId);
    const persistedVersion = Number(persistedDraft?.draft_version || 0);
    const effectiveRecord = (
      Number(knownRecord?.draft_version || 0) > persistedVersion
        ? knownRecord
        : persistedDraft
    );
    if (effectiveRecord) recordsRef.current.set(shotPlanId, effectiveRecord);
    const generated = videoDraftFromDetail(detail, settings, effectiveRecord);
    const hasPendingLocal = pendingRef.current.has(shotPlanId);
    const localDraft = localDraftsRef.current.get(shotPlanId);
    const promptWasDirty = promptDirtyRef.current.has(shotPlanId);
    const promptMatchesServer = Boolean(
      localDraft
      && localDraft.videoPrompt === generated.videoPrompt
      && JSON.stringify(localDraft.videoPromptMentions || [])
        === JSON.stringify(generated.videoPromptMentions || [])
      && localDraft.negativeConstraints === generated.negativeConstraints
    );
    if (promptWasDirty && promptMatchesServer) {
      promptDirtyRef.current.delete(shotPlanId);
    }
    promptBaselinesRef.current.set(shotPlanId, {
      videoPrompt: generated.videoPrompt,
      videoPromptMentions: generated.videoPromptMentions,
      negativeConstraints: generated.negativeConstraints,
    });
    const preservePrompt = promptDirtyRef.current.has(shotPlanId);
    const next = localDraft && (hasPendingLocal || preservePrompt)
      ? {
          ...generated,
          ...(hasPendingLocal ? localVideoDraftParameters(localDraft) : {}),
          ...(preservePrompt
            ? {
                videoPrompt: localDraft.videoPrompt,
                videoPromptMentions: localDraft.videoPromptMentions,
                negativeConstraints: localDraft.negativeConstraints,
              }
            : {}),
        }
      : generated;
    activeShotIdRef.current = shotPlanId;
    applyLocalDraft(next, shotPlanId);
    setSaveState(hasPendingLocal ? "saving" : "saved");
    return next;
  }, [applyLocalDraft]);

  const flushVideoDraft = useCallback(async (shotPlanId = activeShotIdRef.current) => {
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    if (!shotPlanId || !pendingRef.current.has(shotPlanId)) {
      await saveChainRef.current;
      return recordsRef.current.get(shotPlanId) || null;
    }
    return persistPending(shotPlanId);
  }, [persistPending]);

  const applyPersistedVideoDraft = useCallback(({
    shotPlanId,
    detail,
    settings,
    persistedDraft,
  }) => {
    pendingRef.current.delete(shotPlanId);
    localDraftsRef.current.delete(shotPlanId);
    promptDirtyRef.current.delete(shotPlanId);
    recordsRef.current.set(shotPlanId, persistedDraft);
    return hydrateVideoDraft({ shotPlanId, detail, settings, persistedDraft });
  }, [hydrateVideoDraft]);

  const resetVideoDraft = useCallback(() => {
    const activeShotId = activeShotIdRef.current;
    if (activeShotId && pendingRef.current.has(activeShotId)) {
      persistPending(activeShotId).catch(() => undefined);
    }
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    activeShotIdRef.current = null;
    applyLocalDraft({ ...EMPTY_VIDEO_DRAFT }, null);
    setSaveState("idle");
  }, [applyLocalDraft, persistPending]);

  useEffect(() => () => {
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
  }, []);

  return {
    applyPersistedVideoDraft,
    flushVideoDraft,
    hydrateVideoDraft,
    resetVideoDraft,
    saveState,
    setVideoDraft,
    videoDraft,
  };
}
