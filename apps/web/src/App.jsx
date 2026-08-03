import { forwardRef, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwise,
  Bell,
  BracketsCurly,
  CaretDown,
  CaretRight,
  ChartBar,
  Check,
  CheckCircle,
  CircleNotch,
  ClockCounterClockwise,
  Copy,
  DownloadSimple,
  Folder,
  FolderOpen,
  FolderPlus,
  FileVideo,
  FilmStrip,
  Gear,
  LinkSimple,
  ListBullets,
  LockSimple,
  MagnifyingGlass,
  MagicWand,
  PencilSimple,
  Pause,
  Play,
  Plus,
  Question,
  ShieldCheck,
  Sparkle,
  SquaresFour,
  Swap,
  Target,
  TextT,
  UploadSimple,
  VideoCamera,
  X,
} from "@phosphor-icons/react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";
const MODEL_SETTINGS_STORAGE_KEY = "viral-dna:model-settings:v1";
const DEFAULT_MODEL_SETTINGS = Object.freeze({
  targetModel: "seedance",
  analysisProfile: "balanced",
  maxCostCny: "1.00",
});
const DEFAULT_SERVER_MODEL_SETTINGS = Object.freeze({
  provider: "dashscope",
  model_alias: "auto",
  model: null,
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  api_key_configured: false,
  api_key_hint: null,
  last_validated_at: null,
  validation_latency_ms: null,
  providers: [{ id: "dashscope", label: "阿里云百炼（DashScope）" }],
  models: [],
});
const DEFAULT_WORKSPACE_INFO = Object.freeze({
  root_path: "",
  database_path: "",
  writable: false,
  schema_version: 1,
  record_count: 0,
  folder_count: 0,
});
const PROFILE_OPTIONS = [
  { id: "quality", label: "高质量", description: "优先使用能力更强的模型，适合成片级拆解。" },
  { id: "balanced", label: "均衡", description: "质量与成本平衡，推荐作为日常默认。" },
  { id: "economy", label: "经济", description: "优先控制成本，失败时按服务端路由回退。" },
];
const VALID_ANALYSIS_PROFILES = new Set(PROFILE_OPTIONS.map((item) => item.id));
const VALID_TARGET_MODELS = new Set(["seedance", "generic"]);

function loadModelSettings() {
  if (typeof window === "undefined") return { ...DEFAULT_MODEL_SETTINGS };
  try {
    const saved = JSON.parse(window.localStorage.getItem(MODEL_SETTINGS_STORAGE_KEY) || "null");
    if (!saved || typeof saved !== "object") return { ...DEFAULT_MODEL_SETTINGS };
    const storedCost = saved.maxCostCny == null ? DEFAULT_MODEL_SETTINGS.maxCostCny : String(saved.maxCostCny);
    const costNumber = storedCost.trim() ? Number(storedCost) : null;
    return {
      targetModel: VALID_TARGET_MODELS.has(saved.targetModel)
        ? saved.targetModel
        : DEFAULT_MODEL_SETTINGS.targetModel,
      analysisProfile: VALID_ANALYSIS_PROFILES.has(saved.analysisProfile)
        ? saved.analysisProfile
        : DEFAULT_MODEL_SETTINGS.analysisProfile,
      maxCostCny:
        costNumber === null || (Number.isFinite(costNumber) && costNumber > 0 && costNumber <= 1000)
          ? storedCost
          : DEFAULT_MODEL_SETTINGS.maxCostCny,
    };
  } catch {
    return { ...DEFAULT_MODEL_SETTINGS };
  }
}

const stageLabels = {
  queued: "排队中",
  ingesting: "读取来源",
  preprocessing: "媒体预处理",
  segmenting: "分镜检测",
  transcribing: "语音与字幕",
  understanding: "画面理解",
  reasoning: "爆点分析",
  compiling_prompts: "提示词编译",
  validating: "结果校验",
  completed: "已完成",
  failed: "失败",
};
const recordStatusLabels = {
  ready: "待分析",
  analyzing: "分析中",
  completed: "已完成",
  failed: "失败",
};

const navItems = [
  { id: "workspace", label: "工作台", icon: SquaresFour },
  { id: "new-analysis", label: "新建分析", icon: Plus },
  { id: "history", label: "分析记录", icon: ClockCounterClockwise },
  { id: "templates", label: "提示词模板", icon: BracketsCurly },
];

const reportTabs = [
  { id: "overview", label: "总览", icon: ChartBar },
  { id: "shots", label: "分镜拆解", icon: FilmStrip },
  { id: "viral", label: "爆点分析", icon: Target },
  { id: "replace", label: "元素替换", icon: Swap },
  { id: "prompts", label: "提示词", icon: TextT },
];

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(payload?.detail || "请求失败，请稍后重试");
  }
  return payload;
}

function formatTime(seconds = 0) {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.max(0, seconds - minutes * 60);
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
}

function formatCost(micros = 0) {
  const value = Number(micros || 0) / 1_000_000;
  return `¥${value.toFixed(value > 0 ? 4 : 2)}`;
}

