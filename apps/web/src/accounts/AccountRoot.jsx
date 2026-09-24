import { Button } from "../ui/system/Button.jsx";
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { destinationAfterLogin } from "./login-destination.js";
import { requestPasswordLogin } from "./login-service.js";
import { Buildings, CaretDown, Lock, SignOut, UserCircle } from "@phosphor-icons/react";
import {
  accountRequest, currentAccountSession, flushAccountDrafts, mediaUrl,
  setAccountSession, setProjectEditing,
} from "./account-client.js";
import { AccountManagement } from "./AccountManagement.jsx";
import { AccountHeader } from "./AccountHeader.jsx";
import { StorageManagement } from "./StorageManagement.jsx";
import { startSessionActivity } from "./session-activity.js";
import { SessionReauthentication } from "./SessionReauthentication.jsx";
import { startProjectLeaseRecovery } from "./project-lease-recovery.js";
import {
  PASSWORD_MIN_LENGTH, PHONE_INPUT_PROPS,
  passwordError, pastePhone, phoneError, setupRequestBody,
} from "./account-form.js";
import "./accounts.css";

function ErrorMessage({ error }) { return error ? <p className="account-error" role="alert">{error}</p> : null; }

export function AccountLogin({ admin, setup, activation, onDone }) {
  const [draft, setDraft] = useState({ username: admin ? "admin" : "", password: "", kind: "personal", name: "", display_name: "", admin_password: "", owner_password: "", confirm_legacy_ownership: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const field = (name, label, type = "text", props = {}) => <label className="account-field" key={name}>
    <span>{label}</span><input name={name} type={type} value={draft[name]} onChange={e => setDraft({ ...draft, [name]: name === "username" && !admin ? e.target.value.trim() : e.target.value })} onPaste={name === "username" && !admin ? event => pastePhone(event, value => setDraft(current => ({ ...current, username: value }))) : undefined} required maxLength={type === "password" ? undefined : 120} {...props} />
  </label>;
  async function submit(event) {
    event.preventDefault(); setError("");
    const validation = (!admin && !activation && phoneError(draft.username)) || (setup
      ? passwordError(draft.admin_password, "admin 密码") || passwordError(draft.owner_password, "前端登录密码")
      : passwordError(draft.password));
    if (validation) { setError(validation); return; }
    setBusy(true);
    try {
      if (setup) {
        await accountRequest("/auth/setup", { method: "POST", body: setupRequestBody(draft) });
        onDone();
      } else if (activation) {
        await accountRequest("/auth/activate", { method: "POST", body: { token: activation, password: draft.password } });
        window.history.replaceState(null, "", "/login");
        onDone();
      } else {
        const session = await requestPasswordLogin(draft, { admin });
        setAccountSession(session, admin); onDone(session);
      }
    } catch (failure) { setError(failure.message); } finally { setBusy(false); }
  }
  return <main className="account-login-shell">
    <section className="account-login-panel">
      <div className="account-brand"><span aria-hidden="true">▶</span> ViralDNA</div>
      <h1>{setup ? "初始化账户" : activation ? "设置登录密码" : admin ? "后台登录" : "登录"}</h1>
      {setup && <p className="account-help">设置独立的后台管理员，并明确现有项目与资产的归属。原文件不会移动或删除。</p>}
      {activation && <p className="account-help">设置密码后即可使用管理员为你创建的独立账户。</p>}
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          {setup ? <>
            {field("admin_password", "admin 密码（至少 8 位）", "password", { autoComplete: "new-password", minLength: PASSWORD_MIN_LENGTH })}
            <label className="account-field"><span>现有数据归属</span><select value={draft.kind} onChange={e => setDraft({ ...draft, kind: e.target.value })}><option value="personal">个人账户</option><option value="enterprise">企业账户</option></select></label>
            {field("name", draft.kind === "enterprise" ? "企业名称" : "个人账户名称")}
            {field("username", draft.kind === "enterprise" ? "负责人手机号" : "手机号", "tel", PHONE_INPUT_PROPS)}
            {field("display_name", "姓名")}
            {field("owner_password", "前端登录密码（至少 8 位）", "password", { autoComplete: "new-password", minLength: PASSWORD_MIN_LENGTH })}
            <label className="account-checkbox"><input type="checkbox" checked={draft.confirm_legacy_ownership} onChange={e => setDraft({ ...draft, confirm_legacy_ownership: e.target.checked })} required />确认将现有项目与资产归属上述账户</label>
          </> : <>
            {!activation && field("username", admin ? "登录名" : "手机号", admin ? "text" : "tel", admin ? { autoComplete: "username", readOnly: true } : PHONE_INPUT_PROPS)}
            {field("password", activation ? "新密码（至少 8 位）" : "密码（至少 8 位）", "password", { autoComplete: activation ? "new-password" : "current-password", minLength: PASSWORD_MIN_LENGTH })}
          </>}
          <ErrorMessage error={error} />
          <Button className="primary-button account-primary" type="submit">{busy ? "处理中…" : setup ? "确认归属并启用" : activation ? "设置密码" : "登录"}</Button>
        </fieldset>
      </form>
      {!setup && !activation && <footer><span>开通或重置密码，请联系管理员。</span><Link to={admin ? "/login" : "/admin/login"}>{admin ? "前端登录" : "后台登录"}</Link></footer>}
    </section>
  </main>;
}

function ReadOnlyProject({ projectId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    async function refresh() {
      try { const next = await accountRequest(`/projects/${projectId}/readonly`); if (live) { setData(next); setError(""); } }
      catch (failure) { if (live) setError(failure.message); }
    }
    void refresh(); const timer = window.setInterval(refresh, 10000);
    return () => { live = false; clearInterval(timer); };
  }, [projectId]);
  return <main className="account-readonly">
    <Link to="/projects">返回项目</Link><h1>{data?.name || "项目"}</h1><ErrorMessage error={error} />
    {!data && !error && <p role="status">正在读取项目…</p>}
    {data?.brief && <section><h2>创作简报</h2><p className="account-prompt-copy">{data.brief.objective}</p><p className="account-help">{data.brief.audience} · {data.brief.target_duration_seconds} 秒 · {data.brief.output_aspect_ratio}</p></section>}
    {data?.outline && <details><summary>大纲</summary>{data.outline.beats.map(beat => <section key={beat.stable_beat_key}><h3>{beat.title}</h3><p className="account-prompt-copy">{beat.message || beat.purpose}</p></section>)}</details>}
    {data?.productions?.map(production => <section key={production.id}><h2>{production.name}</h2>
      {production.prompts && <details><summary>全局提示词</summary><p className="account-prompt-copy">{production.prompts.common_image_prompt}</p><p className="account-prompt-copy">{production.prompts.common_video_prompt}</p></details>}
      {production.shots.map(shot => <article className="account-readonly-shot" key={shot.id}>
        <h3>分镜{shot.index}</h3>
        <div className="account-readonly-media">{shot.images.map(image => <figure key={image.url}><img src={mediaUrl(image.url)} alt={image.label} loading="lazy" /><figcaption>{image.adopted ? "已采用" : "最新图片"}</figcaption></figure>)}{shot.video_url && <video controls preload="metadata" src={mediaUrl(shot.video_url)} />}</div>
        <details><summary>图片提示词</summary><p className="account-prompt-copy">{shot.image_prompt || "尚未填写"}</p></details>
        <details><summary>视频提示词</summary><p className="account-prompt-copy">{shot.video_prompt || "尚未填写"}</p></details>
      </article>)}
      {!production.shots.length && <p className="account-help">尚未创建分镜。</p>}
    </section>)}
    {data && !data.productions.length && (data.manifest ? <section><h2>分镜提示词</h2>{data.manifest.shots.map(shot => <article key={shot.stable_shot_key} className="account-readonly-shot"><h3>分镜{shot.order}</h3><p className="account-prompt-copy">{shot.image_prompt_body}</p><details><summary>视频提示词</summary><p className="account-prompt-copy">{shot.video_prompt_body}</p></details></article>)}</section> : <p className="account-help">项目仍在准备阶段，尚未创建分镜。</p>)}
    {data?.report && <details><summary>分析报告</summary><p className="account-prompt-copy">{data.report.overview?.summary}</p><p className="account-prompt-copy">{data.report.overview?.narrative_structure}</p>{data.report.viral_findings?.map(finding => <section key={finding.id}><h3>{finding.title}</h3><p>{finding.observation}</p><p>{finding.recommendation}</p></section>)}</details>}
  </main>;
}

// In-memory IDs distinguish duplicated tabs. Refresh releases through pagehide;
// expired leases are recovered server-side when a browser exits unexpectedly.
const editorId = crypto.randomUUID();
function newLease(projectId) { return { projectId, editor_id: editorId, token: crypto.randomUUID() + crypto.randomUUID() }; }

export function AccountRoot({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const admin = location.pathname.startsWith("/admin");
  const [auth, setAuth] = useState({ loading: true });
  const [session, setSession] = useState(null);
  const [lease, setLease] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [sessionHealth, setSessionHealth] = useState("active");
  const [reauthOpen, setReauthOpen] = useState(false);
  const activity = useRef(null), recoveryHandler = useRef(null);
  const [menu, setMenu] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [password, setPassword] = useState({ current_password: "", new_password: "" });
  const content = useRef(null);
  const menuElement = useRef(null);
  const generation = useRef(0);
  const activeLease = useRef(null);
  const requestedLease = useRef(null);
  const sessionRequest = useRef(0);
  const match = location.pathname.match(/^\/projects\/([a-f0-9-]{36})(?:\/skill)?$/i);
  const projectId = match?.[1] || "";
  const activation = location.pathname === "/activate" ? new URLSearchParams(location.hash.slice(1)).get("token") : null;
  const sessionBlocked = sessionHealth === "expired" || sessionHealth === "changed";
  recoveryHandler.current = next => {
    setSession(next); setSessionHealth("active"); setReauthOpen(false); setError("");
    if (projectId) {
      activeLease.current = null; requestedLease.current = null; setProjectEditing(null);
      void acquire(Boolean(lease?.editable || lease?.lost));
    }
  };
  useEffect(() => {
    if (auth.auth_mode !== "password" || !session) return;
    setSessionHealth("active");
    const tracker = startSessionActivity({ admin,
      onRecovered: next => recoveryHandler.current?.(next),
      onState: state => {
        setSessionHealth(state);
        if (state === "expired" || state === "changed") {
          ++generation.current;
          activeLease.current = null; requestedLease.current = null; setProjectEditing(null);
          setLease(current => current ? { ...current, loading: false, lost: true, editable: false } : current);
        }
      },
    });
    activity.current = tracker;
    return () => { tracker.stop(); if (activity.current === tracker) activity.current = null; };
  }, [admin, auth.auth_mode, session?.user_id, session?.admin_id]);
  useEffect(() => {
    if (!sessionBlocked && !lease?.lost) return;
    const protect = event => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [sessionBlocked, lease?.lost]);

  useEffect(() => {
    if (!menu) return;
    const outside = event => { if (!menuElement.current?.contains(event.target)) setMenu(false); };
    const escape = event => {
      if (event.key === "Escape") { setMenu(false); menuElement.current?.querySelector("button")?.focus(); }
    };
    document.addEventListener("pointerdown", outside); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [menu]);

  async function loadSession() {
    const version = ++sessionRequest.current;
    setError("");
    try {
      const status = await accountRequest("/auth/status");
      if (version !== sessionRequest.current) return;
      setAuth(status);
      if (status.auth_mode !== "password" || !status.initialized) return;
      try {
        const next = await accountRequest(admin ? "/admin/session" : "/session");
        if (version !== sessionRequest.current) return;
        setAccountSession(next, admin); setSession(next);
      } catch (failure) {
        if (version !== sessionRequest.current) return;
        if (failure.status !== 401) throw failure;
        setSession(null); setAccountSession(null, admin);
      }
    } catch (failure) { if (version === sessionRequest.current) { setError(failure.message); setAuth({ loading: false, failed: true }); } }
  }
  useEffect(() => { setSession(currentAccountSession(admin)); void loadSession(); }, [admin]);
  useEffect(() => () => {
    // The public homepage lives outside this boundary. Leaving the private app
    // must release its editor immediately, including late in-flight grants.
    ++generation.current; ++sessionRequest.current;
    const previous = activeLease.current;
    activeLease.current = null; requestedLease.current = null;
    setProjectEditing(null); void release(previous);
  }, []);
  useEffect(() => {
    const expired = event => {
      if (event.detail.admin !== admin) return;
      // Retain all editors (including account forms), not only leased projects.
      activity.current?.expire(event.detail.changed);
    };
    window.addEventListener("viraldna:session-expired", expired);
    return () => window.removeEventListener("viraldna:session-expired", expired);
  }, [admin]);

  async function release(target) {
    if (!target) return;
    await accountRequest(`/projects/${target.projectId}/edit-lease/release`, {
      method: "POST", body: { editor_id: target.editor_id, token: target.token }, keepalive: true,
    }).catch(() => undefined);
  }
  async function acquire(preserveDraft = false) {
    // Reauthentication calls this before React commits sessionHealth="active".
    // The account client enforces the current session; the recovery observer and
    // manual button separately stop acquisitions while the session is blocked.
    if (!projectId) return;
    const version = ++generation.current;
    setError("");
    setLease(current => current?.projectId === projectId && !current.editable
      ? { ...current, acquiring: true, checkError: false, lost: preserveDraft || current.lost }
      : { projectId, loading: true, lost: preserveDraft });
    // Reuse an in-flight acquisition across React StrictMode effects, but never
    // reuse an abandoned project's token when navigating back to it.
    if (requestedLease.current?.projectId !== projectId) requestedLease.current = newLease(projectId);
    const next = requestedLease.current;
    try {
      next.pending ??= accountRequest(`/projects/${projectId}/edit-lease/acquire`, {
        method: "POST", body: { editor_id: next.editor_id, token: next.token },
      }).finally(() => { next.pending = null; });
      const result = await next.pending;
      if (version !== generation.current) { if (result.editable && requestedLease.current !== next) await release(next); return; }
      if (result.editable) { activeLease.current = next; setProjectEditing(next); }
      else { activeLease.current = null; setProjectEditing(null); }
      setLease({ projectId, ...result, lost: preserveDraft && !result.editable });
    } catch (failure) { if (version === generation.current) { setError(failure.message); setLease({ projectId, editable: false, lost: preserveDraft }); } }
  }
  useEffect(() => {
    const previous = activeLease.current;
    if (admin && previous) { activeLease.current = null; setProjectEditing(null); void release(previous); }
    if (auth.auth_mode !== "password" || !session || admin) return;
    if (requestedLease.current?.projectId !== projectId) requestedLease.current = projectId ? newLease(projectId) : null;
    if (previous?.projectId !== projectId) { activeLease.current = null; setProjectEditing(null); void release(previous); }
    if (projectId) void acquire(); else { ++generation.current; setLease(null); }
  }, [projectId, session?.user_id, auth.auth_mode, admin]);
  useEffect(() => {
    if (admin || auth.auth_mode !== "password" || !session || sessionBlocked || !projectId
      || lease?.projectId !== projectId || lease.loading || lease.acquiring || lease.editable || lease.lost) return;
    const version = generation.current;
    const observer = startProjectLeaseRecovery({
      projectId,
      isCurrent: () => generation.current === version,
      onState: state => setLease(current => current?.projectId === projectId && !current.editable && !current.lost
        ? { ...current, ...state, editable: false, checkError: false } : current),
      onAvailable: () => acquire(),
      onError: () => setLease(current => current?.projectId === projectId
        ? { ...current, checkError: true } : current),
    });
    return () => observer.stop();
  }, [projectId, session?.user_id, auth.auth_mode, admin, sessionBlocked,
    lease?.projectId, lease?.loading, lease?.acquiring, lease?.editable, lease?.lost]);
  useEffect(() => {
    if (!projectId || !lease?.editable) return;
    let alive = true;
    let lastConfirmed = Date.now();
    const lost = event => { if (event.detail.projectId === projectId) setLease(current => ({ ...current, lost: true, editable: false })); };
    const renew = async () => {
      const current = activeLease.current;
      if (!current || current.projectId !== projectId) return;
      try { await accountRequest(`/projects/${projectId}/edit-lease/renew`, { method: "POST", body: { editor_id: current.editor_id, token: current.token } }); lastConfirmed = Date.now(); }
      catch (failure) {
        if (!alive || activeLease.current !== current || failure.status === 401 || failure.code === "session_changed") return;
        if (failure.status === 423 || Date.now() - lastConfirmed >= 120000) {
          setLease(value => ({ ...value, lost: true, editable: false })); setProjectEditing(null);
          setError(failure.status === 423 ? failure.message : "连接暂时中断，无法确认编辑权限。内容仍保留，请连接恢复后重新取得编辑权。");
        }
      }
    };
    const onHide = () => { void release(activeLease.current); };
    const timer = window.setInterval(renew, 20000);
    window.addEventListener("pagehide", onHide); window.addEventListener("viraldna:edit-unavailable", lost);
    return () => { alive = false; clearInterval(timer); window.removeEventListener("pagehide", onHide); window.removeEventListener("viraldna:edit-unavailable", lost); };
  }, [projectId, lease?.editable]);

  async function logout() {
    setError("");
    try {
      await flushAccountDrafts();
      await accountRequest(admin ? "/admin/auth/logout" : "/auth/logout", { method: "POST" });
      setAccountSession(null, admin); setProjectEditing(null); activeLease.current = null;
      setSession(null); setMenu(false); navigate(admin ? "/admin/login" : "/login");
    } catch (failure) { setError(failure.message); }
  }
  async function changePassword(event) {
    event.preventDefault(); setError("");
    const validation = passwordError(password.current_password, "当前密码") || passwordError(password.new_password, "新密码");
    if (validation) { setError(validation); return; }
    try {
      await flushAccountDrafts();
      await accountRequest(admin ? "/admin/auth/password" : "/auth/password", { method: "POST", body: password });
      setPasswordOpen(false); setAccountSession(null, admin); setSession(null); setPassword({ current_password: "", new_password: "" });
      setProjectEditing(null); activeLease.current = null;
    } catch (failure) { setError(failure.message); }
  }
  async function copyDraft() {
    const values = [...(content.current?.querySelectorAll("textarea,[contenteditable=true]") || [])].map(node => node.value ?? node.innerText).filter(Boolean);
    try { await navigator.clipboard.writeText(values.join("\n\n")); setNotice("内容已复制。重新登录或刷新后，请核对最新版本再手动恢复。"); }
    catch { setError("复制未完成，请保留本页面，不要刷新。"); }
  }
  function downloadDraft() {
    const values = [...(content.current?.querySelectorAll("textarea,[contenteditable=true]") || [])].map(node => node.value ?? node.innerText).filter(Boolean);
    const url = URL.createObjectURL(new Blob([values.join("\n\n")], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "未提交提示词.txt";
    anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function accountNavigate(event, path) {
    event.preventDefault();
    try { await flushAccountDrafts(); setMenu(false); navigate(path); }
    catch (failure) { setError(failure.message); }
  }
  if (auth.loading) return <main className="account-loading" role="status">正在检查登录状态…</main>;
  if (auth.failed) return <main className="account-loading"><ErrorMessage error={error} /><Button className="secondary-button" onClick={loadSession}>重试</Button></main>;
  const loginRoute = location.pathname === "/login" || location.pathname === "/admin/login";
  if (auth.auth_mode !== "password") return loginRoute ? <Navigate to={destinationAfterLogin(location, admin)} replace /> : children;
  if (!auth.initialized && auth.setup_allowed === false) return <main className="account-loading">请在部署本机打开应用完成首次账户设置，完成后即可登录。</main>;
  if (!auth.initialized) return <AccountLogin setup onDone={loadSession} />;
  if (location.pathname === "/setup") return <Navigate to="/login" replace />;
  if (activation) return <AccountLogin activation={activation} onDone={() => { navigate("/login", { replace: true }); void loadSession(); }} />;
  if (!session) return <AccountLogin key={String(admin)} admin={admin} onDone={next => { setSession(next); navigate(destinationAfterLogin(location, admin), { replace: true }); }} />;
  if (loginRoute) return <Navigate to={destinationAfterLogin(location, admin)} replace />;
  const held = lease?.projectId === projectId;
  const editingReady = !projectId || (held && (lease.editable || lease.lost));
  const management = location.pathname === "/admin/accounts" || location.pathname === "/account/members";
  return <div className="account-root">
    <AccountHeader toolbarDisabled={sessionBlocked || !!lease?.lost} onHomeNavigation={() => setMenu(false)}
      identity={<span className="account-identity">{session.account_kind === "enterprise" ? <Buildings size={17} aria-hidden="true" /> : <UserCircle size={17} aria-hidden="true" />}<span className="account-name" title={session.account_name || "平台管理后台"}>{session.account_name || "平台管理后台"}</span><small>{session.account_kind === "enterprise" ? "企业账户" : admin ? "admin" : "个人账户"}</small></span>}
      accountMenu={<div className="account-menu" ref={menuElement}><Button className="text-button" aria-expanded={menu} onClick={() => setMenu(!menu)} title={session.display_name}><span className="account-menu-name">{session.display_name}</span><CaretDown size={14} aria-hidden="true" /></Button>
        {menu && <div className="account-menu-panel">
          <div className="account-menu-identity">{session.account_name || "平台管理后台"}<small>{session.account_kind === "enterprise" ? "企业账户" : admin ? "admin" : "个人账户"}</small></div>
          {admin && <Link to="/admin/accounts" onClick={event => accountNavigate(event, "/admin/accounts")}>账户管理</Link>}
          {!admin && <Link to="/account/storage" onClick={event => accountNavigate(event, "/account/storage")}>存储管理与生成历史</Link>}
          {!admin && session.account_kind === "enterprise" && session.role === "owner" && <Link to="/account/members" onClick={event => accountNavigate(event, "/account/members")}>企业成员</Link>}
          <Button className="text-button" onClick={() => { setPasswordOpen(true); setMenu(false); }}>修改密码</Button>
          <Button className="text-button" onClick={logout}><SignOut size={16} />退出登录</Button>
        </div>}
      </div>}>
    <ErrorMessage error={error} />
    {sessionBlocked && <div className="account-session-notice" role="status"><span>{sessionHealth === "changed" ? "登录用户已改变，请使用原用户重新登录。" : "登录已过期，请重新登录后继续。"}当前页面的未提交内容仍保留，暂时不要刷新页面。</span><Button className="primary-button" onClick={() => setReauthOpen(true)}>重新登录</Button></div>}
    {sessionHealth === "offline" && <div className="account-session-notice" role="status"><span>连接暂时中断，正在重试登录状态检查。当前内容仍保留。</span><Button className="text-button" onClick={() => void activity.current?.retry()}>重试连接</Button></div>}
    {reauthOpen && <SessionReauthentication session={session} admin={admin} onClose={() => setReauthOpen(false)} onDone={next => activity.current?.recover(next)} />}
    {notice && <p className="account-help" role="status">{notice}</p>}
    {passwordOpen && <form className="account-password-form" onSubmit={changePassword}>
      <h2>修改密码</h2>{["current_password", "new_password"].map(name => <label className="account-field" key={name}><span>{name === "current_password" ? "当前密码" : "新密码（至少 8 位）"}</span><input type="password" value={password[name]} autoComplete={name === "current_password" ? "current-password" : "new-password"} minLength={PASSWORD_MIN_LENGTH} required onChange={e => setPassword({ ...password, [name]: e.target.value })} /></label>)}
      <div className="account-actions"><Button type="submit" className="primary-button">修改并重新登录</Button><Button type="button" className="secondary-button" onClick={() => setPasswordOpen(false)}>取消</Button></div>
    </form>}
    {projectId && held && !lease.loading && !lease.editable && <div className="account-edit-notice" role="status"><Lock size={16} /><span>{lease.lost ? (sessionBlocked ? "当前修改已暂停提交。" : lease.occupied ? `${lease.display_name || "其他成员"} 正在编辑。当前修改仍保留，暂不能提交。` : "编辑权已失效，当前修改仍保留。") : lease.checkError ? "暂时无法确认编辑状态，连接恢复后会自动重试。" : lease.occupied ? `${lease.display_name || "其他成员"} 正在编辑，当前为只读查看。编辑权释放后将自动恢复。` : "正在恢复项目编辑状态…"}</span>{lease.lost ? <>{!sessionBlocked && <Button className="text-button" loading={lease.acquiring} loadingLabel="正在检查…" onClick={() => void acquire(true)}>重新取得编辑权</Button>}<Button className="text-button" onClick={copyDraft}>复制未提交内容</Button><Button className="text-button" onClick={downloadDraft}>下载备份</Button></> : <Button className="text-button" loading={lease.acquiring} loadingLabel="正在检查…" disabled={sessionBlocked} onClick={() => void acquire()}>进入编辑</Button>}</div>}
    <div ref={content} inert={sessionBlocked || !!lease?.lost}>
    {location.pathname === "/account/storage" && !admin ? <StorageManagement session={session} /> : management ? <AccountManagement admin={admin} session={session} /> : <>
      {projectId && (!held || (lease?.loading && !lease?.lost)) && <main className="account-loading" role="status">正在检查项目编辑状态…</main>}
      {editingReady && <div>{children}</div>}
      {projectId && held && !lease.loading && !lease.editable && !lease.lost && <ReadOnlyProject projectId={projectId} />}
    </>}
    </div>
    </AccountHeader>
  </div>;
}
