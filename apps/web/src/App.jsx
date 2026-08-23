import {
  forwardRef,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  ArrowClockwise,
  Archive,
  Bell,
  CaretDown,
  CaretLeft,
  CaretRight,
  ChartBar,
  Check,
  CheckCircle,
  CircleNotch,
  ClockCounterClockwise,
  Copy,
  DownloadSimple,
  DotsThree,
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
  Tag,
  TextT,
  Trash,
  UploadSimple,
  VideoCamera,
  X,
} from "@phosphor-icons/react";
import { AssetLibrary } from "./AssetLibrary.jsx";
import { CategoryProfileLibrary } from "./category-profiles/index.js";
import { PlatformAdminConsole } from "./admin/PlatformAdminConsole.jsx";
import { DepthGenerationSettings } from "./depth-settings/DepthGenerationSettings.jsx";
import { MediaStagingSettingsPanel } from "./media-staging/MediaStagingSettingsPanel.jsx";
import { PlatformBrandLogo } from "./PlatformBrandLogo.jsx";
import { PlatformConnections } from "./PlatformConnections.jsx";
import { UserSettingsPage } from "./settings/UserSettingsPage.jsx";
import {
  PromptEditor,
  promptPackageToPlainText,
  promptTextFilename,
} from "./prompt-editor/index.js";
import { PromptSectionView } from "./prompt-presentation/PromptSectionView.jsx";
import {
  NotificationDrawer,
  ToastViewport,
} from "./NotificationCenter.jsx";
import { notificationToastPayload } from "./notification-ui.js";
import { ProductionHub } from "./ProductionWorkflow.jsx";
import {
  buildRecordBreadcrumb,
  shouldShowTopbarCreate,
} from "./app-layout.js";
import {
  pathForNav,
  recordWorkspacePath,
  resolveAppRoute,
} from "./app-routing.js";
import { inferVideoOrientation } from "./video-layout.js";
import {
  buildRecordListParams,
  normalizeRecordLifecycle,
  RECORD_LIFECYCLE_META,
  RECORD_LIFECYCLES,
  recordActionSuccessMessage,
  recordBatchActions,
} from "./record-lifecycle-ui.js";
import {
  forgetRecordThumbnailLoaded,
  recordThumbnailInitialState,
  rememberRecordThumbnailLoaded,
} from "./record-thumbnail-ui.js";
import {
  connectionHealthMeta,
  detectPlatformFromUrl,
  findPlatformConnection,
  isCredentialAnalysisError,
  platformLabel,
  sourceTypeLabel,
  SUPPORTED_PLATFORM_NAMES,
} from "./platform-connection-ui.js";
import { preferredVideoResolution } from "./production-ui.js";
import {
  NewAnalysisPage,
  RecordWorkspacePage,
  RecordWorkspaceState,
  WorkbenchHomePage,
} from "./WorkspacePages.jsx";
import {
  hasReportableNarrativeStructure,
  ReplicationWorkspace,
  ShotTrafficRoles,
  ViralExecutiveSummary,
  ViralMechanismWorkspace,
} from "./viral-report/index.js";
import "./viral-report/viral-report.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";
const DEFAULT_PLATFORM_CONNECTIONS = Object.freeze({
  local_only: true,
  device_name: "当前设备",
  items: [],
});
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
const DEFAULT_IMAGE_GENERATION_SETTINGS = Object.freeze({
  enabled: false,
  execution_mode: "remote_api",
  default_candidate_count: 1,
  remote_provider: "dashscope",
  remote_model_alias: "qwen_image_2_pro",
  remote_model: "qwen-image-2.0-pro",
  remote_base_url: "https://dashscope.aliyuncs.com/api/v1",
  api_key_configured: false,
  api_key_hint: null,
  local_adapter_id: "viral_dna_json_v1",
  local_executable_path: "",
  local_fixed_args: [],
  local_timeout_seconds: 300,
  local_concurrency: 1,
  local_protocol_version: "viral-dna-image-tool/v1",
  local_tool_id: null,
  local_tool_version: null,
  local_cost_source: "unknown",
  local_unit_cost_micros: null,
  semantic_quality_enabled: false,
  local_model_policy: "latest_flagship",
  local_model: null,
  local_reasoning_effort: "xhigh",
  local_proxy_mode: "system",
  local_proxy_url: null,
  local_proxy_detected_url: null,
  local_proxy_effective_url: null,
  local_proxy_delivery: "direct",
  local_proxy_source: "none",
  local_windows_sandbox_mode: "auto",
  selected_capabilities: null,
  models: [],
});
const DEFAULT_VIDEO_GENERATION_SETTINGS = Object.freeze({
  enabled: true,
  default_model_alias: "bailian_wan_2_7_r2v",
  default_resolution: "720P",
  poll_interval_seconds: 5,
  task_timeout_seconds: 900,
  public_media_base_url: null,
  public_media_ttl_seconds: 3600,
  public_media_transport_ready: false,
  public_media_validation_message: null,
  catalog_version: "",
  pricing_version: "",
  providers: [
    { provider: "bailian", label: "阿里云百炼", api_key_configured: false, base_url: "https://dashscope.aliyuncs.com/api/v1" },
    { provider: "volc_ark", label: "火山方舟 Seedance", api_key_configured: false, base_url: "https://ark.cn-beijing.volces.com/api/v3" },
    { provider: "minimax", label: "MiniMax", api_key_configured: false, base_url: "https://api.minimaxi.com/v1" },
  ],
  models: [],
});
const DEFAULT_MEDIA_STAGING_SETTINGS = Object.freeze({
  provider: "disabled",
  credential_mode: "ecs_ram_role",
  region: "oss-cn-shanghai",
  bucket: "",
  internal_endpoint: null,
  public_endpoint: null,
  role_name: null,
  object_prefix: "viraldna/staging",
  signed_url_ttl_seconds: 28800,
  cleanup_grace_seconds: 86400,
  access_key_configured: false,
  access_key_hint: null,
  ready: false,
  validation_status: "not_configured",
  validation_message: null,
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
const HISTORY_STATE_STORAGE_KEY = "viral-dna:history-state:v1";
const HISTORY_PAGE_SIZES = [20, 50, 100];
const VALID_HISTORY_STATUSES = new Set(["", "ready", "analyzing", "completed", "failed"]);
const VALID_HISTORY_SORTS = new Set(["updated_desc", "created_desc", "name_asc"]);
const DEFAULT_HISTORY_STATE = Object.freeze({
  query: "",
  folder: "",
  status: "",
  sort: "updated_desc",
  lifecycle: "active",
  page: 1,
  pageSize: 20,
});

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

function loadHistoryState() {
  if (typeof window === "undefined") return { ...DEFAULT_HISTORY_STATE };
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(HISTORY_STATE_STORAGE_KEY) || "null");
    if (!saved || typeof saved !== "object") return { ...DEFAULT_HISTORY_STATE };
    const page = Number(saved.page);
    const pageSize = Number(saved.pageSize);
    return {
      query: typeof saved.query === "string" ? saved.query.slice(0, 120) : "",
      folder: typeof saved.folder === "string" ? saved.folder : "",
      status: VALID_HISTORY_STATUSES.has(saved.status) ? saved.status : "",
      sort: VALID_HISTORY_SORTS.has(saved.sort) ? saved.sort : DEFAULT_HISTORY_STATE.sort,
      lifecycle: normalizeRecordLifecycle(saved.lifecycle),
      page: Number.isInteger(page) && page > 0 ? page : 1,
      pageSize: HISTORY_PAGE_SIZES.includes(pageSize) ? pageSize : DEFAULT_HISTORY_STATE.pageSize,
    };
  } catch {
    return { ...DEFAULT_HISTORY_STATE };
  }
}

function saveHistoryState(state) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(HISTORY_STATE_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Browsing remains functional when session storage is unavailable.
  }
}

function buildPaginationItems(currentPage, totalPages) {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }
  const visiblePages = [...new Set([1, currentPage - 1, currentPage, currentPage + 1, totalPages])]
    .filter((page) => page >= 1 && page <= totalPages)
    .sort((left, right) => left - right);
  const items = [];
  visiblePages.forEach((page, index) => {
    const previous = visiblePages[index - 1];
    if (index > 0 && page - previous === 2) items.push(previous + 1);
    if (index > 0 && page - previous > 2) items.push(`ellipsis-${previous}-${page}`);
    items.push(page);
  });
  return items;
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
  { id: "assets", label: "资产库", icon: FolderOpen },
  { id: "categories", label: "品类库", icon: Tag },
];

const reportTabs = [
  { id: "overview", label: "总览", icon: ChartBar },
  { id: "viral", label: "爆款机制", icon: Target },
  { id: "shots", label: "分镜拆解", icon: FilmStrip },
  { id: "replicate", label: "复刻与改进", icon: Swap },
  { id: "prompts", label: "提示词", icon: TextT },
];

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail?.message === "string"
          ? detail.message
          : typeof payload?.message === "string"
            ? payload.message
            : "请求失败，请稍后重试";
    const requestError = new Error(message);
    if (detail && typeof detail === "object") {
      requestError.code = detail.code || null;
      requestError.platform = detail.platform || null;
      requestError.retryable = Boolean(detail.retryable);
    }
    requestError.status = response.status;
    throw requestError;
  }
  return payload;
}

function formatTime(seconds = 0) {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.max(0, seconds - minutes * 60);
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
}

function formatBoundaryMethod(method) {
  if (method === "video_start") return "视频起点";
  if (method === "hybrid_vlm_verified") return "VLM 确认边界";
  if (method === "hard_scene_score") return "程序硬切边界";
  return "程序检测边界";
}

