import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  CaretDown,
  Check,
  Cloud,
  Desktop,
  Gear,
  SlidersHorizontal,
  UserCircle,
} from "@phosphor-icons/react";
import {
  SettingsActions,
  SettingsPanel,
  SettingsShell,
} from "../ui/settings/SettingsPrimitives.jsx";
import { VideoEnhancementSettings } from "../video-enhancement/VideoEnhancementSettings.jsx";
import { TextModelIndicator } from "../ui/text-model/TextModelIndicator.jsx";
import {
  DEFAULT_TEXT_MODEL_ALIAS,
  effectiveTextModelLabel,
  normalizeTextModelOverrides,
  textModelOptionLabel,
} from "./text-model-settings.js";
import "./settings-center.css";

const SECTIONS = [
  { id: "profile", label: "账户与分析", Icon: UserCircle },
  { id: "generation", label: "生成偏好", Icon: SlidersHorizontal },
  { id: "device", label: "当前设备", Icon: Desktop },
];

function normalizedSettings(settings) {
  return {
    target_model: settings?.target_model || "seedance",
    analysis_profile: settings?.analysis_profile || "balanced",
    max_cost_cny: settings?.max_cost_cny ?? 1,
    image_model_alias: settings?.image_model_alias || "",
    image_candidate_count: Number(settings?.image_candidate_count || 1),
    video_model_alias: settings?.video_model_alias || "",
    video_resolution: settings?.video_resolution || "",
    text_model_alias: settings?.text_model_alias || DEFAULT_TEXT_MODEL_ALIAS,
    text_model_fallback_enabled: settings?.text_model_fallback_enabled !== false,
    text_model_task_overrides: normalizeTextModelOverrides(
      settings?.text_model_task_overrides,
    ),
  };
}

function modelOptions(models = []) {
  return models.filter((model) => model.enabled !== false);
}

