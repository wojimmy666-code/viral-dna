import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { accountRequest, currentAccountSession, mediaUrl } from "./account-client.js";
import { PHONE_INPUT_PROPS, passwordError, phoneError, pastePhone } from "./account-form.js";
import { formatStorage, historyOffset, quotaBytes, STORAGE_GB, storageRatio, syncStatus } from "./storage-ui.js";
import "./storage.css";

export function StorageUsageStrip() {
  const [usage, setUsage] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const session = currentAccountSession();
  useEffect(() => {
    if (!session?.account_id) return;
    let alive = true;
    const refresh = async () => { try { const data = await accountRequest("/account/storage"); if (data.connection?.confirmed) { try { const remote = await accountRequest("/account/storage/remote-usage"); if (alive) setUsage({ ...data, ...remote, on_server: true }); } catch { if (alive) setUsage({ ...data, local_fallback: true }); } } else if (alive) setUsage(data); } catch { /* The full management page owns retry/error details. */ } };
    void refresh(); const timer = setInterval(refresh, 15000);
    return () => { alive = false; clearInterval(timer); };
  }, [session?.account_id]);
  if (!session?.account_id) return null;
  return <div className="storage-strip"><span>{usage ? `${usage.on_server ? "服务器存储" : usage.local_fallback ? "本地存储（服务器暂不可用）" : "账户存储"} ${formatStorage(usage.used_bytes)} / ${formatStorage(usage.limit_bytes)}` : "账户存储"}</span>{usage?.connection?.confirmed ? <button className="text-button" disabled={busy} onClick={async () => { setBusy(true); setMessage(""); try { await accountRequest("/account/storage/sync", { method: "POST" }); setMessage("已开始同步，本地文件继续保留"); } catch (failure) { setMessage(failure.message); } finally { setBusy(false); } }}>一键同步到服务器</button> : <Link to="/account/storage">连接服务器并同步</Link>}<Link to="/account/storage">存储管理</Link>{message && <span role="status">{message}</span>}</div>;
}

