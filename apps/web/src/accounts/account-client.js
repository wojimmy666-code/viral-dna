export const ACCOUNT_API_BASE = import.meta.env?.VITE_API_BASE_URL || "/api/v1";
const sessions = { user: null, admin: null };
let editing = null;
const flushers = new Set();

export function setAccountSession(session, admin = false) {
  sessions[admin ? "admin" : "user"] = session;
}
export function currentAccountSession(admin = false) { return sessions[admin ? "admin" : "user"]; }
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
    if (requestedSession && requestedSession === currentAccountSession(admin)) window.dispatchEvent(new CustomEvent("viraldna:session-expired", { detail: { admin } }));
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
