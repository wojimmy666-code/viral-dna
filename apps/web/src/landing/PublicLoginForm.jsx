import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Eye, EyeSlash } from "@phosphor-icons/react";
import { setAccountSession } from "../accounts/account-client.js";
import { PASSWORD_MIN_LENGTH, PHONE_INPUT_PROPS, pastePhone } from "../accounts/account-form.js";
import { destinationAfterLogin } from "../accounts/login-destination.js";
import { checkLoginState, loginFailureMessage, requestPasswordLogin } from "../accounts/login-service.js";

export default function PublicLoginForm() {
  const location = useLocation(), navigate = useNavigate();
  const [gate, setGate] = useState({ phase: "checking" });
  const [retry, setRetry] = useState(0);
  const [draft, setDraft] = useState({ username: "", password: "" });
  const [revealed, setRevealed] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submitRequest = useRef(null), destination = useRef("");
  destination.current = destinationAfterLogin(location);
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    setGate({ phase: "checking" });
    checkLoginState(controller.signal).then(next => {
      if (!live) return;
      if (next.phase === "authenticated" || next.phase === "legacy") {
        if (next.session) setAccountSession(next.session);
        navigate(destination.current, { replace: true });
      } else setGate(next);
    }).catch(failure => { if (live) setGate({ phase: "failed", message: loginFailureMessage(failure) }); })
      .finally(() => window.clearTimeout(timer));
    return () => { live = false; controller.abort(); window.clearTimeout(timer); };
  }, [retry, navigate]);
  useEffect(() => () => {
    submitRequest.current?.abort();
    submitRequest.current = null;
  }, []);

  async function submit(event) {
    event.preventDefault();
    if (gate.phase !== "ready" || submitRequest.current) return;
    const controller = new AbortController();
    submitRequest.current = controller;
    setBusy(true); setError("");
    const timer = window.setTimeout(() => controller.abort(), 15000);
    try {
      const session = await requestPasswordLogin(draft, { signal: controller.signal });
      if (submitRequest.current !== controller) return;
      setAccountSession(session);
      setDraft(current => ({ ...current, password: "" }));
      navigate(destination.current, { replace: true });
    } catch (failure) {
      if (submitRequest.current === controller) setError(loginFailureMessage(failure));
    } finally {
      window.clearTimeout(timer);
      if (submitRequest.current === controller) { submitRequest.current = null; setBusy(false); }
    }
  }

  if (gate.phase === "setup") return <div className="vd-login-status" role="status"><p>{gate.setupAllowed ? "当前站点尚未完成首次账户设置。" : "请在部署本机完成首次账户设置，完成后即可登录。"}</p>{gate.setupAllowed && <Link className="vd-login-setup" to="/setup">完成首次设置</Link>}</div>;
  return <>
    <form className="vd-login-form" onSubmit={submit} aria-busy={busy || gate.phase === "checking"}>
      <fieldset disabled={busy || gate.phase !== "ready"}>
        <label className="vd-login-field" htmlFor="vd-login-phone"><span>手机号</span><input {...PHONE_INPUT_PROPS} id="vd-login-phone" name="username" required value={draft.username} onChange={event => setDraft(current => ({ ...current, username: event.target.value.trim() }))} onPaste={event => pastePhone(event, username => setDraft(current => ({ ...current, username })))} /></label>
        <label className="vd-login-field" htmlFor="vd-login-password"><span>密码（至少 8 位）</span></label>
        <div className="vd-login-password"><input id="vd-login-password" name="password" type={revealed ? "text" : "password"} required autoComplete="current-password" minLength={PASSWORD_MIN_LENGTH} value={draft.password} aria-describedby={error ? "vd-login-error" : undefined} onChange={event => setDraft(current => ({ ...current, password: event.target.value }))} /><button type="button" aria-label={revealed ? "隐藏密码" : "显示密码"} aria-pressed={revealed} onClick={() => setRevealed(value => !value)}>{revealed ? <EyeSlash size={20} /> : <Eye size={20} />}</button></div>
        {error && <p className="vd-login-error" id="vd-login-error" role="alert">{error}</p>}
        <button type="submit" className="vd-button vd-primary vd-login-submit">{busy ? "正在登录…" : "登录并进入"}</button>
      </fieldset>
    </form>
    {gate.phase === "checking" && <p className="vd-login-status" role="status">正在连接登录服务…</p>}
    {gate.phase === "failed" && <div className="vd-login-status" role="alert"><p>{gate.message}</p><button className="vd-login-retry" type="button" onClick={() => setRetry(value => value + 1)}>重试连接</button></div>}
  </>;
}