export function StorageManagement({ session }) {
  const [summary, setSummary] = useState(null);
  const [remote, setRemote] = useState(null);
  const [history, setHistory] = useState({ items: [], total: 0 });
  const [kind, setKind] = useState("image");
  const [trash, setTrash] = useState(false);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [remoteError, setRemoteError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [credentials, setCredentials] = useState({ username: "", password: "" });
  const [confirmation, setConfirmation] = useState(null);
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState("");
  useEffect(() => { setConfirmation(null); }, [kind, trash, offset]);
  useEffect(() => {
    let alive = true;
    async function refresh() {
      try {
        const data = await accountRequest("/account/storage");
        if (!alive) return;
        setSummary(data);
        if (data.connection?.confirmed) {
          try { const value = await accountRequest("/account/storage/remote-usage"); if (alive) { setRemote(value); setRemoteError(""); } }
          catch (failure) { if (alive) { setRemote(null); setRemoteError(failure.message); } }
        } else { setRemote(null); setRemoteError(""); }
      } catch (failure) { if (alive) setError(failure.message); }
    }
    void refresh(); const timer = setInterval(refresh, 10000);
    return () => { alive = false; clearInterval(timer); };
  }, [revision, session.account_id]);
  useEffect(() => {
    let alive = true; setLoading(true); setHistory({ items: [], total: 0 });
    accountRequest(`/account/storage/history?kind=${kind}&trash=${trash}&offset=${offset}&limit=30`)
      .then(value => { if (alive) { setHistory(value); if (offset > 0 && offset >= value.total) setOffset(historyOffset(value.total, offset)); } }).catch(failure => { if (alive) setError(failure.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [kind, trash, offset, revision, session.account_id]);
  async function run(operation, success = "") {
    setBusy(true); setError(""); setNotice("");
    try { await operation(); setRevision(value => value + 1); setNotice(success); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  async function connect(event) {
    event.preventDefault(); const invalid = phoneError(credentials.username) || passwordError(credentials.password);
    if (invalid) { setError(invalid); return; }
    await run(async () => { await accountRequest("/account/storage/connection", { method: "POST", body: credentials }); setCredentials(value => ({ ...value, password: "" })); });
  }
  const connection = summary?.connection || {};
  const usage = remote || summary;
  return <main className="account-management storage-management">
    <Link to="/assets">返回资产库</Link>
    <header className="account-management-heading"><h1>存储管理与生成历史</h1><button className="secondary-button" disabled={busy} onClick={() => { setError(""); setRevision(value => value + 1); }}>刷新</button></header>
    {error && <p className="account-error" role="alert">{error}</p>}
    {notice && <p className="account-help" role="status">{notice}</p>}
    <section className="storage-overview" aria-label="账户空间">
      <div className="storage-summary-line"><h2>{remote ? "服务器空间" : "当前账户存储"}</h2><span>{usage ? `${formatStorage(usage.used_bytes)} / ${formatStorage(usage.limit_bytes)}` : "正在读取容量…"}</span></div>
      {usage && <><progress value={storageRatio(usage)} max="100" aria-label="账户空间使用比例" /><p className="account-help">任务预留 {formatStorage(usage.reserved_bytes)} · 可用 {formatStorage(usage.available_bytes)}{session.account_kind === "enterprise" ? " · 企业成员共享额度" : ""}</p></>}
      {usage && storageRatio(usage) >= 80 && <p className="account-help">{usage.available_bytes === 0 ? "空间已用满，新增上传和生成需要先清理文件或联系管理员扩容。" : "空间即将用满，可清理不再使用的文件或联系管理员扩容。"}</p>}
      {remoteError && <p className="account-error" role="alert">服务器容量暂不可用：{remoteError}。上方显示当前后端存储，不代表服务器剩余空间。</p>}
      <p className="account-help">资产和生成历史合计占用；相同文件只计一次。回收站仍占空间，系统缩略图和缓存不计入额度。</p>
      {summary?.inventory_state === "scanning" && <p className="account-help" role="status">正在清点现有文件，完成后可新增上传和生成；可继续浏览现有资产。</p>}
      {summary?.inventory_state === "failed" && <p className="account-help">存储清点尚未完成，请重试归档。</p>}
    </section>
    <section className="storage-sync-section">
      <div className="storage-summary-line"><h2>服务器同步</h2><button className="primary-button" disabled={busy || !connection.confirmed} onClick={() => run(() => accountRequest("/account/storage/sync", { method: "POST" }), "已开始后台同步，本地原文件继续保留。")}>同步到服务器</button></div>
      {!summary?.server_url && <p className="account-help">服务器尚未配置。管理员设置 HTTPS 地址后，即可连接当前账户并同步。</p>}
      {connection.confirmed && <p className="account-help">{connection.account_name} · {connection.server_url}{connection.auto_sync ? " · 自动同步已启用" : ""}</p>}
      {summary?.retained_on_server_count > 0 && <p className="account-help">{summary.retained_on_server_count} 项保留了服务器上的修改或删除状态，没有被本地同步覆盖。</p>}
      {summary?.archive_failure_count > 0 && <p className="account-help">{summary.archive_failure_count} 项归档未完成。<button className="text-button" disabled={busy} onClick={() => run(() => accountRequest("/account/storage/reconcile", { method: "POST" }))}>重试归档</button></p>}
      {session.role === "owner" && summary?.server_url && <details><summary>{connection.confirmed ? "连接设置" : "连接服务器账户"}</summary>
        <form className="storage-connection-form" onSubmit={connect}><fieldset disabled={busy}>
          <p className="account-help">仅将当前账户的资产和历史同步到以下服务器；密码只用于本次登录，不会保存。</p>
          <p className="storage-address">{summary.server_url}</p>
          {!connection.confirmed && <><label className="account-field"><span>服务器账户手机号</span><input {...PHONE_INPUT_PROPS} autoComplete="username" required value={credentials.username} onChange={event => setCredentials({ ...credentials, username: event.target.value.trim() })} onPaste={event => pastePhone(event, value => setCredentials(current => ({ ...current, username: value })))} /></label>
          <label className="account-field"><span>服务器登录密码</span><input type="password" autoComplete="current-password" minLength={8} required value={credentials.password} onChange={event => setCredentials({ ...credentials, password: event.target.value })} /></label></>}
          <div className="account-actions">{!connection.confirmed && <button className="secondary-button" disabled={!summary.secret_store_available}>验证账户</button>}{connection.confirmed && <button type="button" className="text-button" onClick={() => run(() => accountRequest("/account/storage/connection", { method: "DELETE" }), "服务器连接已断开，已保存文件不受影响。")}>断开连接</button>}</div>
          {!summary.secret_store_available && <p className="account-help">当前设备的安全凭据存储不可用，暂不能连接服务器。</p>}
        </fieldset></form>
      </details>}
      {connection.account_id && !connection.confirmed && <div className="storage-confirmation" role="status"><span>确认将本地数据同步至“{connection.account_name}”（{connection.account_kind === "enterprise" ? "企业账户" : "个人账户"}）？</span><button className="secondary-button" disabled={busy} onClick={() => run(() => accountRequest("/account/storage/connection/confirm", { method: "POST", body: { account_id: connection.account_id } }))}>确认目标账户</button></div>}
      {!!summary?.jobs?.length && <details className="storage-jobs"><summary>同步进度 · {syncStatus[summary.jobs[0].status] || "等待同步"}</summary>{summary.jobs.map(job => <div key={job.id}><span>{syncStatus[job.status]} · {job.completed}/{job.total} 个文件</span>{job.error && <p className="account-error">{job.error}</p>}</div>)}</details>}
    </section>
    <section aria-label="长期保存的文件">
      <div className="storage-history-heading"><h2>{connection.confirmed ? "本地文件与生成历史" : "文件与生成历史"}</h2><label><input type="checkbox" checked={trash} onChange={event => { setTrash(event.target.checked); setOffset(0); }} /> 回收站</label></div>
      {connection.confirmed && <p className="account-help">下方清理只影响本地记录，不删除已同步的服务器文件。释放服务器空间，请到 <a href={`${connection.server_url}/account/storage`} target="_blank" rel="noopener noreferrer">服务器存储管理</a> 操作。</p>}
      <div className="storage-tabs" role="group" aria-label="文件类型">{[["image", "生成图片"], ["video", "生成视频"], ["asset", "资产"], ["export", "导出"], ["source", "原视频"], ["audio", "音频"]].map(([value, label]) => <button aria-pressed={kind === value} className="text-button" key={value} onClick={() => { setKind(value); setOffset(0); }}>{label}</button>)}</div>
      {loading && <p className="account-help" role="status">正在读取记录…</p>}
      {!loading && !history.items.length && <p className="account-help">{trash ? "回收站中没有此类文件。" : "暂无此类记录。生成结果会自动保留，不需要先加入资产库。"}</p>}
      <div className="storage-history-list">{history.items.map(item => <article className="storage-history-row" key={item.key}>
        <div className="storage-history-thumb">{item.thumbnail_url || kind === "image" ? <img loading="lazy" src={mediaUrl(item.thumbnail_url || item.content_url)} alt="" /> : <span>{kind === "video" ? "视频" : "文件"}</span>}</div>
        <div className="storage-history-info"><strong>{item.metadata.asset?.name || item.metadata.project_name || item.metadata.filename || "生成结果"}</strong><p className="account-help">{item.metadata.model || item.metadata.mime_type} · {formatStorage(item.size_bytes)} · {new Date(item.created_at * 1000).toLocaleString()}</p>
          <details><summary>查看记录</summary>{(kind === "image" || item.metadata.mime_type?.startsWith("image/")) && <img className="storage-history-preview" loading="lazy" src={mediaUrl(item.content_url)} alt={item.metadata.asset?.name || item.metadata.filename || "生成图片"} />}{(kind === "video" || kind === "export" || item.metadata.mime_type?.startsWith("video/")) && <video controls preload="none" src={mediaUrl(item.content_url)} />}{item.metadata.prompt_snapshot && <pre>{typeof item.metadata.prompt_snapshot === "string" ? item.metadata.prompt_snapshot : JSON.stringify(item.metadata.prompt_snapshot, null, 2)}</pre>}<p className="account-help">{item.metadata.shot_plan_id ? `分镜来源：${item.metadata.shot_plan_id}` : "原文件长期保存，除非明确执行永久删除。"}</p></details>
        </div>
        <div className="storage-row-actions"><a href={mediaUrl(`${item.content_url}?download=true`)} download>下载</a>{trash ? <><button className="text-button" disabled={busy} onClick={() => run(() => accountRequest(`/account/storage/entries/${encodeURIComponent(item.key)}/restore`, { method: "POST" }))}>恢复</button><button className="text-button" disabled={busy} onClick={() => setConfirmation(item)}>永久删除</button></> : <button className="text-button" disabled={busy} onClick={() => run(() => accountRequest(`/account/storage/entries/${encodeURIComponent(item.key)}/trash`, { method: "POST" }))}>移入回收站</button>}</div>
        {confirmation?.key === item.key && <div className="storage-confirmation"><span>永久删除“{item.metadata.asset?.name || item.metadata.filename || item.metadata.project_name || "此生成结果"}”及不再被引用的原文件？此操作不能撤销，共享文件不会被删除。</span><button className="secondary-button" disabled={busy} onClick={() => run(async () => { await accountRequest(`/account/storage/entries/${encodeURIComponent(item.key)}?confirm=true`, { method: "DELETE" }); setConfirmation(null); }, "记录已永久删除；不再被引用的文件已释放，无法从回收站恢复。")}>确认永久删除</button><button className="text-button" disabled={busy} onClick={() => setConfirmation(null)}>取消</button></div>}
      </article>)}</div>
      {(history.total > 30 || offset > 0) && <div className="storage-pagination"><button className="secondary-button" disabled={offset === 0 || loading} onClick={() => setOffset(value => Math.max(0, value - 30))}>上一页</button><span>{offset + 1}–{Math.min(offset + 30, history.total)} / {history.total}</span><button className="secondary-button" disabled={offset + 30 >= history.total || loading} onClick={() => setOffset(value => value + 30)}>下一页</button></div>}
    </section>
  </main>;
}

export function AdminStorageQuota({ accountId, accountName, onUpdated }) {
  const [usage, setUsage] = useState(null); const [limit, setLimit] = useState(""); const [note, setNote] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { let alive = true; setUsage(null); setError(""); accountRequest(`/admin/accounts/${accountId}/storage`).then(value => { if (alive) { setUsage(value); setLimit(String(value.limit_bytes / STORAGE_GB)); } }).catch(failure => { if (alive) setError(failure.message); }); return () => { alive = false; }; }, [accountId]);
  return <form className="storage-quota-form" onSubmit={async event => { event.preventDefault(); setBusy(true); setError(""); try { const result = await accountRequest(`/admin/accounts/${accountId}/storage`, { method: "PATCH", body: { limit_bytes: quotaBytes(limit), note } }); setUsage(result); onUpdated?.(); } catch (failure) { setError(failure.message); } finally { setBusy(false); } }}>
    <h2>{accountName ? `${accountName} · 存储容量` : "存储容量"}</h2>{usage && <p className="account-help">已用 {formatStorage(usage.used_bytes)} · 任务预留 {formatStorage(usage.reserved_bytes)} · 总容量 {formatStorage(usage.limit_bytes)}</p>}
    {error && <p className="account-error" role="alert">{error}</p>}<fieldset disabled={busy || !usage}><label className="account-field"><span>总容量（GB）</span><input inputMode="decimal" type="number" min="0.001" max="100000" step="any" required value={limit} onChange={event => setLimit(event.target.value)} /></label><label className="account-field"><span>调整备注</span><input maxLength={500} value={note} onChange={event => setNote(event.target.value)} /></label><button className="secondary-button">调整容量</button></fieldset><p className="account-help">立即生效，记录修改前后容量；不能低于已用与任务预留空间之和。</p>
    {!!usage?.audit?.length && <details><summary>容量调整记录</summary>{usage.audit.map(item => { let details = {}; try { details = typeof item.details === "string" ? JSON.parse(item.details) : item.details; } catch { /* Older audit records may have no quota detail. */ } return <p className="account-help" key={item.id}>{new Date(item.created_at * 1000).toLocaleString()} · {formatStorage(details.previous)} → {formatStorage(details.next)}{details.note ? ` · ${details.note}` : ""}</p>; })}</details>}
  </form>;
}

export function AdminSyncServer() {
  const [url, setUrl] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [notice, setNotice] = useState("");
  useEffect(() => { let alive = true; accountRequest("/admin/storage/server").then(value => { if (alive) setUrl(value.url); }).catch(failure => { if (alive) setError(failure.message); }); return () => { alive = false; }; }, []);
  return <details className="storage-server-config"><summary>同步服务器设置</summary><form className="storage-quota-form" onSubmit={async event => { event.preventDefault(); setBusy(true); setError(""); setNotice(""); try { await accountRequest("/admin/storage/server", { method: "PUT", body: { url } }); setNotice("服务器地址已保存，账户负责人需单独登录并确认同步目标。"); } catch (failure) { setError(failure.message); } finally { setBusy(false); } }}><label className="account-field"><span>目标服务器 HTTPS 地址</span><input type="url" placeholder="https://video.example.com" value={url} maxLength={500} onChange={event => setUrl(event.target.value)} /></label><p className="account-help">目标服务器须运行兼容版本的 ViralDNA；只填写域名，不包含路径。修改地址不会自动上传资产。</p>{error && <p className="account-error" role="alert">{error}</p>}{notice && <p className="account-help" role="status">{notice}</p>}<button className="secondary-button" disabled={busy}>保存服务器地址</button></form></details>;
}
