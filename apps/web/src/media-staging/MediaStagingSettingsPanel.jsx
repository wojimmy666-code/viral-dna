import { ArrowClockwise, CheckCircle, CloudArrowUp, WarningCircle } from "@phosphor-icons/react";
import "./media-staging-settings.css";

export function MediaStagingSettingsPanel({
  draft,
  onChange,
  onValidate,
  saving,
  serverSettings,
  validating,
  validation,
}) {
  const provider = draft.mediaStagingProvider || "disabled";
  const credentialMode = draft.mediaStagingCredentialMode || "ecs_ram_role";
  const ready = Boolean(serverSettings?.ready);
  const status = validation || (
    serverSettings?.validation_message
      ? { valid: ready, message: serverSettings.validation_message }
      : null
  );

  return (
    <section className="media-staging-settings" aria-label="对象存储媒体暂存">
      <header className="media-staging-heading">
        <span className="media-staging-icon" aria-hidden="true">
          <CloudArrowUp size={22} />
        </span>
        <div>
          <strong>对象存储媒体暂存</strong>
          <p>将深度视频等中间媒体上传到私有桶，仅向模型签发短期只读 URL。</p>
        </div>
        <span className={`image-settings-state ${ready ? "enabled" : ""}`}>
          {ready ? "可用" : "未就绪"}
        </span>
      </header>

      <div className="settings-field-grid media-staging-primary-fields">
        <label className="settings-field">
          <span>暂存方式</span>
          <select
            disabled={saving}
            onChange={(event) => onChange({ mediaStagingProvider: event.target.value })}
            value={provider}
          >
            <option value="aliyun_oss">阿里云 OSS 私有桶（推荐）</option>
            <option value="local_proxy">本机 HTTPS 反向代理</option>
            <option value="disabled">不启用</option>
          </select>
        </label>
        {provider === "aliyun_oss" && (
          <label className="settings-field">
            <span>凭证方式</span>
            <select
              disabled={saving}
              onChange={(event) => onChange({
                mediaStagingCredentialMode: event.target.value,
              })}
              value={credentialMode}
            >
              <option value="ecs_ram_role">ECS RAM 角色（生产推荐）</option>
              <option value="access_key">AccessKey（本机开发）</option>
            </select>
          </label>
        )}
      </div>

      {provider === "aliyun_oss" && (
        <div className="media-staging-oss-fields">
          <div className="settings-field-grid">
            <label className="settings-field">
              <span>地域 Endpoint</span>
              <input
                disabled={saving}
                onChange={(event) => onChange({ mediaStagingRegion: event.target.value })}
                placeholder="oss-cn-shanghai"
                value={draft.mediaStagingRegion || ""}
              />
              <small>上海建议使用 oss-cn-shanghai；不要填写 Bucket 名。</small>
            </label>
            <label className="settings-field">
              <span>私有 Bucket</span>
              <input
                disabled={saving}
                onChange={(event) => onChange({ mediaStagingBucket: event.target.value })}
                placeholder="viraldna-private-media"
                value={draft.mediaStagingBucket || ""}
              />
            </label>
            <label className="settings-field">
              <span>内网上传 Endpoint（可选）</span>
              <input
                disabled={saving}
                onChange={(event) => onChange({
                  mediaStagingInternalEndpoint: event.target.value,
                })}
                placeholder="https://oss-cn-shanghai-internal.aliyuncs.com"
                type="url"
                value={draft.mediaStagingInternalEndpoint || ""}
              />
            </label>
            <label className="settings-field">
              <span>公网签名 Endpoint（可选）</span>
              <input
                disabled={saving}
                onChange={(event) => onChange({
                  mediaStagingPublicEndpoint: event.target.value,
                })}
                placeholder="https://oss-cn-shanghai.aliyuncs.com"
                type="url"
                value={draft.mediaStagingPublicEndpoint || ""}
              />
            </label>
          </div>

          {credentialMode === "ecs_ram_role" ? (
            <label className="settings-field media-staging-role-field">
              <span>RAM 角色名（可选）</span>
              <input
                disabled={saving}
                onChange={(event) => onChange({ mediaStagingRoleName: event.target.value })}
                placeholder="留空时自动读取实例绑定角色"
                value={draft.mediaStagingRoleName || ""}
              />
            </label>
          ) : (
            <div className="settings-field-grid media-staging-secret-fields">
              <label className="settings-field">
                <span>AccessKey ID</span>
                <input
                  autoComplete="off"
                  disabled={saving}
                  onChange={(event) => onChange({ mediaStagingAccessKeyId: event.target.value })}
                  placeholder={serverSettings?.access_key_hint || "留空表示不修改"}
                  type="password"
                  value={draft.mediaStagingAccessKeyId || ""}
                />
              </label>
              <label className="settings-field">
                <span>AccessKey Secret</span>
                <input
                  autoComplete="new-password"
                  disabled={saving}
                  onChange={(event) => onChange({
                    mediaStagingAccessKeySecret: event.target.value,
                  })}
                  placeholder={serverSettings?.access_key_configured ? "已加密保存，留空不修改" : "填写最小权限 RAM 用户密钥"}
                  type="password"
                  value={draft.mediaStagingAccessKeySecret || ""}
                />
              </label>
            </div>
          )}

          <div className="settings-field-grid media-staging-policy-fields">
            <label className="settings-field">
              <span>签名 URL 有效期</span>
              <div className="settings-input-with-suffix">
                <input
                  disabled={saving}
                  max="32400"
                  min="900"
                  onChange={(event) => onChange({ mediaStagingTtlSeconds: event.target.value })}
                  step="300"
                  type="number"
                  value={draft.mediaStagingTtlSeconds || 28800}
                />
                <span>秒</span>
              </div>
              <small>默认 8 小时；V1 签名最长 9 小时，可覆盖排队和 Provider 拉取。</small>
            </label>
            <label className="settings-field">
              <span>过期清理宽限期</span>
              <div className="settings-input-with-suffix">
                <input
                  disabled={saving}
                  max="2592000"
                  min="0"
                  onChange={(event) => onChange({
                    mediaStagingCleanupGraceSeconds: event.target.value,
                  })}
                  step="3600"
                  type="number"
                  value={draft.mediaStagingCleanupGraceSeconds || 86400}
                />
                <span>秒</span>
              </div>
            </label>
          </div>
        </div>
      )}

      <footer className="media-staging-footer">
        <div className={`media-staging-status ${status?.valid ? "success" : status ? "warning" : ""}`}>
          {status?.valid ? <CheckCircle size={18} /> : <WarningCircle size={18} />}
          <span>{status?.message || "保存配置后测试私有桶、凭证和签名读取链路。"}</span>
        </div>
        <button
          className="secondary-button"
          disabled={saving || validating || provider === "disabled"}
          onClick={onValidate}
          type="button"
        >
          <ArrowClockwise className={validating ? "spin" : ""} size={18} />
          {validating ? "正在测试" : "测试连接"}
        </button>
      </footer>
    </section>
  );
}
