export const PROMPT_AUTOSAVE_DELAY_MS = 700;

const ENGLISH_WORD_PATTERN = /[A-Za-z]{2,}/;
const ALLOWED_ENGLISH_LITERAL_PATTERN = /(?:英文)?(?:台词|对白|字幕|标识|画面文字|屏幕文字)\s*[：:]\s*(?:“[^”\n]*”|"[^"\n]*"|「[^」\n]*」|『[^』\n]*』)/gi;

const INTERNAL_GLOBAL_PROMPT_PREFIXES = [
  "逐镜头视觉事实和复刻提示词已生成",
  "尚未生成：真实关键帧已就绪",
];

export function hasReportableGlobalPrompt(value) {
  const text = String(value || "").trim();
  return Boolean(text)
    && !INTERNAL_GLOBAL_PROMPT_PREFIXES.some((prefix) => text.startsWith(prefix));
}

export function containsUnlabeledEnglish(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  return ENGLISH_WORD_PATTERN.test(text.replace(ALLOWED_ENGLISH_LITERAL_PATTERN, ""));
}

export function promptDraftContainsUnlabeledEnglish(draft) {
  if (!draft) return false;
  const values = [
    ...Object.values(draft.visual || {}),
    ...(draft.phases || []).flatMap((phase) => [
      phase.subject_motion,
      phase.camera_motion,
      phase.foreground_motion,
      phase.focus_change,
    ]),
    draft.transition?.instruction,
    draft.transition?.mask_object,
    draft.transition?.direction,
    draft.transition?.terminal_frame,
    ...(draft.negative_constraints || []),
    draft.custom_notes,
  ];
  return values.some(containsUnlabeledEnglish);
}

export function replaceShotDraft(promptPackage, shotId, draft) {
  if (!promptPackage) return promptPackage;
  return {
    ...promptPackage,
    shots: (promptPackage.shots || []).map((shot) => (
      shot.shot_id === shotId ? { ...shot, draft } : shot
    )),
  };
}

export function mergePendingDrafts(promptPackage, pendingDrafts) {
  let merged = promptPackage;
  for (const [shotId, draft] of pendingDrafts) {
    merged = replaceShotDraft(merged, shotId, draft);
  }
  return merged;
}

export function createTimelinePhase(phases, durationSeconds) {
  const ordered = [...(phases || [])].sort((a, b) => a.start_seconds - b.start_seconds);
  const firstStart = Number(ordered[0]?.start_seconds || 0);
  const timelineEnd = firstStart + Math.max(0.1, Number(durationSeconds || 0.1));
  const lastEnd = Number(ordered.at(-1)?.end_seconds ?? firstStart);
  const start = Math.min(lastEnd, Math.max(firstStart, timelineEnd - 0.1));
  const end = Math.min(timelineEnd, Math.max(start + 0.1, start + 0.5));
  return {
    id: `phase_${Date.now().toString(36)}`,
    start_seconds: Number(start.toFixed(2)),
    end_seconds: Number(end.toFixed(2)),
    subject_motion: "",
    camera_motion: "",
    foreground_motion: "",
    focus_change: "",
  };
}

export function moveItem(items, index, direction) {
  const target = index + direction;
  if (target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function promptSaveLabel(status, revisionNumber = 0) {
  if (status === "loading") return "正在读取草稿";
  if (status === "dirty") return "等待自动保存";
  if (status === "saving") return "正在保存";
  if (status === "error") return "保存失败";
  return revisionNumber > 0 ? `已保存 · 修订 ${revisionNumber}` : "已保存";
}
