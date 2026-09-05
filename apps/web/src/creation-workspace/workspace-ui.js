export const CREATION_STEPS = Object.freeze([
  { id: "project_setup", label: "创作方案" },
  { id: "shot_images", label: "分镜图片" },
  { id: "shot_videos", label: "分镜视频" },
  { id: "editing", label: "视频剪辑" },
  { id: "export", label: "导出成片" },
]);

export const PREPARATION_SECTIONS = Object.freeze([
  { id: "creative_brief", label: "创作简报" },
  { id: "style_confirmation", label: "风格确认" },
  { id: "storyboard_design", label: "大纲与分镜" },
]);

const SECTIONS = new Set([
  ...CREATION_STEPS.map((step) => step.id),
  ...PREPARATION_SECTIONS.map((step) => step.id),
  "audio_caption", "reference_assets", "revisions",
]);

export function mainCreationStep(section) {
  if (PREPARATION_SECTIONS.some((item) => item.id === section)) return "project_setup";
  if (section === "audio_caption") return "editing";
  return CREATION_STEPS.some((item) => item.id === section) ? section : "";
}

export function productionNavigation(project = {}, gate = null) {
  const stage = project.active_step === "reference_assets" ? "shot_images" : project.active_step;
  const reached = Math.max(1, CREATION_STEPS.findIndex((item) => item.id === stage));
  return CREATION_STEPS.map((step, index) => ({
    ...step,
    enabled: index <= reached || (step.id === "export" && stage === "editing"),
    complete: index < reached,
    status: index < reached ? "已完成" : step.id === stage && gate && ["shot_images", "shot_videos"].includes(stage)
      ? `已采用 ${gate.approved_shot_count || 0}/${gate.required_shot_count || 0}` : "",
  }));
}

export function readWorkspaceLocation(search = "") {
  const params = new URLSearchParams(search);
  return {
    productionId: params.get("production") || "",
    section: SECTIONS.has(params.get("studio")) ? params.get("studio") : "",
    shotId: params.get("shot") || "",
    visualBeatId: params.get("beat") || "",
    candidateId: params.get("candidate") || "",
  };
}

export function workspaceSearch(search, update) {
  const params = new URLSearchParams(search);
  const keys = { productionId: "production", section: "studio", shotId: "shot", visualBeatId: "beat", candidateId: "candidate" };
  for (const [key, value] of Object.entries(update)) {
    if (!keys[key]) continue;
    if (value && (key !== "section" || SECTIONS.has(value))) params.set(keys[key], value);
    else params.delete(keys[key]);
  }
  const result = params.toString();
  return result ? `?${result}` : "";
}

export function savedWorkspaceLocation(recordId, search = "") {
  const explicit = readWorkspaceLocation(search);
  if (explicit.section || explicit.productionId) return explicit;
  try {
    return readWorkspaceLocation(globalThis.sessionStorage?.getItem(`viraldna:studio:${recordId}`) || "");
  } catch {
    return explicit;
  }
}

export function rememberWorkspaceLocation(recordId, search) {
  try { globalThis.sessionStorage?.setItem(`viraldna:studio:${recordId}`, search); } catch { /* URL remains usable when storage is unavailable. */ }
}

export function sourceCapabilities(project, sourceMedia = {}) {
  const hasVideo = Boolean(project?.video_id) && sourceMedia.hasSourceVideo !== false;
  return { hasVideo, hasAudio: hasVideo && Boolean(sourceMedia.hasAudio) };
}
