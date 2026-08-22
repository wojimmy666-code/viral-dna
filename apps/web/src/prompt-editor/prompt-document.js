import { hasReportableGlobalPrompt } from "./prompt-editor-ui.js";

export const PROMPT_VISUAL_FIELDS = [
  { key: "subjects", label: "主体与服装" },
  { key: "scene", label: "场景" },
  { key: "composition", label: "构图" },
  { key: "lighting", label: "光线" },
  { key: "color", label: "色彩" },
];

export const PROMPT_TRANSITION_OPTIONS = [
  { value: "none", label: "无转场" },
  { value: "hard_cut", label: "硬切" },
  { value: "crossfade", label: "交叉淡化" },
  { value: "foreground_occlusion", label: "前景遮挡" },
  { value: "wipe", label: "擦除" },
  { value: "whip_pan", label: "甩镜" },
  { value: "match_cut", label: "匹配剪辑" },
  { value: "other", label: "其他" },
  { value: "uncertain", label: "待确认" },
];

const TRANSITION_LABELS = new Map(
  PROMPT_TRANSITION_OPTIONS.map((item) => [item.value, item.label]),
);
const TRANSITION_VALUES = new Map(
  PROMPT_TRANSITION_OPTIONS.map((item) => [item.label, item.value]),
);
const VISUAL_KEYS = new Map(PROMPT_VISUAL_FIELDS.map((item) => [item.label, item.key]));
const PHASE_KEYS = new Map([
  ["主体动作", "subject_motion"],
  ["镜头运动", "camera_motion"],
  ["前景运动", "foreground_motion"],
  ["焦点变化", "focus_change"],
]);
const TRANSITION_KEYS = new Map([
  ["转场指令", "instruction"],
  ["遮挡对象", "mask_object"],
  ["运动方向", "direction"],
  ["结束状态", "terminal_frame"],
]);
const SECTION_LABELS = new Set([
  "基础画面",
  "时序运镜",
  "出场转场",
  "连续性引用",
  "负面约束",
  "补充说明",
]);
const EMPTY_TRANSITION = {
  kind: "none",
  start_seconds: null,
  end_seconds: null,
  instruction: "",
  mask_object: "",
  direction: "",
  terminal_frame: "",
};
const PROMPT_REFERENCE_PATTERN = /@[^\s@，。！？；、,:：!?()[\]{}<>【】“”‘’"']+/gu;
const PROMPT_SEMANTIC_PATTERN = /【([^】\n]{1,40})】/gu;
const TIME_LABEL_PATTERN = /^(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*(?:s|秒)?$/iu;

export function normalizePromptEditorText(value) {
  return String(value || "")
    .replace(/\r\n?/g, "\n")
    .replace(/\u00a0/g, " ");
}

export function findPromptReferenceRanges(value) {
  const text = normalizePromptEditorText(value);
  return [...text.matchAll(PROMPT_REFERENCE_PATTERN)].map((match) => ({
    start: match.index,
    end: match.index + match[0].length,
    text: match[0],
    type: "mention",
  }));
}

export function findPromptSemanticRanges(value) {
  const text = normalizePromptEditorText(value);
  return [...text.matchAll(PROMPT_SEMANTIC_PATTERN)].map((match) => {
    const label = match[1].trim();
    return {
      start: match.index,
      end: match.index + match[0].length,
      label,
      text: match[0],
      type: SECTION_LABELS.has(label)
        ? "section"
        : TIME_LABEL_PATTERN.test(label)
          ? "time"
          : "label",
    };
  });
}

export function findPromptDecorationRanges(value) {
  const result = [];
  for (const range of [
    ...findPromptSemanticRanges(value),
    ...findPromptReferenceRanges(value),
  ].sort((left, right) => left.start - right.start || right.end - left.end)) {
    if (result.length === 0 || range.start >= result.at(-1).end) result.push(range);
  }
  return result;
}

function deleteAtomicRange(value, { key, selectionStart, selectionEnd }, ranges) {
  if (key !== "Backspace" && key !== "Delete") return null;
  const text = normalizePromptEditorText(value);
  const start = Math.max(0, Math.min(Number(selectionStart) || 0, text.length));
  const requestedEnd = selectionEnd == null ? start : selectionEnd;
  const end = Math.max(start, Math.min(Number(requestedEnd) || start, text.length));
  let matches = [];
  if (start !== end) {
    matches = ranges.filter((range) => range.start < end && range.end > start);
  } else if (key === "Backspace") {
    matches = ranges.filter((range) => start > range.start && start <= range.end);
  } else {
    matches = ranges.filter((range) => start >= range.start && start < range.end);
  }
  if (matches.length === 0) return null;

  const deleteStart = Math.min(start, ...matches.map((range) => range.start));
  const deleteEnd = Math.max(end, ...matches.map((range) => range.end));
  const before = text.slice(0, deleteStart);
  let after = text.slice(deleteEnd);
  if (before.endsWith(" ") && after.startsWith(" ")) after = after.slice(1);
  return { value: before + after, caret: deleteStart };
}

export function deleteAtomicPromptReference(
  value,
  { key, selectionStart, selectionEnd = selectionStart },
) {
  return deleteAtomicRange(
    value,
    { key, selectionStart, selectionEnd },
    findPromptReferenceRanges(value),
  );
}

export function deleteAtomicPromptDecoration(
  value,
  { key, selectionStart, selectionEnd = selectionStart },
) {
  return deleteAtomicRange(
    value,
    { key, selectionStart, selectionEnd },
    findPromptDecorationRanges(value),
  );
}

export function transitionHasContent(transition = {}) {
  return transition.kind !== "none"
    || transition.start_seconds != null
    || transition.end_seconds != null
    || [
      transition.instruction,
      transition.mask_object,
      transition.direction,
      transition.terminal_frame,
    ].some((value) => String(value || "").trim());
}

function compactText(value) {
  return normalizePromptEditorText(value).trim();
}

function plainSeconds(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  return number.toFixed(2).replace(/0+$/u, "").replace(/\.$/u, ".0");
}

function editorSeconds(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "0.00";
}

function labelLine(label, value = "") {
  const text = normalizePromptEditorText(value).trim();
  return `【${label}】${text ? ` ${text}` : ""}`;
}

function bulletLines(values) {
  return (values || [])
    .map(compactText)
    .filter(Boolean)
    .map((item) => `- ${item}`);
}

export function promptDraftToDocumentText(draft) {
  if (!draft) return "";
  const blocks = [];
  blocks.push([
    "【基础画面】",
    ...PROMPT_VISUAL_FIELDS.map((field) => labelLine(
      field.label,
      draft.visual?.[field.key],
    )),
  ].join("\n"));

  const phaseLines = ["【时序运镜】"];
  (draft.phases || []).forEach((phase, index) => {
    if (index > 0) phaseLines.push("");
    phaseLines.push(`【${editorSeconds(phase.start_seconds)}–${editorSeconds(phase.end_seconds)}s】`);
    for (const [label, key] of PHASE_KEYS) {
      phaseLines.push(labelLine(label, phase[key]));
    }
  });
  blocks.push(phaseLines.join("\n"));

  if (transitionHasContent(draft.transition)) {
    const transition = { ...EMPTY_TRANSITION, ...draft.transition };
    const transitionLines = [
      "【出场转场】",
      labelLine("类型", TRANSITION_LABELS.get(transition.kind) || transition.kind),
    ];
    if (transition.start_seconds != null || transition.end_seconds != null) {
      transitionLines.push(labelLine(
        "时间",
        `${transition.start_seconds == null ? "未设置" : editorSeconds(transition.start_seconds)}`
          + `–${transition.end_seconds == null ? "未设置" : editorSeconds(transition.end_seconds)}s`,
      ));
    }
    for (const [label, key] of TRANSITION_KEYS) {
      if (compactText(transition[key])) transitionLines.push(labelLine(label, transition[key]));
    }
    blocks.push(transitionLines.join("\n"));
  } else {
    blocks.push("【出场转场】\n无转场");
  }

  if (draft.continuity_refs?.length) {
    blocks.push(["【连续性引用】", ...bulletLines(draft.continuity_refs)].join("\n"));
  }
  blocks.push(["【负面约束】", ...bulletLines(draft.negative_constraints)].join("\n"));
  blocks.push(["【补充说明】", compactText(draft.custom_notes)].filter(Boolean).join("\n"));
  return blocks.join("\n\n").trim();
}

function promptTokens(value) {
  const text = normalizePromptEditorText(value);
  const matches = [...text.matchAll(PROMPT_SEMANTIC_PATTERN)];
  return {
    prefix: compactText(text.slice(0, matches[0]?.index ?? text.length)),
    tokens: matches.map((match, index) => ({
      label: match[1].trim(),
      raw: match[0],
      content: text
        .slice(match.index + match[0].length, matches[index + 1]?.index ?? text.length)
        .replace(/^[\t ]+/u, "")
        .replace(/^\n+/u, "")
        .trimEnd(),
    })),
  };
}

function parseList(value) {
  return normalizePromptEditorText(value)
    .split("\n")
    .map((item) => item.replace(/^\s*[-•]\s*/u, "").trim())
    .filter(Boolean);
}

function parseTimeRange(value) {
  const match = compactText(value).match(
    /(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*(?:s|秒)?/iu,
  );
  if (!match) return null;
  return { start: Number(match[1]), end: Number(match[2]) };
}

function phaseId(basePhases, index, start, end) {
  const exact = (basePhases || []).find((phase) => (
    Number(phase.start_seconds) === start && Number(phase.end_seconds) === end
  ));
  return exact?.id || basePhases?.[index]?.id || `phase_document_${index + 1}`;
}

export function promptDocumentTextToDraft(value, baseDraft) {
  if (!baseDraft) return baseDraft;
  const basePhases = baseDraft.phases || [];
  const nextDraft = {
    ...baseDraft,
    visual: Object.fromEntries(PROMPT_VISUAL_FIELDS.map((field) => [field.key, ""])),
    phases: [],
    transition: { ...EMPTY_TRANSITION },
    continuity_refs: [],
    negative_constraints: [],
    custom_notes: "",
  };
  const { prefix, tokens } = promptTokens(value);
  const extras = prefix ? [prefix] : [];
  let section = "";
  let currentPhase = null;

  function finishPhase() {
    if (!currentPhase) return;
    nextDraft.phases.push(currentPhase);
    currentPhase = null;
  }

  for (const token of tokens) {
    const visualKey = VISUAL_KEYS.get(token.label);
    if (visualKey) {
      nextDraft.visual[visualKey] = compactText(token.content);
      continue;
    }

    const time = token.label.match(TIME_LABEL_PATTERN);
    if (time) {
      finishPhase();
      const start = Number(time[1]);
      const end = Number(time[2]);
      currentPhase = {
        id: phaseId(basePhases, nextDraft.phases.length, start, end),
        start_seconds: start,
        end_seconds: end,
        subject_motion: "",
        camera_motion: "",
        foreground_motion: "",
        focus_change: "",
      };
      if (compactText(token.content)) currentPhase.subject_motion = compactText(token.content);
      section = "时序运镜";
      continue;
    }

    const phaseKey = PHASE_KEYS.get(token.label);
    if (phaseKey && currentPhase) {
      currentPhase[phaseKey] = compactText(token.content);
      continue;
    }

    if (token.label === "基础画面" || token.label === "时序运镜") {
      section = token.label;
      if (compactText(token.content)) extras.push(compactText(token.content));
      continue;
    }

    if (token.label === "出场转场") {
      finishPhase();
      section = token.label;
      const content = compactText(token.content);
      if (content && content !== "无转场") {
        nextDraft.transition.kind = baseDraft.transition?.kind === "none"
          ? "other"
          : baseDraft.transition?.kind || "other";
        nextDraft.transition.instruction = content;
      }
      continue;
    }

    if (section === "出场转场" && token.label === "类型") {
      const content = compactText(token.content);
      nextDraft.transition.kind = TRANSITION_VALUES.get(content)
        || (PROMPT_TRANSITION_OPTIONS.some((item) => item.value === content) ? content : "other");
      continue;
    }

    if (section === "出场转场" && token.label === "时间") {
      const range = parseTimeRange(token.content);
      if (range) {
        nextDraft.transition.start_seconds = range.start;
        nextDraft.transition.end_seconds = range.end;
      }
      continue;
    }

    const transitionKey = TRANSITION_KEYS.get(token.label);
    if (section === "出场转场" && transitionKey) {
      nextDraft.transition[transitionKey] = compactText(token.content);
      if (nextDraft.transition.kind === "none" && nextDraft.transition[transitionKey]) {
        nextDraft.transition.kind = baseDraft.transition?.kind === "none"
          ? "other"
          : baseDraft.transition?.kind || "other";
      }
      continue;
    }

    if (token.label === "连续性引用") {
      finishPhase();
      section = token.label;
      nextDraft.continuity_refs = parseList(token.content);
      continue;
    }

    if (token.label === "负面约束") {
      finishPhase();
      section = token.label;
      nextDraft.negative_constraints = parseList(token.content);
      continue;
    }

    if (token.label === "补充说明") {
      finishPhase();
      section = token.label;
      nextDraft.custom_notes = compactText(token.content);
      continue;
    }

    extras.push(token.raw + token.content);
  }
  finishPhase();

  if (nextDraft.phases.length === 0) {
    nextDraft.phases = basePhases.map((phase) => ({
      ...phase,
      subject_motion: "",
      camera_motion: "",
      foreground_motion: "",
      focus_change: "",
    }));
  }
  if (extras.length > 0) {
    nextDraft.custom_notes = [nextDraft.custom_notes, ...extras]
      .map(compactText)
      .filter(Boolean)
      .join("\n");
  }
  return nextDraft;
}

export function promptShotDocumentText(shot) {
  return shot?.draft
    ? promptDraftToDocumentText(shot.draft)
    : compactText(shot?.prompt);
}

export function promptShotSummary(shot, maxLength = 72) {
  const summary = promptShotDocumentText(shot)
    .replace(PROMPT_SEMANTIC_PATTERN, " ")
    .replace(/^\s*[-•]\s*/gmu, " ")
    .replace(/\s+/gu, " ")
    .trim();
  if (!summary) return "暂无提示词内容";
  return summary.length > maxLength ? summary.slice(0, maxLength).trimEnd() + "…" : summary;
}

export function promptShotCharacterCount(shot) {
  return [...promptShotDocumentText(shot).replace(/\s/gu, "")].length;
}

function bulletSection(title, values) {
  const items = bulletLines(values);
  return items.length > 0 ? [title, ...items].join("\n") : "";
}

export function promptShotToPlainText(shot, index = 0) {
  const shotTitle = [
    "分镜 " + String(index + 1).padStart(2, "0"),
    Number.isFinite(Number(shot?.duration_seconds))
      ? plainSeconds(shot.duration_seconds) + " 秒"
      : "",
  ].filter(Boolean).join(" · ");
  return [shotTitle, promptShotDocumentText(shot)].filter(Boolean).join("\n\n");
}

export function promptPackageToPlainText(promptPackage) {
  if (!promptPackage) return "";
  const blocks = [];
  const globalBlocks = [];
  const globalPrompt = compactText(promptPackage.global_prompt);
  if (hasReportableGlobalPrompt(globalPrompt)) globalBlocks.push(globalPrompt);
  const continuity = bulletSection("连续性锁定", promptPackage.continuity_locks);
  if (continuity) globalBlocks.push(continuity);
  const constraints = bulletSection("全局负面约束", promptPackage.negative_constraints);
  if (constraints) globalBlocks.push(constraints);
  if (globalBlocks.length > 0) blocks.push(["全局视觉路径", ...globalBlocks].join("\n\n"));

  const shots = (promptPackage.shots || [])
    .map((shot, index) => promptShotToPlainText(shot, index))
    .filter(Boolean);
  if (shots.length > 0) blocks.push(shots.join("\n\n────────────────────\n\n"));
  return blocks.filter(Boolean).join("\n\n").trim() + "\n";
}

export function promptTextFilename(promptPackage) {
  const version = Number(promptPackage?.version) || 1;
  return "viral-dna-prompts-v" + version + ".txt";
}
