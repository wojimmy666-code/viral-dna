import { Button } from "../ui/system/Button.jsx";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { accountRequest } from "./account-client.js";
import { PHONE_INPUT_PROPS, pastePhone, phoneError } from "./account-form.js";
import { AdminStorageQuota, AdminSyncServer } from "./StorageManagement.jsx";
import { formatStorage } from "./storage-ui.js";
import { MemberPhoneForm } from "./MemberPhoneForm.jsx";
import { EnterpriseMembers } from "./EnterpriseMembers.jsx";

const statusText = { active: "已启用", disabled: "已停用", pending: "待激活" };
export function AccountManagement(props) {
  return props.admin ? <AdminAccountManagement /> : <EnterpriseMembers session={props.session} />;
}

function AdminAccountManagement() {
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
  const [phoneTarget, setPhoneTarget] = useState(null);
  const phoneTrigger = useRef(null);
  useEffect(() => { if (!phoneTarget) phoneTrigger.current?.focus(); }, [phoneTarget]);
  const [accountDetails, setAccountDetails] = useState({ name: "", managed_asset_project: "" });
  const [draft, setDraft] = useState({ kind: "personal", name: "", username: "", display_name: "" });
  async function refresh() {
    try {
      const response = await accountRequest("/admin/accounts");
      setItems(response.items); setError("");
    } catch (failure) { setError(failure.message); } finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, []);
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
      const body = { ...draft, username: draft.username.trim() };
      const response = await accountRequest("/admin/accounts", { method: "POST", body });
      showLink(response.activation_token); setCreating(false);
      setDraft({ kind: "personal", name: "", username: "", display_name: "" });
    });
  }
  async function openMembers(account) {
    setSelected(account); setMembers([]);
    setAccountDetails({ name: account.name, managed_asset_project: account.managed_asset_project || "" });
    await run(async () => { const response = await accountRequest(`/admin/accounts/${account.id}/members`); setMembers(response.items); });
  }
  function closePhoneForm() {
    setPhoneTarget(null);
  }
  function phoneChanged(result) {
    setMembers(current => current.map(member => member.id === result.id ? { ...member, username: result.username } : member));
    setActivation("");
    setNotice("手机号已修改，该用户请使用新手机号和原密码重新登录。");
    closePhoneForm();
  }
  async function reset(member) {
    await run(async () => {
      const path = `/admin/accounts/${selected.id}/members/${member.id}/reset`;
      const response = await accountRequest(path, { method: "POST" }); showLink(response.activation_token);
    });
  }
  async function confirmAction() {
    const action = confirmation;
    await run(async () => {
      await accountRequest(`/admin/accounts/${action.id}`, { method: "PATCH", body: { status: action.status === "disabled" ? "active" : "disabled" } });
      setConfirmation(null);
    });
  }
  const memberRows = members;
  return <main className="account-management">
    <Link to="/admin/providers">返回平台设置</Link>
    <header className="account-management-heading"><h1>账户管理</h1><Button className="primary-button" onClick={() => { setCreating(true); setActivation(""); }} disabled={busy || Boolean(phoneTarget)}>新建账户</Button></header>
    {error && <p className="account-error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <AdminSyncServer />
    {selected && <AdminStorageQuota key={selected.id} accountId={selected.id} accountName={selected.name} onUpdated={refresh} />}
    {activation && <section className="account-activation-link"><h2>激活／重置链接</h2><p>链接 72 小时内有效，仅可使用一次。请单独发送给本人。</p><input aria-label="激活链接" value={activation} readOnly onFocus={event => event.target.select()} /><div className="account-actions"><Button className="secondary-button" onClick={async () => { try { await navigator.clipboard.writeText(activation); setNotice("链接已复制"); } catch { setError("请选中链接后手动复制"); } }}>复制链接</Button><Button className="text-button" onClick={() => setActivation("")}>关闭</Button></div></section>}
    {creating && <form className="account-create-form" onSubmit={create}><fieldset disabled={busy}><h2>新建独立账户</h2>
      <label className="account-field"><span>账户类型</span><select value={draft.kind} onChange={e => setDraft({ ...draft, kind: e.target.value })}><option value="personal">个人账户</option><option value="enterprise">企业账户</option></select></label><label className="account-field"><span>{draft.kind === "enterprise" ? "企业名称" : "账户名称"}</span><input name="name" required maxLength={120} value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label>
      <label className="account-field"><span>{draft.kind === "enterprise" ? "负责人手机号" : "手机号"}</span><input {...PHONE_INPUT_PROPS} name="username" required autoComplete="off" value={draft.username} onChange={e => setDraft({ ...draft, username: e.target.value.trim() })} onPaste={event => pastePhone(event, value => setDraft(current => ({ ...current, username: value })))} /></label>
      <label className="account-field"><span>姓名</span><input name="display_name" required maxLength={120} value={draft.display_name} onChange={e => setDraft({ ...draft, display_name: e.target.value })} /></label>
      <p className="account-help">每个账户使用独立手机号，由本人通过激活链接设置至少 8 位密码。</p><div className="account-actions"><Button className="primary-button" type="submit">{busy ? "处理中…" : "创建并生成激活链接"}</Button><Button className="secondary-button" type="button" onClick={() => setCreating(false)}>取消</Button></div>
    </fieldset></form>}
    {confirmation && <div className="account-edit-notice"><span>{`确认${confirmation.status === "disabled" ? "启用" : "停用"}“${confirmation.name}”？`}</span><Button className="secondary-button" disabled={busy} onClick={confirmAction}>确认</Button><Button className="text-button" disabled={busy} onClick={() => setConfirmation(null)}>取消</Button></div>}
    {loading ? <p role="status">正在读取…</p> : <div className="account-table-wrap"><table><thead><tr><th>账户</th><th>类型</th><th>成员</th><th>状态</th><th>存储用量 / 容量</th><th>操作</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td>{item.name}</td><td>{item.kind === "enterprise" ? "企业" : "个人"}</td><td>{item.member_count}</td><td>{statusText[item.status]}</td><td>{item.storage ? `${formatStorage(item.storage.used_bytes)} / ${formatStorage(item.storage.limit_bytes)}` : "—"}</td><td><div className="account-actions"><Button className="text-button" disabled={busy || Boolean(phoneTarget)} onClick={() => openMembers(item)}>用户与容量</Button><Button className="text-button" disabled={busy || Boolean(phoneTarget)} onClick={() => setConfirmation(item)}>{item.status === "disabled" ? "启用" : "停用"}</Button></div></td></tr>)}</tbody></table></div>}
    {selected && <details className="account-details">
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
        <Button type="submit" className="primary-button">保存账户设置</Button>
      </fieldset></form>
    </details>}
    {selected && <section>
      <h2>{selected.name} · 用户</h2>
      {phoneTarget && <MemberPhoneForm key={phoneTarget.id} accountId={selected.id}
        member={phoneTarget} onClose={closePhoneForm} onChanged={phoneChanged}
        onReload={() => { closePhoneForm(); void openMembers(selected); }} />}
      <div className="account-table-wrap"><table>
        <thead><tr><th>姓名</th><th>手机号</th><th>身份</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>{memberRows.map(item => <tr key={item.id}>
          <td>{item.display_name}</td><td>{item.username}</td><td>{item.role === "owner" ? "负责人" : "成员"}</td><td>{statusText[item.status]}</td>
          <td><div className="account-actions">
            <Button className="text-button" disabled={busy || Boolean(phoneTarget)}
              aria-label={`${item.display_name}：修改手机号`} aria-expanded={phoneTarget?.id === item.id}
              onClick={event => { phoneTrigger.current = event.currentTarget; setPhoneTarget(item); setNotice(""); setError(""); }}>修改手机号</Button>
            {item.status !== "disabled" && <Button className="text-button" disabled={busy || Boolean(phoneTarget)} onClick={() => reset(item)}>{item.status !== "active" ? "重新邀请" : "重置密码"}</Button>}
          </div></td>
        </tr>)}</tbody>
      </table></div>
    </section>}
  </main>;
}
