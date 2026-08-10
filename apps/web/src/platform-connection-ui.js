const PLATFORM_DOMAINS = {
  douyin: ["douyin.com", "iesdouyin.com"],
  xiaohongshu: ["xiaohongshu.com", "xhslink.com", "rednote.com"],
};

export function detectPlatformFromUrl(value) {
  const normalized = String(value || "").trim();
  if (!normalized) return null;
  try {
    const url = new URL(normalized);
    const hostname = url.hostname.toLowerCase().replace(/\.$/, "");
    return Object.entries(PLATFORM_DOMAINS).find(([, domains]) =>
      domains.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`)),
    )?.[0] || null;
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
  return platform === "douyin" ? "抖音" : platform === "xiaohongshu" ? "小红书" : "平台";
}
