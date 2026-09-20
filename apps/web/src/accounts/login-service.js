import { accountRequest } from "./account-client.js";
import { passwordError, phoneError } from "./account-form.js";

function invalidResponse() {
  const error = new Error("登录服务返回异常，请稍后重试");
  error.code = "invalid_login_response";
  return error;
}

export async function checkLoginState(signal) {
  const status = await accountRequest("/auth/status", { signal });
  if (!status || typeof status.auth_mode !== "string" || typeof status.initialized !== "boolean") throw invalidResponse();
  if (status.auth_mode !== "password") return { phase: "legacy" };
  if (!status.initialized) return { phase: "setup", setupAllowed: status.setup_allowed === true };
  try {
    const session = await accountRequest("/session", { signal });
    if (!session?.user_id || !session?.account_id) throw invalidResponse();
    return { phase: "authenticated", session };
  } catch (error) {
    if (error.status === 401) return { phase: "ready" };
    throw error;
  }
}

// Both the public dialog and the existing standalone account forms use this path.
// Callers own navigation/session state so an abandoned request cannot redirect.
export async function requestPasswordLogin(draft, { admin = false, signal, expectedPrincipalId } = {}) {
  const validation = (!admin && phoneError(draft.username)) || passwordError(draft.password);
  if (validation) throw new Error(validation);
  const action = expectedPrincipalId ? "reauthenticate" : "login";
  const session = await accountRequest(`${admin ? "/admin" : ""}/auth/${action}`, {
    method: "POST", signal, body: { username: draft.username.trim(), password: draft.password,
      ...(expectedPrincipalId ? { expected_principal_id: expectedPrincipalId } : {}),
    },
  });
  if (!session || (admin ? !session.admin_id : !session.user_id || !session.account_id)) throw invalidResponse();
  return session;
}

export function loginFailureMessage(error) {
  if (error?.status === 401) return "手机号或密码不正确，或账户未启用";
  if (error?.status === 429) return "操作过于频繁，请稍后再试";
  if (error?.name === "AbortError" || error?.name === "TypeError" || error?.status >= 500) return "暂时无法连接登录服务，请稍后重试";
  return error?.message || "登录未完成，请重试";
}
