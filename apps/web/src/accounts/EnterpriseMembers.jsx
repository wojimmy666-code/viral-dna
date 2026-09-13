import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { InlineMessage, PageHeader, PageShell, StatusBadge } from "../ui/system/index.js";
import { accountRequest } from "./account-client.js";
import { PHONE_INPUT_PROPS, pastePhone, phoneError, passwordError } from "./account-form.js";

const statusText = { active: "已启用", pending: "待激活", disabled: "已移除" };
const actionText = { add: "添加成员", remove: "移除成员", restore: "恢复成员", reset: "重置密码" };

export function EnterpriseMembers({ session }) {
  if (session?.account_kind !== "enterprise" || session?.role !== "owner") {
    return <PageShell className="account-management"><Link to="/projects">返回项目</Link>
      <PageHeader className="account-management-heading" title="企业成员" />
      <InlineMessage tone="warning">只有企业负责人可以管理本企业成员。</InlineMessage>
    </PageShell>;
  }
  return <OwnerMembers key={session.account_id} session={session} />;
}

function MemberEditor({ action, busy, failure, onSubmit, onClose, onShowRemoved }) {
  const { kind, member } = action;
  const headingId = useId(), errorId = useId();
  const firstField = useRef(null);
  const [draft, setDraft] = useState({ display_name: "", username: "", password: "" });
  const [visible, setVisible] = useState(false);
  const [validation, setValidation] = useState(null);
  const isAdd = kind === "add", isRemove = kind === "remove";
  const message = validation?.message || failure?.message;
  const errorField = validation?.field || ({
    display_name_invalid: "display_name", username_invalid: "username", username_exists: "username",
    member_removed: isAdd ? "username" : "", password_length: "password", password_unchanged: "password",
  }[failure?.code] || "");
  const fieldError = field => ({
    "aria-invalid": Boolean(message && errorField === field),
    "aria-describedby": message && errorField === field ? errorId : undefined,
  });
  useEffect(() => { firstField.current?.focus(); }, []);
  function submit(event) {
    event.preventDefault();
    if (busy) return;
    let error = null;
    if (isAdd && !draft.display_name.trim()) error = { field: "display_name", message: "请填写成员姓名" };
    else if (isAdd && phoneError(draft.username)) error = { field: "username", message: phoneError(draft.username) };
    else if (!isRemove && passwordError(draft.password)) error = { field: "password", message: passwordError(draft.password) };
    setValidation(error);
    if (error) return;
    onSubmit(isRemove ? undefined : isAdd
      ? { display_name: draft.display_name.trim(), username: draft.username.trim(), password: draft.password }
      : { password: draft.password });
  }
  function edit(field, value) { setValidation(null); setDraft(current => ({ ...current, [field]: value })); }
  return <form className="account-create-form enterprise-member-editor" aria-labelledby={headingId} aria-busy={busy}
    aria-describedby={message && !errorField ? errorId : undefined}
    onSubmit={submit} noValidate onKeyDown={event => { if (event.key === "Escape" && !busy) { event.preventDefault(); onClose(); } }}>
    <fieldset disabled={busy}>
      <h2 id={headingId} ref={isRemove ? firstField : undefined} tabIndex={-1}>{actionText[kind]}</h2>
      {!isAdd && <p className="enterprise-member-identity">{member.display_name} · {member.username}</p>}
      {isRemove ? <p className="account-help">移除后，该成员将立即退出登录，旧邀请链接、同步授权和项目编辑权失效。企业项目、资产、生成历史及操作记录全部保留；以后可在“已移除”中恢复。</p> : <>
        {isAdd && <>
          <label className="account-field"><span>姓名</span><input ref={firstField} name="display_name" required maxLength={120}
            {...fieldError("display_name")}
            value={draft.display_name} onChange={event => edit("display_name", event.target.value)} /></label>
          <label className="account-field"><span>手机号</span><input {...PHONE_INPUT_PROPS} name="username" required autoComplete="off"
            {...fieldError("username")}
            value={draft.username} onChange={event => edit("username", event.target.value.trim())}
            onPaste={event => pastePhone(event, value => edit("username", value))} /></label>
        </>}
        <div className="account-field">
          <label htmlFor={`${headingId}-password`}>{isAdd ? "初始密码" : "新密码"}（至少 8 位）</label>
          <div className="enterprise-member-password">
            <input id={`${headingId}-password`} ref={!isAdd ? firstField : undefined} name="member_password"
              type={visible ? "text" : "password"} autoComplete="new-password" required minLength={8}
              value={draft.password} onChange={event => edit("password", event.target.value)}
              {...fieldError("password")} />
            <button className="text-button" type="button" aria-label={visible ? "隐藏密码" : "显示密码"}
              aria-pressed={visible} onClick={() => setVisible(value => !value)}>{visible ? "隐藏" : "显示"}</button>
          </div>
        </div>
        <p className="account-help">{isAdd
          ? "创建后可直接登录，共享本企业项目、资产和存储额度。请单独告知本人登录信息。"
          : kind === "restore" ? "设置不同于原密码的新密码后恢复登录，保留原成员身份和历史；旧会话及同步授权不会恢复。"
            : "确认后立即启用新密码，该成员需重新登录；旧邀请链接、同步授权和编辑权失效。"}</p>
      </>}
      {message && <p id={errorId} className="account-error" role="alert">{message}</p>}
      {failure?.code === "member_removed" && <button className="text-button" type="button" onClick={() => onShowRemoved(draft.username || member?.username)}>查看已移除成员</button>}
      <div className="account-actions">
        <button className={isRemove ? "secondary-button enterprise-member-danger" : "primary-button"} type="submit">{busy ? "处理中…" : isRemove ? "确认移除" : kind === "restore" ? "设置密码并恢复" : kind === "reset" ? "确认重置密码" : "创建成员"}</button>
        <button className="secondary-button" type="button" onClick={onClose}>取消</button>
      </div>
    </fieldset>
  </form>;
}

