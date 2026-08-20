import { useCallback, useEffect, useRef, useState } from "react";
import { normalizeVideoDuration } from "../production-ui.js";
import {
  normalizeVideoGenerationReferences,
  normalizeVideoPromptMentions,
  requiredSourceForVideoMention,
  stripLegacyVideoReferencePolicies,
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
  const videoPrompt = stripLegacyVideoReferencePolicies(detail?.plan?.video_prompt || "");
  const legacyMentions = detail?.plan?.video_prompt_mentions || [];
  const selectedReferences = normalizeVideoGenerationReferences(
    persistedDraft?.input_plan?.references?.length
      ? persistedDraft.input_plan.references
      : legacyMentions,
  );
  const inferredSources = selectedReferences
    .map(requiredSourceForVideoMention)
    .filter(Boolean);
  return {
    ...EMPTY_VIDEO_DRAFT,
    videoPrompt,
    videoPromptMentions: normalizeVideoPromptMentions(videoPrompt, legacyMentions),
    selectedReferences,
    negativeConstraints: (
      detail?.plan?.video_negative_constraints || []
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
          if (sameParameters(pendingRef.current.get(shotPlanId), pending)) {
            pendingRef.current.delete(shotPlanId);
          }
          lastNotifiedErrorRef.current = "";
          setSaveState("saved");
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
    const next = typeof updater === "function" ? updater(current) : updater;
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
    flushVideoDraft,
    hydrateVideoDraft,
    resetVideoDraft,
    saveState,
    setVideoDraft,
    videoDraft,
  };
}
