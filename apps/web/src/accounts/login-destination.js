// A login return target is navigation, never an authority to access a resource.
// Keep it within known frontend routes and let AccountRoot/the API enforce access.
export function safeLoginDestination(value, fallback = "/projects") {
  if (typeof value !== "string" || !value.startsWith("/") || /[\\\u0000-\u0020]/.test(value)) return fallback;
  try {
    const decoded = decodeURIComponent(value);
    if (/[\\\u0000-\u0020]/.test(decoded) || decoded.startsWith("//")) return fallback;
    const url = new URL(value, "https://viraldna.invalid");
    if (url.origin !== "https://viraldna.invalid") return fallback;
    if (!/^\/(?:projects|skills|assets|category-profiles|settings|account)(?:\/|$)/.test(url.pathname)) return fallback;
    return url.pathname + url.search + url.hash;
  } catch { return fallback; }
}

export function loginHref(destination = "/projects") {
  return `/login?returnTo=${encodeURIComponent(safeLoginDestination(destination))}`;
}

export function destinationAfterLogin(location, admin = false) {
  if (admin) return "/admin/accounts";
  const requested = new URLSearchParams(location.search).get("returnTo");
  return safeLoginDestination(requested || location.pathname + location.search + location.hash);
}