function formatValidationTime(value) {
  if (!value) return "尚未验证";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "已验证";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
function formatRecordDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function resolveArtifactUrl(path) {
  if (!path || /^https?:\/\//i.test(path) || !API_BASE.startsWith("http")) return path || "";
  return new URL(path, API_BASE).toString();
}

function resolveApiUrl(path) {
  return `${API_BASE.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;
}

function useFilePreview(file) {
  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : ""), [file]);
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);
  return previewUrl;
}

export function App() {
  const initialModelSettings = useMemo(loadModelSettings, []);
  const [activeNav, setActiveNav] = useState("workspace");
  const [sourceMode, setSourceMode] = useState("link");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState(null);
  const [targetModel, setTargetModel] = useState(initialModelSettings.targetModel);
  const [analysisProfile, setAnalysisProfile] = useState(initialModelSettings.analysisProfile);
  const [maxCostCny, setMaxCostCny] = useState(initialModelSettings.maxCostCny);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [serverModelSettings, setServerModelSettings] = useState(DEFAULT_SERVER_MODEL_SETTINGS);
  const [settingsDraft, setSettingsDraft] = useState({
    ...initialModelSettings,
    provider: DEFAULT_SERVER_MODEL_SETTINGS.provider,
    modelAlias: DEFAULT_SERVER_MODEL_SETTINGS.model_alias,
    baseUrl: DEFAULT_SERVER_MODEL_SETTINGS.base_url,
    apiKey: "",
  });
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [workspaceInfo, setWorkspaceInfo] = useState(DEFAULT_WORKSPACE_INFO);
  const [workspaceDraft, setWorkspaceDraft] = useState("");
  const [workspaceValidation, setWorkspaceValidation] = useState(null);
  const [workspaceSaving, setWorkspaceSaving] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [folders, setFolders] = useState([]);
  const [records, setRecords] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyFolder, setHistoryFolder] = useState("");
  const [historyStatus, setHistoryStatus] = useState("");
  const [historySort, setHistorySort] = useState("updated_desc");
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [video, setVideo] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [analysisVersions, setAnalysisVersions] = useState([]);
  const [report, setReport] = useState(null);
  const [activeReportTab, setActiveReportTab] = useState("overview");
  const [activeShotId, setActiveShotId] = useState(null);
  const [replacementVersion, setReplacementVersion] = useState(null);
  const [notice, setNotice] = useState("");
  const eventSourceRef = useRef(null);
  const importSectionRef = useRef(null);
  const reportSectionRef = useRef(null);
  const videoRef = useRef(null);
  const filePreview = useFilePreview(file);

  useEffect(() => {
    return () => eventSourceRef.current?.close();
  }, []);

  useEffect(() => {
    loadWorkspace().catch(() => undefined);
    refreshHistory({ quiet: true }).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (activeNav !== "history") return undefined;
    const timer = window.setTimeout(() => {
      refreshHistory().catch(() => undefined);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [activeNav, historyQuery, historyFolder, historyStatus, historySort]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = window.setTimeout(() => setNotice(""), 2200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (!settingsOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event) => {
      if (event.key === "Escape" && !settingsSaving && !workspaceSaving) setSettingsOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [settingsOpen, settingsSaving, workspaceSaving]);

  async function loadWorkspace() {
    const next = await apiRequest("/workspace");
    setWorkspaceInfo(next);
    setWorkspaceDraft(next.root_path);
    return next;
  }

  async function refreshHistory({ quiet = false } = {}) {
    if (!quiet) setHistoryLoading(true);
    setHistoryError("");
    const params = new URLSearchParams();
    if (historyQuery.trim()) params.set("q", historyQuery.trim());
    if (historyFolder) params.set("folder_id", historyFolder);
    if (historyStatus) params.set("status", historyStatus);
    params.set("sort", historySort);
    try {
      const [recordPayload, folderPayload] = await Promise.all([
        apiRequest(`/records?${params.toString()}`),
        apiRequest("/folders"),
      ]);
      setRecords(recordPayload.items || []);
      setHistoryTotal(recordPayload.total || 0);
      setFolders(folderPayload || []);
      setWorkspaceInfo((current) => ({
        ...current,
        folder_count: folderPayload.length || 0,
      }));
    } catch (requestError) {
      setHistoryError(requestError.message);
      throw requestError;
    } finally {
      if (!quiet) setHistoryLoading(false);
    }
  }

  function selectNav(id) {
    setSettingsOpen(false);
    setActiveNav(id);
    if (id === "new-analysis") {
      importSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    if (id === "history") {
      refreshHistory().catch(() => undefined);
    }
  }

  async function openModelSettings() {
    setSettingsDraft({
      targetModel,
      analysisProfile,
      maxCostCny,
      provider: serverModelSettings.provider,
      modelAlias: serverModelSettings.model_alias,
      baseUrl: serverModelSettings.base_url,
      apiKey: "",
    });
    setSettingsError("");
    setSettingsOpen(true);
    setSettingsLoading(true);
    try {
      const [remote, nextWorkspace] = await Promise.all([
        apiRequest("/settings/model"),
        apiRequest("/workspace"),
      ]);
      setWorkspaceInfo(nextWorkspace);
      setWorkspaceDraft(nextWorkspace.root_path);
      setWorkspaceValidation(null);
      setWorkspaceError("");
      setServerModelSettings(remote);
      setSettingsDraft({
        targetModel,
        analysisProfile,
        maxCostCny,
        provider: remote.provider,
        modelAlias: remote.model_alias,
        baseUrl: remote.base_url,
        apiKey: "",
      });
    } catch (requestError) {
      setSettingsError(`无法读取服务端模型设置：${requestError.message}`);
    } finally {
      setSettingsLoading(false);
    }
  }

  function updateSettingsDraft(update) {
    setSettingsError("");
    setSettingsDraft((current) => ({ ...current, ...update }));
  }

  function updateWorkspaceDraft(value) {
    setWorkspaceDraft(value);
    setWorkspaceValidation(null);
    setWorkspaceError("");
  }

  async function validateWorkspace() {
    if (!workspaceDraft.trim()) {
      setWorkspaceError("请输入工作区文件夹路径。");
      return;
    }
    setWorkspaceSaving(true);
    setWorkspaceError("");
    try {
      const validation = await apiRequest("/workspace/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: workspaceDraft.trim() }),
      });
      setWorkspaceValidation(validation);
      setWorkspaceDraft(validation.normalized_path);
      if (!validation.valid) setWorkspaceError(validation.error || "工作区不可用");
    } catch (requestError) {
      setWorkspaceError(requestError.message);
    } finally {
      setWorkspaceSaving(false);
    }
  }

  async function switchWorkspace() {
    if (!workspaceDraft.trim()) {
      setWorkspaceError("请输入工作区文件夹路径。");
      return;
    }
    setWorkspaceSaving(true);
    setWorkspaceError("");
    try {
      const next = await apiRequest("/workspace", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: workspaceDraft.trim() }),
      });
      setWorkspaceInfo(next);
      setWorkspaceDraft(next.root_path);
      setWorkspaceValidation({ valid: true, writable: true, normalized_path: next.root_path });
      setVideo(null);
      setAnalysis(null);
      setReport(null);
      setReplacementVersion(null);
      await refreshHistory({ quiet: true });
      setNotice("工作区已切换，历史记录已重新加载");
    } catch (requestError) {
      setWorkspaceError(requestError.message);
    } finally {
      setWorkspaceSaving(false);
    }
  }

  async function createHistoryFolder() {
    const name = window.prompt("输入新目录名称");
    if (!name?.trim()) return;
    try {
      await apiRequest("/folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() }),
      });
      await refreshHistory({ quiet: true });
      setNotice("目录已创建");
    } catch (requestError) {
      setHistoryError(requestError.message);
    }
  }

  async function renameHistoryFolder(folder) {
    const name = window.prompt("修改目录名称", folder.name);
    if (!name?.trim() || name.trim() === folder.name) return;
    try {
      await apiRequest(`/folders/${folder.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() }),
      });
      await refreshHistory({ quiet: true });
      setNotice("目录名称已更新");
    } catch (requestError) {
      setHistoryError(requestError.message);
    }
  }

  async function updateHistoryRecord(recordId, update, successMessage) {
    try {
      await apiRequest(`/records/${recordId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      });
      await refreshHistory({ quiet: true });
      if (successMessage) setNotice(successMessage);
    } catch (requestError) {
      setHistoryError(requestError.message);
    }
  }

  async function renameHistoryRecord(record) {
    const name = window.prompt("修改分析记录名称", record.name);
    if (!name?.trim() || name.trim() === record.name) return;
    await updateHistoryRecord(record.id, { name: name.trim() }, "记录名称已更新");
  }

  async function openHistoryRecord(recordId) {
    setHistoryError("");
    try {
      const detail = await apiRequest(`/records/${recordId}`);
      setVideo(detail.video);
      setAnalysisVersions(detail.analyses || []);
      setAnalysis(detail.analyses?.[0] || null);
      setReport(detail.latest_report || null);
      setReplacementVersion(null);
      setActiveShotId(detail.latest_report?.shots?.[0]?.id || null);
      setActiveReportTab("overview");
      setActiveNav("workspace");
      window.setTimeout(() => {
        reportSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 120);
    } catch (requestError) {
      setHistoryError(requestError.message);
    }
  }

  async function saveModelSettings() {
    const trimmedCost = String(settingsDraft.maxCostCny || "").trim();
    const costNumber = trimmedCost ? Number(trimmedCost) : null;
    if (costNumber !== null && (!Number.isFinite(costNumber) || costNumber <= 0 || costNumber > 1000)) {
      setSettingsError("成本上限必须大于 0 且不超过 ¥1000，留空表示不限制。");
      return;
    }
    if (!String(settingsDraft.apiKey || "").trim() && !serverModelSettings.api_key_configured) {
      setSettingsError("首次配置请填写阿里云百炼 API Key。");
      return;
    }

    setSettingsSaving(true);
    setSettingsError("");
    try {
      const remote = await apiRequest("/settings/model", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: settingsDraft.provider,
          model_alias: settingsDraft.modelAlias,
          api_key: String(settingsDraft.apiKey || "").trim() || null,
          base_url: settingsDraft.baseUrl,
        }),
      });
      setServerModelSettings(remote);

      const nextSettings = {
        targetModel: settingsDraft.targetModel,
        analysisProfile: settingsDraft.analysisProfile,
        maxCostCny: costNumber === null ? "" : costNumber.toFixed(2),
      };
      setTargetModel(nextSettings.targetModel);
      setAnalysisProfile(nextSettings.analysisProfile);
      setMaxCostCny(nextSettings.maxCostCny);
      let persisted = true;
      try {
        window.localStorage.setItem(MODEL_SETTINGS_STORAGE_KEY, JSON.stringify(nextSettings));
      } catch {
        persisted = false;
      }
      setSettingsDraft((current) => ({ ...current, apiKey: "" }));
      setSettingsOpen(false);
      setNotice(
        persisted
          ? "API Key 验证通过，模型设置已保存"
          : "API Key 验证通过；设置已应用，但浏览器未保存默认值",
      );
    } catch (requestError) {
      setSettingsError(requestError.message);
    } finally {
      setSettingsSaving(false);
    }
  }

  function rememberAnalysis(next) {
    setAnalysis(next);
    setAnalysisVersions((current) => {
      const merged = [next, ...current.filter((item) => item.id !== next.id)];
      return merged.sort((left, right) => new Date(right.created_at) - new Date(left.created_at));
    });
  }

  async function pollAnalysis(analysisId) {
    for (let index = 0; index < 60; index += 1) {
      const next = await apiRequest(`/analyses/${analysisId}`);
      rememberAnalysis(next);
      if (next.stage === "completed") {
        await loadReport(next.video_id);
        return;
      }
      if (next.stage === "failed") {
        setError(next.error?.message || next.message || "分析失败");
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    }
    setError("分析仍在后台运行，请稍后刷新状态");
  }

  function connectToProgress(analysisId) {
    eventSourceRef.current?.close();
    const source = new EventSource(`${API_BASE}/analyses/${analysisId}/events`);
    eventSourceRef.current = source;
    source.addEventListener("progress", async (event) => {
      const next = JSON.parse(event.data);
      rememberAnalysis(next);
      if (next.stage === "completed") {
        source.close();
        await loadReport(next.video_id);
      }
      if (next.stage === "failed") {
        setError(next.error?.message || next.message || "分析失败");
        source.close();
      }
    });
    source.onerror = () => {
      source.close();
      pollAnalysis(analysisId).catch((requestError) => setError(requestError.message));
    };
  }

  async function loadReport(videoId) {
    const [nextReport, processedVideo] = await Promise.all([
      apiRequest(`/videos/${videoId}/report`),
      apiRequest(`/videos/${videoId}`),
    ]);
    setReport(nextReport);
    setVideo(processedVideo);
    setActiveShotId(nextReport.shots[0]?.id || null);
    setActiveReportTab("overview");
    loadWorkspace().catch(() => undefined);
    refreshHistory({ quiet: true }).catch(() => undefined);
    window.setTimeout(() => {
      reportSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 120);
  }

  async function startAnalysis() {
    setError("");
    setNotice("");
    if (!rightsConfirmed) {
      setError("请先确认拥有视频分析和使用权限");
      return;
    }
    if (sourceMode === "link" && !url.trim()) {
      setError("请粘贴抖音或小红书公开链接");
      return;
    }
    if (sourceMode === "file" && !file) {
      setError("请选择一个视频文件");
      return;
    }

    setSubmitting(true);
    setReport(null);
    setReplacementVersion(null);
    setAnalysis(null);
    setAnalysisVersions([]);
    try {
      let createdVideo;
      if (sourceMode === "link") {
        createdVideo = await apiRequest("/videos/link", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: url.trim(),
            target_model: targetModel,
            rights_confirmed: true,
          }),
        });
      } else {
        const form = new FormData();
        form.append("file", file);
        form.append("title", file.name.replace(/\.[^.]+$/, ""));
        form.append("target_model", targetModel);
        form.append("rights_confirmed", "true");
        createdVideo = await apiRequest("/videos/upload", { method: "POST", body: form });
      }

      setVideo(createdVideo);
      loadWorkspace().catch(() => undefined);
      refreshHistory({ quiet: true }).catch(() => undefined);
      const createdAnalysis = await apiRequest(`/videos/${createdVideo.id}/analyses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          granularity: "fine",
          include_audio: true,
          include_ocr: true,
          analysis_profile: analysisProfile,
          max_cost_cny: maxCostCny ? Number(maxCostCny) : null,
        }),
      });
      rememberAnalysis(createdAnalysis);
      connectToProgress(createdAnalysis.id);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  function seekToShot(shot) {
    setActiveShotId(shot.id);
    if (videoRef.current && Number.isFinite(shot.start_seconds)) {
      videoRef.current.currentTime = shot.start_seconds;
      videoRef.current.play().catch(() => undefined);
    }
  }

  const currentPromptPackage = replacementVersion?.prompt_package || report?.prompt_package;

  async function copyText(text, message = "已复制") {
    await navigator.clipboard.writeText(text);
    setNotice(message);
  }

  async function downloadPromptPackage() {
    if (!currentPromptPackage) return;
    if (video?.record_id && report) {
      try {
        const artifacts = await apiRequest(`/records/${video.record_id}/exports`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            analysis_id: report.analysis_id,
            kinds: ["prompt_package"],
            ...(replacementVersion
              ? { replacement_version_id: replacementVersion.id }
              : {}),
          }),
        });
        const artifact = artifacts[0];
        if (artifact) {
          const anchor = document.createElement("a");
          anchor.href = resolveApiUrl(`/exports/${artifact.id}/download`);
          anchor.download = artifact.filename;
          anchor.click();
          setNotice(
            replacementVersion
              ? "替换版提示词包已保存到工作区并开始下载"
              : "提示词包已保存到工作区并开始下载",
          );
          return;
        }
      } catch (requestError) {
        setError(requestError.message);
        return;
      }
    }
    const blob = new Blob([JSON.stringify(currentPromptPackage, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `viral-dna-prompt-v${currentPromptPackage.version}.json`;
    anchor.click();
    URL.revokeObjectURL(href);
    setNotice("替换版提示词包已下载");
  }

  async function openAnalysisVersion(analysisId) {
    if (!analysisId || analysisId === report?.analysis_id) return;
    const selected = analysisVersions.find((item) => item.id === analysisId);
    if (selected?.stage !== "completed") {
      setNotice("该分析版本尚未完成");
      return;
    }
    setError("");
    try {
      const nextReport = await apiRequest(`/analyses/${analysisId}/report`);
      setAnalysis(selected);
      setReport(nextReport);
      setReplacementVersion(null);
      setActiveShotId(nextReport.shots?.[0]?.id || null);
      setActiveReportTab("overview");
      setNotice("已切换分析版本");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function reanalyzeCurrent() {
    if (!video?.record_id) {
      selectNav("new-analysis");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      const next = await apiRequest(`/records/${video.record_id}/analyses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          granularity: "fine",
          include_audio: true,
          include_ocr: true,
          analysis_profile: analysisProfile,
          max_cost_cny: maxCostCny ? Number(maxCostCny) : null,
        }),
      });
      rememberAnalysis(next);
      setReport(null);
      setReplacementVersion(null);
      connectToProgress(next.id);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="app-shell">
      <Sidebar
        activeNav={activeNav}
        onSelect={selectNav}
        onOpenSettings={openModelSettings}
        settingsOpen={settingsOpen}
        historyCount={workspaceInfo.record_count}
      />

      <div className="app-body">
        <Topbar
          onCreate={() => selectNav("new-analysis")}
          onSearch={(value) => {
            setHistoryQuery(value);
            if (value) setActiveNav("history");
          }}
          searchValue={historyQuery}
        />

        <div className={activeNav === "history" ? "history-layout" : "workspace-layout"}>
          {activeNav === "history" ? (
            <HistoryPage
              records={records}
              folders={folders}
              total={historyTotal}
              loading={historyLoading}
              error={historyError}
              query={historyQuery}
              folderFilter={historyFolder}
              statusFilter={historyStatus}
              sort={historySort}
              workspace={workspaceInfo}
              onQueryChange={setHistoryQuery}
              onFolderChange={setHistoryFolder}
              onStatusChange={setHistoryStatus}
              onSortChange={setHistorySort}
              onCreateFolder={createHistoryFolder}
              onRenameFolder={renameHistoryFolder}
              onRenameRecord={renameHistoryRecord}
              onMoveRecord={(recordId, folderId) => updateHistoryRecord(recordId, { folder_id: folderId || null }, "记录目录已更新")}
              onOpenRecord={openHistoryRecord}
              onCreate={() => selectNav("new-analysis")}
            />
          ) : (<>
          <main className="workspace-main">
            <section className="page-intro">
              <div>
                <div className="breadcrumb">
                  <span>工作台</span>
                  <CaretRight size={14} />
                  <span className="breadcrumb-current">单视频拆解</span>
                </div>
                <h1>把一个视频拆成可复用的创作指令</h1>
                <p>识别分镜、主体、服装、场景和爆点，输出可编辑的复刻提示词包。</p>
              </div>
              <div className="intro-status">
                <ShieldCheck size={17} weight="fill" />
                Phase 1 · 单视频模式
              </div>
            </section>

            <ImportPanel
              ref={importSectionRef}
              sourceMode={sourceMode}
              setSourceMode={setSourceMode}
              url={url}
              setUrl={setUrl}
              file={file}
              setFile={setFile}
              targetModel={targetModel}
              setTargetModel={setTargetModel}
              analysisProfile={analysisProfile}
              setAnalysisProfile={setAnalysisProfile}
              maxCostCny={maxCostCny}
              setMaxCostCny={setMaxCostCny}
              rightsConfirmed={rightsConfirmed}
              setRightsConfirmed={setRightsConfirmed}
              submitting={submitting}
              error={error}
              onStart={startAnalysis}
            />

            {analysis && analysis.stage !== "completed" && (
              <AnalysisProgress analysis={analysis} video={video} />
            )}

            {!analysis && !report && <EmptyWorkspace />}

            {report && (
              <section className="report-card" ref={reportSectionRef}>
                <ReportHeader
                  video={video}
                  report={report}
                  promptPackage={currentPromptPackage}
                  onDownload={downloadPromptPackage}
                  onRestart={reanalyzeCurrent}
                  analysisVersions={analysisVersions}
                  activeAnalysisId={report.analysis_id}
                  onVersionChange={openAnalysisVersion}
                />
                <ReportTabs active={activeReportTab} onChange={setActiveReportTab} mode={report.analysis_mode} />
                <div className="report-content">
                  {activeReportTab === "overview" && (
                    <OverviewTab
                      report={report}
                      filePreview={filePreview}
                      videoRef={videoRef}
                      onOpenShots={() => setActiveReportTab("shots")}
                    />
                  )}
                  {activeReportTab === "shots" && (
                    <ShotsTab
                      shots={report.shots}
                      activeShotId={activeShotId}
                      onSelect={seekToShot}
                      analysisMode={report.analysis_mode}
                      onCopy={copyText}
                    />
                  )}
                  {activeReportTab === "viral" && <ViralTab report={report} />}
                  {activeReportTab === "replace" && (
                    <ReplacementTab
                      videoId={report.video_id}
                      entities={report.entities}
                      replacementVersion={replacementVersion}
                      onCreated={setReplacementVersion}
                      onError={setError}
                    />
                  )}
                  {activeReportTab === "prompts" && (
                    <PromptsTab
                      promptPackage={currentPromptPackage}
                      onCopy={copyText}
                      onDownload={downloadPromptPackage}
                    />
                  )}
                </div>
              </section>
            )}
          </main>

          <InsightsPanel report={report} analysis={analysis} onOpenTab={setActiveReportTab} />
          </>)}
        </div>
      </div>

      {settingsOpen && (
        <ModelSettingsDialog
          draft={settingsDraft}
          error={settingsError}
          loading={settingsLoading}
          saving={settingsSaving}
          serverSettings={serverModelSettings}
          workspace={workspaceInfo}
          workspaceDraft={workspaceDraft}
          workspaceValidation={workspaceValidation}
          workspaceSaving={workspaceSaving}
          workspaceError={workspaceError}
          onWorkspaceChange={updateWorkspaceDraft}
          onValidateWorkspace={validateWorkspace}
          onSwitchWorkspace={switchWorkspace}
          onChange={updateSettingsDraft}
          onClose={() => setSettingsOpen(false)}
          onReset={() =>
            updateSettingsDraft({
              ...DEFAULT_MODEL_SETTINGS,
              provider: DEFAULT_SERVER_MODEL_SETTINGS.provider,
              modelAlias: DEFAULT_SERVER_MODEL_SETTINGS.model_alias,
              baseUrl: DEFAULT_SERVER_MODEL_SETTINGS.base_url,
              apiKey: "",
            })
          }
          onSave={saveModelSettings}
        />
      )}

      {notice && (
        <div className="toast" role="status">
          <CheckCircle size={18} weight="fill" />
          {notice}
        </div>
      )}
    </div>
  );
}

function HistoryPage({
  records,
  folders,
  total,
  loading,
  error,
  query,
  folderFilter,
  statusFilter,
  sort,
  workspace,
  onQueryChange,
  onFolderChange,
  onStatusChange,
  onSortChange,
  onCreateFolder,
  onRenameFolder,
  onRenameRecord,
  onMoveRecord,
  onOpenRecord,
  onCreate,
}) {
  const sourceLabels = { upload: "本地文件", douyin: "抖音", xiaohongshu: "小红书" };
  const folderNames = new Map(folders.map((folder) => [folder.id, folder.name]));

  return (
    <>
      <main className="history-main">
        <section className="page-intro history-intro">
          <div>
            <div className="breadcrumb">
              <span>工作台</span>
              <CaretRight size={14} />
              <span className="breadcrumb-current">分析记录</span>
            </div>
            <h1>分析记录</h1>
            <p>重新打开已完成报告不会调用模型；只有“重新分析”才会产生新版本和费用。</p>
          </div>
          <button className="primary-button compact" onClick={onCreate} type="button">
            <Plus size={16} weight="bold" />
            新建分析
          </button>
        </section>

        <section className="history-toolbar" aria-label="分析记录筛选">
          <label className="history-search">
            <MagnifyingGlass size={18} />
            <input
              aria-label="搜索分析记录"
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="搜索记录名称、链接或作者"
              value={query}
            />
            {query && (
              <button aria-label="清空搜索" onClick={() => onQueryChange("")} type="button">
                <X size={15} />
              </button>
            )}
          </label>
          <label className="history-select">
            <span>状态</span>
            <select value={statusFilter} onChange={(event) => onStatusChange(event.target.value)}>
              <option value="">全部状态</option>
              <option value="ready">待分析</option>
              <option value="analyzing">分析中</option>
              <option value="completed">已完成</option>
              <option value="failed">失败</option>
            </select>
          </label>
          <label className="history-select">
            <span>排序</span>
            <select value={sort} onChange={(event) => onSortChange(event.target.value)}>
              <option value="updated_desc">最近更新</option>
              <option value="created_desc">最近创建</option>
              <option value="name_asc">名称 A–Z</option>
            </select>
          </label>
        </section>

        <div className="history-result-heading">
          <div>
            <strong>{folderFilter ? folderFilter === "unfiled" ? "未分类" : folderNames.get(folderFilter) : "全部记录"}</strong>
            <span>{total} 条结果</span>
          </div>
          {folderFilter && (
            <button className="text-button" onClick={() => onFolderChange("")} type="button">
              清除目录筛选
            </button>
          )}
        </div>

        {error && <div className="inline-error"><X size={17} weight="bold" />{error}</div>}

        {loading ? (
          <div className="history-loading" role="status">
            <CircleNotch className="spin" size={20} />
            正在读取工作区记录…
          </div>
        ) : records.length === 0 ? (
          <section className="history-empty">
            <span><FolderOpen size={30} /></span>
            <h2>{query || folderFilter || statusFilter ? "没有匹配的分析记录" : "工作区还没有分析记录"}</h2>
            <p>{query || folderFilter || statusFilter ? "调整搜索或筛选条件后再试。" : "导入第一个视频后，源文件、报告和导出会自动归档到这里。"}</p>
            {!query && !folderFilter && !statusFilter && (
              <button className="primary-button compact" onClick={onCreate} type="button">
                <Plus size={16} />新建分析
              </button>
            )}
          </section>
        ) : (
          <div className="record-grid">
            {records.map((record) => (
              <article className="record-card" key={record.id}>
                <button
                  className="record-open-area"
                  onClick={() => onOpenRecord(record.id)}
                  type="button"
                >
                  <span className={`record-source-icon ${record.source_type}`}>
                    {record.source_type === "upload" ? <FileVideo size={23} /> : <LinkSimple size={23} />}
                  </span>
                  <span className="record-card-copy">
                    <span className="record-title-row">
                      <strong>{record.name}</strong>
                      <span className={`record-status ${record.status}`}>
                        {recordStatusLabels[record.status] || record.status}
                      </span>
                    </span>
                    <span className="record-meta">
                      {sourceLabels[record.source_type] || record.source_type}
                      <i />
                      {folderNames.get(record.folder_id) || "未分类"}
                    </span>
                    <span className="record-date">更新于 {formatRecordDate(record.updated_at)}</span>
                  </span>
                  <CaretRight className="record-caret" size={18} />
                </button>
                <div className="record-card-actions">
                  <label>
                    <Folder size={15} />
                    <select
                      aria-label={`移动 ${record.name} 到目录`}
                      onChange={(event) => onMoveRecord(record.id, event.target.value)}
                      value={record.folder_id || ""}
                    >
                      <option value="">未分类</option>
                      {folders.map((folder) => (
                        <option key={folder.id} value={folder.id}>{folder.name}</option>
                      ))}
                    </select>
                  </label>
                  <button onClick={() => onRenameRecord(record)} type="button">
                    <PencilSimple size={15} />改名
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </main>

      <aside className="history-sidebar">
        <section className="workspace-summary-card">
          <span className="workspace-summary-icon"><FolderOpen size={21} weight="fill" /></span>
          <div>
            <span className="eyebrow">当前工作区</span>
            <strong title={workspace.root_path}>{workspace.root_path || "正在读取…"}</strong>
            <p>{workspace.record_count || 0} 条记录 · {workspace.folder_count || 0} 个目录</p>
          </div>
        </section>
        <section className="folder-panel">
          <div className="folder-panel-heading">
            <div><span className="eyebrow">一级目录</span><strong>记录分类</strong></div>
            <button aria-label="新建目录" onClick={onCreateFolder} type="button"><FolderPlus size={18} /></button>
          </div>
          <button className={!folderFilter ? "active" : ""} onClick={() => onFolderChange("")} type="button">
            <FolderOpen size={17} /><span>全部记录</span><small>{workspace.record_count || 0}</small>
          </button>
          <button className={folderFilter === "unfiled" ? "active" : ""} onClick={() => onFolderChange("unfiled")} type="button">
            <Folder size={17} /><span>未分类</span>
          </button>
          {folders.map((folder) => (
            <div className={`folder-row ${folderFilter === folder.id ? "active" : ""}`} key={folder.id}>
              <button onClick={() => onFolderChange(folder.id)} type="button">
                <Folder size={17} weight={folderFilter === folder.id ? "fill" : "regular"} />
                <span>{folder.name}</span>
              </button>
              <button aria-label={`重命名${folder.name}`} onClick={() => onRenameFolder(folder)} type="button">
                <PencilSimple size={14} />
              </button>
            </div>
          ))}
        </section>
      </aside>
    </>
  );
}

function Sidebar({ activeNav, onSelect, onOpenSettings, settingsOpen, historyCount }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">
          <Play size={18} weight="fill" />
        </span>
        <span>
          <strong>ViralDNA</strong>
          <small>视频逆向拆解系统</small>
        </span>
      </div>

      <nav className="side-nav" aria-label="主导航">
        <p className="nav-section-label">创作研究</p>
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={`nav-item ${activeNav === item.id ? "active" : ""}`}
              key={item.id}
              onClick={() => onSelect(item.id)}
              type="button"
            >
              <Icon size={18} weight={activeNav === item.id ? "fill" : "regular"} />
              <span>{item.label}</span>
              {item.id === "history" && <span className="nav-count">{historyCount || 0}</span>}
            </button>
          );
        })}

        <div className="nav-divider" />
        <p className="nav-section-label">系统</p>
        <button
          aria-expanded={settingsOpen}
          aria-haspopup="dialog"
          className={`nav-item ${settingsOpen ? "active" : ""}`}
          onClick={onOpenSettings}
          type="button"
        >
          <Gear size={18} weight={settingsOpen ? "fill" : "regular"} />
          <span>模型与设置</span>
        </button>
      </nav>

      <div className="sidebar-footer">
        <span className="environment-icon">
          <ShieldCheck size={18} />
        </span>
        <span>
          <strong>内测环境</strong>
          <small>混合分析引擎已启用</small>
        </span>
      </div>
    </aside>
  );
}

function ModelSettingsDialog({
  draft,
  error,
  loading,
  saving,
  serverSettings,
  workspace,
  workspaceDraft,
  workspaceValidation,
  workspaceSaving,
  workspaceError,
  onWorkspaceChange,
  onValidateWorkspace,
  onSwitchWorkspace,
  onChange,
  onClose,
  onReset,
  onSave,
}) {
  const providerOptions = serverSettings.providers?.length
    ? serverSettings.providers
    : DEFAULT_SERVER_MODEL_SETTINGS.providers;
  const modelOptions = (serverSettings.models || []).filter(
    (model) => model.provider === draft.provider,
  );
  const selectedModel = modelOptions.find((model) => model.alias === draft.modelAlias);
  const hasNewKey = Boolean(String(draft.apiKey || "").trim());
  const credentialState = hasNewKey
    ? "pending"
    : serverSettings.api_key_configured
      ? "connected"
      : "missing";
  const credentialTitle = {
    pending: "新 API Key 等待验证",
    connected: "API Key 已配置",
    missing: "尚未配置 API Key",
  }[credentialState];

  function closeIfIdle() {
    if (!saving && !workspaceSaving) onClose();
  }

  function changeProvider(providerId) {
    const provider = providerOptions.find((item) => item.id === providerId);
    onChange({
      provider: providerId,
      modelAlias: "auto",
      baseUrl: provider?.base_url || DEFAULT_SERVER_MODEL_SETTINGS.base_url,
    });
  }

  return (
    <div
      className="settings-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) closeIfIdle();
      }}
    >
      <section
        aria-describedby="model-settings-description"
        aria-labelledby="model-settings-title"
        aria-modal="true"
        className="settings-dialog"
        role="dialog"
      >
        <header className="settings-header">
          <div>
            <span className="settings-kicker"><Sparkle size={14} weight="fill" /> 分析模型</span>
            <h2 id="model-settings-title">模型与设置</h2>
            <p id="model-settings-description">验证成功后应用于新建分析；运行中的任务不会改变。</p>
          </div>
          <button
            autoFocus
            aria-label="关闭模型设置"
            className="icon-button"
            disabled={saving || workspaceSaving}
            onClick={closeIfIdle}
            type="button"
          >
            <X size={19} />
          </button>
        </header>

        <div className="settings-body">
          <section className="settings-section workspace-settings-section" aria-labelledby="workspace-settings-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="workspace-settings-title">本地工作区</h3>
                <p>源视频、分析记录和导出文件统一保存在这个文件夹。</p>
              </div>
              <span className="recommended-chip">{workspace.record_count || 0} 条记录</span>
            </div>
            <div className="workspace-current-path">
              <span><FolderOpen size={19} weight="fill" /></span>
              <div>
                <small>当前工作区</small>
                <strong title={workspace.root_path}>{workspace.root_path || "正在读取…"}</strong>
              </div>
            </div>
            <label className="settings-field settings-field-wide">
              <span>工作区文件夹路径</span>
              <input
                disabled={workspaceSaving || saving}
                onChange={(event) => onWorkspaceChange(event.target.value)}
                placeholder="例如 D:\\ViralDNA-Workspace"
                spellCheck="false"
                type="text"
                value={workspaceDraft}
              />
              <small>可以填写现有文件夹或新文件夹；切换前会检查路径和写入权限。</small>
            </label>
            <div className="workspace-setting-actions">
              <button
                className="secondary-button compact"
                disabled={workspaceSaving || saving || !workspaceDraft.trim()}
                onClick={onValidateWorkspace}
                type="button"
              >
                {workspaceSaving ? <CircleNotch className="spin" size={15} /> : <ShieldCheck size={15} />}
                验证路径
              </button>
              <button
                className="primary-button compact"
                disabled={workspaceSaving || saving || !workspaceDraft.trim() || workspaceDraft === workspace.root_path}
                onClick={onSwitchWorkspace}
                type="button"
              >
                {workspaceSaving ? <CircleNotch className="spin" size={15} /> : <FolderOpen size={15} weight="fill" />}
                切换工作区
              </button>
            </div>
            {workspaceValidation && (
              <div className={`workspace-validation ${workspaceValidation.valid ? "valid" : "invalid"}`}>
                {workspaceValidation.valid
                  ? <CheckCircle size={17} weight="fill" />
                  : <X size={17} weight="bold" />}
                <span>
                  {workspaceValidation.valid
                    ? `路径有效${workspaceValidation.exists ? "，将读取现有工作区" : "，保存时会创建文件夹"}`
                    : workspaceValidation.error || "路径不可用"}
                </span>
              </div>
            )}
            {workspaceError && <div className="settings-error" role="alert">{workspaceError}</div>}
            <p className="workspace-security-note">
              <LockSimple size={14} /> API Key 保存在本机应用配置中，不会写入工作区或随导出复制。
            </p>
          </section>

          <section className="settings-section" aria-labelledby="model-connection-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="model-connection-title">视觉理解服务</h3>
                <p>选择 Provider 和主模型，并在本机验证访问密钥。</p>
              </div>
              <span className="recommended-chip">本机配置</span>
            </div>

            {loading ? (
              <div className="settings-loading" role="status">
                <CircleNotch className="spin" size={18} />
                正在读取模型目录与配置状态…
              </div>
            ) : (
              <>
                <div className="settings-field-grid">
                  <label className="settings-field">
                    <span>Provider</span>
                    <select
                      disabled={saving}
                      onChange={(event) => changeProvider(event.target.value)}
                      value={draft.provider}
                    >
                      {providerOptions.map((provider) => (
                        <option key={provider.id} value={provider.id}>{provider.label}</option>
                      ))}
                    </select>
                    <small>接口层已解耦，后续可继续增加国内模型服务。</small>
                  </label>
                  <label className="settings-field">
                    <span>分析主模型</span>
                    <select
                      disabled={saving}
                      onChange={(event) => onChange({ modelAlias: event.target.value })}
                      value={draft.modelAlias}
                    >
                      <option value="auto">自动（跟随分析档位）</option>
                      {modelOptions.map((model) => (
                        <option key={model.alias} value={model.alias}>{model.label}</option>
                      ))}
                    </select>
                    <small>
                      {selectedModel?.description || "自动模式按质量档位选择主模型和回退顺序。"}
                    </small>
                  </label>
                  <label className="settings-field settings-field-wide">
                    <span>API Key</span>
                    <input
                      autoComplete="new-password"
                      disabled={saving}
                      onChange={(event) => onChange({ apiKey: event.target.value })}
                      placeholder={
                        serverSettings.api_key_configured
                          ? `已配置 ${serverSettings.api_key_hint || ""}；留空沿用`
                          : "请输入阿里云百炼 API Key"
                      }
                      spellCheck="false"
                      type="password"
                      value={draft.apiKey}
                    />
                    <small>密钥不会写入浏览器存储，也不会通过接口返回。</small>
                  </label>
                  <label className="settings-field settings-field-wide">
                    <span>服务地址</span>
                    <input
                      disabled={saving}
                      onChange={(event) => onChange({ baseUrl: event.target.value })}
                      spellCheck="false"
                      type="url"
                      value={draft.baseUrl}
                    />
                    <small>为防止密钥泄露，后端只接受 DashScope 官方 HTTPS 兼容接口。</small>
                  </label>
                </div>

                <div className={`credential-status ${credentialState}`}>
                  <span>
                    {credentialState === "connected"
                      ? <CheckCircle size={19} weight="fill" />
                      : <ShieldCheck size={19} weight="fill" />}
                  </span>
                  <div>
                    <strong>{credentialTitle}</strong>
                    <p>
                      {hasNewKey
                        ? "点击“验证并保存”后才会替换本机已有密钥。"
                        : serverSettings.api_key_configured
                          ? `最近验证：${formatValidationTime(serverSettings.last_validated_at)}`
                          : "填写密钥后才能启用真实 VLM 视频分析。"}
                    </p>
                  </div>
                </div>
              </>
            )}
          </section>

          <section className="settings-section" aria-labelledby="analysis-profile-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="analysis-profile-title">分析质量</h3>
                <p>档位控制成本和回退策略；手动模型会成为各任务的首选路由。</p>
              </div>
              <span className="recommended-chip">均衡推荐</span>
            </div>
            <div className="profile-option-grid">
              {PROFILE_OPTIONS.map((profile) => (
                <label
                  className={`profile-option ${draft.analysisProfile === profile.id ? "selected" : ""}`}
                  key={profile.id}
                >
                  <input
                    checked={draft.analysisProfile === profile.id}
                    disabled={saving}
                    name="analysis-profile"
                    onChange={() => onChange({ analysisProfile: profile.id })}
                    type="radio"
                    value={profile.id}
                  />
                  <span className="profile-option-topline">
                    <strong>{profile.label}</strong>
                    <span className="profile-option-check"><Check size={13} weight="bold" /></span>
                  </span>
                  <span>{profile.description}</span>
                </label>
              ))}
            </div>
          </section>

          <section className="settings-section settings-field-grid" aria-label="输出与预算">
            <label className="settings-field">
              <span>提示词目标模型</span>
              <select
                disabled={saving}
                value={draft.targetModel}
                onChange={(event) => onChange({ targetModel: event.target.value })}
              >
                <option value="seedance">Seedance</option>
                <option value="generic">通用视频模型</option>
              </select>
              <small>只影响提示词格式，不会调用视频生成模型。</small>
            </label>
            <label className="settings-field">
              <span>单视频模型成本上限</span>
              <span className="settings-cost-input">
                <span>¥</span>
                <input
                  aria-label="单视频模型成本上限"
                  disabled={saving}
                  max="1000"
                  min="0.01"
                  onChange={(event) => onChange({ maxCostCny: event.target.value })}
                  placeholder="不限制"
                  step="0.01"
                  type="number"
                  value={draft.maxCostCny}
                />
              </span>
              <small>留空表示不限制；首次真实调用建议保留小额上限。</small>
            </label>
          </section>

          <section className="server-model-note">
            <span><ShieldCheck size={19} weight="fill" /></span>
            <div>
              <strong>验证后才保存</strong>
              <p>保存时会由本地 API 发起一次 max_tokens=1 的最小模型请求，可能产生极小费用；验证失败不会修改现有配置。</p>
            </div>
          </section>

          {error && <div className="settings-error" role="alert">{error}</div>}
        </div>

        <footer className="settings-footer">
          <button className="text-button" disabled={saving || workspaceSaving} onClick={onReset} type="button">
            恢复推荐值
          </button>
          <span />
          <button className="secondary-button compact" disabled={saving || workspaceSaving} onClick={closeIfIdle} type="button">
            取消
          </button>
          <button
            className="primary-button compact"
            disabled={loading || saving || workspaceSaving}
            onClick={onSave}
            type="button"
          >
            {saving ? (
              <><CircleNotch className="spin" size={15} /> 正在验证</>
            ) : (
              <><ShieldCheck size={15} weight="bold" /> 验证并保存</>
            )}
          </button>
        </footer>
      </section>
    </div>
  );
}

function Topbar({ onCreate, onSearch, searchValue }) {
  return (
    <header className="topbar">
      <div className="global-search">
        <MagnifyingGlass size={18} />
        <input
          aria-label="搜索分析记录"
          onChange={(event) => onSearch(event.target.value)}
          placeholder="搜索视频或报告"
          value={searchValue}
        />
        <kbd>⌘ K</kbd>
      </div>
      <div className="topbar-actions">
        <button className="icon-button" type="button" aria-label="通知">
          <Bell size={19} />
          <span className="notification-dot" />
        </button>
        <button className="icon-button" type="button" aria-label="帮助">
          <Question size={19} />
        </button>
        <button className="primary-button compact" type="button" onClick={onCreate}>
          <Plus size={17} weight="bold" />
          新建分析
        </button>
      </div>
    </header>
  );
}

const ImportPanel = forwardRef(function ImportPanel({
  sourceMode,
  setSourceMode,
  url,
  setUrl,
  file,
  setFile,
  targetModel,
  setTargetModel,
  analysisProfile,
  setAnalysisProfile,
  maxCostCny,
  setMaxCostCny,
  rightsConfirmed,
  setRightsConfirmed,
  submitting,
  error,
  onStart,
}, ref) {
  return (
    <section className="import-card" id="new-analysis" ref={ref}>
      <div className="card-heading">
        <div>
          <span className="eyebrow">新建任务</span>
          <h2>导入一个短视频</h2>
          <p>支持本地文件，以及公开的抖音、小红书视频链接。</p>
        </div>
        <span className="supported-formats">MP4 · MOV · WebM · 最长 5 分钟</span>
      </div>

      <div className="source-tabs" role="tablist" aria-label="视频来源">
        <button
          type="button"
          className={sourceMode === "link" ? "active" : ""}
          onClick={() => setSourceMode("link")}
          role="tab"
          aria-selected={sourceMode === "link"}
        >
          <LinkSimple size={17} />
          视频链接
        </button>
        <button
          type="button"
          className={sourceMode === "file" ? "active" : ""}
          onClick={() => setSourceMode("file")}
          role="tab"
          aria-selected={sourceMode === "file"}
        >
          <UploadSimple size={17} />
          本地文件
        </button>
      </div>

      {sourceMode === "link" ? (
        <div className="link-input-row">
          <div className="input-with-icon">
            <LinkSimple size={19} />
            <input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="粘贴抖音或小红书公开分享链接"
              aria-label="视频链接"
            />
            {url && (
              <button type="button" onClick={() => setUrl("")} aria-label="清空链接">
                <X size={16} />
              </button>
            )}
          </div>
          <p className="link-ingestion-hint">
            <DownloadSimple size={15} />
            系统会采集公开源视频并进入真实分镜流程；平台验证、私密或失效链接会明确报错。
          </p>
        </div>
      ) : (
        <label className={`upload-dropzone ${file ? "has-file" : ""}`}>
          <input
            type="file"
            accept="video/mp4,video/quicktime,video/webm"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
          <span className="upload-icon">
            {file ? <FileVideo size={26} weight="fill" /> : <UploadSimple size={26} />}
          </span>
          {file ? (
            <span>
              <strong>{file.name}</strong>
              <small>{(file.size / 1024 / 1024).toFixed(1)} MB · 点击重新选择</small>
            </span>
          ) : (
            <span>
              <strong>点击选择或拖入视频文件</strong>
              <small>单个文件不超过 500 MB</small>
            </span>
          )}
        </label>
      )}

      <div className="import-options">
        <div className="analysis-option-fields">
          <label className="field-group">
            <span>目标提示词模型</span>
            <span className="select-wrap">
              <select value={targetModel} onChange={(event) => setTargetModel(event.target.value)}>
                <option value="seedance">Seedance</option>
                <option value="generic">通用视频模型</option>
              </select>
              <CaretDown size={15} />
            </span>
          </label>
          <label className="field-group">
            <span>分析质量</span>
            <span className="select-wrap compact-select">
              <select
                value={analysisProfile}
                onChange={(event) => setAnalysisProfile(event.target.value)}
              >
                <option value="quality">高质量</option>
                <option value="balanced">均衡</option>
                <option value="economy">经济</option>
              </select>
              <CaretDown size={15} />
            </span>
          </label>
          <label className="field-group">
            <span>单条模型成本上限</span>
            <span className="cost-input-wrap">
              <span>¥</span>
              <input
                type="number"
                min="0.01"
                max="1000"
                step="0.01"
                value={maxCostCny}
                onChange={(event) => setMaxCostCny(event.target.value)}
                aria-label="单条模型成本上限"
              />
            </span>
          </label>
        </div>
        <label className="rights-check">
          <input
            type="checkbox"
            checked={rightsConfirmed}
            onChange={(event) => setRightsConfirmed(event.target.checked)}
          />
          <span className="checkbox-visual">{rightsConfirmed && <Check size={13} weight="bold" />}</span>
          <span>我确认拥有该视频的分析、复刻和素材使用权限</span>
        </label>
      </div>

      {error && (
        <div className="inline-error" role="alert">
          <X size={17} weight="bold" />
          {error}
        </div>
      )}

      <div className="import-actions">
        <button className="primary-button" type="button" onClick={() => onStart()} disabled={submitting}>
          {submitting ? <CircleNotch className="spin" size={18} /> : <Sparkle size={18} weight="fill" />}
          {submitting ? "正在创建任务" : "开始精细拆解"}
        </button>
      </div>
    </section>
  );
});

function AnalysisProgress({ analysis, video }) {
  const stages = [
    "ingesting",
    "preprocessing",
    "segmenting",
    "transcribing",
    "understanding",
    "reasoning",
    "compiling_prompts",
    "validating",
  ];
  const activeIndex = stages.indexOf(analysis.stage);
  return (
    <section className={`progress-card ${analysis.stage === "failed" ? "failed" : ""}`} aria-live="polite">
      <div className="progress-header">
        <span className="progress-icon">
          {analysis.stage === "failed" ? (
            <X size={22} weight="bold" />
          ) : (
            <CircleNotch className="spin" size={22} />
          )}
        </span>
        <div>
          <span className="eyebrow">分析任务</span>
          <h2>{video?.title || "正在拆解视频"}</h2>
          <p>{analysis.message}</p>
        </div>
        <strong>{analysis.progress}%</strong>
      </div>
      <div className="progress-track">
        <span style={{ width: `${analysis.progress}%` }} />
      </div>
      <div className="stage-list">
        {stages.map((stage, index) => {
          const isDone = index < activeIndex;
          const isActive = index === activeIndex;
          return (
            <div className={`${isDone ? "done" : ""} ${isActive ? "active" : ""}`} key={stage}>
              <span>{isDone ? <Check size={12} weight="bold" /> : index + 1}</span>
              <small>{stageLabels[stage]}</small>
            </div>
          );
        })}
      </div>
      {analysis.simulated && (
        <div className="simulation-note">
          <ShieldCheck size={16} />
          当前服务运行在模拟分析模式，不会下载或处理真实媒体。
        </div>
      )}
      {!analysis.simulated && analysis.stage !== "failed" && (
        <div className="evidence-note compact">
          <ShieldCheck size={16} weight="fill" />
          {video?.source_type === "upload"
            ? "正在从真实视频提取编码信息、镜头边界、关键帧和音频证据，不生成虚构语义结果。"
            : "正在解析平台链接并下载源视频；下载完成后会继续提取真实镜头、关键帧和音频证据。"}
        </div>
      )}
    </section>
  );
}

function EmptyWorkspace() {
  return (
    <section className="empty-workspace">
      <span className="empty-icon">
        <VideoCamera size={30} />
      </span>
      <div>
        <h2>分析结果会在这里展开</h2>
        <p>上传视频文件或粘贴公开平台链接后，可以查看真实镜头时间线、关键帧和媒体证据。</p>
      </div>
    </section>
  );
}

function ReportHeader({
  video,
  report,
  promptPackage,
  onDownload,
  onRestart,
  analysisVersions,
  activeAnalysisId,
  onVersionChange,
}) {
  const isMediaEvidence = report.analysis_mode === "media_evidence";
  const isModel = report.analysis_mode === "model";
  const primaryModel = report.model_cost_summary?.breakdown?.[0]?.model;
  const completedVersions = analysisVersions.filter((item) => item.stage === "completed");
  return (
    <div className="report-header">
      <div className="report-title-wrap">
        <span className="report-video-icon">
          <FileVideo size={21} weight="fill" />
        </span>
        <div>
          <div className="report-title-line">
            <h2>{video?.title || "视频拆解报告"}</h2>
            {report.analysis_mode === "simulated" && <span className="simulation-badge">模拟分析</span>}
            {report.analysis_mode === "media_evidence" && (
              <span className="evidence-badge">真实媒体证据</span>
            )}
            {isModel && <span className="model-badge">VLM 逐镜头分析</span>}
          </div>
          {isMediaEvidence ? (
            <p>{report.shots.length} 个真实镜头 · FFmpeg 证据层 · 语义分析待接入</p>
          ) : isModel ? (
            <p>
              {report.shots.filter((shot) => shot.evidence_kind === "model").length} / {report.shots.length} 个镜头已理解
              {primaryModel ? ` · ${primaryModel}` : ""}
              {report.model_cost_summary
                ? ` · ${formatCost(report.model_cost_summary.measured_cost_micros)}`
                : ""}
            </p>
          ) : (
            <p>
              {report.shots.length} 个镜头 · {report.entities.length} 个可替换元素 · Prompt v{promptPackage.version}
            </p>
          )}
        </div>
      </div>
      <div className="report-actions">
        {completedVersions.length > 1 && (
          <label className="analysis-version-picker">
            <ClockCounterClockwise size={16} />
            <select
              aria-label="分析版本"
              value={activeAnalysisId}
              onChange={(event) => onVersionChange(event.target.value)}
            >
              {completedVersions.map((item, index) => (
                <option key={item.id} value={item.id}>
                  {`版本 ${completedVersions.length - index} · ${formatRecordDate(item.created_at)}`}
                </option>
              ))}
            </select>
            <CaretDown className="analysis-version-caret" size={13} />
          </label>
        )}
        <button className="secondary-button compact" type="button" onClick={onRestart}>
          <ArrowClockwise size={16} />
          重新分析
        </button>
        <button
          className="primary-button compact"
          type="button"
          onClick={
            isMediaEvidence
              ? () => window.open(resolveArtifactUrl(report.media_evidence?.manifest_url), "_blank")
              : onDownload
          }
        >
          <DownloadSimple size={16} />
          {isMediaEvidence ? "证据清单" : "导出"}
        </button>
      </div>
    </div>
  );
}

function ReportTabs({ active, onChange, mode }) {
  const visibleTabs =
    mode === "media_evidence"
      ? reportTabs.slice(0, 2)
      : mode === "model"
        ? reportTabs.filter((tab) => ["overview", "shots", "prompts"].includes(tab.id))
        : reportTabs;
  return (
    <div className="report-tabs" role="tablist" aria-label="分析报告">
      {visibleTabs.map((tab) => {
        const Icon = tab.icon;
        return (
          <button
            type="button"
            key={tab.id}
            className={active === tab.id ? "active" : ""}
            onClick={() => onChange(tab.id)}
            role="tab"
            aria-selected={active === tab.id}
          >
            <Icon size={17} weight={active === tab.id ? "fill" : "regular"} />
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

function VideoPlayer({ src, videoRef, fallbackDuration, downloadUrl }) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(fallbackDuration || 0);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    const player = videoRef.current;
    if (player) {
      player.pause();
      player.currentTime = 0;
    }
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(fallbackDuration || 0);
    setLoadError(false);
  }, [fallbackDuration, src, videoRef]);

  function syncDuration(player) {
    if (Number.isFinite(player.duration) && player.duration > 0) {
      setDuration(player.duration);
    }
  }

  function togglePlayback() {
    const player = videoRef.current;
    if (!player) return;
    if (player.paused || player.ended) {
      player.play().catch(() => setLoadError(true));
    } else {
      player.pause();
    }
  }

  function seekVideo(event) {
    const player = videoRef.current;
    const nextTime = Number(event.target.value);
    setCurrentTime(nextTime);
    if (player && Number.isFinite(nextTime)) {
      player.currentTime = nextTime;
    }
  }

  const resolvedDuration = duration > 0 ? duration : fallbackDuration || 0;
  const progressValue = Math.min(currentTime, resolvedDuration || 0);

  return (
    <div className="video-player">
      <div className="video-stage">
        <video
          ref={videoRef}
          src={src}
          playsInline
          preload="metadata"
          onClick={togglePlayback}
          onLoadedMetadata={(event) => syncDuration(event.currentTarget)}
          onDurationChange={(event) => syncDuration(event.currentTarget)}
          onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={() => setIsPlaying(false)}
          onError={() => setLoadError(true)}
        />
        {!isPlaying && !loadError && (
          <button
            className="video-center-play"
            type="button"
            aria-label="播放视频"
            onClick={togglePlayback}
          >
            <Play size={28} weight="fill" />
          </button>
        )}
        {loadError && <span className="video-load-error">视频加载失败，可尝试下载后播放</span>}
      </div>
      <div className="video-controls">
        <button
          className="video-control-button"
          type="button"
          aria-label={isPlaying ? "暂停视频" : "播放视频"}
          title={isPlaying ? "暂停" : "播放"}
          onClick={togglePlayback}
          disabled={loadError}
        >
          {isPlaying ? <Pause size={17} weight="fill" /> : <Play size={17} weight="fill" />}
        </button>
        <span className="video-time">{formatTime(currentTime)}</span>
        <input
          className="video-progress"
          type="range"
          min="0"
          max={Math.max(resolvedDuration, 0.1)}
          step="0.1"
          value={progressValue}
          aria-label="视频进度"
          aria-valuetext={`${formatTime(currentTime)} / ${formatTime(resolvedDuration)}`}
          onChange={seekVideo}
          disabled={loadError || resolvedDuration <= 0}
        />
        <span className="video-time">{formatTime(resolvedDuration)}</span>
        <a className="video-download-button" href={downloadUrl} download>
          <DownloadSimple size={16} />
          下载视频
        </a>
      </div>
    </div>
  );
}

function OverviewTab({ report, filePreview, videoRef, onOpenShots }) {
  const overview = report.overview;
  const evidence = report.media_evidence;
  const timeline = report.evidence_timeline;
  const metadata = evidence?.metadata;
  const isMediaEvidence = report.analysis_mode === "media_evidence";
  const isModel = report.analysis_mode === "model";
  const mediaAvailable = isMediaEvidence || isModel || Boolean(filePreview);
  const modelCost = report.model_cost_summary;
  const primaryModel = modelCost?.breakdown?.[0]?.model;
  const playbackUrl =
    filePreview ||
    (mediaAvailable
      ? resolveApiUrl(`/videos/${report.video_id}/media`)
      : resolveArtifactUrl(evidence?.proxy_url));
  const downloadUrl = mediaAvailable
    ? resolveApiUrl(`/videos/${report.video_id}/download`)
    : "";
  return (
    <div className="overview-grid">
      <div className="overview-primary">
        {playbackUrl ? (
          <VideoPlayer
            src={playbackUrl}
            videoRef={videoRef}
            fallbackDuration={overview.duration_seconds}
            downloadUrl={downloadUrl}
          />
        ) : (
          <div className="video-stage">
            <div className="video-empty-state">
              <span>
                <Play size={25} weight="fill" />
              </span>
              <strong>暂无可播放视频</strong>
              <small>当前报告没有关联的源视频文件</small>
            </div>
          </div>
        )}

        <div className="section-block">
          <span className="eyebrow">
            {isMediaEvidence
              ? "媒体证据概览"
              : isModel
                ? "逐镜头 VLM 概览"
                : "视频概览"}
          </span>
          <h3>{overview.summary}</h3>
          <p>{overview.narrative_structure}</p>
          <div className="tag-row">
            <span>{overview.content_type}</span>
            <span>{overview.aspect_ratio}</span>
            <span>{overview.visual_style.split("、")[0]}</span>
          </div>
        </div>

        <div className="structure-strip">
          {overview.narrative_structure.split("→").map((part, index, parts) => (
            <div key={part.trim()}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{part.trim()}</strong>
              {index < parts.length - 1 && <CaretRight size={15} />}
            </div>
          ))}
        </div>
      </div>

      <aside className="overview-sidebar">
        {isMediaEvidence ? (
          <div className="media-evidence-card">
            <span className="media-evidence-icon">
              <ShieldCheck size={20} weight="fill" />
            </span>
            <div>
              <span className="eyebrow">真实媒体已验证</span>
              <strong>
                {metadata?.width} × {metadata?.height} · {metadata?.fps?.toFixed(2)} FPS
              </strong>
              <p>编码、时长、分镜和关键帧均来自真实源视频，不包含模型臆测。</p>
            </div>
          </div>
        ) : isModel ? (
          <div className="media-evidence-card model-cost-card">
            <span className="media-evidence-icon">
              <Sparkle size={20} weight="fill" />
            </span>
            <div>
              <span className="eyebrow">本次模型成本</span>
              <strong>{formatCost(modelCost?.measured_cost_micros)}</strong>
              <p>
                {primaryModel || "模型未返回"} · {modelCost?.run_count || 0} 次调用
                {modelCost?.cached_run_count ? ` · ${modelCost.cached_run_count} 次缓存` : ""}
              </p>
            </div>
          </div>
        ) : (
          <div className="score-card">
            <span className="eyebrow">内容爆点潜力</span>
            <div className="score-value">
              <strong>{overview.viral_potential_score}</strong>
              <span>/100</span>
            </div>
            <div className="score-track">
              <span style={{ width: `${overview.viral_potential_score}%` }} />
            </div>
            <p>基于视频内容结构的启发式评分，不代表真实平台播放表现。</p>
          </div>
        )}
        <dl className="overview-facts">
          <div>
            <dt>时长</dt>
            <dd>{overview.duration_seconds.toFixed(1)} 秒</dd>
          </div>
          <div>
            <dt>镜头</dt>
            <dd>{report.shots.length} 个</dd>
          </div>
          {isMediaEvidence ? (
            <>
              <div>
                <dt>视频编码</dt>
                <dd>{metadata?.video_codec?.toUpperCase() || "—"}</dd>
              </div>
              <div>
                <dt>音轨</dt>
                <dd>{metadata?.has_audio ? metadata.audio_codec?.toUpperCase() : "无"}</dd>
              </div>
              <div>
                <dt>独立字幕轨</dt>
                <dd>{metadata?.subtitle_streams?.length || 0} 条</dd>
              </div>
            </>
          ) : isModel ? (
            <>
              <div>
                <dt>VLM 镜头</dt>
                <dd>
                  {report.shots.filter((shot) => shot.evidence_kind === "model").length} / {report.shots.length}
                </dd>
              </div>
              <div>
                <dt>模型调用</dt>
                <dd>{modelCost?.run_count || 0} 次</dd>
              </div>
              <div>
                <dt>实测成本</dt>
                <dd>{formatCost(modelCost?.measured_cost_micros)}</dd>
              </div>
            </>
          ) : (
            <>
              <div>
                <dt>主体元素</dt>
                <dd>{report.entities.length} 个</dd>
              </div>
              <div>
                <dt>分析置信度</dt>
                <dd>{Math.round(overview.confidence * 100)}%</dd>
              </div>
            </>
          )}
        </dl>
        <div className="audience-card">
          <span className="eyebrow">
            {isMediaEvidence ? "语义分析状态" : isModel ? "模型与证据状态" : "受众推断"}
          </span>
          {isMediaEvidence ? (
            <>
              <p>
                {timeline
                  ? `统一证据时间线已生成：${timeline.transcript_segments.length} 条 ASR 转写、${timeline.subtitle_cues?.length || 0} 条独立字幕、${timeline.ocr_observations.length} 条画面 OCR；VLM、爆点判断和复刻提示词待下一批接入。`
                  : "当前是旧版媒体报告，ASR、OCR 和多模态语义分析尚未运行。"}
              </p>
              {timeline?.provider_runs?.length > 0 && (
                <div className="provider-status-list" aria-label="证据 Provider 状态">
                  {timeline.provider_runs.map((run) => (
                    <span className={`provider-status ${run.status}`} key={run.kind}>
                      <strong>{run.kind === "subtitle" ? "字幕轨" : run.kind.toUpperCase()}</strong>
                      {run.status === "completed"
                        ? `完成 · ${run.item_count} 条`
                        : run.status === "skipped"
                          ? "已跳过"
                          : run.status === "unavailable"
                            ? "不可用"
                            : "失败"}
                    </span>
                  ))}
                </div>
              )}
            </>
          ) : isModel ? (
            <>
              <p>
                已结合 {timeline?.transcript_segments?.length || 0} 条 ASR、
                {timeline?.subtitle_cues?.length || 0} 条独立字幕和
                {timeline?.ocr_observations?.length || 0} 条 OCR 证据完成逐镜头理解。
                全局实体归并与爆点推理尚未执行。
              </p>
              {report.model_warnings?.map((warning) => (
                <p className="model-warning" key={warning}>{warning}</p>
              ))}
            </>
          ) : (
            <p>{overview.audience_inference}</p>
          )}
          {(isMediaEvidence || isModel) && metadata?.sha256 && (
            <code className="media-hash">SHA-256 {metadata.sha256.slice(0, 12)}…</code>
          )}
        </div>
        <button className="secondary-button full" type="button" onClick={onOpenShots}>
          {isMediaEvidence ? "查看真实分镜证据" : isModel ? "查看 VLM 分镜事实" : "查看逐镜头拆解"}
          <CaretRight size={16} />
        </button>
      </aside>
    </div>
  );
}

function ShotsTab({ shots, activeShotId, onSelect, onCopy, analysisMode }) {
  const activeShot = shots.find((shot) => shot.id === activeShotId) || shots[0];
  const isMediaEvidence = analysisMode === "media_evidence";
  return (
    <div className="shots-layout">
      <div className="shot-list">
        <div className="shot-list-header">
          <span>分镜时间线</span>
          <small>{shots.length} 个镜头</small>
        </div>
        {shots.map((shot) => (
          <button
            className={`shot-row ${activeShot?.id === shot.id ? "active" : ""}`}
            type="button"
            key={shot.id}
            onClick={() => onSelect(shot)}
          >
            {shot.keyframe_url ? (
              <img
                className="shot-row-thumb"
                src={resolveArtifactUrl(shot.keyframe_url)}
                alt={`${shot.title} 关键帧`}
              />
            ) : (
              <span className="shot-index">{String(shot.index).padStart(2, "0")}</span>
            )}
            <span className="shot-row-copy">
              <strong>{shot.title}</strong>
              <small>
                {formatTime(shot.start_seconds)} — {formatTime(shot.end_seconds)}
              </small>
            </span>
            <CaretRight size={16} />
          </button>
        ))}
      </div>

      {activeShot && (
        <article className="shot-detail">
          <div className="shot-detail-heading">
            <div>
              <span className="eyebrow">镜头 {String(activeShot.index).padStart(2, "0")}</span>
              <h3>{activeShot.title}</h3>
              <p>
                {formatTime(activeShot.start_seconds)} — {formatTime(activeShot.end_seconds)} · {isMediaEvidence ? "真实时间边界" : `置信度 ${Math.round(activeShot.confidence * 100)}%`}
              </p>
            </div>
            {!isMediaEvidence && (
              <button className="icon-button bordered" type="button" onClick={() => onCopy(activeShot.prompt, "镜头提示词已复制")} aria-label="复制镜头提示词">
                <Copy size={17} />
              </button>
            )}
          </div>

          {activeShot.keyframe_url && (
            <figure className="shot-keyframe">
              <img src={resolveArtifactUrl(activeShot.keyframe_url)} alt={`${activeShot.title} 代表关键帧`} />
              <figcaption>代表关键帧 · 截取自该镜头时间区间中点</figcaption>
            </figure>
          )}

          {isMediaEvidence ? (
            <>
              <div className="evidence-note">
                <ShieldCheck size={18} weight="fill" />
                这里只展示可验证的媒体和 Provider 证据。主体、服装、场景、爆点和提示词将在多模态分析接入后生成。
              </div>
              <div className="shot-facts-grid">
                <Fact label="开始时间" value={`${activeShot.start_seconds.toFixed(3)} 秒`} />
                <Fact label="结束时间" value={`${activeShot.end_seconds.toFixed(3)} 秒`} />
                <Fact label="镜头时长" value={`${(activeShot.end_seconds - activeShot.start_seconds).toFixed(3)} 秒`} />
                <Fact label="边界依据" value={activeShot.transition} />
                <Fact label="音频证据" value={activeShot.audio} />
                <Fact label="证据类型" value="FFmpeg 实测" />
              </div>
              {(activeShot.dialogue || activeShot.subtitle_text || activeShot.ocr_text) && (
                <div className="transcript-box">
                  {activeShot.dialogue && (
                    <div>
                      <span>ASR 转写</span>
                      <p>{activeShot.dialogue}</p>
                    </div>
                  )}
                  {activeShot.subtitle_text && (
                    <div>
                      <span>独立字幕轨</span>
                      <p>{activeShot.subtitle_text}</p>
                    </div>
                  )}
                  {activeShot.ocr_text && (
                    <div>
                      <span>OCR 画面文字</span>
                      <p>{activeShot.ocr_text}</p>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="shot-facts-grid">
                <Fact label="主体动作" value={activeShot.action} />
                <Fact label="场景" value={activeShot.scene} />
                <Fact label="机位与运镜" value={activeShot.camera} />
                <Fact label="构图" value={activeShot.composition} />
                <Fact label="灯光" value={activeShot.lighting} />
                <Fact label="色彩" value={activeShot.color} />
                <Fact label="声音" value={activeShot.audio} />
                <Fact label="转场" value={activeShot.transition} />
              </div>
              {(activeShot.dialogue || activeShot.subtitle_text || activeShot.ocr_text) && (
            <div className="transcript-box">
              {activeShot.dialogue && (
                <div>
                  <span>旁白</span>
                  <p>{activeShot.dialogue}</p>
                </div>
              )}
              {activeShot.subtitle_text && (
                <div>
                  <span>字幕</span>
                  <p>{activeShot.subtitle_text}</p>
                </div>
              )}
              {activeShot.ocr_text && (
                <div>
                  <span>画面文字</span>
                  <p>{activeShot.ocr_text}</p>
                </div>
              )}
            </div>
              )}

              <div className="prompt-box">
                <div>
                  <MagicWand size={17} weight="fill" />
                  <strong>逐镜头复刻提示词</strong>
                </div>
                <p>{activeShot.prompt}</p>
              </div>
            </>
          )}
        </article>
      )}
    </div>
  );
}

function Fact({ label, value }) {
  return (
    <div className="fact-card">
      <span>{label}</span>
      <p>{value}</p>
    </div>
  );
}

function ViralTab({ report }) {
  return (
    <div className="viral-layout">
      <div className="viral-summary">
        <span className="target-icon">
          <Target size={25} weight="fill" />
        </span>
        <div>
          <span className="eyebrow">内容潜力评分</span>
          <h3>{report.overview.viral_potential_score} / 100</h3>
          <p>所有判断均来自当前视频的画面、字幕和结构证据，不等同于实际平台表现。</p>
        </div>
      </div>
      <div className="finding-list">
        {report.viral_findings.map((finding, index) => (
          <article className="finding-card" key={finding.id}>
            <div className="finding-rank">{String(index + 1).padStart(2, "0")}</div>
            <div className="finding-content">
              <div className="finding-heading">
                <div>
                  <span>
                    {formatTime(finding.start_seconds)} — {formatTime(finding.end_seconds)}
                  </span>
                  <h3>{finding.title}</h3>
                </div>
                <strong>{finding.score}</strong>
              </div>
              <p>{finding.observation}</p>
              <dl>
                <div>
                  <dt>生效机制</dt>
                  <dd>{finding.mechanism}</dd>
                </div>
                <div>
                  <dt>预期作用</dt>
                  <dd>{finding.expected_effect}</dd>
                </div>
                <div>
                  <dt>复用建议</dt>
                  <dd>{finding.recommendation}</dd>
                </div>
              </dl>
              <span className="confidence">置信度 {Math.round(finding.confidence * 100)}%</span>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function ReplacementTab({ videoId, entities, replacementVersion, onCreated, onError }) {
  const [entityId, setEntityId] = useState(entities[0]?.id || "");
  const [description, setDescription] = useState("");
  const [locks, setLocks] = useState(["timing", "camera", "composition", "action"]);
  const [loading, setLoading] = useState(false);
  const currentEntity = entities.find((entity) => entity.id === entityId);
  const lockOptions = [
    ["timing", "时长节奏"],
    ["camera", "机位运镜"],
    ["composition", "画面构图"],
    ["action", "主体动作"],
    ["lighting", "灯光"],
    ["audio", "音频结构"],
  ];

  function toggleLock(value) {
    setLocks((current) =>
      current.includes(value) ? current.filter((item) => item !== value) : [...current, value],
    );
  }

  async function submitReplacement() {
    if (!description.trim()) {
      onError("请输入替换后的元素描述");
      return;
    }
    setLoading(true);
    onError("");
    try {
      const version = await apiRequest(`/videos/${videoId}/replacement-versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          replacements: [{ entity_id: entityId, description: description.trim() }],
          locks,
        }),
      });
      onCreated(version);
    } catch (requestError) {
      onError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="replacement-layout">
      <div className="entity-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">元素资产</span>
            <h3>选择需要替换的元素</h3>
          </div>
          <span>{entities.length} 项</span>
        </div>
        <div className="entity-list">
          {entities.map((entity) => (
            <button
              type="button"
              className={entity.id === entityId ? "active" : ""}
              key={entity.id}
              onClick={() => setEntityId(entity.id)}
            >
              <span className={`entity-type ${entity.type}`}>
                {entity.type === "person" ? <Target size={17} /> : <SquaresFour size={17} />}
              </span>
              <span>
                <strong>{entity.name}</strong>
                <small>{entity.id}</small>
              </span>
              <span className="entity-confidence">{Math.round(entity.confidence * 100)}%</span>
            </button>
          ))}
        </div>
      </div>

      <div className="replacement-editor">
        <div className="current-entity">
          <span>当前描述</span>
          <p>{currentEntity?.description}</p>
          <div className="tag-row">
            {currentEntity?.replaceable_fields.map((field) => <span key={field}>{field}</span>)}
          </div>
        </div>

        <label className="textarea-field">
          <span>替换为</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="例如：35 岁中国男厨师，黑色短发，穿白色亚麻厨师服，沉稳专业"
            rows={5}
          />
        </label>

        <div className="lock-options">
          <div>
            <LockSimple size={17} />
            <span>保持不变</span>
          </div>
          <div className="lock-grid">
            {lockOptions.map(([value, label]) => (
              <label key={value}>
                <input
                  type="checkbox"
                  checked={locks.includes(value)}
                  onChange={() => toggleLock(value)}
                />
                <span>{locks.includes(value) && <Check size={12} weight="bold" />}</span>
                {label}
              </label>
            ))}
          </div>
        </div>

        <button className="primary-button full" type="button" onClick={submitReplacement} disabled={loading}>
          {loading ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} weight="fill" />}
          生成替换版提示词
        </button>

        {replacementVersion && (
          <div className="replacement-result">
            <div>
              <CheckCircle size={19} weight="fill" />
              <strong>Prompt v{replacementVersion.prompt_package.version} 已生成</strong>
            </div>
            {replacementVersion.diffs.map((diff) => (
              <div className="diff-card" key={diff.entity_id}>
                <span>{diff.entity_id}</span>
                <p><del>{diff.before}</del></p>
                <p><ins>{diff.after}</ins></p>
                <small>影响 {diff.affected_shot_ids.length} 个镜头</small>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PromptsTab({ promptPackage, onCopy, onDownload }) {
  return (
    <div className="prompts-layout">
      <div className="prompt-global-card">
        <div className="prompt-card-header">
          <div>
            <span className="eyebrow">全局视觉圣经</span>
            <h3>{promptPackage.target_model} · Prompt v{promptPackage.version}</h3>
          </div>
          <button className="icon-button bordered" type="button" onClick={() => onCopy(promptPackage.global_prompt, "全局提示词已复制")} aria-label="复制全局提示词">
            <Copy size={17} />
          </button>
        </div>
        <p>{promptPackage.global_prompt}</p>
      </div>

      <div className="prompt-two-column">
        <div className="continuity-card">
          <div className="mini-heading">
            <LockSimple size={17} />
            <strong>连续性锁</strong>
          </div>
          <ul>
            {promptPackage.continuity_locks.map((lock) => <li key={lock}>{lock}</li>)}
          </ul>
        </div>
        <div className="continuity-card negative">
          <div className="mini-heading">
            <ShieldCheck size={17} />
            <strong>负面约束</strong>
          </div>
          <ul>
            {promptPackage.negative_constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}
          </ul>
        </div>
      </div>

      <div className="prompt-shot-list">
        {promptPackage.shots.map((shot, index) => (
          <article key={shot.shot_id}>
            <div>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{shot.shot_id}</strong>
                <small>{shot.duration_seconds.toFixed(1)} 秒</small>
              </div>
            </div>
            <p>{shot.prompt}</p>
            <button type="button" onClick={() => onCopy(shot.prompt, `${shot.shot_id} 已复制`)}>
              <Copy size={16} />
              复制
            </button>
          </article>
        ))}
      </div>

      <div className="export-bar">
        <div>
          <BracketsCurly size={21} />
          <span>
            <strong>机器可读 Prompt Package</strong>
            <small>包含实体、时间线、逐镜头指令与约束</small>
          </span>
        </div>
        <button className="primary-button compact" type="button" onClick={onDownload}>
          <DownloadSimple size={17} />
          下载 JSON
        </button>
      </div>
    </div>
  );
}

function InsightsPanel({ report, analysis, onOpenTab }) {
  const progressMessage = analysis && analysis.stage !== "completed" ? analysis.message : null;
  const isMediaEvidence = report?.analysis_mode === "media_evidence";
  const isModel = report?.analysis_mode === "model";
  const metadata = report?.media_evidence?.metadata;
  return (
    <aside className="insights-panel">
      <div className="insights-heading">
        <div>
          {isMediaEvidence ? (
            <ShieldCheck size={18} weight="fill" />
          ) : isModel ? (
            <Sparkle size={18} weight="fill" />
          ) : (
            <Sparkle size={18} weight="fill" />
          )}
          <strong>{isMediaEvidence ? "真实分析状态" : isModel ? "VLM 分析状态" : "AI 助手建议"}</strong>
        </div>
        <button className="icon-button" type="button" aria-label="刷新建议">
          <ArrowClockwise size={17} />
        </button>
      </div>

      {progressMessage ? (
        <div className="assistant-progress">
          {analysis.stage === "failed" ? (
            <X size={24} weight="bold" />
          ) : (
            <CircleNotch className="spin" size={24} />
          )}
          <strong>{stageLabels[analysis.stage]}</strong>
          <p>{progressMessage}</p>
          <div className="assistant-progress-track">
            <span style={{ width: `${analysis.progress}%` }} />
          </div>
        </div>
      ) : isMediaEvidence ? (
        <>
          <div className="insight-card purple">
            <span className="insight-icon"><ShieldCheck size={20} weight="fill" /></span>
            <div>
              <strong>媒体探测与代理文件已完成</strong>
              <p>
                {metadata?.width} × {metadata?.height} · {report.overview.duration_seconds.toFixed(1)} 秒 · {metadata?.video_codec?.toUpperCase()}
              </p>
            </div>
          </div>
          <div className="insight-card orange">
            <span className="insight-icon"><FilmStrip size={20} weight="fill" /></span>
            <div>
              <strong>检测到 {report.shots.length} 个真实镜头</strong>
              <p>每个时间区间都已生成代表关键帧，可回到原视频对应时间点核验。</p>
            </div>
          </div>
          <div className="insight-card green">
            <span className="insight-icon"><MagicWand size={20} weight="fill" /></span>
            <div>
              <strong>语义层将在下一批接入</strong>
              <p>接入 ASR、OCR 与多模态模型后，再生成主体、场景、爆点和 Seedance 提示词。</p>
            </div>
          </div>
          <button className="assistant-action" type="button" onClick={() => onOpenTab("shots")}>
            查看真实分镜证据
            <CaretRight size={16} />
          </button>
        </>
      ) : isModel ? (
        <>
          <div className="insight-card purple">
            <span className="insight-icon"><Sparkle size={20} weight="fill" /></span>
            <div>
              <strong>
                已理解 {report.shots.filter((shot) => shot.evidence_kind === "model").length} / {report.shots.length} 个镜头
              </strong>
              <p>主体、动作、场景、摄影、灯光、色彩和复刻提示词均保留关键帧证据。</p>
            </div>
          </div>
          <div className="insight-card orange">
            <span className="insight-icon"><BracketsCurly size={20} weight="fill" /></span>
            <div>
              <strong>{formatCost(report.model_cost_summary?.measured_cost_micros)} 模型成本</strong>
              <p>
                {report.model_cost_summary?.run_count || 0} 次调用 ·
                {report.model_cost_summary?.cached_run_count || 0} 次结果缓存
              </p>
            </div>
          </div>
          <div className="insight-card green">
            <span className="insight-icon"><Target size={20} weight="fill" /></span>
            <div>
              <strong>爆点与全局实体尚未推理</strong>
              <p>本批先固定逐镜头事实，下一阶段再归并人物、服装、场景并分析爆点。</p>
            </div>
          </div>
          <button className="assistant-action" type="button" onClick={() => onOpenTab("shots")}>
            查看 VLM 分镜事实
            <CaretRight size={16} />
          </button>
        </>
      ) : report ? (
        <>
          <div className="insight-card purple">
            <span className="insight-icon"><Target size={20} weight="fill" /></span>
            <div>
              <strong>{report.viral_findings[0]?.title}</strong>
              <p>{report.viral_findings[0]?.recommendation}</p>
            </div>
          </div>
          <div className="insight-card orange">
            <span className="insight-icon"><FilmStrip size={20} weight="fill" /></span>
            <div>
              <strong>结构可直接复用</strong>
              <p>{report.overview.narrative_structure}</p>
            </div>
          </div>
          <div className="insight-card green">
            <span className="insight-icon"><Swap size={20} weight="fill" /></span>
            <div>
              <strong>{report.entities.length} 个元素可替换</strong>
              <p>优先替换人物或场景，同时锁定动作、机位和节奏。</p>
            </div>
          </div>
          <button className="assistant-action" type="button" onClick={() => onOpenTab("replace")}>
            生成元素替换方案
            <CaretRight size={16} />
          </button>
        </>
      ) : (
        <div className="assistant-empty">
          <span><Sparkle size={24} /></span>
          <strong>等待视频分析</strong>
          <p>完成导入后，这里会汇总最值得复用的 Hook、结构和视觉元素。</p>
        </div>
      )}

      <div className="phase-note">
        <ShieldCheck size={17} />
        <div>
          <strong>一期边界</strong>
          <p>只分析单条视频，不读取账号，不调用视频生成模型。</p>
        </div>
      </div>
    </aside>
  );
}
