import {
  ArrowLeft,
  CloudArrowUp,
  Cpu,
  Database,
  Key,
  ShieldCheck,
  SlidersHorizontal,
  Sparkle,
} from "@phosphor-icons/react";
import { DepthGenerationSettings } from "../depth-settings/DepthGenerationSettings.jsx";
import { MediaStagingSettingsPanel } from "../media-staging/MediaStagingSettingsPanel.jsx";
import { SettingsActions } from "../ui/settings/SettingsPrimitives.jsx";
import { PlatformSkillAdmin } from "./PlatformSkillAdmin.jsx";
import "./platform-admin.css";

const ADMIN_SECTIONS = [
  { id: "providers", label: "服务商与凭据", Icon: Key },
  { id: "models", label: "模型与默认值", Icon: SlidersHorizontal },
  { id: "skills", label: "平台 Skill", Icon: Sparkle },
  { id: "media", label: "媒体与对象存储", Icon: CloudArrowUp },
  { id: "runtime", label: "运行环境", Icon: Cpu },
];

function stateLabel(configured) {
  return configured ? "已配置" : "未配置";
}

export function PlatformAdminConsole({
  adminSession,
  draft,
  error,
  imageServerSettings,
  loading,
  mediaStagingServerSettings,
  mediaStagingValidating,
  mediaStagingValidation,
  onBack,
  onChange,
  onNavigate,
  onSave,
  onValidateMediaStaging,
  request,
  saving,
  section,
  serverSettings,
  videoServerSettings,
}) {
  const videoProviders = videoServerSettings?.providers || [];
  return (
    <div className="platform-admin-shell settings-surface">
      <aside className="platform-admin-sidebar">
        <div className="platform-admin-brand">
          <span><ShieldCheck size={22} weight="fill" /></span>
          <div>
            <strong>ViralDNA Admin</strong>
            <small>平台管理后台</small>
          </div>
        </div>
        <nav aria-label="平台管理分区">
          {ADMIN_SECTIONS.map(({ id, label, Icon }) => (
            <button
              className={section === id ? "active" : ""}
              key={id}
              onClick={() => onNavigate(id)}
              type="button"
            >
              <Icon size={19} /> {label}
            </button>
          ))}
        </nav>
        <button className="platform-admin-back" onClick={onBack} type="button">
          <ArrowLeft size={18} /> 返回用户设置
        </button>
      </aside>

      <main className="platform-admin-main">
        <header className="platform-admin-header">
          <div>
            <p>平台级配置</p>
            <h1>{ADMIN_SECTIONS.find((item) => item.id === section)?.label}</h1>
          </div>
          <div className="platform-admin-principal">
            <ShieldCheck size={20} />
            <span>
              <strong>{adminSession?.display_name || "本地平台管理员"}</strong>
              <small>对所有账户生效</small>
            </span>
          </div>
        </header>

        <div className="platform-admin-boundary">
          <Database size={19} />
          <p>
            这里保存平台 Provider、API Key、模型目录和基础设施设置。用户账户只能选择已启用模型，不能读取凭据。
          </p>
        </div>

        {section === "providers" && (
          <section className="admin-settings-section">
            <header>
              <h2>视觉分析服务</h2>
              <span className={serverSettings?.api_key_configured ? "ready" : ""}>
                {stateLabel(serverSettings?.api_key_configured)}
              </span>
            </header>
            <div className="settings-form-grid admin-settings-grid">
              <label className="settings-field">
                <span>Provider</span>
                <select
                  disabled={loading || saving}
                  onChange={(event) => onChange({ provider: event.target.value })}
                  value={draft.provider || "bailian"}
                >
                  <option value="bailian">阿里云百炼</option>
                </select>
              </label>
              <label className="settings-field">
                <span>模型别名</span>
                <input
                  disabled={loading || saving}
                  onChange={(event) => onChange({ modelAlias: event.target.value })}
                  value={draft.modelAlias || ""}
                />
              </label>
              <label className="settings-field admin-wide-field">
                <span>API Base URL</span>
                <input
                  disabled={loading || saving}
                  onChange={(event) => onChange({ baseUrl: event.target.value })}
                  type="url"
                  value={draft.baseUrl || ""}
                />
              </label>
              <label className="settings-field admin-wide-field">
                <span>API Key</span>
                <input
                  autoComplete="new-password"
                  disabled={loading || saving}
                  onChange={(event) => onChange({ apiKey: event.target.value })}
                  placeholder={serverSettings?.api_key_configured ? "已配置；留空保持不变" : "填写平台 API Key"}
                  type="password"
                  value={draft.apiKey || ""}
                />
              </label>
            </div>

            <header className="admin-subsection-heading">
              <h2>视频生成服务</h2>
              <span>{videoProviders.filter((item) => item.api_key_configured).length} 个已配置</span>
            </header>
            <div className="admin-provider-list">
              {videoProviders.map((provider) => (
                <article key={provider.provider}>
                  <div>
                    <strong>{provider.label || provider.provider}</strong>
                    <small>{provider.base_url}</small>
                  </div>
                  <span className={provider.api_key_configured ? "ready" : ""}>
                    {stateLabel(provider.api_key_configured)}
                  </span>
                  <label className="settings-field">
                    <span>替换 API Key</span>
                    <input
                      autoComplete="new-password"
                      disabled={loading || saving}
                      onChange={(event) => onChange({
                        videoProviderKeys: {
                          ...(draft.videoProviderKeys || {}),
                          [provider.provider]: event.target.value,
                        },
                      })}
                      placeholder={provider.api_key_configured ? "留空保持不变" : "尚未配置"}
                      type="password"
                      value={draft.videoProviderKeys?.[provider.provider] || ""}
                    />
                  </label>
                  <label className="settings-field admin-provider-url">
                    <span>Base URL</span>
                    <input
                      disabled={loading || saving}
                      onChange={(event) => onChange({
                        videoProviderBaseUrls: {
                          ...(draft.videoProviderBaseUrls || {}),
                          [provider.provider]: event.target.value,
                        },
                      })}
                      type="url"
                      value={draft.videoProviderBaseUrls?.[provider.provider] || provider.base_url || ""}
                    />
                    {provider.provider === "gemini_omni" && (
                      <small>支持 Google 官方地址或兼容 Interactions API 的公网 HTTPS 中转地址。</small>
                    )}
                  </label>
                </article>
              ))}
            </div>
            {videoProviders.some((provider) => provider.provider === "volc_ark") && (
              <div className="admin-managed-assets">
                <h3>火山方舟托管虚拟资产</h3>
                <p>托管演员目录使用独立 AccessKey；不会下发给用户账户。</p>
                <div className="settings-form-grid admin-settings-grid">
                  <label className="settings-field">
                    <span>AccessKey ID</span>
                    <input
                      autoComplete="new-password"
                      disabled={loading || saving}
                      onChange={(event) => onChange({ videoManagedAssetAccessKey: event.target.value })}
                      placeholder="留空保持现有配置"
                      type="password"
                      value={draft.videoManagedAssetAccessKey || ""}
                    />
                  </label>
                  <label className="settings-field">
                    <span>Secret AccessKey</span>
                    <input
                      autoComplete="new-password"
                      disabled={loading || saving}
                      onChange={(event) => onChange({ videoManagedAssetSecretKey: event.target.value })}
                      placeholder="留空保持现有配置"
                      type="password"
                      value={draft.videoManagedAssetSecretKey || ""}
                    />
                  </label>
                  <label className="settings-field">
                    <span>区域</span>
                    <input
                      disabled={loading || saving}
                      onChange={(event) => onChange({ videoManagedAssetRegion: event.target.value })}
                      value={draft.videoManagedAssetRegion || "cn-beijing"}
                    />
                  </label>
                  <label className="settings-field">
                    <span>项目名</span>
                    <input
                      disabled={loading || saving}
                      onChange={(event) => onChange({ videoManagedAssetProjectName: event.target.value })}
                      value={draft.videoManagedAssetProjectName || "default"}
                    />
                  </label>
                </div>
              </div>
            )}
          </section>
        )}

        {section === "models" && (
          <section className="admin-settings-section">
            <header>
              <h2>平台模型默认值</h2>
              <span>所有账户的回退配置</span>
            </header>
            <div className="settings-form-grid admin-settings-grid">
              <label className="settings-field">
                <span>图片执行模式</span>
                <select
                  disabled={loading || saving}
                  onChange={(event) => onChange({ imageExecutionMode: event.target.value })}
                  value={draft.imageExecutionMode || "remote_api"}
                >
                  <option value="remote_api">国内大模型 API</option>
                  <option value="local_tool">本机工具</option>
                </select>
              </label>
              <label className="settings-field">
                <span>默认图片模型</span>
                <input
                  disabled={loading || saving}
                  onChange={(event) => onChange({ imageRemoteModelAlias: event.target.value })}
                  value={draft.imageRemoteModelAlias || ""}
                />
              </label>
              <label className="settings-field">
                <span>默认视频模型</span>
                <select
                  disabled={loading || saving}
                  onChange={(event) => onChange({ videoDefaultModelAlias: event.target.value })}
                  value={draft.videoDefaultModelAlias || ""}
                >
                  {(videoServerSettings?.models || []).map((model) => (
                    <option key={model.alias} value={model.alias}>
                      {model.display_name || model.alias}
                    </option>
                  ))}
                </select>
              </label>
              <label className="settings-field">
                <span>默认视频清晰度</span>
                <select
                  disabled={loading || saving}
                  onChange={(event) => onChange({ videoDefaultResolution: event.target.value })}
                  value={draft.videoDefaultResolution || "720P"}
                >
                  <option value="480P">480P</option>
                  <option value="720P">720P</option>
                  <option value="1080P">1080P</option>
                </select>
              </label>
              <label className="settings-field">
                <span>任务轮询间隔（秒）</span>
                <input
                  disabled={loading || saving}
                  min="1"
                  onChange={(event) => onChange({ videoPollIntervalSeconds: event.target.value })}
                  type="number"
                  value={draft.videoPollIntervalSeconds || 5}
                />
              </label>
              <label className="settings-field">
                <span>任务超时（秒）</span>
                <input
                  disabled={loading || saving}
                  min="60"
                  onChange={(event) => onChange({ videoTaskTimeoutSeconds: event.target.value })}
                  type="number"
                  value={draft.videoTaskTimeoutSeconds || 900}
                />
              </label>
            </div>
            <div className="admin-model-catalog">
              <h3>已注册视频模型</h3>
              {(videoServerSettings?.models || []).map((model) => (
                <div key={model.alias}>
                  <span><strong>{model.display_name || model.alias}</strong><small>{model.provider}</small></span>
                  <code>{model.alias}</code>
                </div>
              ))}
            </div>
          </section>
        )}

        {section === "media" && (
          <section className="admin-settings-section admin-component-section">
            <div className="admin-public-media">
              <h2>模型可访问媒体地址</h2>
              <p>用于向视频模型签发深度视频等中间产物的短期 HTTPS 地址。</p>
              <div className="settings-form-grid admin-settings-grid">
                <label className="settings-field">
                  <span>公开媒体 Base URL</span>
                  <input
                    disabled={loading || saving}
                    onChange={(event) => onChange({ videoPublicMediaBaseUrl: event.target.value })}
                    placeholder="https://media.example.com"
                    type="url"
                    value={draft.videoPublicMediaBaseUrl || ""}
                  />
                </label>
                <label className="settings-field">
                  <span>签名有效期（秒）</span>
                  <input
                    disabled={loading || saving}
                    min="60"
                    onChange={(event) => onChange({ videoPublicMediaTtlSeconds: event.target.value })}
                    type="number"
                    value={draft.videoPublicMediaTtlSeconds || 3600}
                  />
                </label>
              </div>
            </div>
            <MediaStagingSettingsPanel
              draft={draft}
              onChange={onChange}
              onValidate={onValidateMediaStaging}
              saving={saving}
              serverSettings={mediaStagingServerSettings}
              validating={mediaStagingValidating}
              validation={mediaStagingValidation}
            />
          </section>
        )}

        {section === "skills" && <PlatformSkillAdmin request={request} />}

        {section === "runtime" && (
          <section className="admin-settings-section admin-component-section">
            <div className="admin-runtime-tool">
              <h2>本机图片工具</h2>
              <p>只在平台运行节点执行，不属于任何用户账户。</p>
              <div className="settings-form-grid admin-settings-grid">
                <label className="settings-field admin-wide-field">
                  <span>可执行文件</span>
                  <input
                    disabled={loading || saving}
                    onChange={(event) => onChange({ imageLocalExecutablePath: event.target.value })}
                    placeholder="codex 或本机适配器路径"
                    value={draft.imageLocalExecutablePath || ""}
                  />
                </label>
                <label className="settings-field">
                  <span>模型选择</span>
                  <select
                    disabled={loading || saving}
                    onChange={(event) => onChange({ imageLocalModelPolicy: event.target.value })}
                    value={draft.imageLocalModelPolicy || "latest_flagship"}
                  >
                    <option value="latest_flagship">最新旗舰</option>
                    <option value="balanced">均衡模型</option>
                    <option value="pinned">固定指定模型</option>
                  </select>
                  <small>由管理员人工选择并保存；运行时不会因生成速度自动切换模型。</small>
                </label>
                <label className="settings-field">
                  <span>固定模型</span>
                  <input
                    disabled={loading || saving || draft.imageLocalModelPolicy !== "pinned"}
                    onChange={(event) => onChange({ imageLocalModel: event.target.value })}
                    value={draft.imageLocalModel || ""}
                  />
                </label>
                <label className="settings-field">
                  <span>推理等级</span>
                  <select
                    disabled={loading || saving}
                    onChange={(event) => onChange({ imageLocalReasoningEffort: event.target.value })}
                    value={draft.imageLocalReasoningEffort || "xhigh"}
                  >
                    <option value="low">低（更快）</option>
                    <option value="medium">中</option>
                    <option value="high">高</option>
                    <option value="xhigh">最高（更稳）</option>
                  </select>
                  <small>由管理员人工选择；系统不会根据耗时自动调整等级。</small>
                </label>
              </div>
            </div>
            <DepthGenerationSettings request={request} />
          </section>
        )}

        {error && <p className="admin-settings-error" role="alert">{error}</p>}
        <SettingsActions className="platform-admin-actions">
          <button className="primary-button" disabled={loading || saving} onClick={onSave} type="button">
            {saving ? "保存中…" : "保存平台配置"}
          </button>
        </SettingsActions>
      </main>
    </div>
  );
}
