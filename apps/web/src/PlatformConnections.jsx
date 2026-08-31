import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwise,
  CaretDown,
  Check,
  CheckCircle,
  CircleNotch,
  Gear,
  LinkSimple,
  ShieldCheck,
  UploadSimple,
  X,
} from "@phosphor-icons/react";

import {
  connectionHealthMeta,
  findPlatformConnection,
  PLATFORM_IDS,
  platformLabel,
} from "./platform-connection-ui.js";
import { PlatformBrandLogo } from "./PlatformBrandLogo.jsx";
import "./platform-connections.css";

const STRATEGIES = [
  { value: "on_auth_required", label: "平台要求登录时使用" },
  { value: "always", label: "所有链接始终使用" },
  { value: "disabled", label: "暂停使用" },
];

function formatDate(value, fallback = "尚未验证") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function sourceLabel(connection) {
  if (!connection?.configured) return "尚未选择连接方式";
  if (connection.source === "browser_profile") {
    const browser = {
      chrome: "Chrome",
      edge: "Edge",
      firefox: "Firefox",
      brave: "Brave",
    }[connection.browser] || connection.browser;
    return `${browser || "浏览器"} · ${connection.browser_profile_label || "默认用户"}`;
  }
  return connection.legacy_imported ? "旧配置已安全迁移" : "本机加密 cookies.txt";
}

