export const PLATFORM_DEFINITIONS = Object.freeze([
  Object.freeze({
    id: "douyin",
    label: "抖音",
    domains: Object.freeze(["douyin.com", "iesdouyin.com"]),
  }),
  Object.freeze({
    id: "xiaohongshu",
    label: "小红书",
    domains: Object.freeze(["xiaohongshu.com", "xhslink.com", "rednote.com"]),
  }),
  Object.freeze({
    id: "tiktok",
    label: "TikTok",
    domains: Object.freeze(["tiktok.com"]),
  }),
  Object.freeze({
    id: "instagram",
    label: "Instagram",
    domains: Object.freeze(["instagram.com", "instagr.am"]),
  }),
]);

const PLATFORM_BY_ID = new Map(
  PLATFORM_DEFINITIONS.map((platform) => [platform.id, platform]),
);

export const PLATFORM_IDS = Object.freeze(
  PLATFORM_DEFINITIONS.map((platform) => platform.id),
);

export const SUPPORTED_PLATFORM_NAMES = PLATFORM_DEFINITIONS
  .map((platform) => platform.label)
  .join("、");

export function detectPlatformFromUrl(value) {
  const normalized = String(value || "").trim();
  if (!normalized) return null;
  try {
    const url = new URL(normalized);
    const hostname = url.hostname.toLowerCase().replace(/\.$/, "");
    return PLATFORM_DEFINITIONS.find((platform) =>
      platform.domains.some(
        (domain) => hostname === domain || hostname.endsWith(`.${domain}`),
      ),
    )?.id || null;
  } catch {
    return null;
  }
}

export function findPlatformConnection(payload, platform) {
  return payload?.items?.find((item) => item.platform === platform) || null;
}

export function isCredentialAnalysisError(code) {
  const normalized = String(code || "");
  return new Set([
    "link_auth_required",
    "link_cookie_file_missing",
    "platform_connection_auth_required",
    "platform_connection_missing",
    "platform_browser_cookie_locked",
    "platform_browser_cookie_decryption_failed",
    "platform_browser_cookie_missing",
    "platform_browser_cookie_read_failed",
    "platform_browser_profile_missing",
    "platform_cookie_expired",
    "platform_cookie_missing",
    "platform_cookie_secret_missing",
  ]).has(normalized);
}

export function connectionHealthMeta(connection) {
  if (!connection?.configured) {
    return { label: "未配置", tone: "muted", usable: false };
  }
  const health = connection.health || "needs_validation";
  if (health === "valid") return { label: "连接可用", tone: "success", usable: true };
  if (health === "ready") return { label: "已读取", tone: "success", usable: true };
  if (health === "needs_validation") {
    return { label: "待验证", tone: "warning", usable: true };
  }
  if (health === "expired") return { label: "登录已失效", tone: "danger", usable: false };
  return { label: "需要处理", tone: "danger", usable: false };
}

export function platformLabel(platform) {
  return PLATFORM_BY_ID.get(platform)?.label || "平台";
}

export function sourceTypeLabel(sourceType) {
  if (sourceType === "upload") return "本地文件";
  return PLATFORM_BY_ID.get(sourceType)?.label || sourceType || "未知来源";
}
