export const ACCOUNT_API_BASE = import.meta.env?.VITE_API_BASE_URL || "/api/v1";
const sessions = { user: null, admin: null };
const paused = { user: false, admin: false };
let editing = null;
const flushers = new Set();

export function setAccountSession(session, admin = false) {
  sessions[admin ? "admin" : "user"] = session;
  paused[admin ? "admin" : "user"] = false;
}
export function currentAccountSession(admin = false) { return sessions[admin ? "admin" : "user"]; }
export function sameAccountSession(left, right) {
  return left === right || Boolean(left?.csrf_token && right && left.csrf_token === right.csrf_token
    && left.user_id === right.user_id && left.admin_id === right.admin_id && left.account_id === right.account_id);
}
export function pauseAccountSession(admin = false) { paused[admin ? "admin" : "user"] = true; }
export function accountSessionPaused(admin = false) { return paused[admin ? "admin" : "user"]; }
export function setProjectEditing(value) { editing = value; }
export function projectEditing() { return editing; }
export function registerAccountFlusher(flush) { flushers.add(flush); return () => flushers.delete(flush); }
export async function flushAccountDrafts() {
  for (const flush of [...flushers]) {
    if (await flush() === false) throw new Error("请先完成当前修改的保存");
  }
}

export function accountHeaders(url, headers = {}) {
  const result = new Headers(headers);
  const admin = String(url).includes("/admin/");
  const session = currentAccountSession(admin);
  if (session?.csrf_token) result.set("X-CSRF-Token", session.csrf_token);
  const principal = admin ? session?.admin_id : session?.user_id;
  if (principal && !/\/(?:auth\/|session(?:\?|$))/.test(String(url))) result.set("X-Session-Principal", principal);
  if (principal && String(url).endsWith("/auth/refresh")) result.set("X-Session-Principal", principal);
  if (!admin && editing) {
    result.set("X-Editor-Id", editing.editor_id);
    result.set("X-Edit-Token", editing.token);
  }
  return result;
}

export async function accountFetch(url, options = {}) {
  const requestedEditing = editing;
  const adminRequest = String(url).includes("/admin/");
  const requestedSession = currentAccountSession(adminRequest);
  if (accountSessionPaused(adminRequest) && !/\/(?:auth\/|session(?:\?|$))/.test(String(url))) {
    const error = new Error("登录已暂停，请先重新登录；当前页面内容仍保留");
    error.status = 401; error.code = "session_paused"; throw error;
  }
  const response = await fetch(url, {
    ...options, credentials: "include", headers: accountHeaders(url, options.headers),
  });
  if (response.status === 423 && requestedEditing && editing === requestedEditing) {
    const failure = await response.clone().json().catch(() => null);
    if (editing === requestedEditing && failure?.detail?.code !== "project_busy") {
      window.dispatchEvent(new CustomEvent("viraldna:edit-unavailable", {
        detail: { projectId: requestedEditing.projectId },
      }));
    }
  }
  if (response.status === 401 && !String(url).includes("/auth/")) {
    const admin = String(url).includes("/admin/");
    if (requestedSession && sameAccountSession(requestedSession, currentAccountSession(admin))) window.dispatchEvent(new CustomEvent("viraldna:session-expired", { detail: { admin } }));
  }
  if (response.status === 409 && requestedSession && sameAccountSession(requestedSession, currentAccountSession(adminRequest))) {
    const failure = await response.clone().json().catch(() => null);
    if (sameAccountSession(requestedSession, currentAccountSession(adminRequest)) && failure?.detail?.code === "session_changed") window.dispatchEvent(new CustomEvent("viraldna:session-expired", { detail: { admin: adminRequest, changed: true } }));
  }
  return response;
}

export async function accountRequest(path, { body, ...options } = {}) {
  const response = await accountFetch(`${ACCOUNT_API_BASE}${path}`, {
    ...options, ...(body === undefined ? {} : {
      body: JSON.stringify(body), headers: { "Content-Type": "application/json", ...options.headers },
    }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(payload?.detail?.message || (typeof payload?.detail === "string" ? payload.detail : "请求未完成，请重试"));
    error.status = response.status;
    error.code = payload?.detail?.code;
    throw error;
  }
  return payload;
}

export function accountStorageKey(key) {
  const session = currentAccountSession();
  return session?.account_id && session?.user_id
    ? `${key}:account:${session.account_id}:user:${session.user_id}` : key;
}

export function mediaUrl(path) {
  return ACCOUNT_API_BASE.startsWith("http") ? new URL(path, ACCOUNT_API_BASE).toString() : path;
}
