import { Button } from "../ui/system/Button.jsx";
import { Dialog } from "../ui/system/Dialog.jsx";
import { useEffect, useRef, useState } from "react";
import { PASSWORD_MIN_LENGTH, PHONE_INPUT_PROPS, pastePhone } from "./account-form.js";
import { requestPasswordLogin } from "./login-service.js";

export function SessionReauthentication({ session, admin, onDone, onClose }) {
  const dialog = useRef(null), pending = useRef(null), passwordInput = useRef(null);
  const [draft, setDraft] = useState({ username: admin ? "admin" : session.username || "", password: "" });
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => {
    // Disabling a fieldset during verification removes focus. Restore it after
    // a failed attempt so keyboard users remain inside the modal.
    if (!busy && dialog.current?.open) dialog.current.querySelector('input[type="password"]')?.focus();
  }, [busy]);
  async function submit(event) {
    event.preventDefault();
    if (pending.current) return;
    const controller = new AbortController(); pending.current = controller;
    const timer = window.setTimeout(() => controller.abort(), 15000);
    setBusy(true); setError("");
    try {
      const next = await requestPasswordLogin(draft, { admin, signal: controller.signal, expectedPrincipalId: admin ? session.admin_id : session.user_id });
      if (!controller.signal.aborted) onDone(next);
    } catch (failure) {
      if (dialog.current?.open) setError(failure.name === "AbortError" || failure.name === "TypeError" ? "暂时无法连接登录服务，请稍后重试。当前内容仍保留。" : failure.message);
    } finally { window.clearTimeout(timer); pending.current = null; setBusy(false); }
  }
  return <Dialog ref={dialog} className="account-reauth-dialog" size="input" busy={busy} onClose={onClose} initialFocusRef={passwordInput} title="重新登录后继续" description="当前页面的未提交内容仍保留，请使用原用户登录，暂时不要刷新页面。" closeLabel="关闭重新登录">
    <form className="ui-dialog-body" onSubmit={submit}><fieldset disabled={busy}>
      <label className="account-field"><span>{admin ? "登录名" : "手机号"}</span><input name="reauth_username" {...(admin ? { autoComplete: "username", readOnly: true } : PHONE_INPUT_PROPS)} type={admin ? "text" : "tel"} value={draft.username} onChange={event => setDraft({ ...draft, username: event.target.value.trim() })} onPaste={admin ? undefined : event => pastePhone(event, username => setDraft(current => ({ ...current, username })))} required /></label>
      <label className="account-field"><span>密码（至少 8 位）</span><input ref={passwordInput} name="reauth_password" autoFocus type="password" autoComplete="current-password" minLength={PASSWORD_MIN_LENGTH} value={draft.password} onChange={event => setDraft({ ...draft, password: event.target.value })} required /></label>
      {error && <p className="account-error" role="alert">{error}</p>}
      <Button type="submit" className="primary-button account-primary">{busy ? "正在验证…" : "登录并继续"}</Button>
    </fieldset></form>
  </Dialog>;
}
