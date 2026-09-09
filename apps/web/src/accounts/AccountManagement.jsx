import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { accountRequest } from "./account-client.js";
import { PHONE_INPUT_PROPS, pastePhone, phoneError } from "./account-form.js";
import { AdminStorageQuota, AdminSyncServer } from "./StorageManagement.jsx";
import { formatStorage } from "./storage-ui.js";

const statusText = { active: "已启用", disabled: "已停用", pending: "待激活" };
export function AccountManagement({ admin, session }) {
  const [items, setItems] = useState([]);
  const [members, setMembers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [activation, setActivation] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmation, setConfirmation] = useState(null);
  const [name, setName] = useState(session?.account_name || "");
  const [accountDetails, setAccountDetails] = useState({ name: "", managed_asset_project: "" });
  const [draft, setDraft] = useState({ kind: "personal", name: "", username: "", display_name: "" });
  async function refresh() {
    try {
      const response = await accountRequest(admin ? "/admin/accounts" : "/account/members");
      setItems(response.items); setError("");
    } catch (failure) { setError(failure.message); } finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, [admin]);
  async function run(operation) {
    setBusy(true); setError(""); setNotice("");
    try { await operation(); await refresh(); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  function showLink(token) { setActivation(`${window.location.origin}/activate#token=${encodeURIComponent(token)}`); }
  async function create(event) {
    event.preventDefault();
    const validation = phoneError(draft.username);
    if (validation) { setError(validation); return; }
    await run(async () => {
      const body = admin ? { ...draft, username: draft.username.trim() } : { username: draft.username.trim(), display_name: draft.display_name };
      const response = await accountRequest(admin ? "/admin/accounts" : "/account/members", { method: "POST", body });
      showLink(response.activation_token); setCreating(false);
      setDraft({ kind: "personal", name: "", username: "", display_name: "" });
    });
  }
  async function openMembers(account) {
    setSelected(account); setMembers([]);
    setAccountDetails({ name: account.name, managed_asset_project: account.managed_asset_project || "" });
    await run(async () => { const response = await accountRequest(`/admin/accounts/${account.id}/members`); setMembers(response.items); });
  }
  async function reset(member) {
    await run(async () => {
      const path = admin ? `/admin/accounts/${selected.id}/members/${member.id}/reset` : `/account/members/${member.id}/${member.status === "disabled" ? "restore" : "reset"}`;
      const response = await accountRequest(path, { method: "POST" }); showLink(response.activation_token);
    });
  }
  async function confirmAction() {
    const action = confirmation;
    await run(async () => {
      if (admin) await accountRequest(`/admin/accounts/${action.id}`, { method: "PATCH", body: { status: action.status === "disabled" ? "active" : "disabled" } });
      else await accountRequest(`/account/members/${action.id}`, { method: "DELETE" });
      setConfirmation(null);
    });
  }
  const memberRows = admin ? members : items;
  return <main className="account-management">
    <Link to={admin ? "/admin/providers" : "/projects"}>{admin ? "返回平台设置" : "返回项目"}</Link>
    <header className="account-management-heading"><h1>{admin ? "账户管理" : "企业成员"}</h1><button className="primary-button" onClick={() => { setCreating(true); setActivation(""); }} disabled={busy}>{admin ? "新建账户" : "邀请成员"}</button></header>
    {!admin && <form className="account-name-form" onSubmit={event => { event.preventDefault(); void run(async () => { await accountRequest("/account", { method: "PATCH", body: { name } }); setNotice("企业名称已更新"); }); }}><label className="account-field"><span>企业名称</span><input value={name} required maxLength={120} onChange={e => setName(e.target.value)} /></label><button className="secondary-button" disabled={busy}>更新名称</button></form>}
    {error && <p className="account-error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {admin && <AdminSyncServer />}
    {admin && selected && <AdminStorageQuota key={selected.id} accountId={selected.id} accountName={selected.name} onUpdated={refresh} />}
    {activation && <section className="account-activation-link"><h2>激活／重置链接</h2><p>链接 72 小时内有效，仅可使用一次。请单独发送给本人。</p><input aria-label="激活链接" value={activation} readOnly onFocus={event => event.target.select()} /><div className="account-actions"><button className="secondary-button" onClick={async () => { try { await navigator.clipboard.writeText(activation); setNotice("链接已复制"); } catch { setError("请选中链接后手动复制"); } }}>复制链接</button><button className="text-button" onClick={() => setActivation("")}>关闭</button></div></section>}
    {creating && <form className="account-create-form" onSubmit={create}><fieldset disabled={busy}><h2>{admin ? "新建独立账户" : "邀请企业成员"}</h2>
      {admin && <><label className="account-field"><span>账户类型</span><select value={draft.kind} onChange={e => setDraft({ ...draft, kind: e.target.value })}><option value="personal">个人账户</option><option value="enterprise">企业账户</option></select></label><label className="account-field"><span>{draft.kind === "enterprise" ? "企业名称" : "账户名称"}</span><input name="name" required maxLength={120} value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label></>}
      <label className="account-field"><span>{admin && draft.kind === "enterprise" ? "负责人手机号" : "手机号"}</span><input {...PHONE_INPUT_PROPS} name="username" required autoComplete="off" value={draft.username} onChange={e => setDraft({ ...draft, username: e.target.value.trim() })} onPaste={event => pastePhone(event, value => setDraft(current => ({ ...current, username: value })))} /></label>
      <label className="account-field"><span>姓名</span><input name="display_name" required maxLength={120} value={draft.display_name} onChange={e => setDraft({ ...draft, display_name: e.target.value })} /></label>
      <p className="account-help">每个账户使用独立手机号，由本人通过激活链接设置至少 8 位密码。</p><div className="account-actions"><button className="primary-button" type="submit">{busy ? "处理中…" : admin ? "创建并生成激活链接" : "生成邀请链接"}</button><button className="secondary-button" type="button" onClick={() => setCreating(false)}>取消</button></div>
    </fieldset></form>}
    {confirmation && <div className="account-edit-notice"><span>{admin ? `确认${confirmation.status === "disabled" ? "启用" : "停用"}“${confirmation.name}”？` : `确认移除“${confirmation.display_name}”？其企业项目和资产将保留。`}</span><button className="secondary-button" disabled={busy} onClick={confirmAction}>确认</button><button className="text-button" disabled={busy} onClick={() => setConfirmation(null)}>取消</button></div>}
    {loading ? <p role="status">正在读取…</p> : admin ? <div className="account-table-wrap"><table><thead><tr><th>账户</th><th>类型</th><th>成员</th><th>状态</th><th>存储用量 / 容量</th><th>操作</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td>{item.name}</td><td>{item.kind === "enterprise" ? "企业" : "个人"}</td><td>{item.member_count}</td><td>{statusText[item.status]}</td><td>{item.storage ? `${formatStorage(item.storage.used_bytes)} / ${formatStorage(item.storage.limit_bytes)}` : "—"}</td><td><div className="account-actions"><button className="text-button" disabled={busy} onClick={() => openMembers(item)}>用户与容量</button><button className="text-button" disabled={busy} onClick={() => setConfirmation(item)}>{item.status === "disabled" ? "启用" : "停用"}</button></div></td></tr>)}</tbody></table></div> : null}
    {admin && selected && <details className="account-details">
      <summary>账户设置 · {selected.name}</summary>
      <form className="account-create-form" onSubmit={event => {
        event.preventDefault(); void run(async () => {
          await accountRequest(`/admin/accounts/${selected.id}`, { method: "PATCH", body: accountDetails });
          setSelected({ ...selected, ...accountDetails }); setNotice("账户设置已更新");
        });
      }}><fieldset disabled={busy}>
        <label className="account-field"><span>账户名称</span><input required maxLength={120} value={accountDetails.name} onChange={e => setAccountDetails({ ...accountDetails, name: e.target.value })} /></label>
        <label className="account-field"><span>外部真人资产目录（可选）</span><input maxLength={120} value={accountDetails.managed_asset_project} onChange={e => setAccountDetails({ ...accountDetails, managed_asset_project: e.target.value })} /></label>
        <p className="account-help">填写此账户专属的方舟 ProjectName，不能与其他账户共用。留空不启用，不影响普通图片资产。</p>
        <button className="primary-button">保存账户设置</button>
      </fieldset></form>
    </details>}
    {(selected || !admin) && <section>
      <h2>{admin ? `${selected.name} · 用户` : "成员列表"}</h2>
      <div className="account-table-wrap"><table>
        <thead><tr><th>姓名</th><th>手机号</th><th>身份</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>{memberRows.map(item => <tr key={item.id}>
          <td>{item.display_name}</td><td>{item.username}</td><td>{item.role === "owner" ? "负责人" : "成员"}</td><td>{statusText[item.status]}</td>
          <td><div className="account-actions">
            {(item.status !== "disabled" || !admin) && <button className="text-button" disabled={busy} onClick={() => reset(item)}>{item.status !== "active" ? "重新邀请" : "重置密码"}</button>}
            {!admin && item.role !== "owner" && item.status !== "disabled" && <button className="text-button" disabled={busy} onClick={() => setConfirmation(item)}>移除</button>}
          </div></td>
        </tr>)}</tbody>
      </table></div>
    </section>}
  </main>;
}
