import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { X } from "@phosphor-icons/react";
import { PASSWORD_MIN_LENGTH, PHONE_INPUT_PROPS, pastePhone } from "./account-form.js";
import { requestPasswordLogin } from "./login-service.js";

export function SessionReauthentication({ session, admin, onDone, onClose }) {
  const dialog = useRef(null), pending = useRef(null), returnFocus = useRef(null);
  const [draft, setDraft] = useState({ username: admin ? "admin" : session.username || "", password: "" });
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useLayoutEffect(() => {
    const node = dialog.current;
    returnFocus.current ??= document.activeElement;
    node.showModal();
    node.querySelector('input[type="password"]')?.focus();
    // Close before React removes the node: background controls are otherwise
    // still inert when passive cleanup tries to restore focus.
    return () => { pending.current?.abort(); node.close(); if (returnFocus.current?.isConnected) returnFocus.current.focus(); };
  }, []);
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
  return <dialog ref={dialog} className="account-reauth-dialog" aria-labelledby="reauth-title" aria-describedby="reauth-description" onCancel={event => { event.preventDefault(); if (!busy) onClose(); }} onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); if (!busy) onClose(); } }}>
    <div className="account-reauth-heading"><h2 id="reauth-title">重新登录后继续</h2><button className="icon-button" type="button" aria-label="关闭重新登录" disabled={busy} onClick={onClose}><X size={20} /></button></div>
    <p id="reauth-description" className="account-reauth-description">当前页面的未提交内容仍保留，请使用原用户登录，暂时不要刷新页面。</p>
    <form onSubmit={submit}><fieldset disabled={busy}>
      <label className="account-field"><span>{admin ? "登录名" : "手机号"}</span><input name="reauth_username" {...(admin ? { autoComplete: "username", readOnly: true } : PHONE_INPUT_PROPS)} type={admin ? "text" : "tel"} value={draft.username} onChange={event => setDraft({ ...draft, username: event.target.value.trim() })} onPaste={admin ? undefined : event => pastePhone(event, username => setDraft(current => ({ ...current, username })))} required /></label>
      <label className="account-field"><span>密码（至少 8 位）</span><input name="reauth_password" autoFocus type="password" autoComplete="current-password" minLength={PASSWORD_MIN_LENGTH} value={draft.password} onChange={event => setDraft({ ...draft, password: event.target.value })} required /></label>
      {error && <p className="account-error" role="alert">{error}</p>}
      <button type="submit" className="primary-button account-primary">{busy ? "正在验证…" : "登录并继续"}</button>
    </fieldset></form>
  </dialog>;
}
