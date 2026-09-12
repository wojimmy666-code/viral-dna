import { useEffect, useId, useRef, useState } from "react";
import { accountRequest } from "./account-client.js";
import { PHONE_INPUT_PROPS, pastePhone, phoneError } from "./account-form.js";

export function MemberPhoneForm({ accountId, member, onClose, onChanged, onReload }) {
  const headingId = useId();
  const errorId = useId();
  const inputRef = useRef(null);
  const headingRef = useRef(null);
  const submitting = useRef(false);
  const [phone, setPhone] = useState("");
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => { (review ? headingRef : inputRef).current?.focus(); }, [review]);

  function edit(value) { setPhone(value); setError(null); }
  async function submit(event) {
    event.preventDefault();
    if (submitting.current || error?.code === "username_changed") return;
    const username = phone.trim();
    const message = phoneError(username)
      || (username === member.username ? "新手机号不能与当前手机号相同" : "");
    if (message) { setError({ message }); inputRef.current?.focus(); return; }
    setError(null);
    if (!review) { setPhone(username); setReview(true); return; }
    submitting.current = true; setBusy(true);
    try {
      const result = await accountRequest(
        `/admin/accounts/${accountId}/members/${member.id}/phone`,
        { method: "PATCH", body: { current_username: member.username, username, confirm_change: true } },
      );
      onChanged(result);
    } catch (failure) {
      setError({ message: failure.message, code: failure.code });
      // Keep the draft, but a changed identity must be explicitly reloaded.
      if (failure.code !== "username_changed") setReview(false);
    } finally { submitting.current = false; setBusy(false); }
  }

  return <form className="account-create-form account-phone-form" onSubmit={submit}
    aria-labelledby={headingId} aria-busy={busy} noValidate
    onKeyDown={event => { if (event.key === "Escape" && !submitting.current) { event.preventDefault(); onClose(); } }}>
    <fieldset disabled={busy}>
      <h3 id={headingId} ref={headingRef} tabIndex={-1}>{review ? "确认修改手机号" : "修改手机号"} · {member.display_name}</h3>
      <p className="account-help">只修改此用户的登录手机号，密码、账户归属、项目和资产保持不变。</p>
      {review ? <>
        <dl className="account-phone-review">
          <div><dt>当前手机号</dt><dd>{member.username}</dd></div>
          <div><dt>新手机号</dt><dd>{phone}</dd></div>
        </dl>
        <p className="account-help">确认后该用户需重新登录；旧邀请、重置链接和同步令牌将失效，已连接的同步设备需重新认证。不会影响其他成员。</p>
        {member.status !== "active" && <p className="account-help">用户状态不变；待激活用户需要重新发送邀请。</p>}
      </> : <>
        <p className="account-phone-current">当前手机号：{member.username}</p>
        <label className="account-field"><span>新手机号</span>
          <input {...PHONE_INPUT_PROPS} ref={inputRef} name="new_phone" autoComplete="off"
            value={phone} onChange={event => edit(event.target.value.trim())}
            onPaste={event => pastePhone(event, edit)} required
            aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined} />
        </label>
      </>}
      {error && <p className="account-error" role="alert" id={errorId}>{error.message}</p>}
      <div className="account-actions">
        {error?.code === "username_changed"
          ? <button type="button" className="secondary-button" onClick={onReload}>重新读取用户列表</button>
          : <button type="submit" className="primary-button">{busy ? "正在修改…" : review ? "确认修改" : "下一步"}</button>}
        {review && !error && <button type="button" className="secondary-button" onClick={() => setReview(false)}>返回修改</button>}
        <button type="button" className="text-button" onClick={onClose}>取消</button>
      </div>
    </fieldset>
  </form>;
}