export function UserSettingsPage({
  adminAvailable,
  imageSettings,
  loading,
  onBack,
  onNavigate,
  onOpenAdmin,
  onOpenConnections,
  onSave,
  onSwitchWorkspace,
  onValidateWorkspace,
  onWorkspaceChange,
  preferences,
  request,
  section,
  session,
  videoSettings,
  workspace,
  workspaceDraft,
  workspaceError,
  workspaceSaving,
  workspaceValidation,
}) {
  const [draft, setDraft] = useState(() => normalizedSettings(preferences?.settings));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const imageModels = useMemo(
    () => modelOptions(imageSettings?.models),
    [imageSettings?.models],
  );
  const videoModels = useMemo(
    () => modelOptions(videoSettings?.models),
    [videoSettings?.models],
  );
  const textModels = useMemo(
    () => modelOptions(preferences?.text_models),
    [preferences?.text_models],
  );
  const textModelTasks = preferences?.text_model_tasks || [];
  const textModelLabel = effectiveTextModelLabel(
    { ...preferences, settings: draft },
  );
  const textModelOverrideCount = Object.keys(
    normalizeTextModelOverrides(draft.text_model_task_overrides),
  ).length;

  useEffect(() => {
    setDraft(normalizedSettings(preferences?.settings));
  }, [preferences]);

  function change(update) {
    setDraft((current) => ({ ...current, ...update }));
    setError("");
  }

  function changeTextModelOverride(taskId, alias) {
    change({
      text_model_task_overrides: normalizeTextModelOverrides({
        ...draft.text_model_task_overrides,
        [taskId]: alias,
      }),
    });
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      await onSave(draft, preferences?.revision);
    } catch (requestError) {
      setError(requestError.message || "设置保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <SettingsShell className="settings-center">
      <header className="settings-center-header">
        <button className="settings-back" onClick={onBack} type="button">
          <ArrowLeft size={19} /> 返回工作台
        </button>
        <div>
          <p className="settings-eyebrow">用户账户</p>
          <h1>设置</h1>
          <p>这些偏好只属于当前账户，不会改变平台模型凭据或其他账户。</p>
        </div>
        <div className="settings-account-chip">
          <UserCircle size={22} />
          <span>
            <strong>{session?.display_name || "默认用户"}</strong>
            <small>{session?.auth_mode === "external" ? "已登录" : "本机默认账户"}</small>
          </span>
        </div>
      </header>

      <div className="settings-center-layout">
        <nav className="settings-section-nav" aria-label="用户设置分区">
          {SECTIONS.map(({ id, label, Icon }) => (
            <button
              className={section === id ? "active" : ""}
              key={id}
              onClick={() => onNavigate(id)}
              type="button"
            >
              <Icon size={19} /> {label}
            </button>
          ))}
          <div className="settings-nav-divider" />
          <button onClick={onOpenConnections} type="button">
            <Cloud size={19} /> 平台连接
          </button>
          {adminAvailable && (
            <button onClick={onOpenAdmin} type="button">
              <Gear size={19} /> 平台管理后台
            </button>
          )}
        </nav>

        <SettingsPanel busy={loading || saving} className="settings-page-panel">
          {section === "profile" && (
            <>
              <header className="settings-panel-heading">
                <div>
                  <h2>账户与分析</h2>
                  <p>设置新分析默认行为；已运行任务不会被修改。</p>
                </div>
              </header>
              <div className="settings-form-grid">
                <label className="settings-field">
                  <span>目标提示词模型</span>
                  <select
                    disabled={loading || saving}
                    onChange={(event) => change({ target_model: event.target.value })}
                    value={draft.target_model}
                  >
                    <option value="seedance">Seedance</option>
                    <option value="generic">通用视频模型</option>
                  </select>
                  <small>决定提示词组织方式，不代表平台 API 凭据。</small>
                </label>
                <label className="settings-field">
                  <span>分析质量</span>
                  <select
                    disabled={loading || saving}
                    onChange={(event) => change({ analysis_profile: event.target.value })}
                    value={draft.analysis_profile}
                  >
                    <option value="quality">质量优先</option>
                    <option value="balanced">均衡</option>
                    <option value="economy">经济</option>
                  </select>
                </label>
                <label className="settings-field">
                  <span>单条分析成本上限</span>
                  <div className="settings-money-input">
                    <span>¥</span>
                    <input
                      disabled={loading || saving}
                      max="1000"
                      min="0.01"
                      onChange={(event) => change({ max_cost_cny: event.target.value })}
                      step="0.01"
                      type="number"
                      value={draft.max_cost_cny ?? ""}
                    />
                  </div>
                  <small>只控制当前账户的新分析预算。</small>
                </label>
              </div>
            </>
          )}

          {section === "generation" && (
            <>
              <header className="settings-panel-heading">
                <div>
                  <h2>生成偏好</h2>
                  <p>从平台管理员已经启用的模型中选择默认项。</p>
                </div>
              </header>
              <div className="settings-boundary-note">
                <Check size={18} weight="bold" />
                <span>API Key、Provider 地址和计费规则由平台管理员统一维护，本页面不会读取或保存凭据。</span>
              </div>
              <section className="text-model-settings-section" aria-labelledby="text-model-settings-title">
                <header className="text-model-settings-heading">
                  <div>
                    <h3 id="text-model-settings-title">文案与提示词模型</h3>
                    <p>用于复刻方案、分镜说明、图片提示词和视频提示词。</p>
                  </div>
                  <TextModelIndicator label={textModelLabel} />
                </header>
                <div className="text-model-default-row">
                  <label className="settings-field">
                    <span>默认文案模型</span>
                    <select
                      disabled={loading || saving}
                      onChange={(event) => change({ text_model_alias: event.target.value })}
                      value={draft.text_model_alias}
                    >
                      {textModels.map((model) => (
                        <option key={model.alias} value={model.alias}>
                          {textModelOptionLabel(model)}
                        </option>
                      ))}
                    </select>
                    <small>不影响图片生成模型和视频生成模型。</small>
                  </label>
                  <label className="text-model-fallback-field">
                    <input
                      checked={draft.text_model_fallback_enabled}
                      disabled={loading || saving}
                      onChange={(event) => change({
                        text_model_fallback_enabled: event.target.checked,
                      })}
                      type="checkbox"
                    />
                    <span>
                      <strong>失败时自动回退</strong>
                      <small>首选模型不可用或输出无效时，尝试任务默认备选模型。</small>
                    </span>
                  </label>
                </div>
                <details className="text-model-task-overrides">
                  <summary>
                    <span>按任务分别设置</span>
                    <small>{textModelOverrideCount} 项已覆盖</small>
                    <CaretDown aria-hidden="true" size={17} />
                  </summary>
                  <div className="text-model-task-list">
                    {textModelTasks.map((task) => (
                      <label className="text-model-task-row" key={task.id}>
                        <span>
                          <strong>{task.label}</strong>
                          <small>{task.description}</small>
                        </span>
                        <select
                          aria-label={`${task.label}文案模型`}
                          disabled={loading || saving}
                          onChange={(event) => changeTextModelOverride(
                            task.id,
                            event.target.value,
                          )}
                          value={draft.text_model_task_overrides[task.id] || ""}
                        >
                          <option value="">跟随默认（{textModelLabel}）</option>
                          {textModels.map((model) => (
                            <option key={model.alias} value={model.alias}>
                              {textModelOptionLabel(model)}
                            </option>
                          ))}
                        </select>
                      </label>
                    ))}
                  </div>
                </details>
              </section>
              <div className="settings-form-grid">
                <label className="settings-field">
                  <span>默认图片模型</span>
                  <select
                    disabled={loading || saving}
                    onChange={(event) => change({ image_model_alias: event.target.value })}
                    value={draft.image_model_alias}
                  >
                    <option value="">跟随平台默认</option>
                    {imageModels.map((model) => (
                      <option key={model.alias} value={model.alias}>
                        {model.display_name || model.alias}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="settings-field">
                  <span>默认图片候选数量</span>
                  <select
                    disabled={loading || saving}
                    onChange={(event) => change({ image_candidate_count: Number(event.target.value) })}
                    value={draft.image_candidate_count}
                  >
                    {[1, 2, 3, 4].map((count) => (
                      <option key={count} value={count}>{count} 张</option>
                    ))}
                  </select>
                </label>
                <label className="settings-field">
                  <span>默认视频模型</span>
                  <select
                    disabled={loading || saving}
                    onChange={(event) => change({ video_model_alias: event.target.value })}
                    value={draft.video_model_alias}
                  >
                    <option value="">跟随平台默认</option>
                    {videoModels.map((model) => (
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
                    onChange={(event) => change({ video_resolution: event.target.value })}
                    value={draft.video_resolution}
                  >
                    <option value="">跟随模型默认</option>
                    <option value="480P">480P</option>
                    <option value="720P">720P</option>
                    <option value="1080P">1080P</option>
                  </select>
                </label>
              </div>
              <VideoEnhancementSettings request={request} />
            </>
          )}

          {section === "device" && (
            <>
              <header className="settings-panel-heading">
                <div>
                  <h2>当前设备</h2>
                  <p>工作区保存在本机；未来登录后可将账户连接到云端工作区。</p>
                </div>
              </header>
              <dl className="device-settings-list">
                <div><dt>设备模式</dt><dd>本地工作区</dd></div>
                <div><dt>工作区路径</dt><dd>{workspace?.root_path || "尚未读取"}</dd></div>
                <div><dt>账户数据</dt><dd>仅当前账户可见</dd></div>
                <div><dt>云端同步</dt><dd>接口已预留，当前版本未启用</dd></div>
              </dl>
              <div className="device-workspace-editor">
                <label className="settings-field">
                  <span>工作区文件夹</span>
                  <input
                    disabled={workspaceSaving}
                    onChange={(event) => onWorkspaceChange(event.target.value)}
                    value={workspaceDraft || ""}
                  />
                  <small>切换后，下载、分析、导出和资产默认写入新工作区。</small>
                </label>
                <div className="device-workspace-actions">
                  <button
                    className="secondary-button"
                    disabled={workspaceSaving}
                    onClick={onValidateWorkspace}
                    type="button"
                  >
                    检查文件夹
                  </button>
                  <button
                    className="primary-button"
                    disabled={workspaceSaving || workspaceValidation?.valid === false}
                    onClick={onSwitchWorkspace}
                    type="button"
                  >
                    切换工作区
                  </button>
                </div>
                {workspaceValidation?.valid && (
                  <p className="device-workspace-valid"><Check size={17} /> 文件夹可写</p>
                )}
                {workspaceError && <p className="settings-page-error" role="alert">{workspaceError}</p>}
              </div>
            </>
          )}

          {error && <p className="settings-page-error" role="alert">{error}</p>}
          {section !== "device" && (
            <SettingsActions className="settings-page-actions">
              <button
                className="primary-button"
                disabled={loading || saving}
                onClick={save}
                type="button"
              >
                {saving ? "保存中…" : "保存账户设置"}
              </button>
            </SettingsActions>
          )}
        </SettingsPanel>
      </div>
    </SettingsShell>
  );
}