function formatDurationBadge(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "";
  const rounded = Math.round(seconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remaining = rounded % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`;
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

function imageSettingsDraft(server = DEFAULT_IMAGE_GENERATION_SETTINGS) {
  return {
    imageExecutionMode: server.execution_mode || "remote_api",
    imageDefaultCandidateCount: Number(server.default_candidate_count || 1),
    imageRemoteProvider: server.remote_provider || "dashscope",
    imageRemoteModelAlias: server.remote_model_alias || "qwen_image_2_pro",
    imageRemoteBaseUrl:
      server.remote_base_url || DEFAULT_IMAGE_GENERATION_SETTINGS.remote_base_url,
    imageLocalAdapterId: server.local_adapter_id || "viral_dna_json_v1",
    imageLocalExecutablePath: server.local_executable_path || "",
    imageLocalFixedArgs: (server.local_fixed_args || []).join("\n"),
    imageLocalTimeoutSeconds: Number(server.local_timeout_seconds || 300),
    imageLocalConcurrency: Number(server.local_concurrency || 1),
    imageLocalProtocolVersion:
      server.local_protocol_version || "viral-dna-image-tool/v1",
    imageLocalCostSource: server.local_cost_source || "unknown",
    imageSemanticQualityEnabled: Boolean(server.semantic_quality_enabled),
    imageLocalModelPolicy: server.local_model_policy || "latest_flagship",
    imageLocalModel: server.local_model || "",
    imageLocalReasoningEffort: server.local_reasoning_effort || "xhigh",
    imageLocalProxyMode: server.local_proxy_mode || "system",
    imageLocalProxyUrl: server.local_proxy_url || "",
    imageLocalWindowsSandboxMode: server.local_windows_sandbox_mode || "auto",
    imageLocalUnitCostYuan:
      server.local_unit_cost_micros == null
        ? ""
        : (Number(server.local_unit_cost_micros) / 1_000_000).toFixed(4),
  };
}

function imageFixedArgs(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function localProxySourceLabel(value) {
  return {
    windows_user_proxy: "Windows 系统代理",
    environment: "进程环境变量",
    manual: "手动代理",
    disabled: "未使用代理",
    none: "未检测到代理",
  }[value] || "未检测到代理";
}

function supportsProductionVideoWorkflow(model) {
  return Boolean(
    model?.available
    && model.capabilities?.image_to_video
    && model.capabilities?.reference_route?.enabled !== false,
  );
}
function videoSettingsDraft(server = DEFAULT_VIDEO_GENERATION_SETTINGS) {
  const providers = server.providers?.length
    ? server.providers
    : DEFAULT_VIDEO_GENERATION_SETTINGS.providers;
  const models = server.models || [];
  const preferredAlias = (
    server.default_model_alias
    || DEFAULT_VIDEO_GENERATION_SETTINGS.default_model_alias
  );
  const selectedModel = models.find(
    (model) => model.alias === preferredAlias && supportsProductionVideoWorkflow(model),
  ) || models.find(supportsProductionVideoWorkflow);
  const preferredResolution = (
    server.default_resolution
    || DEFAULT_VIDEO_GENERATION_SETTINGS.default_resolution
  );
  const managedAssetProvider = providers.find((item) => item.provider === "volc_ark");
  return {
    videoEnabled: server.enabled !== false,
    videoDefaultModelAlias: selectedModel?.alias || preferredAlias,
    videoDefaultResolution: preferredVideoResolution(
      selectedModel,
      preferredResolution,
    ),
    videoPollIntervalSeconds: Number(server.poll_interval_seconds || 5),
    videoTaskTimeoutSeconds: Number(server.task_timeout_seconds || 900),
    videoPublicMediaBaseUrl: server.public_media_base_url || "",
    videoPublicMediaTtlSeconds: Number(server.public_media_ttl_seconds || 3600),
    videoProviderKeys: Object.fromEntries(providers.map((item) => [item.provider, ""])),
    videoProviderBaseUrls: Object.fromEntries(
      providers.map((item) => [item.provider, item.base_url]),
    ),
    videoManagedAssetAccessKey: "",
    videoManagedAssetSecretKey: "",
    videoManagedAssetRegion: managedAssetProvider?.managed_asset_region || "cn-beijing",
    videoManagedAssetProjectName:
      managedAssetProvider?.managed_asset_project_name || "default",
  };
}

function mediaStagingSettingsDraft(server = DEFAULT_MEDIA_STAGING_SETTINGS) {
  return {
    mediaStagingProvider: server.provider || "disabled",
    mediaStagingCredentialMode: server.credential_mode || "ecs_ram_role",
    mediaStagingRegion: server.region || "oss-cn-shanghai",
    mediaStagingBucket: server.bucket || "",
    mediaStagingInternalEndpoint: server.internal_endpoint || "",
    mediaStagingPublicEndpoint: server.public_endpoint || "",
    mediaStagingRoleName: server.role_name || "",
    mediaStagingObjectPrefix: server.object_prefix || "viraldna/staging",
    mediaStagingTtlSeconds: Number(server.signed_url_ttl_seconds || 28800),
    mediaStagingCleanupGraceSeconds: Number(server.cleanup_grace_seconds || 86400),
    mediaStagingAccessKeyId: "",
    mediaStagingAccessKeySecret: "",
  };
}

function mediaStagingSettingsPayload(draft) {
  return {
    provider: draft.mediaStagingProvider,
    credential_mode: draft.mediaStagingCredentialMode,
    region: String(draft.mediaStagingRegion || "").trim(),
    bucket: String(draft.mediaStagingBucket || "").trim(),
    internal_endpoint: String(draft.mediaStagingInternalEndpoint || "").trim() || null,
    public_endpoint: String(draft.mediaStagingPublicEndpoint || "").trim() || null,
    role_name: String(draft.mediaStagingRoleName || "").trim() || null,
    object_prefix: String(draft.mediaStagingObjectPrefix || "viraldna/staging").trim(),
    signed_url_ttl_seconds: Number(draft.mediaStagingTtlSeconds || 28800),
    cleanup_grace_seconds: Number(draft.mediaStagingCleanupGraceSeconds || 86400),
    access_key_id: String(draft.mediaStagingAccessKeyId || "").trim() || null,
    access_key_secret: String(draft.mediaStagingAccessKeySecret || "").trim() || null,
    clear_access_key: false,
  };
}

function localProxyDeliveryLabel(value) {
  return {
    codex_native: "由 Codex 读取系统代理",
    environment: "显式注入进程代理",
    direct: "直连",
  }[value] || "直连";
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
  const initialHistoryState = useMemo(loadHistoryState, []);
  const location = useLocation();
  const navigate = useNavigate();
  const appRoute = useMemo(
    () => resolveAppRoute(location.pathname),
    [location.pathname],
  );
  const activeNav = appRoute.activeNav;
  const [sourceMode, setSourceMode] = useState("link");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState(null);
  const [targetModel, setTargetModel] = useState(initialModelSettings.targetModel);
  const [analysisProfile, setAnalysisProfile] = useState(initialModelSettings.analysisProfile);
  const [maxCostCny, setMaxCostCny] = useState(initialModelSettings.maxCostCny);
  const [userSession, setUserSession] = useState(null);
  const [adminSession, setAdminSession] = useState(null);
  const [userPreferences, setUserPreferences] = useState(null);
  const [userSettingsLoading, setUserSettingsLoading] = useState(false);
  const [adminSettingsLoading, setAdminSettingsLoading] = useState(false);
  const [serverModelSettings, setServerModelSettings] = useState(DEFAULT_SERVER_MODEL_SETTINGS);
  const [serverImageSettings, setServerImageSettings] = useState(
    DEFAULT_IMAGE_GENERATION_SETTINGS,
  );
  const [serverVideoSettings, setServerVideoSettings] = useState(
    DEFAULT_VIDEO_GENERATION_SETTINGS,
  );
  const [serverMediaStagingSettings, setServerMediaStagingSettings] = useState(
    DEFAULT_MEDIA_STAGING_SETTINGS,
  );
  const [mediaStagingValidating, setMediaStagingValidating] = useState(false);
  const [mediaStagingValidation, setMediaStagingValidation] = useState(null);
  const [videoSettingsLoadState, setVideoSettingsLoadState] = useState("idle");
  const [videoSettingsLoadError, setVideoSettingsLoadError] = useState("");
  const [settingsDraft, setSettingsDraft] = useState({
    ...initialModelSettings,
    ...imageSettingsDraft(),
    ...videoSettingsDraft(),
    ...mediaStagingSettingsDraft(),
    provider: DEFAULT_SERVER_MODEL_SETTINGS.provider,
    modelAlias: DEFAULT_SERVER_MODEL_SETTINGS.model_alias,
    baseUrl: DEFAULT_SERVER_MODEL_SETTINGS.base_url,
    apiKey: "",
  });
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [imageToolDetecting, setImageToolDetecting] = useState(false);
  const [imageToolDetection, setImageToolDetection] = useState(null);
  const [codexDiscovering, setCodexDiscovering] = useState(false);
  const [codexDiscovery, setCodexDiscovery] = useState(null);
  const [codexApplying, setCodexApplying] = useState(false);
  const [codexNetworkTesting, setCodexNetworkTesting] = useState(false);
  const [codexNetworkTest, setCodexNetworkTest] = useState(null);
  const [codexSandboxTesting, setCodexSandboxTesting] = useState(false);
  const [codexSandboxTest, setCodexSandboxTest] = useState(null);
  const [workspaceInfo, setWorkspaceInfo] = useState(DEFAULT_WORKSPACE_INFO);
  const [workspaceDraft, setWorkspaceDraft] = useState("");
  const [workspaceValidation, setWorkspaceValidation] = useState(null);
  const [workspaceSaving, setWorkspaceSaving] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [folders, setFolders] = useState([]);
  const [records, setRecords] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyTotalPages, setHistoryTotalPages] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyQuery, setHistoryQuery] = useState(initialHistoryState.query);
  const [historyFolder, setHistoryFolder] = useState(initialHistoryState.folder);
  const [historyStatus, setHistoryStatus] = useState(initialHistoryState.status);
  const [historySort, setHistorySort] = useState(initialHistoryState.sort);
  const [historyLifecycle, setHistoryLifecycle] = useState(initialHistoryState.lifecycle);
  const [historyLifecycleCounts, setHistoryLifecycleCounts] = useState({
    active: 0,
    archived: 0,
    trashed: 0,
  });
  const [historyPage, setHistoryPage] = useState(initialHistoryState.page);
  const [historyPageSize, setHistoryPageSize] = useState(initialHistoryState.pageSize);
  const [historyActionBusy, setHistoryActionBusy] = useState(false);
  const [workbenchRecords, setWorkbenchRecords] = useState([]);
  const [workbenchTotal, setWorkbenchTotal] = useState(0);
  const [workbenchLoading, setWorkbenchLoading] = useState(false);
  const [platformConnections, setPlatformConnections] = useState(
    DEFAULT_PLATFORM_CONNECTIONS,
  );
  const [platformConnectionsLoading, setPlatformConnectionsLoading] = useState(false);
  const [platformConnectionsError, setPlatformConnectionsError] = useState("");
  const [platformConnectionTarget, setPlatformConnectionTarget] = useState("");
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [analysisErrorCode, setAnalysisErrorCode] = useState("");
  const [analysisErrorPlatform, setAnalysisErrorPlatform] = useState("");
  const [video, setVideo] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [analysisVersions, setAnalysisVersions] = useState([]);
  const [report, setReport] = useState(null);
  const [activeReportTab, setActiveReportTab] = useState("overview");
  const [activeShotId, setActiveShotId] = useState(null);
  const [replacementVersion, setReplacementVersion] = useState(null);
  const [recordWorkspaceMode, setRecordWorkspaceMode] = useState("analysis");
  const [productionProjects, setProductionProjects] = useState([]);
  const [productionsLoading, setProductionsLoading] = useState(false);
  const [productionsError, setProductionsError] = useState("");
  const [productionListSignal, setProductionListSignal] = useState(0);
  const [activeProductionProjectName, setActiveProductionProjectName] = useState("");
  const [toasts, setToasts] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [notificationUnreadCount, setNotificationUnreadCount] = useState(0);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [notificationFilter, setNotificationFilter] = useState("all");
  const [notificationLoading, setNotificationLoading] = useState(false);
  const [notificationTarget, setNotificationTarget] = useState(null);
  const [recordRouteLoading, setRecordRouteLoading] = useState(false);
  const [recordRouteError, setRecordRouteError] = useState("");
  const eventSourceRef = useRef(null);
  const toastSequenceRef = useRef(0);
  const notificationSnapshotRef = useRef(new Map());
  const notificationFeedInitializedRef = useRef(false);
  const historyRequestIdRef = useRef(0);
  const recordRouteRequestIdRef = useRef(0);
  const productionRequestIdRef = useRef(0);
  const videoSettingsRequestIdRef = useRef(0);
  const videoSettingsLoadedRef = useRef(false);
  const videoSettingsLoadStateRef = useRef("idle");
  const importSectionRef = useRef(null);
  const reportSectionRef = useRef(null);
  const videoRef = useRef(null);
  const filePreview = useFilePreview(file);

  const dismissToast = useCallback((toastId) => {
    setToasts((current) => current.filter((item) => item.id !== toastId));
  }, []);

  const showNotice = useCallback((notice) => {
    if (!notice) {
      setToasts([]);
      return;
    }
    const normalized = typeof notice === "string"
      ? { message: notice, type: "success" }
      : {
          message: notice.message || notice.title || "操作已完成",
          title: notice.message && notice.title ? notice.title : "",
          type: notice.type || notice.level || "success",
          duration: notice.duration,
          actionLabel: notice.actionLabel,
          onAction: notice.onAction,
        };
    const id = `toast-${Date.now()}-${toastSequenceRef.current += 1}`;
    setToasts((current) => [...current.slice(-2), { id, ...normalized }]);
  }, []);

  const loadPlatformConnections = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setPlatformConnectionsLoading(true);
    setPlatformConnectionsError("");
    try {
      const payload = await apiRequest("/settings/platform-connections");
      setPlatformConnections(payload || DEFAULT_PLATFORM_CONNECTIONS);
      return payload;
    } catch (requestError) {
      setPlatformConnectionsError(requestError.message);
      if (!quiet) throw requestError;
      return null;
    } finally {
      if (!quiet) setPlatformConnectionsLoading(false);
    }
  }, []);

  const refreshNotifications = useCallback(async ({ announce = true } = {}) => {
    try {
      const feed = await apiRequest("/me/notifications?limit=100");
      const items = feed.items || [];
      const nextSnapshot = new Map(
        items.map((item) => [item.id, `${item.status}:${item.updated_at}`]),
      );
      if (announce && notificationFeedInitializedRef.current) {
        for (const item of [...items].reverse()) {
          const previous = notificationSnapshotRef.current.get(item.id);
          const changed = previous !== nextSnapshot.get(item.id);
          if (changed && ["succeeded", "failed", "cancelled"].includes(item.status)) {
            showNotice(notificationToastPayload(item));
          }
        }
      }
      notificationSnapshotRef.current = nextSnapshot;
      notificationFeedInitializedRef.current = true;
      setNotifications(items);
      setNotificationUnreadCount(Number(feed.unread_count || 0));
    } catch {
      // The message center is auxiliary; a temporary polling failure should stay silent.
    }
  }, [showNotice]);

  useEffect(() => {
    return () => eventSourceRef.current?.close();
  }, []);

  useEffect(() => {
    loadWorkspace().catch(() => undefined);
    loadGenerationSettings().catch(() => undefined);
    loadUserSettings({ quiet: true }).catch(() => undefined);
    refreshHistory({ quiet: true }).catch(() => undefined);
    loadPlatformConnections({ quiet: true }).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (appRoute.name !== "user-settings") return;
    loadUserSettings().catch(() => undefined);
  }, [appRoute.name]);

  useEffect(() => {
    if (appRoute.name !== "platform-admin") return;
    loadPlatformAdminSettings().catch(() => undefined);
  }, [appRoute.name]);

  useEffect(() => {
    const recoverVideoSettings = () => {
      if (videoSettingsLoadStateRef.current === "loading") return;
      if (
        videoSettingsLoadedRef.current
        && videoSettingsLoadStateRef.current !== "error"
      ) return;
      loadVideoGenerationSettings({ quiet: true, retryCount: 1 }).catch(() => undefined);
    };
    window.addEventListener("online", recoverVideoSettings);
    window.addEventListener("focus", recoverVideoSettings);
    return () => {
      window.removeEventListener("online", recoverVideoSettings);
      window.removeEventListener("focus", recoverVideoSettings);
    };
  }, []);

  useEffect(() => {
    if (
      videoSettingsLoadState !== "error"
      || videoSettingsLoadedRef.current
    ) return undefined;
    const timer = window.setTimeout(() => {
      loadVideoGenerationSettings({ quiet: true, retryCount: 1 }).catch(() => undefined);
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [videoSettingsLoadState]);

  useEffect(() => {
    if (activeNav !== "platform-connections") return;
    loadPlatformConnections().catch(() => undefined);
  }, [activeNav, loadPlatformConnections]);

  useEffect(() => {
    refreshNotifications({ announce: false }).catch(() => undefined);
    const timer = window.setInterval(() => {
      refreshNotifications().catch(() => undefined);
    }, 8000);
    return () => window.clearInterval(timer);
  }, [refreshNotifications]);

  useEffect(() => {
    if (activeNav !== "history") return undefined;
    const timer = window.setTimeout(() => {
      refreshHistory().catch(() => undefined);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [
    activeNav,
    historyQuery,
    historyFolder,
    historyStatus,
    historySort,
    historyLifecycle,
    historyPage,
    historyPageSize,
  ]);

  useEffect(() => {
    if (appRoute.name !== "workbench-home") return;
    loadWorkbenchRecords().catch(() => undefined);
  }, [appRoute.name]);

  useEffect(() => {
    if (appRoute.name !== "record-workspace" || !appRoute.recordId) return;
    const currentRecordReady = video?.record_id === appRoute.recordId
      && Boolean(analysis || report);
    if (currentRecordReady) {
      setRecordRouteError("");
      setRecordRouteLoading(false);
      return;
    }
    loadRecordWorkspace(appRoute.recordId).catch(() => undefined);
  }, [appRoute.name, appRoute.recordId]);

  useEffect(() => {
    if (appRoute.name !== "not-found") return;
    navigate(pathForNav("workspace"), { replace: true });
  }, [appRoute.name, navigate]);

  useEffect(() => {
    saveHistoryState({
      query: historyQuery,
      folder: historyFolder,
      status: historyStatus,
      sort: historySort,
      lifecycle: historyLifecycle,
      page: historyPage,
      pageSize: historyPageSize,
    });
  }, [
    historyQuery,
    historyFolder,
    historyStatus,
    historySort,
    historyLifecycle,
    historyPage,
    historyPageSize,
  ]);

  async function loadUserSettings({ quiet = false } = {}) {
    if (!quiet) setUserSettingsLoading(true);
    try {
      const [session, preferences] = await Promise.all([
        apiRequest("/session"),
        apiRequest("/me/settings/preferences"),
      ]);
      setUserSession(session);
      setUserPreferences(preferences);
      setTargetModel(preferences.settings.target_model);
      setAnalysisProfile(preferences.settings.analysis_profile);
      setMaxCostCny(
        preferences.settings.max_cost_cny == null
          ? ""
          : Number(preferences.settings.max_cost_cny).toFixed(2),
      );
      apiRequest("/admin/session")
        .then(setAdminSession)
        .catch(() => setAdminSession(null));
      return preferences;
    } finally {
      if (!quiet) setUserSettingsLoading(false);
    }
  }

  async function saveUserSettings(nextSettings, revision) {
    const maxCost = String(nextSettings.max_cost_cny ?? "").trim();
    const payload = {
      ...nextSettings,
      max_cost_cny: maxCost ? Number(maxCost) : null,
      image_model_alias: nextSettings.image_model_alias || null,
      video_model_alias: nextSettings.video_model_alias || null,
      video_resolution: nextSettings.video_resolution || null,
    };
    const saved = await apiRequest("/me/settings/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ revision, settings: payload }),
    });
    setUserPreferences(saved);
    setTargetModel(saved.settings.target_model);
    setAnalysisProfile(saved.settings.analysis_profile);
    setMaxCostCny(
      saved.settings.max_cost_cny == null
        ? ""
        : Number(saved.settings.max_cost_cny).toFixed(2),
    );
    showNotice("账户设置已保存");
    return saved;
  }

  async function loadPlatformAdminSettings() {
    setAdminSettingsLoading(true);
    setSettingsError("");
    try {
      const [session, remote, imageRemote, videoRemote, mediaRemote] = await Promise.all([
        apiRequest("/admin/session"),
        apiRequest("/admin/settings/model"),
        apiRequest("/admin/settings/image-generation"),
        apiRequest("/admin/settings/video-generation"),
        apiRequest("/admin/settings/media-staging"),
      ]);
      setAdminSession(session);
      setServerModelSettings(remote);
      setServerImageSettings(imageRemote);
      setServerVideoSettings(videoRemote);
      setServerMediaStagingSettings(mediaRemote);
      setSettingsDraft((current) => ({
        ...current,
        ...imageSettingsDraft(imageRemote),
        ...videoSettingsDraft(videoRemote),
        ...mediaStagingSettingsDraft(mediaRemote),
        provider: remote.provider,
        modelAlias: remote.model_alias,
        baseUrl: remote.base_url,
        apiKey: "",
      }));
    } catch (requestError) {
      setSettingsError(requestError.message);
      throw requestError;
    } finally {
      setAdminSettingsLoading(false);
    }
  }

  async function loadWorkspace() {
    const next = await apiRequest("/workspace");
    setWorkspaceInfo(next);
    setWorkspaceDraft(next.root_path);
    return next;
  }

  function updateVideoSettingsLoadState(nextState) {
    videoSettingsLoadStateRef.current = nextState;
    setVideoSettingsLoadState(nextState);
  }

  async function loadVideoGenerationSettings({ quiet = false, retryCount = 2 } = {}) {
    const requestId = ++videoSettingsRequestIdRef.current;
    const hasCachedCatalog = videoSettingsLoadedRef.current;
    if (!quiet || !hasCachedCatalog) updateVideoSettingsLoadState("loading");
    setVideoSettingsLoadError("");

    let lastError = null;
    for (let attempt = 0; attempt <= retryCount; attempt += 1) {
      try {
        const next = await apiRequest("/settings/video-generation");
        if (requestId === videoSettingsRequestIdRef.current) {
          setServerVideoSettings(next);
          videoSettingsLoadedRef.current = true;
          updateVideoSettingsLoadState("ready");
          setVideoSettingsLoadError("");
        }
        return next;
      } catch (requestError) {
        lastError = requestError;
        if (attempt < retryCount) {
          await new Promise((resolve) => {
            window.setTimeout(resolve, 250 * (2 ** attempt));
          });
        }
      }
    }

    if (requestId === videoSettingsRequestIdRef.current) {
      updateVideoSettingsLoadState("error");
      setVideoSettingsLoadError(
        lastError?.message || "视频模型目录读取失败，请重新加载",
      );
    }
    throw lastError || new Error("视频模型目录读取失败");
  }

  async function loadMediaStagingSettings() {
    const next = await apiRequest("/settings/media-staging");
    setServerMediaStagingSettings(next || DEFAULT_MEDIA_STAGING_SETTINGS);
    return next || DEFAULT_MEDIA_STAGING_SETTINGS;
  }

  async function loadGenerationSettings() {
    const [imageResult, videoResult, mediaStagingResult] = await Promise.allSettled([
      apiRequest("/settings/image-generation"),
      loadVideoGenerationSettings(),
      loadMediaStagingSettings(),
    ]);
    if (imageResult.status === "fulfilled") {
      setServerImageSettings(imageResult.value);
    }
    return { imageResult, videoResult, mediaStagingResult };
  }

  function resetProductionWorkspace() {
    productionRequestIdRef.current += 1;
    setRecordWorkspaceMode("analysis");
    setProductionProjects([]);
    setProductionsLoading(false);
    setProductionsError("");
    setProductionListSignal(0);
    setActiveProductionProjectName("");
    setNotificationTarget(null);
  }

  async function loadProductions(recordId, { quiet = false } = {}) {
    if (!recordId) {
      resetProductionWorkspace();
      return [];
    }
    const requestId = ++productionRequestIdRef.current;
    if (!quiet) setProductionsLoading(true);
    setProductionsError("");
    try {
      const next = await apiRequest(`/records/${recordId}/productions`);
      if (requestId !== productionRequestIdRef.current) return next || [];
      setProductionProjects(next || []);
      return next || [];
    } catch (requestError) {
      if (requestId === productionRequestIdRef.current) {
        setProductionsError(requestError.message);
      }
      throw requestError;
    } finally {
      if (requestId === productionRequestIdRef.current) {
        setProductionsLoading(false);
      }
    }
  }

  async function refreshHistory({
    quiet = false,
    page = historyPage,
    pageSize = historyPageSize,
    query = historyQuery,
    folder = historyFolder,
    status = historyStatus,
    sort = historySort,
    lifecycle = historyLifecycle,
  } = {}) {
    const requestId = ++historyRequestIdRef.current;
    if (!quiet) setHistoryLoading(true);
    setHistoryError("");
    const params = buildRecordListParams({
      query,
      folder,
      status,
      sort,
      lifecycle,
      page,
      pageSize,
    });
    try {
      const [recordPayload, folderPayload] = await Promise.all([
        apiRequest(`/records?${params.toString()}`),
        apiRequest("/folders"),
      ]);
      if (requestId !== historyRequestIdRef.current) return;
      setRecords(recordPayload.items || []);
      setHistoryTotal(recordPayload.total || 0);
      setHistoryTotalPages(recordPayload.total_pages || 0);
      setHistoryLifecycleCounts(recordPayload.lifecycle_counts || {
        active: 0,
        archived: 0,
        trashed: 0,
      });
      if (recordPayload.page && recordPayload.page !== page) {
        setHistoryPage(recordPayload.page);
      }
      setFolders(folderPayload || []);
      setWorkspaceInfo((current) => ({
        ...current,
        folder_count: folderPayload.length || 0,
      }));
    } catch (requestError) {
      if (requestId === historyRequestIdRef.current) {
        setHistoryError(requestError.message);
      }
      throw requestError;
    } finally {
      if (requestId === historyRequestIdRef.current) {
        setHistoryLoading(false);
      }
    }
  }

  function selectNav(id) {
    setPlatformConnectionTarget("");
    navigate(pathForNav(id));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function changeHistoryQuery(value) {
    setHistoryPage(1);
    setHistoryQuery(value);
  }

  function changeHistoryFolder(value) {
    setHistoryPage(1);
    setHistoryFolder(value);
  }

  function changeHistoryStatus(value) {
    setHistoryPage(1);
    setHistoryStatus(value);
  }

  function changeHistorySort(value) {
    setHistoryPage(1);
    setHistorySort(value);
  }

  async function loadWorkbenchRecords() {
    setWorkbenchLoading(true);
    const params = buildRecordListParams({
      lifecycle: "active",
      page: 1,
      pageSize: 6,
      sort: "updated_desc",
    });
    try {
      const payload = await apiRequest(`/records?${params.toString()}`);
      setWorkbenchRecords(payload.items || []);
      setWorkbenchTotal(payload.total || 0);
      setHistoryLifecycleCounts(payload.lifecycle_counts || {
        active: 0,
        archived: 0,
        trashed: 0,
      });
      return payload.items || [];
    } finally {
      setWorkbenchLoading(false);
    }
  }

  function applyRecordWorkspaceDetail(detail) {
    resetProductionWorkspace();
    setVideo(detail.video);
    setAnalysisVersions(detail.analyses || []);
    setAnalysis(detail.analyses?.[0] || null);
    setReport(detail.latest_report || null);
    setReplacementVersion(null);
    setActiveShotId(detail.latest_report?.shots?.[0]?.id || null);
    setActiveReportTab("overview");
    loadProductions(detail.record.id).catch(() => undefined);
  }

  async function loadRecordWorkspace(recordId, { quiet = false } = {}) {
    const requestId = ++recordRouteRequestIdRef.current;
    if (!quiet) setRecordRouteLoading(true);
    setRecordRouteError("");
    try {
      const detail = await apiRequest(`/records/${recordId}`);
      if (requestId !== recordRouteRequestIdRef.current) return null;
      applyRecordWorkspaceDetail(detail);
      return detail;
    } catch (requestError) {
      if (requestId === recordRouteRequestIdRef.current) {
        setRecordRouteError(requestError.message);
      }
      throw requestError;
    } finally {
      if (requestId === recordRouteRequestIdRef.current) {
        setRecordRouteLoading(false);
      }
    }
  }

  function openPlatformConnections(platform = "") {
    setPlatformConnectionTarget(platform);
    navigate(pathForNav("platform-connections"));
  }

  function changeHistoryLifecycle(value) {
    setHistoryPage(1);
    setHistoryLifecycle(normalizeRecordLifecycle(value));
  }

  function changeHistoryPageSize(value) {
    setHistoryPage(1);
    setHistoryPageSize(Number(value));
  }

  async function openModelSettings(section = "generation") {
    navigate(`/settings/${section}`);
    await loadUserSettings({ quiet: true }).catch(() => undefined);
  }

  function updateSettingsDraft(update) {
    setSettingsError("");
    if (
      Object.hasOwn(update, "imageLocalProxyMode")
      || Object.hasOwn(update, "imageLocalProxyUrl")
    ) {
      setCodexNetworkTest(null);
      setCodexSandboxTest(null);
    }
    if (Object.hasOwn(update, "imageLocalWindowsSandboxMode")) {
      setCodexSandboxTest(null);
    }
    setSettingsDraft((current) => ({ ...current, ...update }));
  }

  async function validateMediaStaging() {
    setMediaStagingValidating(true);
    setMediaStagingValidation(null);
    setSettingsError("");
    try {
      const saved = await apiRequest("/admin/settings/media-staging", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mediaStagingSettingsPayload(settingsDraft)),
      });
      setServerMediaStagingSettings(saved);
      setSettingsDraft((current) => ({
        ...current,
        mediaStagingAccessKeyId: "",
        mediaStagingAccessKeySecret: "",
      }));
      const result = await apiRequest("/admin/settings/media-staging/validate", {
        method: "POST",
      });
      setMediaStagingValidation(result);
      if (!result.valid) setSettingsError(result.message);
    } catch (requestError) {
      setMediaStagingValidation({ valid: false, message: requestError.message });
      setSettingsError(requestError.message);
    } finally {
      setMediaStagingValidating(false);
    }
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
      resetProductionWorkspace();
      setHistoryQuery("");
      setHistoryFolder("");
      setHistoryStatus("");
      setHistorySort(DEFAULT_HISTORY_STATE.sort);
      setHistoryLifecycle("active");
      setHistoryPage(1);
      await refreshHistory({
        quiet: true,
        page: 1,
        pageSize: historyPageSize,
        query: "",
        folder: "",
        status: "",
        sort: DEFAULT_HISTORY_STATE.sort,
        lifecycle: "active",
      });
      showNotice("工作区已切换，历史记录已重新加载");
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
      showNotice("目录已创建");
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
      showNotice("目录名称已更新");
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
      if (successMessage) showNotice(successMessage);
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
      const detail = await loadRecordWorkspace(recordId);
      if (!detail) return null;
      navigate(recordWorkspacePath(detail.record.id));
      window.scrollTo({ top: 0, behavior: "smooth" });
      return detail;
    } catch (requestError) {
      setHistoryError(requestError.message);
      showNotice({ type: "error", title: "无法打开分析记录", message: requestError.message });
      return null;
    }
  }

  async function openHistoryProductions(recordId) {
    const detail = await openHistoryRecord(recordId);
    if (!detail) return null;
    setRecordWorkspaceMode("production");
    return detail;
  }

  async function mutateHistoryRecords(recordIds, action) {
    const ids = [...new Set(recordIds)].filter(Boolean);
    if (!ids.length || historyActionBusy) return false;
    if (
      action === "purge"
      && !window.confirm(`将永久删除选中的 ${ids.length} 条记录。共享资产会保留，但记录无法恢复。是否继续？`)
    ) {
      return false;
    }
    setHistoryActionBusy(true);
    setHistoryError("");
    try {
      const result = action === "purge"
        ? await apiRequest("/records/batch", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ record_ids: ids }),
          })
        : await apiRequest("/records/batch/lifecycle", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ record_ids: ids, action }),
          });
      await refreshHistory({ quiet: true });
      if (action === "purge") {
        loadWorkspace().catch(() => undefined);
      }
      showNotice(recordActionSuccessMessage(action, Number(result.affected_count || ids.length)));
      return true;
    } catch (requestError) {
      setHistoryError(requestError.message);
      showNotice({ type: "error", title: "记录操作失败", message: requestError.message });
      return false;
    } finally {
      setHistoryActionBusy(false);
    }
  }

  function toggleNotificationCenter() {
    const nextOpen = !notificationOpen;
    setNotificationOpen(nextOpen);
    if (!nextOpen) return;
    setNotificationLoading(true);
    refreshNotifications({ announce: false })
      .finally(() => setNotificationLoading(false));
  }

  async function markNotificationRead(notificationId) {
    const current = notifications.find((item) => item.id === notificationId);
    if (!current || current.read_at) return;
    try {
      const updated = await apiRequest(`/me/notifications/${notificationId}/read`, {
        method: "PATCH",
      });
      setNotifications((items) => items.map(
        (item) => (item.id === notificationId ? updated : item),
      ));
      setNotificationUnreadCount((count) => Math.max(0, count - 1));
    } catch (requestError) {
      showNotice({ type: "error", title: "消息状态更新失败", message: requestError.message });
    }
  }

  async function markAllNotificationsRead() {
    if (!notificationUnreadCount) return;
    try {
      await apiRequest("/me/notifications/read-all", { method: "POST" });
      const readAt = new Date().toISOString();
      setNotifications((items) => items.map(
        (item) => (item.read_at ? item : { ...item, read_at: readAt }),
      ));
      setNotificationUnreadCount(0);
    } catch (requestError) {
      showNotice({ type: "error", title: "消息状态更新失败", message: requestError.message });
    }
  }

  async function openNotificationAction(notification) {
    await markNotificationRead(notification.id);
    setNotificationOpen(false);
    const payload = notification.action_payload || {};
    if (notification.action_kind === "model_settings") {
      await openModelSettings();
      return;
    }
    if (notification.action_kind === "asset_library") {
      selectNav("assets");
      return;
    }
    if (notification.action_kind === "analysis_record") {
      if (payload.record_id) await openHistoryRecord(payload.record_id);
      return;
    }
    if (notification.action_kind !== "production_shot" || !payload.record_id) return;
    const opened = await openHistoryRecord(payload.record_id);
    if (!opened) return;
    setRecordWorkspaceMode("production");
    setNotificationTarget({
      candidateId: payload.candidate_id || "",
      projectId: payload.project_id || "",
      recordId: payload.record_id,
      shotPlanId: payload.shot_plan_id || "",
      step: payload.step || "shot_videos",
      token: `${notification.id}:${Date.now()}`,
    });
  }

  async function savePlatformSettings() {
    const hasConfiguredKey =
      serverModelSettings.api_key_configured || serverImageSettings.api_key_configured;
    const needsRemoteKey = settingsDraft.imageExecutionMode === "remote_api";
    if (
      !String(settingsDraft.apiKey || "").trim()
      && !hasConfiguredKey
      && needsRemoteKey
    ) {
      setSettingsError("首次配置请填写阿里云百炼 API Key。");
      return;
    }
    if (
      settingsDraft.imageExecutionMode === "local_tool"
      && !String(settingsDraft.imageLocalExecutablePath || "").trim()
    ) {
      setSettingsError("本机工具模式必须填写可执行文件路径。");
      return;
    }
    const localCostText = String(settingsDraft.imageLocalUnitCostYuan || "").trim();
    const localCostNumber = localCostText ? Number(localCostText) : null;
    if (
      settingsDraft.imageLocalCostSource === "configured_rate"
      && (
        localCostNumber === null
        || !Number.isFinite(localCostNumber)
        || localCostNumber < 0
      )
    ) {
      setSettingsError("按配置费率计费时，请填写有效的单张成本。");
      return;
    }

    setSettingsSaving(true);
    setSettingsError("");
    try {
      const sharedApiKey = String(settingsDraft.apiKey || "").trim() || null;
      if (sharedApiKey || serverModelSettings.api_key_configured) {
        const remote = await apiRequest("/admin/settings/model", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider: settingsDraft.provider,
            model_alias: settingsDraft.modelAlias,
            api_key: sharedApiKey,
            base_url: settingsDraft.baseUrl,
          }),
        });
        setServerModelSettings(remote);
      }
      const imageRemote = await apiRequest("/admin/settings/image-generation", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          execution_mode: settingsDraft.imageExecutionMode,
          default_candidate_count: Number(settingsDraft.imageDefaultCandidateCount || 1),
          remote_provider: settingsDraft.imageRemoteProvider,
          remote_model_alias: settingsDraft.imageRemoteModelAlias,
          remote_api_key: sharedApiKey,
          remote_base_url: settingsDraft.imageRemoteBaseUrl,
          local_adapter_id: settingsDraft.imageLocalAdapterId,
          local_executable_path: settingsDraft.imageLocalExecutablePath.trim() || null,
          local_fixed_args: imageFixedArgs(settingsDraft.imageLocalFixedArgs),
          local_timeout_seconds: Number(settingsDraft.imageLocalTimeoutSeconds || 300),
          local_concurrency: Number(settingsDraft.imageLocalConcurrency || 1),
          local_protocol_version: settingsDraft.imageLocalProtocolVersion,
          local_cost_source: settingsDraft.imageLocalCostSource,
          local_unit_cost_micros:
            localCostNumber === null ? null : Math.round(localCostNumber * 1_000_000),
          semantic_quality_enabled: Boolean(settingsDraft.imageSemanticQualityEnabled),
          local_model_policy: settingsDraft.imageLocalModelPolicy,
          local_model: String(settingsDraft.imageLocalModel || "").trim() || null,
          local_reasoning_effort: settingsDraft.imageLocalReasoningEffort,
          local_proxy_mode: settingsDraft.imageLocalProxyMode,
          local_proxy_url:
            String(settingsDraft.imageLocalProxyUrl || "").trim() || null,
          local_windows_sandbox_mode:
            settingsDraft.imageLocalWindowsSandboxMode,
        }),
      });
      setServerImageSettings(imageRemote);

      const videoRemote = await apiRequest("/admin/settings/video-generation", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: Boolean(settingsDraft.videoEnabled),
          default_model_alias: settingsDraft.videoDefaultModelAlias,
          default_resolution: settingsDraft.videoDefaultResolution,
          poll_interval_seconds: Number(settingsDraft.videoPollIntervalSeconds || 5),
          task_timeout_seconds: Number(settingsDraft.videoTaskTimeoutSeconds || 900),
          public_media_base_url:
            String(settingsDraft.videoPublicMediaBaseUrl || "").trim() || null,
          public_media_ttl_seconds: Number(
            settingsDraft.videoPublicMediaTtlSeconds || 3600,
          ),
          providers: (serverVideoSettings.providers || []).map((provider) => {
            const managedAccessKey = String(
              settingsDraft.videoManagedAssetAccessKey || "",
            ).trim();
            const managedSecretKey = String(
              settingsDraft.videoManagedAssetSecretKey || "",
            ).trim();
            const managedRegionChanged = provider.provider === "volc_ark" && (
              settingsDraft.videoManagedAssetRegion
              !== (provider.managed_asset_region || "cn-beijing")
            );
            const managedProjectChanged = provider.provider === "volc_ark" && (
              String(settingsDraft.videoManagedAssetProjectName || "default").trim()
              !== (provider.managed_asset_project_name || "default")
            );
            const managedChanged = provider.provider === "volc_ark" && (
              managedAccessKey
              || managedSecretKey
              || managedRegionChanged
              || managedProjectChanged
            );
            return {
              provider: provider.provider,
              api_key:
                String(settingsDraft.videoProviderKeys?.[provider.provider] || "").trim()
                || null,
              base_url:
                settingsDraft.videoProviderBaseUrls?.[provider.provider]
                || provider.base_url,
              clear_api_key: false,
              ...(managedChanged ? {
                managed_asset_access_key: managedAccessKey || null,
                managed_asset_secret_key: managedSecretKey || null,
                managed_asset_region: settingsDraft.videoManagedAssetRegion,
                managed_asset_project_name:
                  String(settingsDraft.videoManagedAssetProjectName || "default").trim(),
              } : {}),
            };
          }),
        }),
      });
      const mediaStagingRemote = await apiRequest("/admin/settings/media-staging", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mediaStagingSettingsPayload(settingsDraft)),
      });
      videoSettingsRequestIdRef.current += 1;
      setServerVideoSettings(videoRemote);
      setServerMediaStagingSettings(mediaStagingRemote);
      videoSettingsLoadedRef.current = true;
      updateVideoSettingsLoadState("ready");
      setVideoSettingsLoadError("");

      setSettingsDraft((current) => ({
        ...current,
        apiKey: "",
        videoProviderKeys: Object.fromEntries(
          (videoRemote.providers || []).map((provider) => [provider.provider, ""]),
        ),
        videoManagedAssetAccessKey: "",
        videoManagedAssetSecretKey: "",
        mediaStagingAccessKeyId: "",
        mediaStagingAccessKeySecret: "",
        videoManagedAssetRegion: (
          videoRemote.providers?.find((provider) => provider.provider === "volc_ark")
            ?.managed_asset_region || "cn-beijing"
        ),
        videoManagedAssetProjectName: (
          videoRemote.providers?.find((provider) => provider.provider === "volc_ark")
            ?.managed_asset_project_name || "default"
        ),
      }));
      showNotice("平台模型、凭据与媒体配置已保存");
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
        setAnalysisErrorCode("");
        setAnalysisErrorPlatform("");
        await loadReport(next.video_id);
        return;
      }
      if (next.stage === "failed") {
        setError(next.error?.message || next.message || "分析失败");
        setAnalysisErrorCode(next.error?.code || "");
        setAnalysisErrorPlatform(detectPlatformFromUrl(video?.source_url || url) || "");
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
        setAnalysisErrorCode("");
        setAnalysisErrorPlatform("");
        source.close();
        await loadReport(next.video_id);
      }
      if (next.stage === "failed") {
        setError(next.error?.message || next.message || "分析失败");
        setAnalysisErrorCode(next.error?.code || "");
        setAnalysisErrorPlatform(detectPlatformFromUrl(video?.source_url || url) || "");
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
    setAnalysisErrorCode("");
    setAnalysisErrorPlatform("");
    setRecordRouteError("");
    setRecordRouteLoading(false);
    navigate(recordWorkspacePath(processedVideo.record_id), { replace: true });
    setActiveShotId(nextReport.shots[0]?.id || null);
    setActiveReportTab("overview");
    resetProductionWorkspace();
    loadProductions(processedVideo.record_id).catch(() => undefined);
    loadWorkspace().catch(() => undefined);
    refreshHistory({ quiet: true }).catch(() => undefined);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function createAnalysisForVideo(createdVideo) {
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
    return createdAnalysis;
  }

  async function startAnalysis() {
    setError("");
    setAnalysisErrorCode("");
    setAnalysisErrorPlatform("");
    showNotice("");
    if (!rightsConfirmed) {
      setError("请先确认拥有视频分析和使用权限");
      return;
    }
    if (sourceMode === "link" && !url.trim()) {
      setError(`请粘贴以下平台的公开链接：${SUPPORTED_PLATFORM_NAMES}`);
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
    resetProductionWorkspace();
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
      await createAnalysisForVideo(createdVideo);
      setRecordRouteError("");
      setRecordRouteLoading(false);
      navigate(recordWorkspacePath(createdVideo.record_id));
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (requestError) {
      setError(requestError.message);
      setAnalysisErrorCode(requestError.code || "");
      setAnalysisErrorPlatform(
        requestError.platform || detectPlatformFromUrl(url) || "",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function retryCurrentLinkAnalysis() {
    const normalizedUrl = url.trim();
    const canReuseVideo = sourceMode === "link"
      && video?.id
      && video.source_url === normalizedUrl;
    if (!canReuseVideo) {
      await startAnalysis();
      return;
    }

    setSubmitting(true);
    setError("");
    setAnalysisErrorCode("");
    setAnalysisErrorPlatform("");
    setReport(null);
    setReplacementVersion(null);
    setAnalysis(null);
    resetProductionWorkspace();
    try {
      await loadPlatformConnections({ quiet: true });
      await createAnalysisForVideo(video);
      showNotice({ type: "success", message: "已使用更新后的平台连接重试原任务" });
    } catch (requestError) {
      setError(requestError.message);
      setAnalysisErrorCode(requestError.code || "");
      setAnalysisErrorPlatform(
        requestError.platform || detectPlatformFromUrl(normalizedUrl) || "",
      );
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

  const updateCurrentPromptPackage = useCallback((nextPackage) => {
    if (replacementVersion) return;
    const promptByShotId = new Map(
      (nextPackage?.shots || []).map((shot) => [shot.shot_id, shot.prompt]),
    );
    setReport((current) => current
      ? {
          ...current,
          prompt_package: nextPackage,
          shots: (current.shots || []).map((shot) => (
            promptByShotId.has(shot.id)
              ? { ...shot, prompt: promptByShotId.get(shot.id) }
              : shot
          )),
        }
      : current);
  }, [replacementVersion]);

  async function copyText(text, message = "已复制") {
    await navigator.clipboard.writeText(text);
    showNotice(message);
  }

  async function downloadPromptPackage(packageOverride = null) {
    const packageToDownload = Array.isArray(packageOverride?.shots)
      ? packageOverride
      : currentPromptPackage;
    if (!packageToDownload) return;
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
          showNotice(
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
    const blob = new Blob([JSON.stringify(packageToDownload, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `viral-dna-prompt-v${packageToDownload.version}.json`;
    anchor.click();
    URL.revokeObjectURL(href);
    showNotice("替换版提示词包已下载");
  }

  function downloadPromptText(packageOverride = null) {
    const packageToDownload = Array.isArray(packageOverride?.shots)
      ? packageOverride
      : currentPromptPackage;
    if (!packageToDownload) return;
    const blob = new Blob(["\uFEFF" + promptPackageToPlainText(packageToDownload)], {
      type: "text/plain;charset=utf-8",
    });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = promptTextFilename(packageToDownload);
    anchor.hidden = true;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(href), 0);
    showNotice("提示词 TXT 已下载");
  }

  async function openAnalysisVersion(analysisId) {
    if (!analysisId || analysisId === report?.analysis_id) return;
    const selected = analysisVersions.find((item) => item.id === analysisId);
    if (selected?.stage !== "completed") {
      showNotice("该分析版本尚未完成");
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
      setRecordWorkspaceMode("analysis");
      showNotice("已切换分析版本");
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
      resetProductionWorkspace();
      connectToProgress(next.id);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function detectLocalImageTool() {
    if (!String(settingsDraft.imageLocalExecutablePath || "").trim()) {
      setSettingsError("请先填写本机工具可执行文件路径。");
      return;
    }
    setImageToolDetecting(true);
    setImageToolDetection(null);
    setSettingsError("");
    try {
      const result = await apiRequest("/settings/image-generation/detect-local", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          adapter_id: settingsDraft.imageLocalAdapterId,
          executable_path: settingsDraft.imageLocalExecutablePath.trim(),
          fixed_args: imageFixedArgs(settingsDraft.imageLocalFixedArgs),
          protocol_version: settingsDraft.imageLocalProtocolVersion,
          timeout_seconds: Math.min(
            120,
            Number(settingsDraft.imageLocalTimeoutSeconds || 20),
          ),
          proxy_mode: settingsDraft.imageLocalProxyMode,
          proxy_url: String(settingsDraft.imageLocalProxyUrl || "").trim() || null,
        }),
      });
      setImageToolDetection(result);
    } catch (requestError) {
      setSettingsError(requestError.message);
    } finally {
      setImageToolDetecting(false);
    }
  }

  async function discoverLocalCodex({ quiet = false } = {}) {
    setCodexDiscovering(true);
    if (!quiet) setSettingsError("");
    try {
      const result = await apiRequest(
        "/settings/image-generation/discover-local-codex",
        { method: "POST" },
      );
      setCodexDiscovery(result);
      return result;
    } catch (requestError) {
      setCodexDiscovery(null);
      if (!quiet) setSettingsError(`无法检测本机 Codex：${requestError.message}`);
      return null;
    } finally {
      setCodexDiscovering(false);
    }
  }

  async function testLocalCodexNetwork() {
    setCodexNetworkTesting(true);
    setCodexNetworkTest(null);
    setSettingsError("");
    try {
      const result = await apiRequest(
        "/settings/image-generation/test-local-network",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            proxy_mode: settingsDraft.imageLocalProxyMode,
            proxy_url:
              String(settingsDraft.imageLocalProxyUrl || "").trim() || null,
            timeout_seconds: 15,
          }),
        },
      );
      setCodexNetworkTest(result);
    } catch (requestError) {
      setSettingsError(`Codex 网络检测失败：${requestError.message}`);
    } finally {
      setCodexNetworkTesting(false);
    }
  }

  function openInsightEvidenceAt(seconds) {
    setActiveReportTab("overview");
    window.setTimeout(() => {
      if (!videoRef.current || !Number.isFinite(seconds)) return;
      videoRef.current.currentTime = seconds;
      videoRef.current.play().catch(() => undefined);
    }, 80);
  }

  async function openPublishedConcept(result) {
    if (!video?.record_id || !result?.project_id) return;
    await loadProductions(video.record_id, { quiet: true });
    setRecordWorkspaceMode("production");
    setProductionListSignal((current) => current + 1);
    setNotificationTarget({
      candidateId: "",
      projectId: result.project_id,
      recordId: video.record_id,
      shotPlanId: "",
      step: "shot_images",
      token: `viral-concept:${result.project_id}:${Date.now()}`,
    });
  }

  async function testLocalCodexSandbox() {
    setCodexSandboxTesting(true);
    setCodexSandboxTest(null);
    setSettingsError("");
    try {
      const result = await apiRequest(
        "/settings/image-generation/test-local-sandbox",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            proxy_mode: settingsDraft.imageLocalProxyMode,
            proxy_url:
              String(settingsDraft.imageLocalProxyUrl || "").trim() || null,
            windows_sandbox_mode:
              settingsDraft.imageLocalWindowsSandboxMode,
            timeout_seconds: 45,
          }),
        },
      );
      setCodexSandboxTest(result);
    } catch (requestError) {
      setCodexSandboxTest({
        ready: false,
        sandbox_mode: settingsDraft.imageLocalWindowsSandboxMode,
        proxy_delivery: "direct",
        latency_ms: 0,
        message: requestError.message,
      });
    } finally {
      setCodexSandboxTesting(false);
    }
  }

  async function applyLocalCodexConfiguration() {
    setCodexApplying(true);
    setSettingsError("");
    try {
      const result = await apiRequest(
        "/settings/image-generation/auto-configure-codex",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model_policy: settingsDraft.imageLocalModelPolicy,
            model: String(settingsDraft.imageLocalModel || "").trim() || null,
            reasoning_effort: settingsDraft.imageLocalReasoningEffort,
            default_candidate_count: Number(
              settingsDraft.imageDefaultCandidateCount || 1,
            ),
            proxy_mode: settingsDraft.imageLocalProxyMode,
            proxy_url:
              String(settingsDraft.imageLocalProxyUrl || "").trim() || null,
            windows_sandbox_mode:
              settingsDraft.imageLocalWindowsSandboxMode,
          }),
        },
      );
      setServerImageSettings(result);
      setSettingsDraft((current) => ({
        ...current,
        ...imageSettingsDraft(result),
        imageExecutionMode: "local_tool",
      }));
      setImageToolDetection({
        tool_id: result.local_tool_id,
        tool_version: result.local_tool_version,
        protocol_version: result.local_protocol_version,
        capabilities: result.selected_capabilities,
      });
      setCodexSandboxTest({
        ready: true,
        sandbox_mode: result.local_windows_sandbox_mode,
        proxy_delivery: result.local_proxy_delivery,
        latency_ms: result.validation_latency_ms || 0,
        message: "Codex Windows 沙箱预检已通过，本次未调用图片模型。",
      });
      showNotice(
        "Codex + ImageGen 已自动配置并通过无费用沙箱预检；首次出图仍需人工触发",
      );
    } catch (requestError) {
      setSettingsError(requestError.message);
    } finally {
      setCodexApplying(false);
    }
  }

  function changeRecordWorkspace(mode) {
    setRecordWorkspaceMode(mode);
    if (mode !== "production") setActiveProductionProjectName("");
    if (mode === "production" && video?.record_id) {
      loadVideoGenerationSettings({
        quiet: videoSettingsLoadedRef.current,
        retryCount: 1,
      }).catch(() => undefined);
      loadProductions(video.record_id, { quiet: productionProjects.length > 0 }).catch(() => undefined);
    }
  }

  function openWorkspaceHome() {
    setError("");
    setVideo(null);
    setAnalysis(null);
    setAnalysisVersions([]);
    setReport(null);
    setActiveReportTab("overview");
    setActiveShotId(null);
    setReplacementVersion(null);
    resetProductionWorkspace();
    navigate(pathForNav("workspace"));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function navigateRecordBreadcrumb(destination) {
    if (destination === "workspace") {
      openWorkspaceHome();
      return;
    }
    if (destination === "history") {
      selectNav("history");
      return;
    }
    if (destination === "production") {
      setActiveProductionProjectName("");
      setProductionListSignal((current) => current + 1);
    }
  }

  const recordDetailMode = appRoute.name === "record-workspace";
  const recordBreadcrumbItems = buildRecordBreadcrumb(
    recordWorkspaceMode,
    activeProductionProjectName,
  );
  const recordMatchesRoute = appRoute.name === "record-workspace"
    && video?.record_id === appRoute.recordId;
  const effectiveImageSettings = useMemo(() => {
    const preferences = userPreferences?.settings;
    if (!preferences) return serverImageSettings;
    return {
      ...serverImageSettings,
      default_candidate_count: preferences.image_candidate_count
        || serverImageSettings.default_candidate_count,
      remote_model_alias: preferences.image_model_alias
        || serverImageSettings.remote_model_alias,
    };
  }, [serverImageSettings, userPreferences]);
  const effectiveVideoSettings = useMemo(() => {
    const preferences = userPreferences?.settings;
    if (!preferences) return serverVideoSettings;
    return {
      ...serverVideoSettings,
      default_model_alias: preferences.video_model_alias
        || serverVideoSettings.default_model_alias,
      default_resolution: preferences.video_resolution
        || serverVideoSettings.default_resolution,
    };
  }, [serverVideoSettings, userPreferences]);

  if (appRoute.name === "platform-admin") {
    return (
      <PlatformAdminConsole
        adminSession={adminSession}
        draft={settingsDraft}
        error={settingsError}
        imageServerSettings={serverImageSettings}
        loading={adminSettingsLoading}
        mediaStagingServerSettings={serverMediaStagingSettings}
        mediaStagingValidating={mediaStagingValidating}
        mediaStagingValidation={mediaStagingValidation}
        onBack={() => navigate(pathForNav("settings"))}
        onChange={updateSettingsDraft}
        onNavigate={(section) => navigate(`/admin/${section}`)}
        onSave={savePlatformSettings}
        onValidateMediaStaging={validateMediaStaging}
        request={apiRequest}
        saving={settingsSaving}
        section={appRoute.adminSection}
        serverSettings={serverModelSettings}
        videoServerSettings={serverVideoSettings}
      />
    );
  }

  if (appRoute.name === "user-settings") {
    return (
      <UserSettingsPage
        adminAvailable={userSession?.auth_mode === "local_bootstrap"}
        imageSettings={serverImageSettings}
        loading={userSettingsLoading}
        onBack={() => navigate(pathForNav("workspace"))}
        onNavigate={(section) => navigate(`/settings/${section}`)}
        onOpenAdmin={() => navigate(pathForNav("admin"))}
        onOpenConnections={() => navigate(pathForNav("platform-connections"))}
        onSave={saveUserSettings}
        onSwitchWorkspace={switchWorkspace}
        onValidateWorkspace={validateWorkspace}
        onWorkspaceChange={updateWorkspaceDraft}
        preferences={userPreferences}
        section={appRoute.settingsSection}
        session={userSession}
        videoSettings={serverVideoSettings}
        workspace={workspaceInfo}
        workspaceDraft={workspaceDraft}
        workspaceError={workspaceError}
        workspaceSaving={workspaceSaving}
        workspaceValidation={workspaceValidation}
      />
    );
  }

  return (
    <div className="app-shell">
      <Sidebar
        activeNav={activeNav}
        historyLifecycle={historyLifecycle}
        historyLifecycleCounts={historyLifecycleCounts}
        onSelect={selectNav}
        onSelectHistoryLifecycle={(value) => {
          changeHistoryLifecycle(value);
          navigate(pathForNav("history"));
        }}
        onOpenSettings={() => openModelSettings("profile")}
        settingsOpen={activeNav === "settings"}
        historyCount={historyLifecycleCounts.active}
      />

      <div className="app-body">
        <Topbar
          assetMode={["assets", "categories", "platform-connections"].includes(activeNav)}
          focusMode={recordDetailMode}
          hideCreate={!shouldShowTopbarCreate(activeNav, report)}
          notificationOpen={notificationOpen}
          notificationUnreadCount={notificationUnreadCount}
          onCreate={() => selectNav("new-analysis")}
          onToggleNotifications={toggleNotificationCenter}
          onSearch={(value) => {
            changeHistoryQuery(value);
            if (value) navigate(pathForNav("history"));
          }}
          searchValue={historyQuery}
        />

        <div
          className={
            activeNav === "platform-connections"
              ? "platform-connections-layout"
              : activeNav === "history"
              ? "history-layout"
              : activeNav === "assets"
                ? "asset-library-layout"
              : activeNav === "categories"
                ? "category-profile-layout"
                : "workspace-layout"
          }
        >
          {activeNav === "platform-connections" ? (
            <PlatformConnections
              data={platformConnections}
              error={platformConnectionsError}
              initialPlatform={platformConnectionTarget}
              loading={platformConnectionsLoading}
              onBack={() => selectNav("new-analysis")}
              onNotice={showNotice}
              onRefresh={() => loadPlatformConnections()}
              request={apiRequest}
            />
          ) : activeNav === "history" ? (
            <HistoryPage
              records={records}
              folders={folders}
              total={historyTotal}
              totalPages={historyTotalPages}
              page={historyPage}
              pageSize={historyPageSize}
              loading={historyLoading}
              error={historyError}
              query={historyQuery}
              folderFilter={historyFolder}
              statusFilter={historyStatus}
              sort={historySort}
              lifecycle={historyLifecycle}
              lifecycleCounts={historyLifecycleCounts}
              actionBusy={historyActionBusy}
              onQueryChange={changeHistoryQuery}
              onFolderChange={changeHistoryFolder}
              onStatusChange={changeHistoryStatus}
              onSortChange={changeHistorySort}
              onLifecycleChange={changeHistoryLifecycle}
              onPageChange={setHistoryPage}
              onPageSizeChange={changeHistoryPageSize}
              onCreateFolder={createHistoryFolder}
              onRenameFolder={renameHistoryFolder}
              onRenameRecord={renameHistoryRecord}
              onMoveRecord={(recordId, folderId) => updateHistoryRecord(recordId, { folder_id: folderId || null }, "记录目录已更新")}
              onMutateRecords={mutateHistoryRecords}
              onOpenRecord={openHistoryRecord}
              onOpenProductions={openHistoryProductions}
              onCreate={() => selectNav("new-analysis")}
            />
          ) : activeNav === "assets" ? (
            <AssetLibrary
              onNotice={showNotice}
              request={apiRequest}
              resolveUrl={resolveArtifactUrl}
            />
          ) : activeNav === "categories" ? (
            <CategoryProfileLibrary
              onNotice={showNotice}
              request={apiRequest}
            />
          ) : appRoute.name === "new-analysis" ? (
            <NewAnalysisPage>
              <ImportPanel
                ref={importSectionRef}
                sourceMode={sourceMode}
                setSourceMode={setSourceMode}
                url={url}
                setUrl={(value) => {
                  setUrl(value);
                  setError("");
                  setAnalysisErrorCode("");
                  setAnalysisErrorPlatform("");
                }}
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
                errorCode={analysisErrorCode}
                errorPlatform={analysisErrorPlatform}
                platformConnections={platformConnections}
                onConfigurePlatform={openPlatformConnections}
                onRetry={retryCurrentLinkAnalysis}
                onStart={startAnalysis}
              />
            </NewAnalysisPage>
          ) : appRoute.name === "record-workspace" ? (
            <RecordWorkspacePage>
              {!recordMatchesRoute || recordRouteLoading ? (
                <RecordWorkspaceState
                  error={recordRouteError}
                  loading={!recordRouteError}
                  onBack={() => selectNav("history")}
                  onRetry={() => loadRecordWorkspace(appRoute.recordId).catch(() => undefined)}
                />
              ) : (
              <>
                <RecordBreadcrumb
                  items={recordBreadcrumbItems}
                  onNavigate={navigateRecordBreadcrumb}
                />
                {analysis && analysis.stage !== "completed" && (
                  <AnalysisProgress analysis={analysis} video={video} />
                )}
                {analysis?.stage === "completed" && !report && (
                  <RecordWorkspaceState loading />
                )}
                {!analysis && !report && (
                  <RecordWorkspaceState onBack={() => selectNav("history")} />
                )}
                {report && (
                <section className="report-card" ref={reportSectionRef}>
                  <ReportHeader
                    video={video}
                    report={report}
                    onDownload={downloadPromptPackage}
                    onRestart={reanalyzeCurrent}
                    analysisVersions={analysisVersions}
                    activeAnalysisId={report.analysis_id}
                    onVersionChange={openAnalysisVersion}
                    showActions={recordWorkspaceMode === "analysis"}
                  />
                  <RecordWorkspaceTabs
                    active={recordWorkspaceMode}
                    count={productionProjects.length}
                    onChange={changeRecordWorkspace}
                  />
                  {recordWorkspaceMode === "analysis" ? (
                  <>
                    <ReportTabs active={activeReportTab} onChange={setActiveReportTab} mode={report.analysis_mode} />
                    <div className="report-content">
                  {activeReportTab === "overview" && (
                    <>
                      <ViralExecutiveSummary
                        analysisId={report.analysis_id}
                        request={apiRequest}
                        onOpenMechanisms={() => setActiveReportTab("viral")}
                        onOpenReplication={() => setActiveReportTab("replicate")}
                      />
                      <OverviewTab
                        report={report}
                        filePreview={filePreview}
                        videoRef={videoRef}
                        onOpenShots={() => setActiveReportTab("shots")}
                      />
                    </>
                  )}
                  {activeReportTab === "shots" && (
                    <>
                      <ShotsTab
                        shots={report.shots}
                        segmentation={report.media_evidence?.segmentation}
                        activeShotId={activeShotId}
                        onSelect={seekToShot}
                        analysisMode={report.analysis_mode}
                        onCopy={copyText}
                      />
                      <ShotTrafficRoles
                        analysisId={report.analysis_id}
                        request={apiRequest}
                        resolveUrl={resolveArtifactUrl}
                        onSeek={openInsightEvidenceAt}
                      />
                    </>
                  )}
                  {activeReportTab === "viral" && (
                    <ViralMechanismWorkspace
                      analysisId={report.analysis_id}
                      request={apiRequest}
                      resolveUrl={resolveArtifactUrl}
                      onSeek={openInsightEvidenceAt}
                    />
                  )}
                  {activeReportTab === "replicate" && (
                    <ReplicationWorkspace
                      analysisId={report.analysis_id}
                      recordId={video.record_id}
                      request={apiRequest}
                      onPublished={openPublishedConcept}
                      onNotice={showNotice}
                      onManageCategories={() => navigate(pathForNav("categories"))}
                    />
                  )}
                  {activeReportTab === "prompts" && (
                    <PromptEditor
                      analysisId={report.analysis_id}
                      promptPackage={currentPromptPackage}
                      request={apiRequest}
                      readOnly={Boolean(replacementVersion)}
                      onCopy={copyText}
                      onDownload={downloadPromptText}
                      onNotice={showNotice}
                      onPromptPackageChange={updateCurrentPromptPackage}
                    />
                  )}
                    </div>
                  </>
                ) : (
                  <ProductionHub
                    analysisId={report.analysis_id}
                    error={productionsError}
                    imageGenerationSettings={effectiveImageSettings}
                    videoGenerationSettings={effectiveVideoSettings}
                    videoGenerationSettingsError={videoSettingsLoadError}
                    videoGenerationSettingsStatus={videoSettingsLoadState}
                    listSignal={productionListSignal}
                    loading={productionsLoading}
                    navigationTarget={notificationTarget}
                    onNavigationChange={setActiveProductionProjectName}
                    onNotificationsChanged={refreshNotifications}
                    onNotice={showNotice}
                    onOpenModelSettings={openModelSettings}
                    onReloadVideoGenerationSettings={() => (
                      loadVideoGenerationSettings({ retryCount: 1 })
                    )}
                    onProjectsChanged={async () => {
                      const next = await loadProductions(video.record_id, { quiet: true });
                      refreshHistory({ quiet: true }).catch(() => undefined);
                      return next;
                    }}
                    projects={productionProjects}
                    recordId={video.record_id}
                    request={apiRequest}
                    resolveUrl={resolveArtifactUrl}
                    sourceMedia={{
                      aspectRatio: report.media_evidence?.metadata?.aspect_ratio
                        || report.overview?.aspect_ratio
                        || currentPromptPackage?.aspect_ratio,
                      height: video.height || report.media_evidence?.metadata?.height,
                      width: video.width || report.media_evidence?.metadata?.width,
                    }}
                    sourceTitle={video.title}
                  />
                  )}
                </section>
                )}
              </>
              )}
            </RecordWorkspacePage>
          ) : (
            <WorkbenchHomePage
              loading={workbenchLoading}
              onCreate={() => selectNav("new-analysis")}
              onOpenHistory={() => selectNav("history")}
              onOpenRecord={openHistoryRecord}
              records={workbenchRecords}
              total={workbenchTotal}
            />
          )}
        </div>
      </div>

      <NotificationDrawer
        filter={notificationFilter}
        items={notifications}
        loading={notificationLoading}
        onAction={openNotificationAction}
        onClose={() => setNotificationOpen(false)}
        onFilterChange={setNotificationFilter}
        onMarkAllRead={markAllNotificationsRead}
        onMarkRead={markNotificationRead}
        open={notificationOpen}
        unreadCount={notificationUnreadCount}
      />
      <ToastViewport onDismiss={dismissToast} toasts={toasts} />
    </div>
  );
}

function RecordThumbnail({ record }) {
  const imageUrl = record.thumbnail_url ? resolveArtifactUrl(record.thumbnail_url) : "";
  const imageRef = useRef(null);
  const [imageState, setImageState] = useState(() => recordThumbnailInitialState(imageUrl));

  useLayoutEffect(() => {
    if (!imageUrl) {
      setImageState("missing");
      return;
    }

    const image = imageRef.current;
    if (!image?.complete) {
      setImageState("loading");
      return;
    }

    if (image.naturalWidth > 0) {
      rememberRecordThumbnailLoaded(imageUrl);
      setImageState("loaded");
      return;
    }

    forgetRecordThumbnailLoaded(imageUrl);
    setImageState("failed");
  }, [imageUrl]);

  function handleImageLoad(event) {
    if (event.currentTarget.naturalWidth > 0) {
      rememberRecordThumbnailLoaded(imageUrl);
      setImageState("loaded");
      return;
    }
    forgetRecordThumbnailLoaded(imageUrl);
    setImageState("failed");
  }

  function handleImageError() {
    forgetRecordThumbnailLoaded(imageUrl);
    setImageState("failed");
  }

  const loaded = imageState === "loaded";
  const showImage = Boolean(imageUrl) && imageState !== "failed";
  const duration = formatDurationBadge(record.duration_seconds);

  return (
    <span
      aria-hidden="true"
      className={`record-thumbnail ${record.source_type} ${showImage ? "has-image" : "fallback"} ${loaded ? "loaded" : "loading"}`}
    >
      {showImage ? (
        <>
          <span className="record-thumbnail-skeleton" />
          <img
            alt=""
            className="record-thumbnail-image"
            decoding="async"
            draggable="false"
            key={imageUrl}
            loading="lazy"
            onError={handleImageError}
            onLoad={handleImageLoad}
            ref={imageRef}
            src={imageUrl}
          />
          {loaded && duration && <span className="record-thumbnail-duration">{duration}</span>}
        </>
      ) : (
        <span className="record-thumbnail-fallback">
          {record.source_type === "upload" ? <FileVideo size={24} /> : <LinkSimple size={24} />}
        </span>
      )}
    </span>
  );
}

function HistoryPage({
  records,
  folders,
  total,
  totalPages,
  page,
  pageSize,
  loading,
  error,
  query,
  folderFilter,
  statusFilter,
  sort,
  lifecycle,
  lifecycleCounts,
  actionBusy,
  onQueryChange,
  onFolderChange,
  onStatusChange,
  onSortChange,
  onLifecycleChange,
  onPageChange,
  onPageSizeChange,
  onCreateFolder,
  onRenameFolder,
  onRenameRecord,
  onMoveRecord,
  onMutateRecords,
  onOpenRecord,
  onOpenProductions,
  onCreate,
}) {
  const folderNames = new Map(folders.map((folder) => [folder.id, folder.name]));
  const paginationItems = buildPaginationItems(page, totalPages);
  const firstResult = total > 0 ? (page - 1) * pageSize + 1 : 0;
  const lastResult = Math.min(page * pageSize, total);
  const filteredFolderName = folderFilter
    ? folderFilter === "unfiled"
      ? "未分类"
      : folderNames.get(folderFilter)
    : "";
  const resultHeadingRef = useRef(null);
  const selectAllRef = useRef(null);
  const [selectedRecordIds, setSelectedRecordIds] = useState([]);
  const lifecycleMeta = RECORD_LIFECYCLE_META[lifecycle] || RECORD_LIFECYCLE_META.active;
  const selectedIdSet = new Set(selectedRecordIds);
  const visibleRecordIds = records.map((record) => record.id);
  const allVisibleSelected = visibleRecordIds.length > 0
    && visibleRecordIds.every((recordId) => selectedIdSet.has(recordId));
  const someVisibleSelected = visibleRecordIds.some((recordId) => selectedIdSet.has(recordId));
  const batchActions = recordBatchActions(lifecycle);

  useEffect(() => {
    setSelectedRecordIds((current) => current.filter((recordId) => visibleRecordIds.includes(recordId)));
  }, [lifecycle, page, records]);

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someVisibleSelected && !allVisibleSelected;
    }
  }, [allVisibleSelected, someVisibleSelected]);

  function scrollToHistoryResults() {
    window.requestAnimationFrame(() => {
      resultHeadingRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function selectHistoryPage(nextPage) {
    onPageChange(nextPage);
    scrollToHistoryResults();
  }

  function selectHistoryPageSize(nextPageSize) {
    onPageSizeChange(nextPageSize);
    scrollToHistoryResults();
  }

  function toggleRecordSelection(recordId) {
    setSelectedRecordIds((current) => (
      current.includes(recordId)
        ? current.filter((item) => item !== recordId)
        : [...current, recordId]
    ));
  }

  function toggleVisibleSelection() {
    setSelectedRecordIds(allVisibleSelected ? [] : visibleRecordIds);
  }

  async function runRecordAction(recordIds, action) {
    const changed = await onMutateRecords(recordIds, action);
    if (changed) setSelectedRecordIds([]);
  }

  return (
    <>
      <main aria-busy={loading} className="history-main">
        <section className="page-intro history-intro">
          <div>
            <div className="breadcrumb">
              <span>工作台</span>
              <CaretRight size={14} />
              <span className="breadcrumb-current">分析记录</span>
            </div>
            <div className="history-title-line">
              <h1>{lifecycleMeta.title}</h1>
              <span>{total} 条结果</span>
              {filteredFolderName && (
                <button
                  aria-label={`清除目录筛选：${filteredFolderName}`}
                  className="history-scope-filter"
                  onClick={() => onFolderChange("")}
                  type="button"
                >
                  <Folder size={13} />
                  <span>{filteredFolderName}</span>
                  <X size={12} />
                </button>
              )}
            </div>
            <p>{lifecycleMeta.description}</p>
          </div>
        </section>

        <nav className="history-lifecycle-mobile" aria-label="分析记录范围">
          {RECORD_LIFECYCLES.map((item) => (
            <button
              className={lifecycle === item ? "active" : ""}
              key={item}
              onClick={() => onLifecycleChange(item)}
              type="button"
            >
              {RECORD_LIFECYCLE_META[item].label}
              <small>{lifecycleCounts[item] || 0}</small>
            </button>
          ))}
        </nav>

        <section className="history-toolbar" aria-label="分析记录筛选" ref={resultHeadingRef}>
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
          <label className="history-select history-folder-filter">
            <span>目录</span>
            <select value={folderFilter} onChange={(event) => onFolderChange(event.target.value)}>
              <option value="">全部目录</option>
              <option value="unfiled">未分类</option>
              {folders.map((folder) => (
                <option key={folder.id} value={folder.id}>{folder.name}</option>
              ))}
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
          <details className="history-folder-manager">
            <summary aria-label="管理目录"><FolderPlus size={17} />目录管理</summary>
            <div>
              <button className="history-create-folder" onClick={onCreateFolder} type="button">
                <FolderPlus size={15} />新建一级目录
              </button>
              {folders.length > 0 ? folders.map((folder) => (
                <span key={folder.id}>
                  <Folder size={15} />
                  <strong>{folder.name}</strong>
                  <button aria-label={`重命名${folder.name}`} onClick={() => onRenameFolder(folder)} type="button">
                    <PencilSimple size={14} />
                  </button>
                </span>
              )) : <p>还没有自定义目录</p>}
            </div>
          </details>
        </section>

        {error && <div className="inline-error"><X size={17} weight="bold" />{error}</div>}

        {loading && records.length === 0 ? (
          <div className="history-loading" role="status">
            <CircleNotch className="spin" size={20} />
            正在读取工作区记录…
          </div>
        ) : records.length === 0 ? (
          <section className="history-empty">
            <span><FolderOpen size={30} /></span>
            <h2>{query || folderFilter || statusFilter ? "没有匹配的分析记录" : lifecycleMeta.emptyTitle}</h2>
            <p>{query || folderFilter || statusFilter ? "调整搜索或筛选条件后再试。" : lifecycleMeta.emptyDescription}</p>
            {lifecycle === "active" && !query && !folderFilter && !statusFilter && (
              <button className="primary-button compact" onClick={onCreate} type="button">
                <Plus size={16} />新建分析
              </button>
            )}
          </section>
        ) : (
          <>
            <section
              aria-busy={loading}
              className={`record-table ${selectedRecordIds.length ? "has-selection" : ""}`}
            >
              <div className="record-table-head" role="row">
                <label className="record-select-cell">
                  <input
                    aria-label="选择本页记录"
                    checked={allVisibleSelected}
                    onChange={toggleVisibleSelection}
                    ref={selectAllRef}
                    type="checkbox"
                  />
                </label>
                <span className="record-main-head">记录</span>
                <span className="record-status-head">状态</span>
                <span className="record-source-head">来源</span>
                <span className="record-folder-head">目录</span>
                <span className="record-production-head">创作方案</span>
                <span className="record-updated-head">更新时间</span>
                <span className="record-actions-head">操作</span>
              </div>
              <div className="record-table-body">
                {records.map((record) => {
                  const selected = selectedIdSet.has(record.id);
                  const duration = formatDurationBadge(record.duration_seconds);
                  const productionCount = Number(record.production_project_count || 0);
                  const folderLabel = record.folder_id
                    ? folderNames.get(record.folder_id) || "未知目录"
                    : "未分类";
                  const folderDisabled = lifecycle === "trashed" || actionBusy;
                  return (
                    <article
                      aria-selected={selected}
                      className={`record-table-row ${selected ? "selected" : ""}`}
                      key={record.id}
                    >
                      <label className="record-select-cell">
                        <input
                          aria-label={`选择 ${record.name}`}
                          checked={selected}
                          onChange={() => toggleRecordSelection(record.id)}
                          type="checkbox"
                        />
                      </label>
                      <button
                        className="record-list-open"
                        disabled={lifecycle === "trashed"}
                        onClick={() => onOpenRecord(record.id)}
                        type="button"
                      >
                        <RecordThumbnail record={record} />
                        <span>
                          <strong>{record.name}</strong>
                          <small>
                            {duration ? `时长 ${duration}` : "时长未知"}
                            <i className="record-id-divider" />
                            <span className="record-id-meta">ID: {record.id.slice(0, 8)}</span>
                            <span className="record-production-mobile">{productionCount} 个方案</span>
                          </small>
                        </span>
                      </button>
                      <span className={`record-status ${record.status}`}>
                        {recordStatusLabels[record.status] || record.status}
                      </span>
                      <span className="record-source-cell">
                        {sourceTypeLabel(record.source_type)}
                      </span>
                      <label className="record-folder-cell">
                        <Folder aria-hidden="true" size={15} />
                        <span className={`record-folder-select ${folderDisabled ? "disabled" : ""}`}>
                          <span className="record-folder-value" title={folderLabel}>{folderLabel}</span>
                          <CaretDown aria-hidden="true" className="record-folder-caret" size={13} />
                          <select
                            aria-label={`移动 ${record.name} 到目录`}
                            disabled={folderDisabled}
                            onChange={(event) => onMoveRecord(record.id, event.target.value)}
                            value={record.folder_id || ""}
                          >
                            <option value="">未分类</option>
                            {folders.map((folder) => (
                              <option key={folder.id} value={folder.id}>{folder.name}</option>
                            ))}
                          </select>
                        </span>
                      </label>
                      <button
                        aria-label={`打开“${record.name}”的 ${productionCount} 个创作方案`}
                        className={`record-production-cell ${productionCount === 0 ? "empty" : ""}`}
                        disabled={lifecycle === "trashed"}
                        onClick={() => onOpenProductions(record.id)}
                        title={lifecycle === "trashed" ? "恢复记录后可查看创作方案" : undefined}
                        type="button"
                      >
                        <span>{productionCount} 个方案</span>
                      </button>
                      <time className="record-updated-cell" dateTime={record.updated_at}>
                        {formatRecordDate(record.updated_at)}
                      </time>
                      <details className="record-more-menu">
                        <summary aria-label={`${record.name} 的更多操作`}><DotsThree size={20} weight="bold" /></summary>
                        <div>
                          {lifecycle !== "trashed" && (
                            <button disabled={actionBusy} onClick={() => onRenameRecord(record)} type="button">
                              <PencilSimple size={15} />改名
                            </button>
                          )}
                          {batchActions.map((item) => {
                            const ActionIcon = item.action === "archive"
                              ? Archive
                              : ["trash", "purge"].includes(item.action)
                                ? Trash
                                : ArrowClockwise;
                            return (
                              <button
                                className={item.tone === "danger" ? "danger" : ""}
                                disabled={actionBusy}
                                key={item.action}
                                onClick={() => runRecordAction([record.id], item.action)}
                                type="button"
                              >
                                <ActionIcon size={15} />{item.label}
                              </button>
                            );
                          })}
                        </div>
                      </details>
                    </article>
                  );
                })}
              </div>
            </section>

            <nav className="history-pagination" aria-label="分析记录分页">
              <div className="history-page-summary">
                <span>显示 {firstResult}–{lastResult} 条，共 {total} 条</span>
                <label>
                  每页
                  <select
                    aria-label="每页记录数"
                    disabled={loading}
                    onChange={(event) => selectHistoryPageSize(event.target.value)}
                    value={pageSize}
                  >
                    {HISTORY_PAGE_SIZES.map((size) => (
                      <option key={size} value={size}>{size} 条</option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="history-page-controls">
                <button
                  aria-label="上一页"
                  disabled={loading || page <= 1}
                  onClick={() => selectHistoryPage(page - 1)}
                  type="button"
                >
                  <CaretLeft size={15} />
                </button>
                {paginationItems.map((item) => (
                  typeof item === "number" ? (
                    <button
                      aria-current={item === page ? "page" : undefined}
                      className={item === page ? "active" : ""}
                      disabled={loading}
                      key={item}
                      onClick={() => selectHistoryPage(item)}
                      type="button"
                    >
                      {item}
                    </button>
                  ) : (
                    <span aria-hidden="true" className="history-page-ellipsis" key={item}>…</span>
                  )
                ))}
                <button
                  aria-label="下一页"
                  disabled={loading || page >= totalPages}
                  onClick={() => selectHistoryPage(page + 1)}
                  type="button"
                >
                  <CaretRight size={15} />
                </button>
              </div>
            </nav>
            {selectedRecordIds.length > 0 && (
              <div className="history-batch-bar" role="region" aria-label="批量操作">
                <strong>已选择 {selectedRecordIds.length} 条</strong>
                {batchActions.map((item) => {
                  const ActionIcon = item.action === "archive"
                    ? Archive
                    : ["trash", "purge"].includes(item.action)
                      ? Trash
                      : ArrowClockwise;
                  return (
                    <button
                      className={item.tone === "danger" ? "danger" : ""}
                      disabled={actionBusy}
                      key={item.action}
                      onClick={() => runRecordAction(selectedRecordIds, item.action)}
                      type="button"
                    >
                      {actionBusy ? <CircleNotch className="spin" size={16} /> : <ActionIcon size={16} />}
                      {item.label}
                    </button>
                  );
                })}
                <button
                  className="clear-selection"
                  disabled={actionBusy}
                  onClick={() => setSelectedRecordIds([])}
                  type="button"
                >
                  取消选择
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}

function Sidebar({
  activeNav,
  historyLifecycle,
  historyLifecycleCounts,
  onSelect,
  onSelectHistoryLifecycle,
  onOpenSettings,
  settingsOpen,
  historyCount,
}) {
  const activeNavItemRef = useRef(null);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia("(max-width: 820px)").matches) return;
    const frame = window.requestAnimationFrame(() => {
      activeNavItemRef.current?.scrollIntoView({ block: "nearest", inline: "center" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeNav]);

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
            <div className={`nav-group ${item.id === "history" ? "history-nav-group" : ""}`} key={item.id}>
              <button
                className={`nav-item ${activeNav === item.id ? "active" : ""}`}
                onClick={() => onSelect(item.id)}
                ref={activeNav === item.id ? activeNavItemRef : undefined}
                type="button"
              >
                <Icon size={18} weight={activeNav === item.id ? "fill" : "regular"} />
                <span>{item.label}</span>
                {item.id === "history" && <span className="nav-count">{historyCount || 0}</span>}
              </button>
              {item.id === "history" && activeNav === "history" && (
                <div className="history-lifecycle-nav" aria-label="分析记录范围">
                  {RECORD_LIFECYCLES.map((lifecycle) => (
                    <button
                      className={historyLifecycle === lifecycle ? "active" : ""}
                      key={lifecycle}
                      onClick={() => onSelectHistoryLifecycle(lifecycle)}
                      type="button"
                    >
                      <span>{RECORD_LIFECYCLE_META[lifecycle].label}</span>
                      <small>{historyLifecycleCounts[lifecycle] || 0}</small>
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}

        <div className="nav-divider" />
        <p className="nav-section-label">系统</p>
        <button
          className={`nav-item ${activeNav === "platform-connections" ? "active" : ""}`}
          onClick={() => onSelect("platform-connections")}
          ref={activeNav === "platform-connections" ? activeNavItemRef : undefined}
          type="button"
        >
          <LinkSimple
            size={18}
            weight={activeNav === "platform-connections" ? "bold" : "regular"}
          />
          <span>平台连接</span>
        </button>
        <button
          aria-expanded={settingsOpen}
          aria-haspopup="dialog"
          className={`nav-item ${settingsOpen ? "active" : ""}`}
          onClick={onOpenSettings}
          ref={settingsOpen ? activeNavItemRef : undefined}
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
  imageServerSettings,
  videoServerSettings,
  mediaStagingServerSettings,
  mediaStagingValidating,
  mediaStagingValidation,
  imageToolDetecting,
  imageToolDetection,
  codexApplying,
  codexDiscovering,
  codexDiscovery,
  codexNetworkTesting,
  codexNetworkTest,
  codexSandboxTesting,
  codexSandboxTest,
  workspace,
  workspaceDraft,
  workspaceValidation,
  workspaceSaving,
  workspaceError,
  onWorkspaceChange,
  onValidateWorkspace,
  onSwitchWorkspace,
  onChange,
  onApplyLocalCodex,
  onDetectLocalImageTool,
  onDiscoverLocalCodex,
  onTestLocalCodexNetwork,
  onTestLocalCodexSandbox,
  onValidateMediaStaging,
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
  const imageModelOptions = imageServerSettings.models || [];
  const selectedImageModel = imageModelOptions.find(
    (model) => model.alias === draft.imageRemoteModelAlias,
  );
  const selectedImageCapabilities =
    imageToolDetection?.capabilities
    || imageServerSettings.selected_capabilities
    || selectedImageModel?.capabilities;
  const videoModelOptions = videoServerSettings.models || [];
  const selectableVideoModelOptions = videoModelOptions.filter(
    supportsProductionVideoWorkflow,
  );
  const selectedVideoModel = selectableVideoModelOptions.find(
    (model) => model.alias === draft.videoDefaultModelAlias,
  );
  const unavailableVideoModelCount = (
    videoModelOptions.length - selectableVideoModelOptions.length
  );
  const videoResolutions = selectedVideoModel?.capabilities?.supported_resolutions || [];
  const imageCandidateCount = Number(draft.imageDefaultCandidateCount || 2);
  const estimatedImageCost = selectedImageModel
    ? (Number(selectedImageModel.unit_cost_micros || 0) * imageCandidateCount) / 1_000_000
    : null;
  const hasNewKey = Boolean(String(draft.apiKey || "").trim());
  const credentialState = hasNewKey
    ? "pending"
    : serverSettings.api_key_configured || imageServerSettings.api_key_configured
      ? "connected"
      : "missing";
  const credentialTitle = {
    pending: "新 API Key 等待验证",
    connected: "API Key 已配置",
    missing: "尚未配置 API Key",
  }[credentialState];

  function closeIfIdle() {
    if (
      !saving
      && !workspaceSaving
      && !codexApplying
      && !codexDiscovering
      && !codexNetworkTesting
      && !codexSandboxTesting
    ) onClose();
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
                        serverSettings.api_key_configured || imageServerSettings.api_key_configured
                          ? `已配置 ${
                              serverSettings.api_key_hint
                              || imageServerSettings.api_key_hint
                              || ""
                            }；留空沿用`
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
                        : serverSettings.api_key_configured || imageServerSettings.api_key_configured
                          ? `最近验证：${formatValidationTime(serverSettings.last_validated_at)}`
                          : "填写密钥后才能启用真实 VLM 视频分析。"}
                    </p>
                  </div>
                </div>
              </>
            )}
          </section>

          <section className="settings-section image-generation-settings" aria-labelledby="image-generation-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="image-generation-title">分镜图片生成</h3>
                <p>真实候选可以通过国内大模型 API，或符合协议的本机工具生成。</p>
              </div>
              <span className={"image-settings-state " + (imageServerSettings.enabled ? "enabled" : "")}>
                {imageServerSettings.enabled ? "已启用" : "尚未启用"}
              </span>
            </div>

            <div className="image-mode-grid">
              <label className={draft.imageExecutionMode === "remote_api" ? "selected" : ""}>
                <input
                  checked={draft.imageExecutionMode === "remote_api"}
                  disabled={saving}
                  name="image-execution-mode"
                  onChange={() => onChange({ imageExecutionMode: "remote_api" })}
                  type="radio"
                />
                <span><Sparkle size={18} weight="fill" /></span>
                <div>
                  <strong>国内大模型 API</strong>
                  <small>百炼 Qwen Image，按成功生成图片计费</small>
                </div>
              </label>
              <label className={draft.imageExecutionMode === "local_tool" ? "selected" : ""}>
                <input
                  checked={draft.imageExecutionMode === "local_tool"}
                  disabled={saving}
                  name="image-execution-mode"
                  onChange={() => onChange({ imageExecutionMode: "local_tool" })}
                  type="radio"
                />
                <span><Gear size={18} weight="fill" /></span>
                <div>
                  <strong>本机工具 / CLI</strong>
                  <small>通过版本化 JSON 协议调用 imagegen 类工具</small>
                </div>
              </label>
            </div>

            {draft.imageExecutionMode === "remote_api" ? (
              <div className="image-mode-panel">
                <div className="settings-field-grid">
                  <label className="settings-field">
                    <span>图片模型</span>
                    <select
                      disabled={saving}
                      onChange={(event) => onChange({
                        imageRemoteModelAlias: event.target.value,
                      })}
                      value={draft.imageRemoteModelAlias}
                    >
                      {imageModelOptions.map((model) => (
                        <option key={model.alias} value={model.alias}>
                          {model.label}{model.recommended ? "（推荐）" : ""}
                        </option>
                      ))}
                    </select>
                    <small>{selectedImageModel?.description || "正在读取图片模型目录…"}</small>
                  </label>
                  <label className="settings-field">
                    <span>默认候选数量</span>
                    <select
                      disabled={saving}
                      onChange={(event) => onChange({
                        imageDefaultCandidateCount: Number(event.target.value),
                      })}
                      value={draft.imageDefaultCandidateCount}
                    >
                      {[1, 2, 3, 4].map((count) => (
                        <option key={count} value={count}>{count} 张</option>
                      ))}
                    </select>
                    <small>
                      本次预计目录价：
                      {estimatedImageCost == null
                        ? "—"
                        : "¥" + estimatedImageCost.toFixed(2)}
                    </small>
                  </label>
                  <label className="settings-field settings-field-wide">
                    <span>图片服务地址</span>
                    <input
                      disabled={saving}
                      onChange={(event) => onChange({
                        imageRemoteBaseUrl: event.target.value,
                      })}
                      spellCheck="false"
                      type="url"
                      value={draft.imageRemoteBaseUrl}
                    />
                    <small>
                      仅接受百炼官方 HTTPS /api/v1 地址；工作空间 Endpoint 需包含正确区域。
                    </small>
                  </label>
                </div>
                <div className="image-mode-note">
                  <ShieldCheck size={18} weight="fill" />
                  <div>
                    <strong>复用上方百炼 API Key</strong>
                    <p>
                      保存时执行低成本认证校验，不会调用付费图片生成；模型权限在首次出图时确认。
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="image-mode-panel">
                <div
                  className={`codex-auto-card ${
                    codexDiscovery?.can_auto_configure ? "ready" : ""
                  }`}
                >
                  <div className="codex-auto-heading">
                    <span><Sparkle size={19} weight="fill" /></span>
                    <div>
                      <strong>自动发现 Codex + ImageGen</strong>
                      <p>只检测本机安装、登录状态和版本，不会提交提示词或消耗图片额度。</p>
                    </div>
                    <button
                      className="secondary-button compact"
                      disabled={saving || codexApplying || codexDiscovering}
                      onClick={() => onDiscoverLocalCodex()}
                      type="button"
                    >
                      {codexDiscovering
                        ? <CircleNotch className="spin" size={15} />
                        : <ArrowClockwise size={15} />}
                      {codexDiscovering ? "检测中" : "重新检测"}
                    </button>
                  </div>

                  {codexDiscovering && !codexDiscovery ? (
                    <div className="codex-auto-loading">
                      <CircleNotch className="spin" size={16} />
                      正在读取 Codex CLI、ChatGPT 桌面端和 imagegen 技能…
                    </div>
                  ) : codexDiscovery ? (
                    <>
                      <div className="codex-status-grid">
                        <span className={codexDiscovery.codex_found ? "positive" : "warning"}>
                          <strong>Codex CLI</strong>
                          {codexDiscovery.codex_version || "未找到"}
                        </span>
                        <span className={codexDiscovery.auth_status === "authenticated" ? "positive" : "warning"}>
                          <strong>登录状态</strong>
                          {{
                            authenticated: "已登录",
                            not_authenticated: "未登录",
                            unknown: "无法确认",
                          }[codexDiscovery.auth_status] || "无法确认"}
                        </span>
                        <span className={codexDiscovery.imagegen_status === "installed_unverified" ? "positive" : "warning"}>
                          <strong>ImageGen</strong>
                          {codexDiscovery.imagegen_status === "installed_unverified"
                            ? "已安装，待首次出图验证"
                            : "未找到"}
                        </span>
                        <span className={codexDiscovery.desktop_app_found ? "positive" : "neutral"}>
                          <strong>ChatGPT / Codex</strong>
                          {codexDiscovery.desktop_app_found ? "桌面端已安装" : "未检测到桌面端"}
                        </span>
                      </div>

                      <div className="settings-field-grid codex-policy-grid">
                        <label className="settings-field">
                          <span>模型策略</span>
                          <select
                            disabled={saving || codexApplying}
                            onChange={(event) => {
                              const policy = event.target.value;
                              onChange({
                                imageLocalModelPolicy: policy,
                                ...(policy === "latest_flagship"
                                  ? { imageLocalModel: codexDiscovery.recommended_model }
                                  : policy === "balanced"
                                    ? { imageLocalModel: "gpt-5.6-terra" }
                                    : {}),
                              });
                            }}
                            value={draft.imageLocalModelPolicy}
                          >
                            <option value="latest_flagship">始终使用最新旗舰</option>
                            <option value="balanced">均衡模型</option>
                            <option value="pinned">固定指定模型</option>
                          </select>
                          <small>最新旗舰由版本化目录解析，当前为 {codexDiscovery.recommended_model}。</small>
                        </label>
                        <label className="settings-field">
                          <span>推理强度</span>
                          <select
                            disabled={saving || codexApplying}
                            onChange={(event) => onChange({
                              imageLocalReasoningEffort: event.target.value,
                            })}
                            value={draft.imageLocalReasoningEffort}
                          >
                            <option value="xhigh">最高（xhigh）</option>
                            <option value="high">高（high）</option>
                            <option value="medium">中（medium）</option>
                            <option value="low">低（low）</option>
                          </select>
                          <small>最高质量更慢，也可能消耗更多订阅配额。</small>
                        </label>
                        <label className="settings-field settings-field-wide">
                          <span>实际模型</span>
                          <input
                            disabled={
                              saving
                              || codexApplying
                              || draft.imageLocalModelPolicy !== "pinned"
                            }
                            onChange={(event) => onChange({
                              imageLocalModel: event.target.value,
                            })}
                            spellCheck="false"
                            type="text"
                            value={
                              draft.imageLocalModel
                              || (draft.imageLocalModelPolicy === "balanced"
                                ? "gpt-5.6-terra"
                                : codexDiscovery.recommended_model)
                            }
                          />
                          <small>只有“固定指定模型”允许手动编辑；其他策略在保存时自动解析。</small>
                        </label>
                      </div>

                      <div className="codex-proxy-card">
                        <div className="codex-proxy-heading">
                          <div>
                            <strong>命令行网络代理</strong>
                            <p>
                              Windows 系统代理交给 Codex 原生读取；只有手动或纯环境代理才显式注入，
                              避免反复刷新沙箱防火墙。
                            </p>
                          </div>
                          <span>
                            {localProxySourceLabel(
                              codexNetworkTest?.proxy_source
                              || imageServerSettings.local_proxy_source,
                            )}
                            {" · "}
                            {localProxyDeliveryLabel(
                              draft.imageLocalProxyMode === "manual"
                                ? "environment"
                                : draft.imageLocalProxyMode === "disabled"
                                  ? "direct"
                                  : imageServerSettings.local_proxy_delivery,
                            )}
                          </span>
                        </div>
                        <div className="settings-field-grid">
                          <label className="settings-field">
                            <span>代理模式</span>
                            <select
                              disabled={saving || codexApplying || codexNetworkTesting}
                              onChange={(event) => onChange({
                                imageLocalProxyMode: event.target.value,
                              })}
                              value={draft.imageLocalProxyMode}
                            >
                              <option value="system">自动读取 Windows 系统代理（推荐）</option>
                              <option value="manual">手动指定 HTTP 代理</option>
                              <option value="disabled">不使用代理</option>
                            </select>
                            <small>
                              {draft.imageLocalProxyMode === "system"
                                ? imageServerSettings.local_proxy_detected_url
                                  ? `已检测：${imageServerSettings.local_proxy_detected_url}；Windows 系统代理不会重复注入进程环境。`
                                  : "当前未检测到 Windows 或环境变量代理。"
                                : draft.imageLocalProxyMode === "disabled"
                                  ? "Codex 将直接连接 ChatGPT。"
                                  : "仅支持不含账号密码的 HTTP/HTTPS 代理。"}
                            </small>
                          </label>
                          {draft.imageLocalProxyMode === "manual" && (
                            <label className="settings-field">
                              <span>代理地址</span>
                              <input
                                disabled={saving || codexApplying || codexNetworkTesting}
                                onChange={(event) => onChange({
                                  imageLocalProxyUrl: event.target.value,
                                })}
                                placeholder="http://127.0.0.1:10808"
                                spellCheck="false"
                                type="url"
                                value={draft.imageLocalProxyUrl}
                              />
                              <small>示例：http://127.0.0.1:10808</small>
                            </label>
                          )}
                        </div>
                        <div className="codex-proxy-actions">
                          <button
                            className="secondary-button compact"
                            disabled={
                              saving
                              || codexApplying
                              || codexNetworkTesting
                              || (
                                draft.imageLocalProxyMode === "manual"
                                && !String(draft.imageLocalProxyUrl || "").trim()
                              )
                            }
                            onClick={onTestLocalCodexNetwork}
                            type="button"
                          >
                            {codexNetworkTesting
                              ? <CircleNotch className="spin" size={15} />
                              : <ShieldCheck size={15} />}
                            {codexNetworkTesting ? "正在测试" : "测试网络与登录"}
                          </button>
                          <small>只建立 HTTPS 连接并检查本机登录状态，不生成图片。</small>
                        </div>
                        {codexNetworkTest && (
                          <div
                            className={`codex-network-result ${
                              codexNetworkTest.reachable
                              && codexNetworkTest.auth_status === "authenticated"
                                ? "positive"
                                : "warning"
                            }`}
                            role="status"
                          >
                            {codexNetworkTest.reachable
                              && codexNetworkTest.auth_status === "authenticated"
                              ? <CheckCircle size={17} weight="fill" />
                              : <Question size={17} weight="fill" />}
                            <div>
                              <strong>{codexNetworkTest.message}</strong>
                              <small>
                                {codexNetworkTest.effective_proxy_url || "直连"}
                                {` · ${codexNetworkTest.latency_ms} ms`}
                              </small>
                            </div>
                          </div>
                        )}
                      </div>

                      <div className="codex-proxy-card codex-sandbox-card">
                        <div className="codex-proxy-heading">
                          <div>
                            <strong>Windows 沙箱</strong>
                            <p>
                              保存和自动配置前执行一次无模型费用预检；不会生成图片，也不会自动降级。
                            </p>
                          </div>
                          <span>
                            {draft.imageLocalWindowsSandboxMode === "unelevated"
                              ? "兼容隔离"
                              : draft.imageLocalWindowsSandboxMode === "elevated"
                                ? "增强隔离"
                                : "自动选择"}
                          </span>
                        </div>
                        <div className="settings-field-grid">
                          <label className="settings-field settings-field-wide">
                            <span>沙箱模式</span>
                            <select
                              disabled={saving || codexApplying || codexSandboxTesting}
                              onChange={(event) => onChange({
                                imageLocalWindowsSandboxMode: event.target.value,
                              })}
                              value={draft.imageLocalWindowsSandboxMode}
                            >
                              <option value="auto">自动（推荐，优先增强隔离）</option>
                              <option value="elevated">增强模式（elevated）</option>
                              <option value="unelevated">兼容模式（unelevated）</option>
                            </select>
                            <small>
                              仅当自动/增强模式持续出现沙箱辅助程序弹窗时，手动选择兼容模式；
                              兼容模式仍限制文件访问，但网络隔离较弱。
                            </small>
                          </label>
                        </div>
                        <div className="codex-proxy-actions">
                          <button
                            className="secondary-button compact"
                            disabled={
                              saving
                              || codexApplying
                              || codexSandboxTesting
                              || !codexDiscovery.codex_found
                              || (
                                draft.imageLocalProxyMode === "manual"
                                && !String(draft.imageLocalProxyUrl || "").trim()
                              )
                            }
                            onClick={onTestLocalCodexSandbox}
                            type="button"
                          >
                            {codexSandboxTesting
                              ? <CircleNotch className="spin" size={15} />
                              : <ShieldCheck size={15} />}
                            {codexSandboxTesting ? "正在预检" : "无费用预检"}
                          </button>
                          <small>仅启动受限命令验证沙箱，不请求模型、不消耗订阅额度。</small>
                        </div>
                        {codexSandboxTest && (
                          <div
                            className={
                              codexSandboxTest.ready
                                ? "codex-network-result positive"
                                : "codex-network-result warning"
                            }
                            role="status"
                          >
                            {codexSandboxTest.ready
                              ? <CheckCircle size={17} weight="fill" />
                              : <Question size={17} weight="fill" />}
                            <div>
                              <strong>{codexSandboxTest.message}</strong>
                              <small>
                                {localProxyDeliveryLabel(codexSandboxTest.proxy_delivery)}
                                {codexSandboxTest.latency_ms
                                  ? " · " + codexSandboxTest.latency_ms + " ms"
                                  : ""}
                              </small>
                            </div>
                          </div>
                        )}
                      </div>

                      {codexDiscovery.warnings?.length > 0 && (
                        <ul className="codex-warning-list">
                          {codexDiscovery.warnings.map((warning) => (
                            <li key={warning}>{warning}</li>
                          ))}
                        </ul>
                      )}

                      <div className="codex-auto-footer">
                        <small>
                          自动配置会先做无费用沙箱预检，再保存包装器与订阅配额口径；
                          首次生成仍由你手动触发。
                        </small>
                        <button
                          className="primary-button compact"
                          disabled={
                            saving
                            || codexApplying
                            || codexSandboxTesting
                            || !codexDiscovery.can_auto_configure
                            || (
                              draft.imageLocalModelPolicy === "pinned"
                              && !String(draft.imageLocalModel || "").trim()
                            )
                          }
                          onClick={onApplyLocalCodex}
                          type="button"
                        >
                          {codexApplying
                            ? <CircleNotch className="spin" size={15} />
                            : <MagicWand size={15} weight="fill" />}
                          {codexApplying ? "正在配置" : "应用推荐配置"}
                        </button>
                      </div>
                    </>
                  ) : (
                    <div className="codex-auto-empty">
                      尚未读取本机环境。点击“重新检测”后可获得自动配置建议。
                    </div>
                  )}
                </div>

                <div className="local-tool-manual-label">
                  <strong>高级手动配置</strong>
                  <small>仅在接入其他 CLI 或自定义包装器时修改以下字段。</small>
                </div>
                <div className="settings-field-grid">
                  <label className="settings-field settings-field-wide">
                    <span>可执行文件绝对路径</span>
                    <input
                      disabled={saving || imageToolDetecting}
                      onChange={(event) => {
                        onChange({ imageLocalExecutablePath: event.target.value });
                      }}
                      placeholder="例如 C:\Tools\viral-imagegen.exe"
                      spellCheck="false"
                      type="text"
                      value={draft.imageLocalExecutablePath}
                    />
                    <small>直接启动可执行文件，不经过 shell；路径和工具版本会在本机检测。</small>
                  </label>
                  <label className="settings-field settings-field-wide">
                    <span>固定参数（每行一项）</span>
                    <textarea
                      disabled={saving || imageToolDetecting}
                      onChange={(event) => onChange({
                        imageLocalFixedArgs: event.target.value,
                      })}
                      placeholder={"例如包装脚本路径\n--profile\nproduction"}
                      rows={3}
                      spellCheck="false"
                      value={draft.imageLocalFixedArgs}
                    />
                    <small>参数按数组传递，不支持命令拼接；不要在参数里填写密钥。</small>
                  </label>
                  <label className="settings-field">
                    <span>超时</span>
                    <select
                      disabled={saving || imageToolDetecting}
                      onChange={(event) => onChange({
                        imageLocalTimeoutSeconds: Number(event.target.value),
                      })}
                      value={draft.imageLocalTimeoutSeconds}
                    >
                      <option value={120}>2 分钟</option>
                      <option value={300}>5 分钟</option>
                      <option value={600}>10 分钟</option>
                      <option value={1200}>20 分钟</option>
                    </select>
                  </label>
                  <label className="settings-field">
                    <span>并发上限</span>
                    <select
                      disabled={saving || imageToolDetecting}
                      onChange={(event) => onChange({
                        imageLocalConcurrency: Number(event.target.value),
                      })}
                      value={draft.imageLocalConcurrency}
                    >
                      {[1, 2, 3, 4].map((count) => (
                        <option key={count} value={count}>{count}</option>
                      ))}
                    </select>
                  </label>
                  <label className="settings-field">
                    <span>成本口径</span>
                    <select
                      disabled={saving || imageToolDetecting}
                      onChange={(event) => onChange({
                        imageLocalCostSource: event.target.value,
                      })}
                      value={draft.imageLocalCostSource}
                    >
                      <option value="unknown">未知成本</option>
                      <option value="subscription_quota">ChatGPT / Codex 订阅配额</option>
                      <option value="configured_rate">按配置费率</option>
                      <option value="unmetered">确认不计费</option>
                    </select>
                    <small>调用云服务但不返回用量的 CLI 应选择未知成本。</small>
                  </label>
                  {draft.imageLocalCostSource === "configured_rate" && (
                    <label className="settings-field">
                      <span>单张成本（元）</span>
                      <input
                        disabled={saving || imageToolDetecting}
                        min="0"
                        onChange={(event) => onChange({
                          imageLocalUnitCostYuan: event.target.value,
                        })}
                        step="0.0001"
                        type="number"
                        value={draft.imageLocalUnitCostYuan}
                      />
                    </label>
                  )}
                </div>
                <div className="local-tool-actions">
                  <button
                    className="secondary-button compact"
                    disabled={
                      saving
                      || imageToolDetecting
                      || !String(draft.imageLocalExecutablePath || "").trim()
                    }
                    onClick={onDetectLocalImageTool}
                    type="button"
                  >
                    {imageToolDetecting
                      ? <CircleNotch className="spin" size={15} />
                      : <ShieldCheck size={15} />}
                    {imageToolDetecting ? "正在检测" : "检测工具"}
                  </button>
                  {(imageToolDetection || imageServerSettings.local_tool_id) && (
                    <div className="local-tool-result">
                      <CheckCircle size={17} weight="fill" />
                      <span>
                        <strong>
                          {imageToolDetection?.tool_id || imageServerSettings.local_tool_id}
                        </strong>
                        {" · "}
                        {imageToolDetection?.tool_version || imageServerSettings.local_tool_version}
                      </span>
                    </div>
                  )}
                </div>
                {draft.imageLocalCostSource === "unknown" && (
                  <div className="image-cost-warning">
                    <Question size={17} weight="fill" />
                    每次生成前必须人工确认接受未知成本，不会把未知成本记为 ¥0。
                  </div>
                )}
                {draft.imageLocalCostSource === "subscription_quota" && (
                  <div className="image-subscription-note">
                    <Sparkle size={17} weight="fill" />
                    使用 ChatGPT / Codex 订阅配额；金额不可核算，因此不显示为 ¥0，也无需每次确认未知成本。
                  </div>
                )}
              </div>
            )}

            {selectedImageCapabilities && (
              <div className="image-capability-row">
                <span>图生图</span>
                <span>最多 {selectedImageCapabilities.max_reference_images} 张参考图</span>
                <span>最多 {selectedImageCapabilities.max_candidates} 个候选</span>
                <span>
                  上限 {selectedImageCapabilities.maximum_width} ×
                  {selectedImageCapabilities.maximum_height}
                </span>
              </div>
            )}

            <label className="image-semantic-quality-option">
              <input
                checked={Boolean(draft.imageSemanticQualityEnabled)}
                disabled={saving}
                onChange={(event) => onChange({
                  imageSemanticQualityEnabled: event.target.checked,
                })}
                type="checkbox"
              />
              <span><ShieldCheck size={18} weight="fill" /></span>
              <div>
                <strong>生成后使用 VLM 做语义质检（可选）</strong>
                <small>
                  逐张核对人物、产品、服装、场景和异常文字，并单独记录 Token 与费用；
                  结果只作为人工审核证据，不会自动采用或淘汰候选。
                </small>
              </div>
            </label>
          </section>

          <section className="settings-section video-generation-settings" aria-labelledby="video-generation-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="video-generation-title">分段视频生成</h3>
                <p>配置国内远程 API；默认模型可在每个分镜生成前临时切换。</p>
              </div>
              <span className={"image-settings-state " + (draft.videoEnabled ? "enabled" : "")}>
                {draft.videoEnabled ? "已启用" : "已停用"}
              </span>
            </div>

            <label className="semantic-quality-toggle">
              <input
                checked={Boolean(draft.videoEnabled)}
                disabled={saving}
                onChange={(event) => onChange({ videoEnabled: event.target.checked })}
                type="checkbox"
              />
              <span><Check size={14} weight="bold" /></span>
              <div>
                <strong>启用真实分段视频生成</strong>
                <small>未配置对应 API Key 时仍可保存，但生成按钮会明确提示缺少配置。</small>
              </div>
            </label>

            <div className="settings-field-grid">
              <label className="settings-field">
                <span>默认视频模型</span>
                <select
                  disabled={saving || !draft.videoEnabled}
                  onChange={(event) => {
                    const model = videoModelOptions.find(
                      (item) => item.alias === event.target.value,
                    );
                    onChange({
                      videoDefaultModelAlias: event.target.value,
                      videoDefaultResolution: preferredVideoResolution(
                        model,
                        draft.videoDefaultResolution,
                      ),
                    });
                  }}
                  value={draft.videoDefaultModelAlias}
                >
                  {selectableVideoModelOptions.length === 0 && (
                    <option value="">暂无支持有序多图的视频模型</option>
                  )}
                  {selectableVideoModelOptions.map((model) => (
                    <option key={model.alias} value={model.alias}>
                      {model.label}{model.recommended ? "（推荐）" : ""}
                    </option>
                  ))}
                </select>
                <small>
                  {selectedVideoModel?.description || "正在读取视频模型目录…"}
                  {unavailableVideoModelCount > 0
                    ? `；另有 ${unavailableVideoModelCount} 个模型因未验证有序多图能力而不可选`
                    : ""}
                </small>
              </label>
              <label className="settings-field">
                <span>默认分辨率</span>
                <select
                  disabled={saving || !draft.videoEnabled}
                  onChange={(event) => onChange({ videoDefaultResolution: event.target.value })}
                  value={draft.videoDefaultResolution}
                >
                  {videoResolutions.map((resolution) => (
                    <option key={resolution} value={resolution}>{resolution}</option>
                  ))}
                </select>
                <small>分辨率直接影响计费；每次生成前会再次显示预计费用。</small>
              </label>
            </div>

            <MediaStagingSettingsPanel
              draft={draft}
              onChange={onChange}
              onValidate={onValidateMediaStaging}
              saving={saving}
              serverSettings={mediaStagingServerSettings}
              validating={mediaStagingValidating}
              validation={mediaStagingValidation}
            />

            {draft.mediaStagingProvider === "local_proxy" && (
            <section className="managed-asset-settings-panel" aria-label="本机反向代理媒体暂存">
              <div className="settings-section-heading compact-heading">
                <div>
                  <strong>本机反向代理（高级备用）</strong>
                  <p>
                    仅在不使用 OSS 时，通过自己的公网 ViralDNA API 临时提供媒体。
                  </p>
                </div>
                <span className={`image-settings-state ${videoServerSettings.public_media_transport_ready ? "enabled" : ""}`}>
                  {videoServerSettings.public_media_transport_ready ? "已配置" : "未配置"}
                </span>
              </div>
              <div className="settings-field-grid">
                <label className="settings-field settings-field-wide">
                  <span>ViralDNA 公网 API 地址</span>
                  <input
                    disabled={saving}
                    onChange={(event) => onChange({
                      videoPublicMediaBaseUrl: event.target.value,
                    })}
                    placeholder="https://viraldna.example.com"
                    spellCheck="false"
                    type="url"
                    value={draft.videoPublicMediaBaseUrl || ""}
                  />
                  <small>
                    填写能从公网访问当前 ViralDNA API 的 HTTPS 域名或反向代理地址；
                    不接受 localhost、内网 IP 或 HTTP。需要深度视频的模型在未配置时会明确阻止生成。
                  </small>
                </label>
                <label className="settings-field">
                  <span>链接有效期（秒）</span>
                  <input
                    disabled={saving}
                    max="604800"
                    min="900"
                    onChange={(event) => onChange({
                      videoPublicMediaTtlSeconds: event.target.value,
                    })}
                    step="300"
                    type="number"
                    value={draft.videoPublicMediaTtlSeconds || 3600}
                  />
                  <small>建议保持 3600 秒；只读地址到期后自动失效。</small>
                </label>
              </div>
              <small className="managed-asset-settings-note">
                {videoServerSettings.public_media_validation_message
                  || "配置后，生成任务会把已启用的全场景深度视频暂存为短期签名地址。"}
              </small>
            </section>
            )}

            <div className="video-provider-settings-list">
              {(videoServerSettings.providers || []).map((provider) => (
                <article className="image-mode-panel" key={provider.provider}>
                  <div className="settings-section-heading compact-heading">
                    <div>
                      <strong>{provider.label}</strong>
                      <p>
                        {provider.api_key_configured
                          ? `已保存 ${provider.api_key_hint || "API Key"} · ${provider.validation_status === "valid" ? "已校验" : "待重新校验"}`
                          : "未配置；可留空，使用该 Provider 时再填写。"}
                      </p>
                    </div>
                    <span className={"image-settings-state " + (provider.api_key_configured ? "enabled" : "")}>
                      {provider.api_key_configured ? "已连接" : "未配置"}
                    </span>
                  </div>
                  <div className="settings-field-grid">
                    <label className="settings-field">
                      <span>API Key</span>
                      <input
                        autoComplete="off"
                        disabled={saving}
                        onChange={(event) => onChange({
                          videoProviderKeys: {
                            ...(draft.videoProviderKeys || {}),
                            [provider.provider]: event.target.value,
                          },
                        })}
                        placeholder={provider.api_key_hint || "留空表示不修改"}
                        type="password"
                        value={draft.videoProviderKeys?.[provider.provider] || ""}
                      />
                      <small>
                        {provider.provider === "minimax"
                          ? "请使用“接口密钥”创建的按量付费 Key；Token Plan Key 与视频接口不互通。"
                          : "仅当填写新 Key 时，保存操作才会联网校验该 Provider。"}
                      </small>
                    </label>
                    <label className="settings-field">
                      <span>官方服务地址</span>
                      <input
                        disabled={saving}
                        onChange={(event) => onChange({
                          videoProviderBaseUrls: {
                            ...(draft.videoProviderBaseUrls || {}),
                            [provider.provider]: event.target.value,
                          },
                        })}
                        spellCheck="false"
                        type="url"
                        value={draft.videoProviderBaseUrls?.[provider.provider] || provider.base_url}
                      />
                      <small>
                        {provider.provider === "minimax"
                          ? "国内使用 api.minimaxi.com，国际使用 api.minimax.io；Key 不写入项目快照。"
                          : "只接受该 Provider 的官方 HTTPS 域名，Key 不写入项目快照。"}
                      </small>
                    </label>
                  </div>
                  {provider.managed_asset_catalog_supported && (
                    <section className="managed-asset-settings-panel" aria-label="火山方舟托管资产目录">
                      <div className="settings-section-heading compact-heading">
                        <div>
                          <strong>托管虚拟资产目录</strong>
                          <p>
                            {provider.managed_asset_credentials_configured
                              ? `${provider.managed_asset_access_key_hint || "AK 已保存"} · ${provider.managed_asset_validation_status === "valid" ? "已校验" : "待校验"}`
                              : "视频 API Key 不能读取目录；请另行配置火山 Access Key / Secret Key。"}
                          </p>
                        </div>
                        <span className={`image-settings-state ${provider.managed_asset_validation_status === "valid" ? "enabled" : ""}`}>
                          {provider.managed_asset_validation_status === "valid" ? "目录已连接" : "目录未连接"}
                        </span>
                      </div>
                      <div className="settings-field-grid">
                        <label className="settings-field">
                          <span>Access Key</span>
                          <input
                            autoComplete="off"
                            disabled={saving}
                            onChange={(event) => onChange({
                              videoManagedAssetAccessKey: event.target.value,
                            })}
                            placeholder={provider.managed_asset_access_key_hint || "火山账号 Access Key"}
                            type="password"
                            value={draft.videoManagedAssetAccessKey || ""}
                          />
                        </label>
                        <label className="settings-field">
                          <span>Secret Key</span>
                          <input
                            autoComplete="off"
                            disabled={saving}
                            onChange={(event) => onChange({
                              videoManagedAssetSecretKey: event.target.value,
                            })}
                            placeholder={provider.managed_asset_credentials_configured ? "留空表示不修改" : "火山账号 Secret Key"}
                            type="password"
                            value={draft.videoManagedAssetSecretKey || ""}
                          />
                        </label>
                        <label className="settings-field">
                          <span>资产区域</span>
                          <select
                            disabled={saving}
                            onChange={(event) => onChange({
                              videoManagedAssetRegion: event.target.value,
                            })}
                            value={draft.videoManagedAssetRegion || "cn-beijing"}
                          >
                            <option value="cn-beijing">华北（北京）</option>
                            <option value="cn-shanghai">华东（上海）</option>
                          </select>
                        </label>
                        <label className="settings-field">
                          <span>ProjectName</span>
                          <input
                            disabled={saving}
                            onChange={(event) => onChange({
                              videoManagedAssetProjectName: event.target.value,
                            })}
                            placeholder="default"
                            spellCheck="false"
                            value={draft.videoManagedAssetProjectName || "default"}
                          />
                        </label>
                      </div>
                      <small className="managed-asset-settings-note">
                        保存时会调用官方目录接口校验 AK/SK。IAM 需具备 ark:*Asset* 权限；ProjectName 必须与视频推理 API Key 一致。目录资产将在分镜中可视化选择，不需要手动输入资产 ID。
                      </small>
                    </section>
                  )}
                </article>
              ))}
            </div>

            <div className="image-mode-note">
              <ShieldCheck size={18} weight="fill" />
              <div>
                <strong>费用与余额保护</strong>
                <p>生成前显示目录价；Provider 返回余额不足时会标记任务失败并提示充值，不会显示为 ¥0。</p>
              </div>
            </div>
          </section>

          <DepthGenerationSettings request={apiRequest} />

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
              <p>保存时只发起最小文本认证请求，不执行付费图片生成；任一校验失败都不会覆盖图片生成配置。</p>
            </div>
          </section>

          {error && <div className="settings-error" role="alert">{error}</div>}
        </div>

        <footer className="settings-footer">
          <button className="text-button" disabled={saving || workspaceSaving || codexApplying || codexDiscovering} onClick={onReset} type="button">
            恢复推荐值
          </button>
          <span />
          <button className="secondary-button compact" disabled={saving || workspaceSaving || codexApplying || codexDiscovering} onClick={closeIfIdle} type="button">
            取消
          </button>
          <button
            className="primary-button compact"
            disabled={loading || saving || workspaceSaving || codexApplying || codexDiscovering}
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

function Topbar({
  assetMode = false,
  focusMode = false,
  hideCreate = false,
  notificationOpen = false,
  notificationUnreadCount = 0,
  onCreate,
  onSearch,
  onToggleNotifications,
  searchValue,
}) {
  const primaryActionsHidden = assetMode || focusMode;
  return (
    <header className={`topbar ${assetMode ? "asset-mode" : ""} ${focusMode ? "focus-mode" : ""}`}>
      {!primaryActionsHidden && (
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
      )}
      <div className="topbar-actions">
        <button
          aria-expanded={notificationOpen}
          aria-label={notificationUnreadCount ? `通知，${notificationUnreadCount} 条未读` : "通知"}
          className={`icon-button notification-bell ${notificationOpen ? "active" : ""}`}
          onClick={onToggleNotifications}
          type="button"
        >
          <Bell size={19} />
          {notificationUnreadCount > 0 && (
            <span className="notification-badge">
              {notificationUnreadCount > 9 ? "9+" : notificationUnreadCount}
            </span>
          )}
        </button>
        <button className="icon-button" type="button" aria-label="帮助">
          <Question size={19} />
        </button>
        {!primaryActionsHidden && !hideCreate && (
          <button className="primary-button compact" type="button" onClick={onCreate}>
            <Plus size={17} weight="bold" />
            新建分析
          </button>
        )}
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
  errorCode,
  errorPlatform,
  platformConnections,
  onConfigurePlatform,
  onRetry,
  onStart,
}, ref) {
  const detectedPlatform = sourceMode === "link" ? detectPlatformFromUrl(url) : null;
  const activePlatform = errorPlatform || detectedPlatform;
  const connection = findPlatformConnection(platformConnections, detectedPlatform);
  const health = connectionHealthMeta(connection);
  const connectionEnabled = connection?.configured
    && connection.usage_strategy !== "disabled"
    && health.usable;
  const credentialError = Boolean(error && isCredentialAnalysisError(errorCode));

  return (
    <section className="import-card" id="new-analysis" ref={ref}>
      <div className="card-heading">
        <div>
          <span className="eyebrow">新建任务</span>
          <h2>导入一个短视频</h2>
          <p>支持本地文件，以及来自{SUPPORTED_PLATFORM_NAMES}的公开视频链接。</p>
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
              placeholder="粘贴公开视频分享链接"
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
          {detectedPlatform && (
            <div className={`link-platform-status ${connectionEnabled ? "ready" : "attention"}`}>
              <PlatformBrandLogo
                className="link-platform-mark"
                platform={detectedPlatform}
              />
              <span>
                <strong>{platformLabel(detectedPlatform)}</strong>
                <small>
                  {connectionEnabled
                    ? `${health.label} · 平台要求登录时自动使用`
                    : connection?.configured
                      ? `${health.label} · 请更新登录状态`
                      : "未配置登录状态；公开链接仍会先匿名采集"}
                </small>
              </span>
              <button onClick={() => onConfigurePlatform(detectedPlatform)} type="button">
                {connection?.configured ? "更新连接" : "配置平台"}
              </button>
            </div>
          )}
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

      {credentialError ? (
        <div className="credential-action-error" role="alert">
          <span className="credential-error-icon"><LinkSimple size={18} /></span>
          <div>
            <strong>{activePlatform ? `${platformLabel(activePlatform)}需要更新登录状态` : "平台需要登录状态"}</strong>
            <p>{error}</p>
          </div>
          <div className="credential-error-actions">
            <button
              className="secondary-button compact"
              onClick={() => onConfigurePlatform(activePlatform)}
              type="button"
            >
              配置{activePlatform ? platformLabel(activePlatform) : "平台"}
            </button>
            <button className="primary-button compact" disabled={submitting} onClick={onRetry} type="button">
              {submitting ? <CircleNotch className="spin" size={16} /> : <ArrowClockwise size={16} />}
              更新后重试
            </button>
          </div>
        </div>
      ) : error && (
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
        <span style={{ transform: `scaleX(${analysis.progress / 100})` }} />
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

function RecordBreadcrumb({ items, onNavigate }) {
  return (
    <nav className="record-breadcrumb" aria-label="面包屑">
      <ol>
        {items.map((item, index) => (
          <li key={item.id}>
            {index > 0 && <CaretRight aria-hidden="true" size={14} />}
            {item.current ? (
              <span
                aria-current="page"
                className={item.id === "project" ? "project-name" : ""}
                title={item.id === "project" ? item.label : undefined}
              >
                {item.label}
              </span>
            ) : (
              <button onClick={() => onNavigate(item.id)} type="button">
                {item.label}
              </button>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

function RecordWorkspaceTabs({ active, count, onChange }) {
  return (
    <div className="record-workspace-tabs" role="tablist" aria-label="记录工作区">
      <button
        aria-selected={active === "analysis"}
        className={active === "analysis" ? "active" : ""}
        onClick={() => onChange("analysis")}
        role="tab"
        type="button"
      >
        <ChartBar size={17} weight={active === "analysis" ? "fill" : "regular"} />
        分析报告
      </button>
      <button
        aria-selected={active === "production"}
        className={active === "production" ? "active" : ""}
        onClick={() => onChange("production")}
        role="tab"
        type="button"
      >
        <MagicWand size={17} weight={active === "production" ? "fill" : "regular"} />
        创作方案
        <small>{count}</small>
      </button>
    </div>
  );
}

function ReportHeader({
  video,
  report,
  onDownload,
  onRestart,
  analysisVersions,
  activeAnalysisId,
  onVersionChange,
  showActions = true,
}) {
  const isMediaEvidence = report.analysis_mode === "media_evidence";
  const isModel = report.analysis_mode === "model";
  const segmentation = report.media_evidence?.segmentation;
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
            {isModel && (
              <span className="model-badge">
                {segmentation?.verified_by_model ? "混合分镜 + VLM 分析" : "VLM 逐镜头分析"}
              </span>
            )}
          </div>
          {isMediaEvidence ? (
            <p>{report.shots.length} 个镜头 · 媒体证据已生成</p>
          ) : isModel ? (
            <p>{report.shots.length} 个镜头 · 分析完成</p>
          ) : (
            <p>{report.shots.length} 个镜头 · {report.entities.length} 个可替换元素</p>
          )}
        </div>
      </div>
      {showActions && (
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
      )}
    </div>
  );
}

function ReportTabs({ active, onChange, mode }) {
  const visibleTabs =
    mode === "media_evidence"
      ? reportTabs.filter((tab) => ["overview", "shots"].includes(tab.id))
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

function VideoPlayer({
  src,
  videoRef,
  fallbackDuration,
  downloadUrl,
  mediaWidth,
  mediaHeight,
  aspectRatio,
  posterUrl,
}) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(fallbackDuration || 0);
  const [loadError, setLoadError] = useState(false);
  const sourceOrientation = useMemo(
    () => inferVideoOrientation({ width: mediaWidth, height: mediaHeight, aspectRatio }),
    [aspectRatio, mediaHeight, mediaWidth],
  );
  const [orientation, setOrientation] = useState(sourceOrientation);
  const [posterFailed, setPosterFailed] = useState(false);

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
    setOrientation(sourceOrientation);
    setPosterFailed(false);
  }, [fallbackDuration, sourceOrientation, src, videoRef]);

  function syncDuration(player) {
    if (Number.isFinite(player.duration) && player.duration > 0) {
      setDuration(player.duration);
    }
  }

  function handleLoadedMetadata(player) {
    syncDuration(player);
    setOrientation(
      inferVideoOrientation({
        width: player.videoWidth,
        height: player.videoHeight,
        aspectRatio,
      }),
    );
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
  const hasPoster = Boolean(posterUrl) && !posterFailed;
  const stageClassName = [
    "video-stage",
    "video-stage-" + orientation,
    hasPoster ? "has-poster" : "no-poster",
  ].join(" ");

  return (
    <div className="video-player">
      <div className={stageClassName} data-video-orientation={orientation}>
        {hasPoster && (
          <>
            <img
              alt=""
              aria-hidden="true"
              className="video-stage-ambient"
              decoding="async"
              draggable="false"
              onError={() => setPosterFailed(true)}
              src={posterUrl}
            />
            <span aria-hidden="true" className="video-stage-tint" />
          </>
        )}
        <video
          ref={videoRef}
          src={src}
          poster={hasPoster ? posterUrl : undefined}
          playsInline
          preload="metadata"
          onClick={togglePlayback}
          onLoadedMetadata={(event) => handleLoadedMetadata(event.currentTarget)}
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
  const showNarrativeStructure = hasReportableNarrativeStructure(
    overview.narrative_structure,
  );
  const playbackUrl =
    filePreview ||
    (mediaAvailable
      ? resolveApiUrl(`/videos/${report.video_id}/media`)
      : resolveArtifactUrl(evidence?.proxy_url));
  const downloadUrl = mediaAvailable
    ? resolveApiUrl(`/videos/${report.video_id}/download`)
    : "";
  const posterPath =
    report.shots?.find((shot) => shot.keyframe_url)?.keyframe_url ||
    evidence?.shots?.find((shot) => shot.keyframe_url)?.keyframe_url;
  const posterUrl = posterPath ? resolveArtifactUrl(posterPath) : "";
  return (
    <div className="overview-grid">
      <div className="overview-primary">
        {playbackUrl ? (
          <VideoPlayer
            src={playbackUrl}
            videoRef={videoRef}
            fallbackDuration={overview.duration_seconds}
            downloadUrl={downloadUrl}
            mediaWidth={metadata?.width}
            mediaHeight={metadata?.height}
            aspectRatio={metadata?.aspect_ratio || overview.aspect_ratio}
            posterUrl={posterUrl}
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

        <div className="section-block overview-media-summary">
          <h3>原视频与内容结构</h3>
          <div className="tag-row">
            <span>{overview.content_type}</span>
            <span>{overview.aspect_ratio}</span>
            <span>{overview.visual_style.split("、")[0]}</span>
          </div>
        </div>

        {showNarrativeStructure && (
          <div className="structure-strip">
            {overview.narrative_structure.split("→").map((part, index, parts) => (
              <div key={part.trim()}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{part.trim()}</strong>
                {index < parts.length - 1 && <CaretRight size={15} />}
              </div>
            ))}
          </div>
        )}
      </div>

      <aside className="overview-sidebar">
        {!isMediaEvidence && !isModel && (
          <div className="score-card">
            <span className="eyebrow">内容爆点潜力</span>
            <div className="score-value">
              <strong>{overview.viral_potential_score}</strong>
              <span>/100</span>
            </div>
            <div className="score-track">
              <span style={{ transform: `scaleX(${overview.viral_potential_score / 100})` }} />
            </div>
            <p>基于视频内容结构的启发式评分，不代表真实平台播放表现。</p>
          </div>
        )}
        <dl className="overview-facts overview-core-facts">
          <div>
            <dt>时长</dt>
            <dd>{overview.duration_seconds.toFixed(1)} 秒</dd>
          </div>
          <div>
            <dt>镜头</dt>
            <dd>{report.shots.length} 个</dd>
          </div>
          {!isMediaEvidence && !isModel && (
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
        {(isMediaEvidence || isModel) ? (
          <details className="overview-technical-details">
            <summary>分析详情<CaretDown size={15} /></summary>
            <dl className="overview-facts">
              <div><dt>画面</dt><dd>{metadata?.width} × {metadata?.height}</dd></div>
              <div><dt>编码与帧率</dt><dd>{metadata?.video_codec?.toUpperCase() || "—"} · {metadata?.fps?.toFixed(2) || "—"} FPS</dd></div>
              <div><dt>模型调用</dt><dd>{modelCost?.run_count || 0} 次</dd></div>
              <div><dt>实测成本</dt><dd>{formatCost(modelCost?.measured_cost_micros)}</dd></div>
            </dl>
            <div className="audience-card">
            {isMediaEvidence ? <>
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
            </> : <>
              <p>
                已结合 {timeline?.transcript_segments?.length || 0} 条 ASR、
                {timeline?.subtitle_cues?.length || 0} 条独立字幕和
                {timeline?.ocr_observations?.length || 0} 条 OCR 证据完成逐镜头理解。
                全局实体归并与爆点推理尚未执行。
              </p>
              {report.model_warnings?.map((warning) => (
                <p className="model-warning" key={warning}>{warning}</p>
              ))}
            </>}
          {metadata?.sha256 && (
            <code className="media-hash">SHA-256 {metadata.sha256.slice(0, 12)}…</code>
          )}
            </div>
          </details>
        ) : <div className="audience-card"><span className="eyebrow">受众推断</span><p>{overview.audience_inference}</p></div>}
        <button className="secondary-button full" type="button" onClick={onOpenShots}>
          {isMediaEvidence ? "查看真实分镜证据" : isModel ? "查看 VLM 分镜事实" : "查看逐镜头拆解"}
          <CaretRight size={16} />
        </button>
      </aside>
    </div>
  );
}

function ShotsTab({ shots, segmentation, activeShotId, onSelect, onCopy, analysisMode }) {
  const activeShot = shots.find((shot) => shot.id === activeShotId) || shots[0];
  const isMediaEvidence = analysisMode === "media_evidence";
  const hasHybridSegmentation = Boolean(segmentation);
  const segmentationVerified = Boolean(segmentation?.verified_by_model);
  const hasFourFrameEvidence = segmentation?.detector_version?.endsWith("-v3");
  return (
    <div className="shots-layout">
      <div className="shot-list">
        <div className="shot-list-header">
          <span>分镜时间线</span>
          <div className="shot-list-meta">
            <small>{shots.length} 个镜头</small>
            {hasHybridSegmentation && (
              <span
                className={`segmentation-status ${segmentationVerified ? "verified" : "fallback"}`}
                title={segmentation?.fallback_reason || segmentation?.model_summary || ""}
              >
                {segmentationVerified ? "程序候选 + VLM 确认" : "程序边界 · VLM 已降级"}
              </span>
            )}
          </div>
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
                {formatTime(activeShot.start_seconds)} — {formatTime(activeShot.end_seconds)} · {isMediaEvidence ? "真实时间边界" : `内容置信度 ${Math.round(activeShot.confidence * 100)}%`}
                {hasHybridSegmentation && ` · ${formatBoundaryMethod(activeShot.boundary_method)}`}
                {activeShot.boundary_confidence != null && ` ${Math.round(activeShot.boundary_confidence * 100)}%`}
              </p>
            </div>
          </div>

          {hasHybridSegmentation && (
            <details className="segmentation-evidence">
              <summary>
                查看边界候选证据
                <span>{segmentation.candidate_count} 个候选 · 最终 {segmentation.final_shot_count} 个镜头</span>
              </summary>
              {hasFourFrameEvidence && (
                <p className="segmentation-evidence-guide">
                  每张候选图从左到右：远前、近前｜近后、远后；中间白线为候选时刻。
                </p>
              )}
              <div className="segmentation-candidate-grid">
                {segmentation.candidates.map((candidate) => (
                  <article
                    className={`segmentation-candidate ${segmentation.selected_candidate_ids?.includes(candidate.id) ? "selected" : ""}`}
                    key={candidate.id}
                  >
                    {candidate.comparison_image_url && (
                      <img
                        className={hasFourFrameEvidence ? "micro-timeline" : ""}
                        src={resolveArtifactUrl(candidate.comparison_image_url)}
                        alt={
                          hasFourFrameEvidence
                            ? `${candidate.id} 边界四帧微时间线`
                            : `${candidate.id} 边界前后对比`
                        }
                      />
                    )}
                    <div>
                      <strong>{formatTime(candidate.timestamp_seconds)}</strong>
                      <span>
                        {candidate.hard_boundary
                          ? "硬切锁定"
                          : candidate.selected_by_model
                            ? "VLM 已确认"
                            : candidate.model_consistency_adjusted
                              ? "一致性校验已合并"
                              : candidate.model_reason
                                ? "VLM 已拒绝"
                                : "候选已合并"}
                      </span>
                      <small>{candidate.model_reason || candidate.methods.join(" / ")}</small>
                    </div>
                  </article>
                ))}
              </div>
            </details>
          )}

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
                {hasHybridSegmentation && (
                  <Fact
                    label="边界来源"
                    value={`${formatBoundaryMethod(activeShot.boundary_method)}${activeShot.source_candidate_ids?.length ? ` · ${activeShot.source_candidate_ids.join(", ")}` : ""}`}
                  />
                )}
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
                <Fact label="转场" value={activeShot.transition} />
              </div>
              <details className="shot-secondary-facts">
                <summary>查看构图、灯光、色彩与声音<CaretDown size={16} /></summary>
                <div className="shot-facts-grid">
                  <Fact label="构图" value={activeShot.composition} />
                  <Fact label="灯光" value={activeShot.lighting} />
                  <Fact label="色彩" value={activeShot.color} />
                  <Fact label="声音" value={activeShot.audio} />
                  {hasHybridSegmentation && <Fact label="分镜边界" value={`${formatBoundaryMethod(activeShot.boundary_method)}${activeShot.semantic_group ? ` · ${activeShot.semantic_group}` : ""}`} />}
                </div>
              </details>
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

              <details className="prompt-box shot-prompt-disclosure">
                <summary><span><MagicWand size={17} weight="fill" /><strong>逐镜头复刻提示词</strong></span><CaretDown size={16} /></summary>
                <PromptSectionView prompt={activeShot.prompt} />
                <button type="button" onClick={() => onCopy(activeShot.prompt, "镜头提示词已复制")}><Copy size={16} />复制提示词</button>
              </details>
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