export function PlatformConnections({
  data,
  error,
  initialPlatform = "",
  loading,
  onBack,
  onNotice,
  onRefresh,
  request,
}) {
  const [editorPlatform, setEditorPlatform] = useState(null);
  const [method, setMethod] = useState("browser");
  const [browsers, setBrowsers] = useState([]);
  const [browserLoading, setBrowserLoading] = useState(false);
  const [browser, setBrowser] = useState("chrome");
  const [profileKey, setProfileKey] = useState("");
  const [strategy, setStrategy] = useState("on_auth_required");
  const [consent, setConsent] = useState(false);
  const [cookieFile, setCookieFile] = useState(null);
  const [testUrl, setTestUrl] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState("");
  const fileInputRef = useRef(null);
  const initialPlatformRef = useRef(initialPlatform);

  const editorConnection = findPlatformConnection(data, editorPlatform);
  const selectedBrowser = browsers.find((item) => item.browser === browser);
  const profiles = selectedBrowser?.profiles || [];

  useEffect(() => {
    if (!profiles.length) {
      setProfileKey("");
      return;
    }
    if (!profiles.some((item) => item.key === profileKey)) {
      setProfileKey(profiles.find((item) => item.most_recent)?.key || profiles[0].key);
    }
  }, [browser, profileKey, profiles]);

  const configuredCount = useMemo(
    () => data?.items?.filter((item) => item.configured).length || 0,
    [data],
  );

  async function loadBrowsers() {
    setBrowserLoading(true);
    setActionError("");
    try {
      const payload = await request("/settings/platform-connections/browsers");
      setBrowsers(payload.browsers || []);
      const recommended = payload.browsers?.find(
        (item) => item.installed && item.profiles?.some((profile) => profile.most_recent),
      ) || payload.browsers?.find((item) => item.installed && item.profiles?.length);
      if (recommended) {
        setBrowser(recommended.browser);
        setProfileKey(
          recommended.profiles.find((profile) => profile.most_recent)?.key
            || recommended.profiles[0]?.key
            || "",
        );
      }
    } catch (requestError) {
      setActionError(requestError.message);
    } finally {
      setBrowserLoading(false);
    }
  }

  useEffect(() => {
    const platform = initialPlatformRef.current;
    if (!platform) return;
    initialPlatformRef.current = "";
    openEditor(platform);
  }, []);

  function openEditor(platform, preferredMethod) {
    const connection = findPlatformConnection(data, platform);
    setEditorPlatform(platform);
    setMethod(
      preferredMethod
        || (connection?.source === "netscape_file" ? "file" : "browser"),
    );
    setStrategy(connection?.usage_strategy || "on_auth_required");
    setBrowser(connection?.browser || "chrome");
    setProfileKey(connection?.browser_profile_key || "");
    setConsent(false);
    setCookieFile(null);
    setTestUrl("");
    setActionError("");
    if (!browsers.length) loadBrowsers();
  }

  function closeEditor() {
    if (busy) return;
    setEditorPlatform(null);
    setActionError("");
    setCookieFile(null);
  }

  async function saveBrowser() {
    if (!profileKey) {
      setActionError("请选择一个浏览器用户配置");
      return;
    }
    if (!consent) {
      setActionError("请先确认本机浏览器登录信息读取授权");
      return;
    }
    setBusy("browser");
    setActionError("");
    try {
      await request(`/settings/platform-connections/${editorPlatform}/browser`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          browser,
          profile_key: profileKey,
          usage_strategy: strategy,
          consent_confirmed: true,
        }),
      });
      await onRefresh();
      onNotice({ type: "success", message: `${platformLabel(editorPlatform)}登录状态已读取` });
      setEditorPlatform(null);
      setCookieFile(null);
    } catch (requestError) {
      setActionError(requestError.message);
    } finally {
      setBusy("");
    }
  }

  async function importCookies() {
    if (!cookieFile) {
      setActionError("请选择 Netscape 格式的 cookies.txt 文件");
      return;
    }
    setBusy("file");
    setActionError("");
    try {
      const form = new FormData();
      form.append("file", cookieFile);
      form.append("usage_strategy", strategy);
      await request(`/settings/platform-connections/${editorPlatform}/cookies`, {
        method: "POST",
        body: form,
      });
      await onRefresh();
      onNotice({ type: "success", message: `${platformLabel(editorPlatform)} Cookie 已加密保存` });
      setEditorPlatform(null);
      setCookieFile(null);
    } catch (requestError) {
      setActionError(requestError.message);
    } finally {
      setBusy("");
    }
  }

  async function validateConnection(platform) {
    setBusy(`validate-${platform}`);
    setActionError("");
    try {
      const payload = await request(`/settings/platform-connections/${platform}/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ test_url: editorPlatform === platform ? testUrl.trim() || null : null }),
      });
      await onRefresh();
      onNotice({ type: "success", message: payload.message });
    } catch (requestError) {
      setActionError(requestError.message);
      await onRefresh().catch(() => undefined);
    } finally {
      setBusy("");
    }
  }

  async function changeStrategy(platform, usageStrategy) {
    setBusy(`strategy-${platform}`);
    setActionError("");
    try {
      await request(`/settings/platform-connections/${platform}/strategy`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ usage_strategy: usageStrategy }),
      });
      await onRefresh();
      onNotice({ type: "success", message: `${platformLabel(platform)}使用策略已更新` });
    } catch (requestError) {
      setActionError(requestError.message);
    } finally {
      setBusy("");
    }
  }

  async function disconnect(platform) {
    if (!window.confirm(`断开${platformLabel(platform)}连接并删除本机保存的登录信息？`)) return;
    setBusy(`disconnect-${platform}`);
    setActionError("");
    try {
      await request(`/settings/platform-connections/${platform}`, { method: "DELETE" });
      await onRefresh();
      onNotice({ type: "success", message: `${platformLabel(platform)}连接已断开` });
      if (editorPlatform === platform) {
        setEditorPlatform(null);
        setCookieFile(null);
      }
    } catch (requestError) {
      setActionError(requestError.message);
    } finally {
      setBusy("");
    }
  }

  return (
    <main className="platform-connections-page">
      <header className="platform-connections-header">
        <div>
          <span className="platform-page-kicker"><LinkSimple size={15} /> 本机平台会话</span>
          <h1>平台连接</h1>
          <p>连接已经登录的平台账户，只在采集对应平台视频时使用。</p>
        </div>
        <div className="platform-header-actions">
          <span className="platform-local-badge"><ShieldCheck size={15} weight="fill" /> 仅此设备</span>
          {onBack && (
            <button className="platform-secondary-button" onClick={onBack} type="button">
              返回新建项目
            </button>
          )}
        </div>
      </header>

      <section className="platform-privacy-note">
        <ShieldCheck size={21} weight="fill" />
        <div>
          <strong>登录信息不会上传到云端</strong>
          <p>
            Cookie 按账户和当前设备隔离；导入文件使用 Windows 加密保存，API、日志和分析报告只记录状态。
          </p>
        </div>
        <span>{configuredCount}/{PLATFORM_IDS.length} 已配置</span>
      </section>

      {error && <div className="platform-page-error" role="alert"><X size={17} />{error}</div>}
      {actionError && !editorPlatform && (
        <div className="platform-page-error" role="alert"><X size={17} />{actionError}</div>
      )}

      <section className="platform-card-grid" aria-busy={loading}>
        {PLATFORM_IDS.map((platform) => {
          const connection = findPlatformConnection(data, platform);
          const health = connectionHealthMeta(connection);
          const cardState = connection?.configured ? "is-configured" : "is-empty";
          return (
            <article
              className={`platform-card platform-${platform} ${cardState}`}
              key={platform}
            >
              <div className="platform-card-topline">
                <PlatformBrandLogo className="platform-logo" platform={platform} />
                <div>
                  <h2>{platformLabel(platform)}</h2>
                  <p>{sourceLabel(connection)}</p>
                </div>
                <span className={`platform-health ${health.tone}`}>{health.label}</span>
              </div>

              {connection?.configured ? (
                <>
                  <dl className="platform-card-metadata">
                    <div><dt>Cookie</dt><dd>{connection.cookie_count || 0} 条</dd></div>
                    <div><dt>最近验证</dt><dd>{formatDate(connection.last_validated_at)}</dd></div>
                    <div><dt>最近成功</dt><dd>{formatDate(connection.last_success_at, "尚未采集")}</dd></div>
                  </dl>
                  {connection.last_error_message && (
                    <div className="platform-card-warning">{connection.last_error_message}</div>
                  )}
                  <label className="platform-strategy-field">
                    <span>使用策略</span>
                    <span className="platform-select-wrap">
                      <select
                        aria-label={`${platformLabel(platform)}使用策略`}
                        disabled={Boolean(busy)}
                        onChange={(event) => changeStrategy(platform, event.target.value)}
                        value={connection.usage_strategy}
                      >
                        {STRATEGIES.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                      <CaretDown size={14} />
                    </span>
                  </label>
                  <div className="platform-card-actions">
                    <button
                      disabled={Boolean(busy)}
                      onClick={() => validateConnection(platform)}
                      type="button"
                    >
                      {busy === `validate-${platform}`
                        ? <CircleNotch className="spin" size={16} />
                        : <CheckCircle size={16} />}
                      检查状态
                    </button>
                    <button disabled={Boolean(busy)} onClick={() => openEditor(platform)} type="button">
                      <ArrowClockwise size={16} /> 更新
                    </button>
                    <button
                      className="danger"
                      disabled={Boolean(busy)}
                      onClick={() => disconnect(platform)}
                      type="button"
                    >
                      断开
                    </button>
                  </div>
                </>
              ) : (
                <div className="platform-empty-state">
                  <p>连接后，可在平台要求登录时自动使用当前设备的登录状态。</p>
                  <div>
                    <button className="platform-primary-button" onClick={() => openEditor(platform, "browser")} type="button">
                      自动检测浏览器
                    </button>
                    <button className="platform-secondary-button" onClick={() => openEditor(platform, "file")} type="button">
                      导入 cookies.txt
                    </button>
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </section>

      {editorPlatform && (
        <div className="platform-editor-backdrop" role="presentation" onMouseDown={closeEditor}>
          <aside
            aria-labelledby="platform-editor-title"
            aria-modal="true"
            className="platform-editor"
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
          >
            <header>
              <div>
                <span>仅此设备</span>
                <h2 id="platform-editor-title">配置{platformLabel(editorPlatform)}</h2>
                <p>选择本机登录状态的读取方式。</p>
              </div>
              <button aria-label="关闭" disabled={Boolean(busy)} onClick={closeEditor} type="button">
                <X size={19} />
              </button>
            </header>

            <div className="platform-editor-body">
              <div className="platform-method-tabs" role="tablist" aria-label="连接方式">
                <button
                  aria-selected={method === "browser"}
                  className={method === "browser" ? "active" : ""}
                  onClick={() => setMethod("browser")}
                  role="tab"
                  type="button"
                >
                  <Gear size={17} /> 自动读取浏览器
                </button>
                <button
                  aria-selected={method === "file"}
                  className={method === "file" ? "active" : ""}
                  onClick={() => setMethod("file")}
                  role="tab"
                  type="button"
                >
                  <UploadSimple size={17} /> 导入 cookies.txt
                </button>
              </div>

              {method === "browser" ? (
                <section className="platform-method-panel">
                  <div className="platform-method-heading">
                    <div>
                      <h3>从已登录浏览器读取</h3>
                      <p>直接读取本机 Profile，不保存其他网站 Cookie。</p>
                    </div>
                    <button disabled={browserLoading || Boolean(busy)} onClick={loadBrowsers} type="button">
                      {browserLoading ? <CircleNotch className="spin" size={15} /> : <ArrowClockwise size={15} />}
                      重新检测
                    </button>
                  </div>
                  <label className="platform-field">
                    <span>浏览器</span>
                    <span className="platform-select-wrap">
                      <select onChange={(event) => setBrowser(event.target.value)} value={browser}>
                        {browsers.map((item) => (
                          <option disabled={!item.installed || !item.profiles.length} key={item.browser} value={item.browser}>
                            {item.label}{!item.installed ? " · 未安装" : !item.profiles.length ? " · 未发现 Profile" : ""}
                          </option>
                        ))}
                      </select>
                      <CaretDown size={14} />
                    </span>
                  </label>
                  <label className="platform-field">
                    <span>用户配置</span>
                    <span className="platform-select-wrap">
                      <select onChange={(event) => setProfileKey(event.target.value)} value={profileKey}>
                        {!profiles.length && <option value="">未发现可用 Profile</option>}
                        {profiles.map((profile) => (
                          <option key={profile.key} value={profile.key}>
                            {profile.label}{profile.most_recent ? " · 最近使用" : ""}
                          </option>
                        ))}
                      </select>
                      <CaretDown size={14} />
                    </span>
                  </label>
                  <label className="platform-consent">
                    <input checked={consent} onChange={(event) => setConsent(event.target.checked)} type="checkbox" />
                    <span className="platform-checkbox">{consent && <Check size={12} weight="bold" />}</span>
                    <span>
                      我授权 ViralDNA 在本机读取该 Profile 的 Cookie；仅向匹配的{platformLabel(editorPlatform)}域名发送。
                    </span>
                  </label>
                  <div className="platform-browser-caveat">
                    新版 Chrome 安全保护可能阻止第三方程序解密。失败时无需修改系统安全策略，直接改用 cookies.txt。
                  </div>
                </section>
              ) : (
                <section className="platform-method-panel">
                  <div className="platform-method-heading">
                    <div>
                      <h3>导入 Netscape Cookie 文件</h3>
                      <p>只保留{platformLabel(editorPlatform)}域名，并使用 Windows 加密保存。</p>
                    </div>
                  </div>
                  <input
                    accept=".txt,text/plain"
                    hidden
                    onChange={(event) => setCookieFile(event.target.files?.[0] || null)}
                    ref={fileInputRef}
                    type="file"
                  />
                  <button className={`platform-file-picker ${cookieFile ? "selected" : ""}`} onClick={() => fileInputRef.current?.click()} type="button">
                    <UploadSimple size={22} />
                    <span>
                      <strong>{cookieFile?.name || "选择 cookies.txt"}</strong>
                      <small>{cookieFile ? `${(cookieFile.size / 1024).toFixed(1)} KB` : "UTF-8 · 不超过 2 MB"}</small>
                    </span>
                  </button>
                </section>
              )}

              <label className="platform-field">
                <span>使用策略</span>
                <span className="platform-select-wrap">
                  <select onChange={(event) => setStrategy(event.target.value)} value={strategy}>
                    {STRATEGIES.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                  <CaretDown size={14} />
                </span>
              </label>

              {editorConnection?.configured && (
                <label className="platform-field">
                  <span>测试视频链接（可选）</span>
                  <input
                    onChange={(event) => setTestUrl(event.target.value)}
                    placeholder={`粘贴${platformLabel(editorPlatform)}视频链接进行在线测试`}
                    value={testUrl}
                  />
                </label>
              )}

              {actionError && <div className="platform-page-error" role="alert"><X size={17} />{actionError}</div>}
            </div>

            <footer>
              {editorConnection?.configured && (
                <button
                  className="platform-secondary-button"
                  disabled={Boolean(busy)}
                  onClick={() => validateConnection(editorPlatform)}
                  type="button"
                >
                  检查现有连接
                </button>
              )}
              <button
                className="platform-primary-button"
                disabled={Boolean(busy)}
                onClick={method === "browser" ? saveBrowser : importCookies}
                type="button"
              >
                {busy ? <CircleNotch className="spin" size={16} /> : <CheckCircle size={16} weight="fill" />}
                {method === "browser" ? "读取并保存" : "校验并导入"}
              </button>
            </footer>
          </aside>
        </div>
      )}
    </main>
  );
}