function OwnerMembers({ session }) {
  const headingId = useId();
  const [items, setItems] = useState([]), [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(""), [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [view, setView] = useState("current"), [query, setQuery] = useState("");
  const [editor, setEditor] = useState(null), [name, setName] = useState(session.account_name || "");
  const sequence = useRef(0), submitting = useRef(false), trigger = useRef(null), addButton = useRef(null);
  const focusPending = useRef(false);
  const refresh = useCallback(async () => {
    const request = ++sequence.current;
    try {
      const response = await accountRequest("/account/members");
      if (request === sequence.current) { setItems(response.items); setLoadError(""); }
    } catch (error) { if (request === sequence.current) setLoadError(error.message); }
    finally { if (request === sequence.current) setLoaded(true); }
  }, []);
  useEffect(() => { void refresh(); return () => { sequence.current++; }; }, [refresh]);
  useEffect(() => {
    if (editor || busy || !focusPending.current) return;
    focusPending.current = false;
    const original = trigger.current;
    const target = original?.isConnected && !original.disabled ? original
      : addButton.current && !addButton.current.disabled ? addButton.current : document.getElementById(headingId);
    target?.focus();
  }, [editor, busy, loaded, loadError, headingId]);
  function closeEditor() {
    focusPending.current = true;
    setEditor(null); setFailure(null);
  }
  function openEditor(kind, member, event) {
    trigger.current = event.currentTarget;
    setEditor({ kind, member }); setFailure(null); setNotice("");
  }
  async function submit(body) {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setFailure(null); setNotice("");
    const { kind, member } = editor;
    try {
      const path = kind === "add" ? "/account/members" : `/account/members/${member.id}${kind === "remove" ? "" : `/${kind}`}`;
      await accountRequest(path, { method: kind === "remove" ? "DELETE" : "POST", body });
      closeEditor();
      setNotice(kind === "remove" ? "成员已移除，企业数据保留。" : kind === "add" ? "成员已创建，可使用手机号和初始密码登录。" : kind === "restore" ? "成员已恢复，请使用新密码重新登录。" : "密码已重置，请通知成员重新登录。");
      await refresh();
    } catch (error) { setFailure({ message: error.message, code: error.code }); }
    finally { submitting.current = false; setBusy(false); }
  }
  async function rename(event) {
    event.preventDefault();
    if (submitting.current || !name.trim()) return;
    submitting.current = true; setBusy(true); setNotice("");
    try { await accountRequest("/account", { method: "PATCH", body: { name: name.trim() } }); setNotice("企业名称已更新"); }
    catch (error) { setLoadError(error.message); }
    finally { submitting.current = false; setBusy(false); }
  }
  const removed = view === "removed";
  const search = query.trim().toLocaleLowerCase();
  const visible = items.filter(item => (item.status === "disabled") === removed
    && `${item.display_name} ${item.username}`.toLocaleLowerCase().includes(search));
  const disabled = busy || Boolean(editor) || !loaded || Boolean(loadError);
  return <PageShell className="account-management enterprise-members">
    <Link to="/projects">返回项目</Link>
    <PageHeader id={headingId} tabIndex={-1} className="account-management-heading" title="企业成员" description="成员独立登录，共享本企业的项目和资产。"
      actions={<button ref={addButton} className="primary-button" disabled={disabled} onClick={event => openEditor("add", null, event)}>添加成员</button>} />
    <form className="account-name-form" onSubmit={rename}>
      <label className="account-field"><span>企业名称</span><input name="enterprise_name" required maxLength={120} disabled={busy || Boolean(editor)} value={name} onChange={event => setName(event.target.value)} /></label>
      <button className="secondary-button" disabled={disabled || !name.trim()}>更新名称</button>
    </form>
    {notice && <p role="status" className="account-help">{notice}</p>}
    {loadError && <InlineMessage tone="danger">{loadError}<button className="text-button" disabled={busy} onClick={refresh}>重新加载</button></InlineMessage>}
    {editor && <MemberEditor key={`${editor.kind}:${editor.member?.id || "new"}`} action={editor} busy={busy} failure={failure}
      onSubmit={submit} onClose={closeEditor} onShowRemoved={phone => { closeEditor(); setView("removed"); setQuery(phone); }} />}
    <div className="enterprise-member-toolbar">
      <div className="account-actions" role="group" aria-label="成员状态">
        <button className="secondary-button" aria-pressed={!removed} disabled={busy || Boolean(editor)} onClick={() => setView("current")}>当前成员（{items.filter(item => item.status !== "disabled").length}）</button>
        <button className="secondary-button" aria-pressed={removed} disabled={busy || Boolean(editor)} onClick={() => setView("removed")}>已移除（{items.filter(item => item.status === "disabled").length}）</button>
      </div>
      <label className="account-field"><input type="search" aria-label="搜索成员" placeholder="搜索姓名或手机号" value={query} onChange={event => setQuery(event.target.value)} /></label>
    </div>
    {!loaded ? <p role="status">正在读取成员…</p> : !visible.length ? <p className="account-help" role="status">{search ? "没有匹配的成员，请更换姓名或手机号搜索。" : removed ? "暂无已移除成员。" : "暂无成员。"}</p> :
      <div className="account-table-wrap enterprise-member-table"><table aria-label={removed ? "已移除成员" : "当前成员"}>
        <thead><tr>{["姓名", "手机号", "身份", "状态", "创建时间", "操作"].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
        <tbody>{visible.map(item => <tr key={item.id}>
          <td data-label="姓名">{item.display_name}</td><td data-label="手机号">{item.username}</td>
          <td data-label="身份">{item.role === "owner" ? "负责人" : "成员"}</td>
          <td data-label="状态"><StatusBadge tone={item.status === "active" ? "success" : "neutral"}>{statusText[item.status] || item.status}</StatusBadge></td>
          <td data-label="创建时间">{item.created_at ? new Date(item.created_at * 1000).toLocaleDateString("zh-CN") : "—"}</td>
          <td data-label="操作"><div className="account-actions">{item.role === "member" && item.id !== session.user_id ? <>
            <button className="text-button" disabled={disabled} aria-label={`${item.display_name}：${removed ? "恢复成员" : "重置密码"}`}
              onClick={event => openEditor(removed ? "restore" : "reset", item, event)}>{removed ? "恢复成员" : "重置密码"}</button>
            {!removed && <button className="text-button enterprise-member-danger" disabled={disabled} aria-label={`${item.display_name}：移除成员`} onClick={event => openEditor("remove", item, event)}>移除</button>}
          </> : <span className="account-help">负责人不可移除</span>}</div></td>
        </tr>)}</tbody>
      </table></div>}
  </PageShell>;
}
