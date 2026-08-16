import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CaretRight,
  Check,
  CheckCircle,
  CircleNotch,
  ClockCounterClockwise,
  FileImage,
  FloppyDisk,
  FolderOpen,
  GitBranch,
  ImageSquare,
  LockSimple,
  MagicWand,
  PencilSimple,
  Plus,
  Trash,
  UploadSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  PRODUCTION_STEPS,
  REFERENCE_TYPE_OPTIONS,
  budgetMicrosFromYuan,
  budgetYuanFromMicros,
  constraintsFromText,
  dimensionsForRatio,
  imageGenerationIntentForShot,
  imageGenerationModeLabel,
  resolveImageExecutionMode,
  formatProductionDate,
  normalizeReferenceTags,
  productionDefaultsForSource,
  productionChangeLabel,
  productionUnlockedStepIndex,
  referenceAssetsContinueLabel,
  referenceTypeLabel,
} from "./production-ui.js";
import { ShotImageWorkspace } from "./ShotImageWorkspace.jsx";
import { ShotVideoWorkspace } from "./ShotVideoWorkspace.jsx";
import { VideoEditorWorkspace } from "./video-editor/index.js";
import { ProductionExportWorkspace } from "./ProductionExportWorkspace.jsx";
import {
  useShotVideoGenerationDraft,
} from "./video-generation-controls/useShotVideoGenerationDraft.js";
import "./production-workflow.css";
import "./video-candidate-library.css";

const EMPTY_CREATE_DRAFT = Object.freeze({
  name: "",
  outputAspectRatio: "9:16",
  outputWidth: 1080,
  outputHeight: 1920,
  budgetYuan: "",
});

const EMPTY_REFERENCE_DRAFT = Object.freeze({
  type: "person",
  name: "",
  description: "",
  tags: "",
  rightsConfirmed: false,
  rightsNote: "",
});

const EMPTY_SHOT_DRAFT = Object.freeze({
  imagePrompt: "",
  imagePromptMentions: [],
  negativeConstraints: "",
  locks: [],
  required: true,
  referenceBindings: [],
});

const DEFAULT_PRODUCTION_IMAGE_SETTINGS = Object.freeze({
  enabled: false,
  execution_mode: "remote_api",
  default_candidate_count: 1,
  remote_model_alias: "qwen_image_2_pro",
  remote_model: "qwen-image-2.0-pro",
  local_tool_id: null,
  local_cost_source: "unknown",
  local_unit_cost_micros: null,
  models: [],
});

const DEFAULT_PRODUCTION_VIDEO_SETTINGS = Object.freeze({
  enabled: true,
  default_model_alias: "bailian_wan_2_7_r2v",
  default_resolution: "720P",
  providers: [],
  models: [],
});

function visualBeatFromDetail(detail, visualBeatId = null) {
  const beats = detail?.plan?.visual_beats || [];
  return beats.find((item) => item.id === visualBeatId) || beats[0] || null;
}

function shotDraftFromDetail(detail, visualBeatId = null) {
  if (!detail?.plan) return { ...EMPTY_SHOT_DRAFT };
  const beat = visualBeatFromDetail(detail, visualBeatId);
  return {
    imagePrompt: beat?.image_prompt || detail.plan.image_prompt || "",
    imagePromptMentions: (
      beat?.image_prompt_mentions || detail.plan.image_prompt_mentions || []
    ).map((item) => ({
      reference_asset_id: item.reference_asset_id,
      label: item.label,
    })),
    negativeConstraints: (
      beat?.image_negative_constraints || detail.plan.image_negative_constraints || []
    ).join("\n"),
    locks: [...(detail.plan.locks || [])],
    required: beat ? beat.required !== false : detail.plan.required !== false,
    referenceBindings: (detail.reference_bindings || []).map((item) => ({
      reference_asset_id: item.reference_asset_id,
      role: item.role,
      weight: item.weight,
      crop_hint: item.crop_hint,
      notes: item.notes,
    })),
  };
}

function videoPromptChangesFromDraft(
  detail,
  draft,
) {
  if (!detail?.plan) return {};
  const nextConstraints = constraintsFromText(draft.negativeConstraints);
  const currentConstraints = detail.plan.video_negative_constraints || [];
  const changes = {};
  if (draft.videoPrompt.trim() !== (detail.plan.video_prompt || "").trim()) {
    changes.video_prompt = draft.videoPrompt.trim();
  }
  if (JSON.stringify(nextConstraints) !== JSON.stringify(currentConstraints)) {
    changes.video_negative_constraints = nextConstraints;
  }
  return changes;
}

function shotDraftPatch(detail, visualBeatId, draft) {
  const activeBeat = visualBeatFromDetail(detail, visualBeatId);
  if (!detail?.plan || !activeBeat) {
    return { activeBeat: null, beatChanges: {}, shotChanges: {} };
  }
  const original = shotDraftFromDetail(detail, activeBeat.id);
  const nextConstraints = constraintsFromText(draft.negativeConstraints);
  const currentConstraints = constraintsFromText(original.negativeConstraints);
  const beatChanges = {};
  const shotChanges = {};
  if (draft.imagePrompt.trim() !== original.imagePrompt.trim()) {
    beatChanges.image_prompt = draft.imagePrompt.trim();
  }
  if (
    JSON.stringify(draft.imagePromptMentions)
    !== JSON.stringify(original.imagePromptMentions)
  ) {
    beatChanges.image_prompt_mentions = draft.imagePromptMentions;
  }
  if (JSON.stringify(nextConstraints) !== JSON.stringify(currentConstraints)) {
    beatChanges.image_negative_constraints = nextConstraints;
  }
  if (JSON.stringify(draft.locks) !== JSON.stringify(original.locks)) {
    shotChanges.locks = draft.locks;
  }
  if (draft.required !== original.required) {
    beatChanges.required = draft.required;
  }
  if (
    JSON.stringify(draft.referenceBindings)
    !== JSON.stringify(original.referenceBindings)
  ) {
    shotChanges.reference_bindings = draft.referenceBindings;
  }
  return { activeBeat, beatChanges, shotChanges };
}

function useObjectUrl(file) {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : ""), [file]);
  useEffect(() => {
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [url]);
  return url;
}

function projectStatusLabel(status) {
  if (status === "active") return "进行中";
  if (status === "completed") return "已完成";
  if (status === "archived") return "已归档";
  return "草稿";
}

function projectStatusClass(status) {
  return ["active", "completed"].includes(status) ? "positive" : "neutral";
}

function settingsFromProject(project) {
  return {
    name: project?.name || "",
    outputAspectRatio: project?.output_aspect_ratio || "9:16",
    outputWidth: project?.output_width || 1080,
    outputHeight: project?.output_height || 1920,
    budgetYuan: budgetYuanFromMicros(project?.budget_limit_micros),
  };
}

function defaultProductionName(sourceTitle) {
  const title = String(sourceTitle || "视频").trim() || "视频";
  return `${title.slice(0, 108)} 复刻方案`;
}

function formatGenerationCost(micros) {
  const value = Math.max(0, Number(micros || 0)) / 1_000_000;
  return `¥${value.toFixed(value > 0 ? 2 : 0)}`;
}

const ACTIVE_GENERATION_RUN_STATUSES = new Set([
  "queued",
  "running",
  "cancellation_requested",
]);

function upsertGenerationRun(current, run) {
  if (!current || current.plan?.id !== run?.shot_plan_id) return current;
  const existingRuns = current.generation_runs || [];
  return {
    ...current,
    generation_runs: [
      run,
      ...existingRuns.filter((item) => item.id !== run.id),
    ],
  };
}

function ProductionDialog({ title, description, children, busy, onClose, size = "medium" }) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [busy, onClose]);

  return (
    <div className="production-modal-backdrop" role="presentation" onMouseDown={() => !busy && onClose()}>
      <section
        aria-modal="true"
        aria-label={title}
        className={`production-modal production-modal-${size}`}
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="production-modal-header">
          <div>
            <h3>{title}</h3>
            {description && <p>{description}</p>}
          </div>
          <button aria-label="关闭" className="production-icon-button" disabled={busy} onClick={onClose} type="button">
            <X size={18} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}

function ReferenceThumbnail({ asset, resolveUrl }) {
  const [failed, setFailed] = useState(false);
  const source = resolveUrl(asset.thumbnail_url);
  if (!source || failed) {
    return (
      <div className="reference-thumbnail reference-thumbnail-fallback" aria-hidden="true">
        <FileImage size={30} />
      </div>
    );
  }
  return (
    <div className="reference-thumbnail">
      <img alt={`${asset.name}缩略图`} loading="lazy" onError={() => setFailed(true)} src={source} />
    </div>
  );
}

function ProductionList({ projects, loading, error, onCreate, onOpen }) {
  return (
    <section className="production-list-view">
      <header className="production-section-header">
        <div>
          <h3>创作方案</h3>
          <p>每个方案独立保存输出设置、参考资产和版本历史，不会改动原分析报告。</p>
        </div>
        <button className="primary-button compact" onClick={onCreate} type="button">
          <Plus size={16} weight="bold" />
          创建方案
        </button>
      </header>

      {loading && (
        <div className="production-list-skeleton" aria-label="正在加载创作方案">
          {[0, 1, 2].map((item) => <span key={item} />)}
        </div>
      )}
      {!loading && error && (
        <div className="production-inline-error" role="alert">
          <WarningCircle size={18} weight="fill" />
          <span>{error}</span>
        </div>
      )}
      {!loading && !error && projects.length === 0 && (
        <div className="production-empty-state">
          <span className="production-empty-icon"><MagicWand size={28} /></span>
          <div>
            <h4>从当前分析创建第一个方案</h4>
            <p>基础镜头、实体和提示词会冻结到首个版本，之后可以安全修改和回退。</p>
          </div>
          <button className="primary-button compact" onClick={onCreate} type="button">
            创建创作方案
          </button>
        </div>
      )}
      {!loading && !error && projects.length > 0 && (
        <div className="production-project-grid">
          {projects.map((project) => (
            <article className="production-project-card" key={project.id}>
              <button className="production-project-open" onClick={() => onOpen(project.id)} type="button">
                <span className="production-project-icon"><MagicWand size={21} weight="fill" /></span>
                <span className="production-project-copy">
                  <span className="production-project-title-line">
                    <strong>{project.name}</strong>
                    <small className={`production-status ${projectStatusClass(project.status)}`}>
                      {projectStatusLabel(project.status)}
                    </small>
                  </span>
                  <span>{project.output_aspect_ratio} · {project.output_width} × {project.output_height}</span>
                  <span>更新于 {formatProductionDate(project.updated_at)}</span>
                </span>
                <CaretRight size={18} />
              </button>
              <footer>
                <span>当前版本 {project.current_revision_id ? "已保存" : "未创建"}</span>
                {project.source_project_id && <span><GitBranch size={14} /> 历史分支</span>}
              </footer>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ProductionSteps({ active, project, referenceCount, gate, onChange }) {
  const activeIndex = productionUnlockedStepIndex(project.active_step);
  return (
    <nav aria-label="创作工作流" className="production-stepper">
      {PRODUCTION_STEPS.map((step, index) => {
        const exportReady = step.id === "export" && project.active_step === "editing";
        const locked = Boolean(step.locked) || (index > activeIndex && !exportReady);
        const selected = active === step.id;
        const completed = index < activeIndex || (step.id === "project_setup" && project.current_revision_id);
        return (
          <button
            aria-current={selected ? "step" : undefined}
            className={`${selected ? "active" : ""} ${locked ? "locked" : ""}`}
            disabled={locked}
            key={step.id}
            onClick={() => onChange(step.id)}
            type="button"
          >
            <span className="production-step-number">
              {locked ? <LockSimple size={13} /> : completed ? <Check size={13} weight="bold" /> : index + 1}
            </span>
            <span>
              <strong>{step.label}</strong>
              <small>
                {step.id === "reference_assets"
                  ? referenceCount > 0
                    ? `${referenceCount} 项资产`
                    : "可选 · 0 项"
                  : step.id === "shot_videos"
                    && step.id === project.active_step
                    && gate
                    ? `${gate.approved_shot_count || 0} / ${gate.required_shot_count} 已采用`
                    : step.id === "shot_images"
                      && step.id === project.active_step
                      && gate
                      ? `${gate.approved_shot_count} / ${gate.required_shot_count} 已确认`
                    : step.description}
              </small>
            </span>
          </button>
        );
      })}
    </nav>
  );
}

function promptDecisionKey(shotPlanId, fieldKey) {
  return `${shotPlanId}:${fieldKey}`;
}

function AnalysisUpdateBanner({ preview, open, onOpen }) {
  if (!preview?.update_available) return null;
  return (
    <section className="analysis-update-banner" aria-label="基础分析更新提醒">
      <span className="analysis-update-banner-icon"><WarningCircle size={20} weight="fill" /></span>
      <div>
        <strong>基础分析已有更新</strong>
        <p>
          {preview.changed_field_count > 0 ? (
            <>
              检测到 {preview.changed_field_count} 处提示词差异
              {preview.conflict_field_count > 0 ? `，其中 ${preview.conflict_field_count} 处包含手动修改` : ""}。
            </>
          ) : (
            <>新分析仍有分镜或画面结构变化待处理。</>
          )}
          当前候选、参考资产和采用结果不会被覆盖。
        </p>
      </div>
      <button className="secondary-button compact" onClick={onOpen} type="button">
        {open ? "收起差异" : "查看差异"}
        <ArrowRight size={15} />
      </button>
    </section>
  );
}

function AnalysisUpdatePanel({
  preview,
  decisions,
  busy,
  error,
  onChangeDecision,
  onClose,
  onSync,
}) {
  if (!preview) return null;
  return (
    <section className="analysis-update-panel" aria-label="分析提示词差异预览">
      <header className="analysis-update-header">
        <div>
          <span className="analysis-update-eyebrow">仅同步提示词</span>
          <h3>比较当前方案与新分析</h3>
          <p>
            新分析生成于 {formatProductionDate(preview.target_generated_at)}。应用后会创建新 Revision，
            不改分镜结构、参考资产、图片/视频候选或采用状态。
          </p>
        </div>
        <button aria-label="关闭差异预览" className="production-icon-button" onClick={onClose} type="button">
          <X size={18} />
        </button>
      </header>

      <div className="analysis-update-summary" aria-label="差异统计">
        <span><strong>{preview.changed_field_count}</strong> 处差异</span>
        <span><strong>{preview.automatic_field_count}</strong> 处建议更新</span>
        <span className={preview.conflict_field_count > 0 ? "attention" : ""}>
          <strong>{preview.conflict_field_count}</strong> 处手动修改
        </span>
      </div>

      {preview.structural_change_detected && (
        <div className="analysis-update-structural-warning" role="alert">
          <WarningCircle size={19} weight="fill" />
          <div>
            <strong>
              {preview.compatible
                ? "检测到额外结构变化，本轮只同步安全提示词"
                : "结构变化待后续处理"}
            </strong>
            <ul>
              {preview.structural_change_messages.map((message) => <li key={message}>{message}</li>)}
            </ul>
            <p>
              当前版本只处理一一对应的提示词，分镜增删和画面拆合不会被覆盖，
              将在后续结构同步中单独处理。
            </p>
          </div>
        </div>
      )}

      {error && <div className="production-inline-error" role="alert"><WarningCircle size={17} />{error}</div>}

      {preview.shots.length > 0 ? (
        <div className="analysis-update-shot-list">
          {preview.shots.map((shot) => (
            <article className="analysis-update-shot" key={shot.shot_plan_id}>
              <header>
                <span className="analysis-update-shot-index">{String(shot.index).padStart(2, "0")}</span>
                <div><strong>分镜 {shot.index}</strong><p>{shot.title}</p></div>
                <small>{shot.fields.length} 处差异</small>
              </header>
              <div className="analysis-update-field-list">
                {shot.fields.map((field) => {
                  const key = promptDecisionKey(shot.shot_plan_id, field.field_key);
                  const choice = decisions[key] || field.suggested_choice;
                  return (
                    <section className="analysis-update-field" key={field.field_key}>
                      <div className="analysis-update-field-heading">
                        <strong>{field.label}</strong>
                        {field.manually_edited && <span>当前方案已手动修改</span>}
                      </div>
                      <div className="analysis-update-diff-grid">
                        <div>
                          <small>当前方案</small>
                          <p>{field.current_value || "（空）"}</p>
                        </div>
                        <div className="latest">
                          <small>新分析</small>
                          <p>{field.latest_value || "（空）"}</p>
                        </div>
                      </div>
                      <fieldset className="analysis-update-choice">
                        <legend>此字段采用</legend>
                        <label className={choice === "use_latest" ? "selected" : ""}>
                          <input
                            checked={choice === "use_latest"}
                            name={key}
                            onChange={() => onChangeDecision(key, "use_latest")}
                            type="radio"
                          />
                          使用新分析
                          {!field.manually_edited && <small>建议</small>}
                        </label>
                        <label className={choice === "keep_current" ? "selected" : ""}>
                          <input
                            checked={choice === "keep_current"}
                            name={key}
                            onChange={() => onChangeDecision(key, "keep_current")}
                            type="radio"
                          />
                          保留当前
                          {field.manually_edited && <small>建议</small>}
                        </label>
                      </fieldset>
                    </section>
                  );
                })}
              </div>
            </article>
          ))}
        </div>
      ) : (
        !preview.structural_change_detected && (
          <div className="production-empty-state analysis-update-empty">
            <CheckCircle size={24} weight="fill" />
            <div><h4>提示词没有差异</h4><p>当前方案无需同步。</p></div>
          </div>
        )
      )}

      <footer className="analysis-update-footer">
        <p>同步后仍可从版本记录查看旧 Revision；历史候选继续保留并可重新选择。</p>
        <div>
          <button className="secondary-button compact" disabled={busy} onClick={onClose} type="button">稍后处理</button>
          <button
            className="primary-button compact"
            disabled={busy || !preview.compatible || preview.changed_field_count === 0}
            onClick={onSync}
            type="button"
          >
            {busy ? <CircleNotch className="spin" size={16} /> : <Check size={16} weight="bold" />}
            同步所选提示词并创建 Revision
          </button>
        </div>
      </footer>
    </section>
  );
}

function ProjectSettings({ detail, draft, setDraft, busy, error, onSave, onOpenReferences }) {
  const project = detail.project;
  const current = settingsFromProject(project);
  const dirty = JSON.stringify(draft) !== JSON.stringify(current);

  function changeRatio(value) {
    const dimensions = dimensionsForRatio(value);
    setDraft((state) => ({
      ...state,
      outputAspectRatio: value,
      outputWidth: dimensions.width,
      outputHeight: dimensions.height,
    }));
  }

  return (
    <div className="production-settings-layout">
      <form className="production-settings-form" onSubmit={onSave}>
        <div className="production-form-heading">
          <div>
            <h3>方案设置</h3>
            <p>修改会创建新版本。已保存的历史版本保持不变。</p>
          </div>
          <button className="primary-button compact" disabled={busy || !dirty} type="submit">
            {busy ? <CircleNotch className="spin" size={16} /> : <FloppyDisk size={16} />}
            保存设置
          </button>
        </div>
        {error && <div className="production-inline-error" role="alert"><WarningCircle size={17} />{error}</div>}
        <label className="production-field production-field-wide">
          <span>方案名称</span>
          <input
            maxLength={120}
            onChange={(event) => setDraft((state) => ({ ...state, name: event.target.value }))}
            required
            value={draft.name}
          />
          <small>用于区分人物替换版、产品版或不同成本方案。</small>
        </label>
        <fieldset className="production-field production-field-wide">
          <legend>输出画幅</legend>
          <div className="production-ratio-options">
            {["9:16", "16:9", "1:1", "4:5"].map((ratio) => (
              <button
                className={draft.outputAspectRatio === ratio ? "active" : ""}
                key={ratio}
                onClick={() => changeRatio(ratio)}
                type="button"
              >
                <span className={`ratio-shape ratio-${ratio.replace(":", "-")}`} />
                {ratio}
              </button>
            ))}
          </div>
        </fieldset>
        <label className="production-field">
          <span>输出宽度</span>
          <input
            max={8192}
            min={256}
            onChange={(event) => setDraft((state) => ({ ...state, outputWidth: Number(event.target.value) }))}
            required
            type="number"
            value={draft.outputWidth}
          />
        </label>
        <label className="production-field">
          <span>输出高度</span>
          <input
            max={8192}
            min={256}
            onChange={(event) => setDraft((state) => ({ ...state, outputHeight: Number(event.target.value) }))}
            required
            type="number"
            value={draft.outputHeight}
          />
        </label>
        <label className="production-field production-field-wide">
          <span>预算上限（元）</span>
          <input
            inputMode="decimal"
            onChange={(event) => setDraft((state) => ({ ...state, budgetYuan: event.target.value }))}
            placeholder="留空表示暂不限制"
            value={draft.budgetYuan}
          />
          <small>图片生成会按当前模式估算并记录费用；本机工具成本未知时需逐次确认。视频模型接入后将共用此预算。</small>
        </label>
      </form>

      <aside className="production-settings-summary">
        <h3>方案快照</h3>
        <dl>
          <div><dt>基础分析</dt><dd>{String(project.base_analysis_id).slice(0, 8)}</dd></div>
          <div><dt>当前版本</dt><dd>Revision {detail.current_revision?.revision_number || 1}</dd></div>
          <div><dt>参考资产</dt><dd>{detail.reference_count} 项</dd></div>
          <div><dt>分镜图片</dt><dd>{detail.approved_image_count} / {detail.shot_count} 已确认</dd></div>
          <div><dt>实际成本</dt><dd>¥{(Number(project.actual_cost_micros || 0) / 1_000_000).toFixed(2)}</dd></div>
        </dl>
        <button className="secondary-button compact" onClick={onOpenReferences} type="button">
          添加参考资产
          <ArrowRight size={15} />
        </button>
      </aside>
    </div>
  );
}

function ReferenceAssets({
  assets, busy, error, resolveUrl, onUpload, onOpenLibrary, onEdit, onArchive,
  onContinue,
}) {
  const continueLabel = referenceAssetsContinueLabel(assets.length);
  return (
    <section className="production-reference-view">
      <header className="production-section-header compact-heading">
        <div>
          <h3>参考资产（可选）</h3>
          <p>需要替换人物、产品或场景时再添加；没有参考资产也可以直接进入分镜图片。</p>
        </div>
        <div className="production-reference-actions">
          <button className="secondary-button compact" disabled={busy} onClick={onUpload} type="button">
            <UploadSimple size={16} />
            快速上传
          </button>
          <button className="secondary-button compact" disabled={busy} onClick={onOpenLibrary} type="button">
            <FolderOpen size={16} />
            从资产库添加
          </button>
          {assets.length > 0 && (
            <button className="primary-button compact" disabled={busy} onClick={onContinue} type="button">
              {continueLabel}
              <ArrowRight size={15} />
            </button>
          )}
        </div>
      </header>
      {error && <div className="production-inline-error" role="alert"><WarningCircle size={17} />{error}</div>}
      {assets.length === 0 ? (
        <div className="production-empty-state reference-empty">
          <span className="production-empty-icon"><ImageSquare size={28} /></span>
          <div>
            <h4>还没有参考资产</h4>
            <p>如果不需要替换固定人物、产品或场景，可以直接使用原视频关键帧和文字提示词继续。</p>
          </div>
          <div className="reference-empty-actions">
            <button className="secondary-button compact" disabled={busy} onClick={onOpenLibrary} type="button">
              从资产库添加
            </button>
            <button className="primary-button compact" disabled={busy} onClick={onContinue} type="button">
              {continueLabel}
              <ArrowRight size={15} />
            </button>
          </div>
        </div>
      ) : (
        <div className="reference-asset-grid">
          {assets.map((asset) => (
            <article className="reference-asset-card" key={asset.id}>
              <ReferenceThumbnail asset={asset} resolveUrl={resolveUrl} />
              <div className="reference-asset-body">
                <div className="reference-asset-title">
                  <span>{referenceTypeLabel(asset.type)}</span>
                  <small>{asset.width} × {asset.height}</small>
                </div>
                <strong title={asset.name}>{asset.name}</strong>
                <p>{asset.description || "暂无说明"}</p>
                <div className="reference-tag-row">
                  {asset.tags.slice(0, 3).map((tag) => <span key={tag}>{tag}</span>)}
                  {asset.tags.length > 3 && <span>+{asset.tags.length - 3}</span>}
                </div>
                <div className="reference-rights">
                  <CheckCircle size={14} weight="fill" />
                  已确认使用权
                </div>
              </div>
              <footer>
                <button onClick={() => onEdit(asset)} type="button"><PencilSimple size={15} />编辑</button>
                <button className="danger-text" onClick={() => onArchive(asset)} type="button"><Trash size={15} />移出项目</button>
              </footer>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function AssetPickerDialog({
  assets,
  busy,
  error,
  linkedIds,
  loading,
  onClose,
  onConfirm,
  resolveUrl,
  selectedId,
  setSelectedId,
}) {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
  const available = assets.filter((asset) => (
    !linkedIds.has(asset.id)
    && (!normalizedQuery || [asset.name, asset.description, ...(asset.tags || [])]
      .join(" ")
      .toLocaleLowerCase("zh-CN")
      .includes(normalizedQuery))
  ));
  return (
    <ProductionDialog
      busy={busy}
      description="选择工作区资产后只建立项目关联，不会复制图片文件。"
      onClose={onClose}
      size="large"
      title="从资产库添加"
    >
      <div className="project-asset-picker">
        <label className="project-asset-picker-search">
          <FolderOpen size={18} />
          <input
            autoFocus
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索名称、说明或标签"
            value={query}
          />
        </label>
        {error && <div className="production-inline-error" role="alert"><WarningCircle size={17} />{error}</div>}
        {loading ? (
          <div className="production-dialog-loading"><CircleNotch className="spin" size={22} />正在读取资产库</div>
        ) : available.length === 0 ? (
          <div className="production-empty-state reference-empty">
            <span className="production-empty-icon"><ImageSquare size={26} /></span>
            <div><h4>没有可添加的资产</h4><p>资产可能已经全部加入项目，或没有匹配当前搜索。</p></div>
          </div>
        ) : (
          <div className="project-asset-picker-grid">
            {available.map((asset) => (
              <button
                aria-pressed={selectedId === asset.id}
                className={selectedId === asset.id ? "selected" : ""}
                key={asset.id}
                onClick={() => setSelectedId(asset.id)}
                type="button"
              >
                <span className="project-asset-picker-thumb">
                  <img alt="" src={resolveUrl(asset.thumbnail_url)} />
                </span>
                <span>
                  <strong>{asset.name}</strong>
                  <small>{referenceTypeLabel({
                    clothing: "wardrobe",
                    logo: "prop",
                    other: "prop",
                  }[asset.type] || asset.type)} · {asset.width} × {asset.height}</small>
                </span>
                {selectedId === asset.id && <CheckCircle size={18} weight="fill" />}
              </button>
            ))}
          </div>
        )}
        <footer className="production-modal-actions">
          <button className="secondary-button compact" disabled={busy} onClick={onClose} type="button">取消</button>
          <button className="primary-button compact" disabled={busy || !selectedId} onClick={onConfirm} type="button">
            {busy ? <CircleNotch className="spin" size={16} /> : <Plus size={16} />}
            添加到项目
          </button>
        </footer>
      </div>
    </ProductionDialog>
  );
}


function ChangeImpactPanel({ review, busy, onCancel, onConfirm }) {
  if (!review) return null;
  const impact = review.impact;
  return (
    <aside aria-label="修改影响确认" className="change-impact-panel">
      <header>
        <span><WarningCircle size={19} weight="fill" /></span>
        <div>
          <strong>{review.title}</strong>
          <p>{impact.summary}</p>
        </div>
        <button aria-label="关闭影响面板" disabled={busy} onClick={onCancel} type="button"><X size={16} /></button>
      </header>
      <dl>
        <div><dt>受影响分镜</dt><dd>{impact.impacted_shot_plan_ids?.length || 0} 个</dd></div>
        <div><dt>过期候选</dt><dd>{impact.stale_candidate_ids?.length || 0} 个</dd></div>
        <div><dt>下游阶段</dt><dd>{impact.stale_stage_ids?.length || 0} 个</dd></div>
      </dl>
      <p className="change-impact-note">旧结果和文件会继续保留，但不能作为后续阶段的有效输入。</p>
      <footer>
        <button className="secondary-button compact" disabled={busy} onClick={onCancel} type="button">取消修改</button>
        <button className="primary-button compact" disabled={busy} onClick={onConfirm} type="button">
          {busy ? <CircleNotch className="spin" size={15} /> : <Check size={15} />}
          确认并保存
        </button>
      </footer>
    </aside>
  );
}

function RevisionHistory({ revisions, currentRevisionId, busy, onPreview, onBranch }) {
  return (
    <section className="production-revision-view">
      <header className="production-section-header compact-heading">
        <div>
          <h3>版本记录</h3>
          <p>每次重要修改都会冻结快照。旧版本只读，可以从任意版本创建独立分支。</p>
        </div>
      </header>
      <div className="production-revision-list">
        {revisions.map((revision) => {
          const current = revision.id === currentRevisionId;
          return (
            <article className={current ? "current" : ""} key={revision.id}>
              <span className="revision-index">R{revision.revision_number}</span>
              <div className="revision-copy">
                <div>
                  <strong>{revision.change_summary}</strong>
                  {current && <small className="current-revision-label">当前版本</small>}
                </div>
                <p>{productionChangeLabel(revision.change_kind)} · {formatProductionDate(revision.created_at)}</p>
              </div>
              <div className="revision-actions">
                <button disabled={busy} onClick={() => onPreview(revision)} type="button">查看</button>
                <button disabled={busy} onClick={() => onBranch(revision)} type="button"><GitBranch size={14} />创建分支</button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function CreateProjectDialog({
  draft,
  setDraft,
  busy,
  error,
  onClose,
  onSubmit,
  sourceDefaultRatio,
}) {
  function selectRatio(value) {
    const dimensions = dimensionsForRatio(value);
    setDraft((state) => ({
      ...state,
      outputAspectRatio: value,
      outputWidth: dimensions.width,
      outputHeight: dimensions.height,
    }));
  }
  return (
    <ProductionDialog
      busy={busy}
      description="基础分析、Prompt Package 和镜头列表将冻结到首个版本。"
      onClose={onClose}
      title="创建创作方案"
    >
      <form className="production-modal-form" onSubmit={onSubmit}>
        {error && <div className="production-inline-error" role="alert"><WarningCircle size={17} />{error}</div>}
        <label className="production-field">
          <span>方案名称</span>
          <input autoFocus maxLength={120} onChange={(event) => setDraft((state) => ({ ...state, name: event.target.value }))} required value={draft.name} />
        </label>
        <fieldset className="production-field">
          <legend>输出画幅</legend>
          <div className="production-ratio-options compact-ratios">
            {["9:16", "16:9", "1:1", "4:5"].map((ratio) => (
              <button className={draft.outputAspectRatio === ratio ? "active" : ""} key={ratio} onClick={() => selectRatio(ratio)} type="button">{ratio}</button>
            ))}
          </div>
          <small className="production-ratio-hint">
            已按源视频预选 {sourceDefaultRatio}，可在创建前手动调整。
          </small>
        </fieldset>
        <div className="production-field-pair">
          <label className="production-field"><span>宽度</span><input min={256} max={8192} onChange={(event) => setDraft((state) => ({ ...state, outputWidth: Number(event.target.value) }))} type="number" value={draft.outputWidth} /></label>
          <label className="production-field"><span>高度</span><input min={256} max={8192} onChange={(event) => setDraft((state) => ({ ...state, outputHeight: Number(event.target.value) }))} type="number" value={draft.outputHeight} /></label>
        </div>
        <label className="production-field">
          <span>预算上限（元）</span>
          <input inputMode="decimal" onChange={(event) => setDraft((state) => ({ ...state, budgetYuan: event.target.value }))} placeholder="可稍后设置" value={draft.budgetYuan} />
        </label>
        <footer className="production-modal-actions">
          <button className="secondary-button compact" disabled={busy} onClick={onClose} type="button">取消</button>
          <button className="primary-button compact" disabled={busy} type="submit">
            {busy ? <CircleNotch className="spin" size={16} /> : <MagicWand size={16} />}
            创建方案
          </button>
        </footer>
      </form>
    </ProductionDialog>
  );
}

function ReferenceAssetDialog({ mode, draft, setDraft, file, setFile, previewUrl, busy, error, onClose, onSubmit }) {
  const uploading = mode === "upload";
  return (
    <ProductionDialog
      busy={busy}
      description={uploading ? "支持 JPG、PNG 和 WebP，单张不超过 15 MB。" : "修改元数据会创建新的方案版本，原图片保持不变。"}
      onClose={onClose}
      size="large"
      title={uploading ? "上传参考资产" : "编辑参考资产"}
    >
      <form className="reference-dialog-layout" onSubmit={onSubmit}>
        {uploading && (
          <label className={`reference-file-drop ${previewUrl ? "has-preview" : ""}`}>
            {previewUrl ? <img alt="待上传参考图预览" src={previewUrl} /> : <><UploadSimple size={28} /><strong>选择参考图片</strong><span>点击浏览本地文件</span></>}
            <input accept="image/jpeg,image/png,image/webp" onChange={(event) => setFile(event.target.files?.[0] || null)} required type="file" />
          </label>
        )}
        <div className="reference-dialog-fields">
          {error && <div className="production-inline-error" role="alert"><WarningCircle size={17} />{error}</div>}
          <label className="production-field">
            <span>资产类型</span>
            <select disabled={!uploading} onChange={(event) => setDraft((state) => ({ ...state, type: event.target.value }))} value={draft.type}>
              {REFERENCE_TYPE_OPTIONS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label className="production-field">
            <span>名称</span>
            <input maxLength={120} onChange={(event) => setDraft((state) => ({ ...state, name: event.target.value }))} required value={draft.name} />
          </label>
          <label className="production-field">
            <span>说明</span>
            <textarea maxLength={2000} onChange={(event) => setDraft((state) => ({ ...state, description: event.target.value }))} rows={3} value={draft.description} />
          </label>
          <label className="production-field">
            <span>标签</span>
            <input onChange={(event) => setDraft((state) => ({ ...state, tags: event.target.value }))} placeholder="正面，全身，棚拍" value={draft.tags} />
          </label>
          <label className="reference-rights-check">
            <input checked={draft.rightsConfirmed} onChange={(event) => setDraft((state) => ({ ...state, rightsConfirmed: event.target.checked }))} type="checkbox" />
            <span><strong>我确认拥有该图片的使用权</strong><small>图片只保存在当前本地工作区。</small></span>
          </label>
          <label className="production-field">
            <span>权利说明</span>
            <input maxLength={1000} onChange={(event) => setDraft((state) => ({ ...state, rightsNote: event.target.value }))} placeholder="例如：品牌自有素材或已取得授权" value={draft.rightsNote} />
          </label>
        </div>
        <footer className="production-modal-actions reference-dialog-actions">
          <button className="secondary-button compact" disabled={busy} onClick={onClose} type="button">取消</button>
          <button className="primary-button compact" disabled={busy || (uploading && !file) || !draft.rightsConfirmed} type="submit">
            {busy ? <CircleNotch className="spin" size={16} /> : uploading ? <UploadSimple size={16} /> : <FloppyDisk size={16} />}
            {uploading ? "上传并保存" : "保存修改"}
          </button>
        </footer>
      </form>
    </ProductionDialog>
  );
}

function ArchiveDialog({ asset, busy, error, onClose, onConfirm }) {
  return (
    <ProductionDialog busy={busy} description="只会移除当前项目关联；资产库原图、其他项目引用和历史版本都不受影响。" onClose={onClose} title="从项目移出参考资产">
      <div className="archive-dialog-copy">
        <span><Trash size={22} /></span>
        <div><strong>{asset.name}</strong><p>{referenceTypeLabel(asset.type)} · {asset.width} × {asset.height}</p></div>
      </div>
      {error && <div className="production-inline-error modal-inline-error" role="alert"><WarningCircle size={17} />{error}</div>}
      <footer className="production-modal-actions">
        <button className="secondary-button compact" disabled={busy} onClick={onClose} type="button">取消</button>
        <button className="danger-button compact" disabled={busy} onClick={onConfirm} type="button">
          {busy ? <CircleNotch className="spin" size={16} /> : <Trash size={16} />}
          确认移出
        </button>
      </footer>
    </ProductionDialog>
  );
}

function RevisionPreviewDialog({ revision, detail, busy, error, onClose, onBranch }) {
  const snapshot = detail?.snapshot;
  return (
    <ProductionDialog busy={busy} description="这是不可变的只读快照。" onClose={onClose} size="large" title={`Revision ${revision.revision_number}`}>
      {error ? (
        <div className="production-inline-error modal-inline-error" role="alert"><WarningCircle size={17} />{error}</div>
      ) : !snapshot ? (
        <div className="production-dialog-loading"><CircleNotch className="spin" size={22} />正在读取版本快照</div>
      ) : (
        <div className="revision-preview-grid">
          <div><span>方案名称</span><strong>{snapshot.project?.name || "未命名方案"}</strong></div>
          <div><span>输出规格</span><strong>{snapshot.project?.output_aspect_ratio} · {snapshot.project?.output_width} × {snapshot.project?.output_height}</strong></div>
          <div><span>源镜头</span><strong>{snapshot.source_analysis?.shots?.length || 0} 个</strong></div>
          <div><span>参考资产</span><strong>{snapshot.references?.filter((item) => !item.archived_at).length || 0} 项</strong></div>
          <div className="revision-preview-summary"><span>变更说明</span><strong>{revision.change_summary}</strong></div>
        </div>
      )}
      <footer className="production-modal-actions">
        <button className="secondary-button compact" disabled={busy} onClick={onClose} type="button">关闭</button>
        <button className="primary-button compact" disabled={busy || !snapshot} onClick={onBranch} type="button"><GitBranch size={16} />从此版本创建分支</button>
      </footer>
    </ProductionDialog>
  );
}

function BranchDialog({ revision, name, setName, busy, error, onClose, onSubmit }) {
  return (
    <ProductionDialog busy={busy} description={`新方案会复制 Revision ${revision.revision_number} 的设置和有效参考资产。`} onClose={onClose} title="创建版本分支">
      <form className="production-modal-form" onSubmit={onSubmit}>
        {error && <div className="production-inline-error" role="alert"><WarningCircle size={17} />{error}</div>}
        <label className="production-field"><span>分支名称</span><input autoFocus maxLength={120} onChange={(event) => setName(event.target.value)} required value={name} /></label>
        <footer className="production-modal-actions">
          <button className="secondary-button compact" disabled={busy} onClick={onClose} type="button">取消</button>
          <button className="primary-button compact" disabled={busy} type="submit">{busy ? <CircleNotch className="spin" size={16} /> : <GitBranch size={16} />}创建分支</button>
        </footer>
      </form>
    </ProductionDialog>
  );
}

export function ProductionHub({
  recordId,
  analysisId,
  sourceTitle,
  sourceMedia = {},
  projects,
  loading,
  error,
  request,
  resolveUrl,
  imageGenerationSettings = DEFAULT_PRODUCTION_IMAGE_SETTINGS,
  videoGenerationSettings = DEFAULT_PRODUCTION_VIDEO_SETTINGS,
  videoGenerationSettingsError = "",
  videoGenerationSettingsStatus = "ready",
  listSignal = 0,
  navigationTarget = null,
  onNavigationChange,
  onNotificationsChanged,
  onOpenModelSettings,
  onReloadVideoGenerationSettings,
  onProjectsChanged,
  onNotice,
}) {
  const sourceProductionDefaults = useMemo(
    () => productionDefaultsForSource({
      width: sourceMedia.width,
      height: sourceMedia.height,
      aspectRatio: sourceMedia.aspectRatio,
    }),
    [sourceMedia.aspectRatio, sourceMedia.height, sourceMedia.width],
  );
  const [selectedProjectId, setSelectedProjectId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [analysisUpdatePreview, setAnalysisUpdatePreview] = useState(null);
  const [analysisUpdateOpen, setAnalysisUpdateOpen] = useState(false);
  const [analysisUpdateDecisions, setAnalysisUpdateDecisions] = useState({});
  const [analysisUpdateError, setAnalysisUpdateError] = useState("");
  const [assets, setAssets] = useState([]);
  const [revisions, setRevisions] = useState([]);
  const [shots, setShots] = useState([]);
  const [gate, setGate] = useState(null);
  const [continuityReport, setContinuityReport] = useState(null);
  const [selectedShotId, setSelectedShotId] = useState(null);
  const [selectedVisualBeatId, setSelectedVisualBeatId] = useState(null);
  const [shotDetail, setShotDetail] = useState(null);
  const [shotDraft, setShotDraft] = useState({ ...EMPTY_SHOT_DRAFT });
  const {
    flushVideoDraft,
    hydrateVideoDraft,
    resetVideoDraft,
    setVideoDraft,
    videoDraft,
  } = useShotVideoGenerationDraft({ request, onNotice });
  const [impactReview, setImpactReview] = useState(null);
  const [activeSection, setActiveSection] = useState("project_setup");
  const [contentLoading, setContentLoading] = useState(false);
  const [contentError, setContentError] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState({
    ...EMPTY_CREATE_DRAFT,
    ...sourceProductionDefaults,
  });
  const [settingsDraft, setSettingsDraft] = useState({ ...EMPTY_CREATE_DRAFT });
  const [referenceMode, setReferenceMode] = useState(null);
  const [referenceAsset, setReferenceAsset] = useState(null);
  const [referenceDraft, setReferenceDraft] = useState({ ...EMPTY_REFERENCE_DRAFT });
  const [referenceFile, setReferenceFile] = useState(null);
  const [archiveAsset, setArchiveAsset] = useState(null);
  const [assetPickerOpen, setAssetPickerOpen] = useState(false);
  const [assetPickerLoading, setAssetPickerLoading] = useState(false);
  const [assetPickerError, setAssetPickerError] = useState("");
  const [libraryAssets, setLibraryAssets] = useState([]);
  const [selectedLibraryAssetId, setSelectedLibraryAssetId] = useState(null);
  const [previewRevision, setPreviewRevision] = useState(null);
  const [previewDetail, setPreviewDetail] = useState(null);
  const [previewError, setPreviewError] = useState("");
  const [branchRevision, setBranchRevision] = useState(null);
  const [branchName, setBranchName] = useState("");
  const [generationSettings, setGenerationSettings] = useState(
    imageGenerationSettings || DEFAULT_PRODUCTION_IMAGE_SETTINGS,
  );
  const [generationEngine, setGenerationEngine] = useState("default");
  const [generationInputMode, setGenerationInputMode] = useState("keyframe_edit");
  const [generationCandidateCount, setGenerationCandidateCount] = useState(1);
  const [focusedCandidateId, setFocusedCandidateId] = useState("");
  const referencePreviewUrl = useObjectUrl(referenceFile);
  const imageGate = useMemo(() => {
    const requiredShots = shots.filter(
      (item) => item.plan.lifecycle_status !== "discarded" && item.plan.required !== false,
    );
    const approvedCount = requiredShots.filter(
      (item) => item.plan.image_status === "approved",
    ).length;
    return {
      allowed: requiredShots.length > 0 && approvedCount === requiredShots.length,
      required_shot_count: requiredShots.length,
      approved_shot_count: approvedCount,
      blocker_messages: approvedCount === requiredShots.length
        ? []
        : [`仍有 ${requiredShots.length - approvedCount} 个必需分镜图片未确认`],
    };
  }, [shots]);

  useEffect(() => {
    setGenerationSettings(
      imageGenerationSettings || DEFAULT_PRODUCTION_IMAGE_SETTINGS,
    );
  }, [imageGenerationSettings]);

  useEffect(() => {
    if (!listSignal) return;
    setSelectedProjectId(null);
    setDetail(null);
    setAnalysisUpdatePreview(null);
    setAnalysisUpdateOpen(false);
    setAnalysisUpdateDecisions({});
    setAnalysisUpdateError("");
    setContentError("");
    setActionError("");
    setContinuityReport(null);
    setActiveSection("project_setup");
  }, [listSignal]);

  useEffect(() => {
    if (!selectedProjectId) {
      onNavigationChange?.("");
      return;
    }
    const projectName = detail?.project?.id === selectedProjectId
      ? detail.project.name
      : projects.find((project) => project.id === selectedProjectId)?.name || "";
    onNavigationChange?.(projectName);
  }, [detail?.project?.id, detail?.project?.name, onNavigationChange, projects, selectedProjectId]);

  useEffect(() => {
    setSelectedProjectId(null);
    setDetail(null);
    setAnalysisUpdatePreview(null);
    setAnalysisUpdateOpen(false);
    setAnalysisUpdateDecisions({});
    setAnalysisUpdateError("");
    setAssets([]);
    setRevisions([]);
    setShots([]);
    setGate(null);
    setContinuityReport(null);
    setSelectedShotId(null);
    setSelectedVisualBeatId(null);
    setShotDetail(null);
    setShotDraft({ ...EMPTY_SHOT_DRAFT });
    resetVideoDraft();
    setImpactReview(null);
    setActiveSection("project_setup");
    setCreateOpen(false);
    setReferenceMode(null);
    setArchiveAsset(null);
    setPreviewRevision(null);
    setBranchRevision(null);
    setGenerationSettings(
      imageGenerationSettings || DEFAULT_PRODUCTION_IMAGE_SETTINGS,
    );
    setGenerationEngine("default");
    setGenerationInputMode("keyframe_edit");
    setGenerationCandidateCount(1);
    setFocusedCandidateId("");
  }, [recordId]);

  useEffect(() => {
    if (
      !navigationTarget?.token
      || !navigationTarget.projectId
      || (navigationTarget.recordId && navigationTarget.recordId !== recordId)
    ) {
      return;
    }
    setFocusedCandidateId(navigationTarget.candidateId || "");
    openProject(navigationTarget.projectId, {
      section: navigationTarget.step || "shot_videos",
      shotPlanId: navigationTarget.shotPlanId || null,
    }).catch(() => undefined);
  }, [navigationTarget?.token, recordId]);

  const activeGenerationRun = (shotDetail?.generation_runs || []).find(
    (run) => ACTIVE_GENERATION_RUN_STATUSES.has(run.status),
  );

  useEffect(() => {
    if (!activeGenerationRun?.id || !selectedProjectId || !selectedShotId) {
      return undefined;
    }
    let disposed = false;
    let timer = null;
    const runId = activeGenerationRun.id;
    const projectId = selectedProjectId;
    const shotPlanId = selectedShotId;

    async function pollGenerationRun() {
      try {
        const run = await request(`/generation-runs/${runId}`);
        if (disposed) return;
        setShotDetail((current) => upsertGenerationRun(current, run));
        if (ACTIVE_GENERATION_RUN_STATUSES.has(run.status)) {
          timer = window.setTimeout(pollGenerationRun, 1000);
          return;
        }
        await Promise.all([
          refreshProject(projectId, shotPlanId),
          onProjectsChanged(),
          onNotificationsChanged?.(),
        ]);
      } catch {
        if (!disposed) {
          timer = window.setTimeout(pollGenerationRun, 2000);
        }
      }
    }

    timer = window.setTimeout(pollGenerationRun, 500);
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [
    activeGenerationRun?.id,
    activeGenerationRun?.status,
    selectedProjectId,
    selectedShotId,
  ]);

  async function loadContinuityReport(projectId) {
    try {
      return await request(`/productions/${projectId}/continuity-reports/latest`);
    } catch (error) {
      if (error?.status === 404) return null;
      throw error;
    }
  }

  async function refreshProject(
    projectId = selectedProjectId,
    preferredShotId = selectedShotId,
    preferredVisualBeatId = selectedVisualBeatId,
  ) {
    if (!projectId) return null;
    const [
      nextDetail,
      nextAssets,
      nextRevisions,
      nextShots,
      nextGate,
      nextGenerationSettings,
      nextContinuityReport,
    ] = await Promise.all([
      request(`/productions/${projectId}`),
      request(`/productions/${projectId}/references`),
      request(`/productions/${projectId}/revisions`),
      request(`/productions/${projectId}/shots`),
      request(`/productions/${projectId}/gate-status`),
      request("/settings/image-generation"),
      loadContinuityReport(projectId),
    ]);
    setDetail(nextDetail);
    setAssets(nextAssets || []);
    setRevisions(nextRevisions || []);
    setShots(nextShots || []);
    setGate(nextGate);
    setContinuityReport(nextContinuityReport);
    setGenerationSettings(nextGenerationSettings);
    setSettingsDraft(settingsFromProject(nextDetail.project));
    const targetShotId = (
      preferredShotId
      && (nextShots || []).some(
        (item) => item.plan.id === preferredShotId
          && item.plan.lifecycle_status !== "discarded",
      )
    )
      ? preferredShotId
      : (nextShots || []).find(
        (item) => item.plan.lifecycle_status !== "discarded",
      )?.plan?.id || null;
    setSelectedShotId(targetShotId);
    if (targetShotId) {
      const [nextShotDetail, persistedVideoDraft] = await Promise.all([
        request(`/production-shots/${targetShotId}`),
        request(`/production-shots/${targetShotId}/video-generation-draft`),
      ]);
      const targetVisualBeat = visualBeatFromDetail(
        nextShotDetail,
        preferredVisualBeatId,
      );
      setShotDetail(nextShotDetail);
      setSelectedVisualBeatId(targetVisualBeat?.id || null);
      setShotDraft(shotDraftFromDetail(nextShotDetail, targetVisualBeat?.id));
      hydrateVideoDraft({
        shotPlanId: targetShotId,
        detail: nextShotDetail,
        settings: videoGenerationSettings,
        persistedDraft: persistedVideoDraft,
      });
    } else {
      setShotDetail(null);
      setSelectedVisualBeatId(null);
      setShotDraft({ ...EMPTY_SHOT_DRAFT });
      resetVideoDraft();
    }
    await refreshAnalysisUpdate(projectId);
    return nextDetail;
  }

  async function refreshAnalysisUpdate(projectId = selectedProjectId) {
    if (!projectId) return null;
    try {
      const preview = await request(`/productions/${projectId}/analysis-update`);
      setAnalysisUpdatePreview(preview);
      setAnalysisUpdateError("");
      const defaults = {};
      for (const shot of preview.shots || []) {
        for (const field of shot.fields || []) {
          defaults[promptDecisionKey(shot.shot_plan_id, field.field_key)] = field.suggested_choice;
        }
      }
      setAnalysisUpdateDecisions(defaults);
      if (!preview.update_available) setAnalysisUpdateOpen(false);
      return preview;
    } catch (requestError) {
      setAnalysisUpdatePreview(null);
      setAnalysisUpdateOpen(false);
      setAnalysisUpdateDecisions({});
      setAnalysisUpdateError(requestError.message);
      return null;
    }
  }

  async function openProject(
    projectId,
    { section = "project_setup", shotPlanId = null } = {},
  ) {
    setSelectedProjectId(projectId);
    setContentLoading(true);
    setContentError("");
    setActionError("");
    setActiveSection(section);
    setSelectedShotId(null);
    setSelectedVisualBeatId(null);
    setShotDetail(null);
    resetVideoDraft();
    setImpactReview(null);
    setAnalysisUpdatePreview(null);
    setAnalysisUpdateOpen(false);
    setAnalysisUpdateDecisions({});
    setAnalysisUpdateError("");
    try {
      await refreshProject(projectId, shotPlanId);
    } catch (requestError) {
      setContentError(requestError.message);
    } finally {
      setContentLoading(false);
    }
  }

  async function selectShot(shotPlanId) {
    await flushVideoDraft().catch(() => undefined);
    setSelectedShotId(shotPlanId);
    setActionError("");
    setImpactReview(null);
    setShotDetail(null);
    try {
      const [nextShotDetail, persistedVideoDraft] = await Promise.all([
        request(`/production-shots/${shotPlanId}`),
        request(`/production-shots/${shotPlanId}/video-generation-draft`),
      ]);
      const firstVisualBeat = visualBeatFromDetail(nextShotDetail);
      setShotDetail(nextShotDetail);
      setSelectedVisualBeatId(firstVisualBeat?.id || null);
      setShotDraft(shotDraftFromDetail(nextShotDetail, firstVisualBeat?.id));
      hydrateVideoDraft({
        shotPlanId,
        detail: nextShotDetail,
        settings: videoGenerationSettings,
        persistedDraft: persistedVideoDraft,
      });
    } catch (requestError) {
      setActionError(requestError.message);
    }
  }

  async function executeAction(action) {
    setBusy(true);
    setActionError("");
    try {
      await action(false);
    } catch (requestError) {
      setActionError(requestError.message);
      onNotice({
        type: "error",
        title: "操作失败",
        message: requestError.message,
      });
    } finally {
      setBusy(false);
    }
  }

  async function prepareImpact(
    { changeType, shotPlanIds = [], referenceAssetIds = [], title },
    action,
  ) {
    setBusy(true);
    setActionError("");
    try {
      const impact = await request(
        `/productions/${detail.project.id}/change-impact`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            change_type: changeType,
            shot_plan_ids: shotPlanIds,
            reference_asset_ids: referenceAssetIds,
          }),
        },
      );
      if (impact.requires_confirmation) {
        setImpactReview({ impact, title, action });
      } else {
        await action(false);
      }
    } catch (requestError) {
      setActionError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmImpactReview() {
    if (!impactReview) return;
    const review = impactReview;
    setBusy(true);
    setActionError("");
    try {
      await review.action(true);
      setImpactReview(null);
    } catch (requestError) {
      setActionError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitShot(event) {
    event.preventDefault();
    const { activeBeat, beatChanges, shotChanges } = shotDraftPatch(
      shotDetail,
      selectedVisualBeatId,
      shotDraft,
    );
    if (!shotDetail?.plan || !activeBeat) return;
    if (
      Object.keys(beatChanges).length === 0
      && Object.keys(shotChanges).length === 0
    ) {
      onNotice("当前画面没有需要保存的修改");
      return;
    }
    const apply = async (confirmStale) => {
      await persistShotDraftChanges({
        activeBeat,
        beatChanges,
        shotChanges,
        confirmStale,
      });
      await Promise.all([
        refreshProject(detail.project.id, shotDetail.plan.id, activeBeat.id),
        onProjectsChanged(),
      ]);
      onNotice(`分镜 ${shotDetail.plan.index} 的画面 ${activeBeat.index} 已保存`);
    };
    const changesImageInput = Object.keys(beatChanges).length > 0
      || Object.keys(shotChanges).length > 0;
    if (changesImageInput) {
      await prepareImpact(
        {
          changeType: "shot_plan",
          shotPlanIds: [shotDetail.plan.id],
          title: "保存分镜修改",
        },
        apply,
      );
    } else {
      await executeAction(apply);
    }
  }

  async function createShot(payload) {
    if (!detail?.project) return;
    await executeAction(async () => {
      const created = await request(
        `/productions/${detail.project.id}/shots`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            ...payload,
          }),
        },
      );
      await Promise.all([
        refreshProject(detail.project.id, created.plan.id),
        onProjectsChanged(),
      ]);
      onNotice(`已新增分镜 ${created.plan.index}`);
    });
  }

  async function discardShot(shotPlanId) {
    if (!detail?.project) return;
    const activeShots = shots.filter(
      (item) => item.plan.lifecycle_status !== "discarded",
    );
    const currentIndex = activeShots.findIndex((item) => item.plan.id === shotPlanId);
    const preferredShotId = (
      activeShots[currentIndex + 1]?.plan.id
      || activeShots[currentIndex - 1]?.plan.id
      || null
    );
    await executeAction(async () => {
      await request(`/production-shots/${shotPlanId}/discard`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, preferredShotId),
        onProjectsChanged(),
      ]);
      onNotice("分镜已舍弃，可从列表底部恢复");
    });
  }

  async function restoreShot(shotPlanId) {
    if (!detail?.project) return;
    await executeAction(async () => {
      await request(`/production-shots/${shotPlanId}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, shotPlanId),
        onProjectsChanged(),
      ]);
      onNotice("分镜已恢复到有效分镜末尾");
    });
  }

  async function reorderShots(orderedShotPlanIds) {
    if (!detail?.project) return;
    await executeAction(async () => {
      await request(`/productions/${detail.project.id}/shots/order`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
          ordered_shot_plan_ids: orderedShotPlanIds,
        }),
      });
      await refreshProject(detail.project.id, selectedShotId);
      onNotice("分镜顺序已更新");
    });
  }

  async function generateShotCandidates() {
    const { activeBeat, beatChanges, shotChanges } = shotDraftPatch(
      shotDetail,
      selectedVisualBeatId,
      shotDraft,
    );
    if (!shotDetail?.plan || !activeBeat) return;
    const candidateCount = Math.min(
      4,
      Math.max(1, Math.trunc(Number(generationCandidateCount) || 1)),
    );
    const executionMode = resolveImageExecutionMode(
      generationSettings,
      generationEngine,
    );
    const acceptsUnknownCost = (
      generationSettings.enabled
      && executionMode === "local_tool"
      && generationSettings.local_cost_source === "unknown"
    );
    if (
      acceptsUnknownCost
      && !window.confirm(
        `本机工具无法提供可验证的成本信息。是否仍要为画面 ${activeBeat.index} 生成 ${candidateCount} 张候选？`,
      )
    ) {
      return;
    }
    await executeAction(async () => {
      const draftChanged = Object.keys(beatChanges).length > 0
        || Object.keys(shotChanges).length > 0;
      const expectedRevisionId = await persistShotDraftChanges({
        activeBeat,
        beatChanges,
        shotChanges,
      });
      const effectiveInputMode = shotDraft.referenceBindings.some(
        (binding) => binding.role === "identity",
      )
        ? "keyframe_edit"
        : generationInputMode;
      const run = await request(
        `/production-shots/${shotDetail.plan.id}/image-runs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: expectedRevisionId,
            visual_beat_id: activeBeat.id,
            candidate_count: candidateCount,
            input_mode: effectiveInputMode,
            execution_mode: executionMode,
            allow_unknown_cost: acceptsUnknownCost,
            generation_intent: imageGenerationIntentForShot(shotDetail),
          }),
        },
      );
      setShotDetail((current) => upsertGenerationRun(current, run));
      await onProjectsChanged();
      onNotice(
        `${draftChanged ? "当前提示词与参考资产已自动保存；" : ""}分镜 ${shotDetail.plan.index} 画面 ${activeBeat.index} 的图片任务已加入队列`,
      );
    });
  }

  async function cancelShotGeneration(runId) {
    if (!runId) return;
    await executeAction(async () => {
      const run = await request(`/generation-runs/${runId}/cancel`, {
        method: "POST",
      });
      setShotDetail((current) => upsertGenerationRun(current, run));
      onNotice("图片生成任务已取消");
    });
  }

  async function retryShotGeneration(runId) {
    if (!runId) return;
    await executeAction(async () => {
      const run = await request(`/generation-runs/${runId}/retry`, {
        method: "POST",
      });
      setShotDetail((current) => upsertGenerationRun(current, run));
      await onProjectsChanged();
      onNotice("重试任务已加入队列");
    });
  }

  async function selectSourceKeyframe(timestampSeconds) {
    const activeBeat = visualBeatFromDetail(shotDetail, selectedVisualBeatId);
    if (!shotDetail?.plan || !activeBeat) return;
    const hasReviewedOutput = (
      Boolean(activeBeat.approved_image_candidate_id)
      || ["approved", "review_required", "stale"].includes(
        activeBeat.image_status,
      )
    );
    if (
      hasReviewedOutput
      && !window.confirm(
        "更换关键帧会归档当前图片候选，并使后续视频结果过期。是否继续？",
      )
    ) {
      return;
    }
    await executeAction(async () => {
      await request(
        "/production-shots/" + shotDetail.plan.id + "/source-keyframe",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            visual_beat_id: activeBeat.id,
            timestamp_seconds: Number(timestampSeconds),
            confirm_stale: hasReviewedOutput,
          }),
        },
      );
      await Promise.all([
        refreshProject(detail.project.id, shotDetail.plan.id, activeBeat.id),
        onProjectsChanged(),
      ]);
      onNotice("分镜 " + shotDetail.plan.index + " 的关键帧已更新");
    });
  }

  async function approveSourceKeyframe() {
    const activeBeat = visualBeatFromDetail(shotDetail, selectedVisualBeatId);
    if (!shotDetail?.plan || !activeBeat) return;
    const shotPlanId = shotDetail.plan.id;
    const replacingApproved = activeBeat.image_status === "approved";
    const expectedRevisionId = detail.project.current_revision_id;
    const apply = async (confirmDownstreamStale) => {
      await request(
        "/production-shots/" + shotPlanId + "/source-keyframe/approval",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: expectedRevisionId,
            visual_beat_id: activeBeat.id,
            confirm_downstream_stale: confirmDownstreamStale,
          }),
        },
      );
      await Promise.all([
        refreshProject(detail.project.id, shotPlanId, activeBeat.id),
        onProjectsChanged(),
      ]);
      onNotice(replacingApproved
        ? "已改用当前关键帧，历史 AI 候选仍保留"
        : "已直接使用当前关键帧，未调用图片生成模型");
    };
    if (replacingApproved) {
      await prepareImpact(
        {
          changeType: "candidate_selection",
          shotPlanIds: [shotPlanId],
          title: "改用当前视频关键帧",
        },
        apply,
      );
    } else {
      await executeAction(() => apply(false));
    }
  }

  async function selectCandidate(candidateId) {
    await executeAction(async () => {
      await request(`/generation-candidates/${candidateId}/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      onNotice("候选已选择，请继续人工确认");
    });
  }

  async function approveCandidate(candidateId) {
    const activeBeat = visualBeatFromDetail(shotDetail, selectedVisualBeatId);
    if (!shotDetail?.plan || !activeBeat) return;
    const shotPlanId = shotDetail.plan.id;
    const replacingApproved = (
      activeBeat.image_status === "approved"
      && activeBeat.approved_image_candidate_id !== candidateId
    );
    const expectedRevisionId = detail.project.current_revision_id;
    const apply = async (confirmDownstreamStale) => {
      await request(
        `/generation-candidates/${candidateId}/approvals`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: expectedRevisionId,
            decision: "approved",
            confirm_downstream_stale: confirmDownstreamStale,
          }),
        },
      );
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId, activeBeat.id),
        onProjectsChanged(),
      ]);
      onNotice(replacingApproved
        ? "已改用所选历史候选，其他候选仍保留"
        : `画面 ${activeBeat.index} 图片已确认`);
    };
    if (replacingApproved) {
      await prepareImpact(
        {
          changeType: "candidate_selection",
          shotPlanIds: [shotPlanId],
          title: "改用所选图片候选",
        },
        apply,
      );
    } else {
      await executeAction(() => apply(false));
    }
  }

  async function persistShotDraftChanges({
    activeBeat,
    beatChanges,
    shotChanges,
    confirmStale = false,
  }) {
    let expectedRevisionId = detail.project.current_revision_id;
    if (Object.keys(beatChanges).length > 0) {
      const updated = await request(
        `/production-shots/${shotDetail.plan.id}/visual-beats/${activeBeat.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: expectedRevisionId,
            confirm_stale: confirmStale,
            ...beatChanges,
          }),
        },
      );
      expectedRevisionId = updated.current_revision_id;
    }
    if (Object.keys(shotChanges).length > 0) {
      const updated = await request(`/production-shots/${shotDetail.plan.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: expectedRevisionId,
          confirm_stale: confirmStale,
          ...shotChanges,
        }),
      });
      expectedRevisionId = updated.current_revision_id;
    }
    return expectedRevisionId;
  }

  async function syncAnalysisPrompts() {
    if (!detail?.project || !analysisUpdatePreview) return;
    setBusy(true);
    setAnalysisUpdateError("");
    try {
      const decisions = (analysisUpdatePreview.shots || []).flatMap((shot) => (
        (shot.fields || []).map((field) => ({
          shot_plan_id: shot.shot_plan_id,
          field_key: field.field_key,
          choice: analysisUpdateDecisions[
            promptDecisionKey(shot.shot_plan_id, field.field_key)
          ] || field.suggested_choice,
        }))
      ));
      await request(
        `/productions/${detail.project.id}/analysis-update/sync-prompts`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            target_analysis_id: analysisUpdatePreview.target_analysis_id,
            decisions,
          }),
        },
      );
      setAnalysisUpdateOpen(false);
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId, selectedVisualBeatId),
        onProjectsChanged(),
      ]);
      onNotice("已同步所选提示词，并创建新的 Revision");
    } catch (requestError) {
      setAnalysisUpdateError(requestError.message);
      onNotice({
        type: "error",
        title: "提示词同步失败",
        message: requestError.message,
      });
    } finally {
      setBusy(false);
    }
  }

  function selectVisualBeat(visualBeatId) {
    const beat = visualBeatFromDetail(shotDetail, visualBeatId);
    if (!beat) return;
    setSelectedVisualBeatId(beat.id);
    setShotDraft(shotDraftFromDetail(shotDetail, beat.id));
    setActionError("");
  }

  async function revokeImageApproval() {
    const activeBeat = visualBeatFromDetail(shotDetail, selectedVisualBeatId);
    if (!shotDetail?.plan || activeBeat?.image_status !== "approved") return;
    const shotPlanId = shotDetail.plan.id;
    const shotIndex = shotDetail.plan.index;
    const expectedRevisionId = detail.project.current_revision_id;
    await executeAction(async () => {
      await request(
        `/production-shots/${shotPlanId}/image-approval/revoke`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: expectedRevisionId,
            visual_beat_id: activeBeat.id,
            reason: "用户重新打开图片审核",
            confirm_downstream_stale: true,
          }),
        },
      );
      await Promise.all([
        refreshProject(detail.project.id, shotPlanId, activeBeat.id),
        onProjectsChanged(),
      ]);
      onNotice(`已取消采用分镜 ${shotIndex} 的图片；相关后续结果已标记为需要更新`);
    });
  }

  async function createVisualBeat() {
    if (!shotDetail?.plan) return;
    const beats = shotDetail.plan.visual_beats || [];
    const current = visualBeatFromDetail(shotDetail, selectedVisualBeatId);
    await executeAction(async () => {
      const updated = await request(
        `/production-shots/${shotDetail.plan.id}/visual-beats`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            insert_after_visual_beat_id: current?.id || null,
            title: `画面 ${beats.length + 1}`,
            image_prompt: "",
            required: true,
          }),
        },
      );
      const previousIds = new Set(beats.map((item) => item.id));
      const created = (updated.plan.visual_beats || []).find(
        (item) => !previousIds.has(item.id),
      );
      await Promise.all([
        refreshProject(
          detail.project.id,
          shotDetail.plan.id,
          created?.id || current?.id,
        ),
        onProjectsChanged(),
      ]);
      onNotice(`已新增画面 ${created?.index || beats.length + 1}`);
    });
  }

  async function reorderVisualBeats(orderedVisualBeatIds) {
    if (!shotDetail?.plan) return;
    await executeAction(async () => {
      await request(`/production-shots/${shotDetail.plan.id}/visual-beats/order`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
          ordered_visual_beat_ids: orderedVisualBeatIds,
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, shotDetail.plan.id, selectedVisualBeatId),
        onProjectsChanged(),
      ]);
      onNotice("画面顺序已更新；视频输入图号将按新顺序重新编号");
    });
  }

  async function deleteVisualBeat(visualBeatId) {
    if (!shotDetail?.plan || (shotDetail.plan.visual_beats || []).length <= 1) return;
    const beats = shotDetail.plan.visual_beats || [];
    const index = beats.findIndex((item) => item.id === visualBeatId);
    const nextSelected = beats[index + 1] || beats[index - 1] || null;
    const hasDownstream = ["generating", "review_required", "approved", "stale"].includes(
      shotDetail.plan.video_status,
    );
    if (
      hasDownstream
      && !window.confirm("删除画面会使当前分段视频及下游结果过期。是否继续？")
    ) return;
    await executeAction(async () => {
      await request(
        `/production-shots/${shotDetail.plan.id}/visual-beats/${visualBeatId}`,
        {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            confirm_stale: hasDownstream,
          }),
        },
      );
      await Promise.all([
        refreshProject(detail.project.id, shotDetail.plan.id, nextSelected?.id),
        onProjectsChanged(),
      ]);
      onNotice("画面已删除并重新编号");
    });
  }

  async function updateVisualBeat(visualBeatId, changes) {
    if (!shotDetail?.plan || !Object.keys(changes || {}).length) return;
    const hasDownstream = ["generating", "review_required", "approved", "stale"].includes(
      shotDetail.plan.video_status,
    );
    await executeAction(async () => {
      await request(
        `/production-shots/${shotDetail.plan.id}/visual-beats/${visualBeatId}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            confirm_stale: hasDownstream,
            ...changes,
          }),
        },
      );
      await Promise.all([
        refreshProject(detail.project.id, shotDetail.plan.id, visualBeatId),
        onProjectsChanged(),
      ]);
    });
  }

  async function advanceWorkflow() {
    await executeAction(async () => {
      await request(`/productions/${detail.project.id}/advance`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
          target_step: "shot_videos",
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      setActiveSection("shot_videos");
      onNotice("图片阶段已完成，已进入分段视频工作台");
    });
  }

  async function generateVideoCandidates() {
    if (!shotDetail?.plan) return;
    const candidateCount = Math.min(
      4,
      Math.max(1, Math.trunc(Number(videoDraft.candidateCount) || 1)),
    );
    const durationSeconds = Number(videoDraft.durationSeconds);
    const hasPriorCandidate = (shotDetail.generation_runs || []).some(
      (run) => run.kind === "video" && (run.candidates || []).length > 0,
    );
    const selectedModel = (videoGenerationSettings.models || []).find(
      (item) => item.alias === videoDraft.modelAlias,
    );
    const costUnknown = !selectedModel
      || ["unknown", "provider_usage_tokens"].includes(selectedModel.pricing?.kind);
    const promptChanges = videoPromptChangesFromDraft(shotDetail, videoDraft);
    const promptChanged = Object.keys(promptChanges).length > 0;
    const confirmStale = promptChanged && shotDetail.plan.video_status === "approved";
    if (
      confirmStale
      && !window.confirm("生成前会自动保存当前提示词，并使已采用视频过期。是否继续？")
    ) {
      return;
    }
    if (
      costUnknown
      && !window.confirm("该模型需要按 Provider 实际用量结算，提交前无法给出可靠金额。是否继续？")
    ) {
      return;
    }
    await executeAction(async () => {
      await flushVideoDraft(shotDetail.plan.id);
      let expectedRevisionId = detail.project.current_revision_id;
      let persistedShotDetail = null;
      if (promptChanged) {
        persistedShotDetail = await request(`/production-shots/${shotDetail.plan.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: expectedRevisionId,
            confirm_stale: confirmStale,
            ...promptChanges,
          }),
        });
        expectedRevisionId = persistedShotDetail.current_revision_id;
        setDetail((current) => current ? ({
          ...current,
          project: {
            ...current.project,
            active_step: "shot_videos",
            current_revision_id: expectedRevisionId,
          },
        }) : current);
        setShots((current) => current.map((item) => (
          item.plan.id === persistedShotDetail.plan.id
            ? {
              ...item,
              current_revision_id: expectedRevisionId,
              image_preview: persistedShotDetail.image_preview,
              plan: persistedShotDetail.plan,
              reference_bindings: persistedShotDetail.reference_bindings,
              video_preview: persistedShotDetail.video_preview,
            }
            : item
        )));
        setShotDetail(persistedShotDetail);
      }
      const run = await request(
        `/production-shots/${shotDetail.plan.id}/video-runs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: expectedRevisionId,
            candidate_count: candidateCount,
            input_mode: "multi_image_to_video",
            execution_mode: "remote_api",
            model_alias: videoDraft.modelAlias,
            resolution: videoDraft.resolution,
            duration_seconds: Number.isFinite(durationSeconds)
              ? durationSeconds
              : shotDetail.plan.duration_seconds,
            generation_intent: hasPriorCandidate ? "new_variation" : "standard",
            allow_unknown_cost: costUnknown,
          }),
        },
      );
      setShotDetail((current) => upsertGenerationRun(
        persistedShotDetail || current,
        run,
      ));
      await onProjectsChanged();
      await onNotificationsChanged?.();
      onNotice(promptChanged
        ? `提示词已自动保存，分镜 ${shotDetail.plan.index} 的 ${selectedModel?.label || "视频"} 任务已加入队列`
        : `分镜 ${shotDetail.plan.index} 的 ${selectedModel?.label || "视频"} 任务已加入队列`);
    });
  }

  async function updateManagedAssetBinding(binding) {
    if (!shotDetail?.plan || !detail?.project) return false;
    if (
      shotDetail.plan.video_status === "approved"
      && !window.confirm("更改演员身份会使当前已采用视频过期。是否继续？")
    ) {
      return false;
    }
    let succeeded = false;
    await executeAction(async () => {
      const updated = await request(`/production-shots/${shotDetail.plan.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
          confirm_stale: shotDetail.plan.video_status === "approved",
          managed_asset_bindings: binding ? [binding] : [],
        }),
      });
      await Promise.all([
        refreshProject(
          detail.project.id,
          updated.plan.id,
          selectedVisualBeatId,
        ),
        onProjectsChanged(),
      ]);
      onNotice(
        binding
          ? `已将 ${binding.name} 绑定为分镜 ${shotDetail.plan.index} 的演员身份`
          : `已解除分镜 ${shotDetail.plan.index} 的演员身份绑定`,
      );
      succeeded = true;
    });
    return succeeded;
  }

  async function createReferenceProxy({
    kind,
    sourceKind,
    sourceCandidateId = null,
    visualBeatId,
    renderProfile = "structural",
    privacyMode = null,
    enhancerEngine = null,
    fallbackToStructural = true,
    allowUnknownCost = false,
  }) {
    if (!shotDetail?.plan || !detail?.project || !visualBeatId) return false;
    let succeeded = false;
    await executeAction(async () => {
      const response = await request(
        `/video-references/shots/${shotDetail.plan.id}/proxies`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            source_kind: sourceKind,
            source_candidate_id: sourceCandidateId,
            visual_beat_id: visualBeatId,
            kind,
            order: 1,
            render_profile: renderProfile,
            privacy_mode: privacyMode,
            enhancer_engine: enhancerEngine,
            fallback_to_structural: fallbackToStructural,
            allow_unknown_cost: allowUnknownCost,
          }),
        },
      );
      await Promise.all([
        refreshProject(
          detail.project.id,
          shotDetail.plan.id,
          visualBeatId,
        ),
        onProjectsChanged(),
      ]);
      const proxyLabel = response.proxy.media_type === "video"
        ? "视频动作白模"
        : "图片姿态白模";
      onNotice(
        response.proxy.fallback_applied
          ? `${proxyLabel}的 AI 增强未通过，已安全回退到本机结构白模`
          : response.proxy.semantic_validation_status === "passed"
            ? `${proxyLabel}${response.proxy.effective_render_profile === "ai_enhanced" ? "已完成 AI 增强，" : ""}已通过校验并自动启用`
          : `${proxyLabel}已生成，但姿态质量需要复核，暂未启用`,
      );
      succeeded = true;
    });
    return succeeded;
  }

  async function disableReferenceProxy(proxyAssetId) {
    return setReferenceProxyEnabled(proxyAssetId, false);
  }

  async function enableReferenceProxy(proxyAssetId) {
    return setReferenceProxyEnabled(proxyAssetId, true);
  }

  async function deleteReferenceProxy(proxyAssetId) {
    if (!shotDetail?.plan || !detail?.project || !proxyAssetId) return false;
    const target = (shotDetail.plan.reference_proxy_assets || []).find(
      (item) => item.id === proxyAssetId,
    );
    if (!target) return false;
    const inUse = (shotDetail.plan.video_reference_bindings || []).some(
      (item) => item.enabled && item.proxy_asset_id === proxyAssetId,
    );
    if (inUse) {
      onNotice({
        type: "error",
        title: "白模正在使用",
        message: "请先停用该白模，再执行删除。",
      });
      return false;
    }
    const label = target.media_type === "video" ? "视频白模" : "图片白模";
    if (
      typeof window !== "undefined"
      && !window.confirm(`永久删除此${label}及其本地文件？此操作无法恢复。`)
    ) {
      return false;
    }
    let succeeded = false;
    await executeAction(async () => {
      const query = new URLSearchParams({
        expected_revision_id: detail.project.current_revision_id,
      });
      const response = await request(
        `/video-references/shots/${shotDetail.plan.id}/proxies/${proxyAssetId}?${query}`,
        { method: "DELETE" },
      );
      await Promise.all([
        refreshProject(detail.project.id, shotDetail.plan.id, selectedVisualBeatId),
        onProjectsChanged(),
      ]);
      onNotice(
        response.local_content_removed
          ? {
              type: "success",
              title: `${label}已删除`,
              message: "方案记录与本地派生文件均已移除。",
            }
          : {
              type: "warning",
              title: `${label}已从方案删除`,
              message: response.cleanup_warning || "本地临时文件仍待清理。",
            },
      );
      succeeded = true;
    });
    return succeeded;
  }

  async function setReferenceProxyEnabled(proxyAssetId, enabled) {
    if (!shotDetail?.plan || !detail?.project || !proxyAssetId) return false;
    const target = (shotDetail.plan.reference_proxy_assets || []).find(
      (item) => item.id === proxyAssetId,
    );
    if (!target) return false;
    const nextBindings = (shotDetail.plan.video_reference_bindings || []).map((binding) => {
      if (binding.proxy_asset_id === proxyAssetId) {
        return { ...binding, enabled };
      }
      if (
        enabled
        && binding.source_kind === "generated_proxy"
        && binding.media_type === target.media_type
      ) {
        return { ...binding, enabled: false };
      }
      return binding;
    });
    let succeeded = false;
    await executeAction(async () => {
      const updated = await request(`/production-shots/${shotDetail.plan.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
          confirm_stale: shotDetail.plan.video_status === "approved",
          video_reference_bindings: nextBindings,
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, updated.plan.id, selectedVisualBeatId),
        onProjectsChanged(),
      ]);
      onNotice(
        enabled
          ? `${target.media_type === "video" ? "视频" : "图片"}白模已启用`
          : "白模已从当前生成策略停用；历史派生资产仍保留",
      );
      succeeded = true;
    });
    return succeeded;
  }

  async function cancelVideoGeneration(runId) {
    if (!runId) return;
    await executeAction(async () => {
      const run = await request(`/generation-runs/${runId}/cancel`, {
        method: "POST",
      });
      setShotDetail((current) => upsertGenerationRun(current, run));
      await onNotificationsChanged?.();
      onNotice("视频生成任务已取消");
    });
  }

  async function retryVideoGeneration(runId) {
    if (!runId) return;
    await executeAction(async () => {
      const run = await request(`/generation-runs/${runId}/retry`, {
        method: "POST",
      });
      setShotDetail((current) => upsertGenerationRun(current, run));
      await onProjectsChanged();
      await onNotificationsChanged?.();
      onNotice("视频重试任务已加入队列");
    });
  }

  async function archiveVideoCandidates(candidateIds) {
    if (!candidateIds?.length) return false;
    let succeeded = false;
    await executeAction(async () => {
      await request("/generation-candidates/batch-archive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
          candidate_ids: candidateIds,
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
        onNotificationsChanged?.(),
      ]);
      onNotice(`已将 ${candidateIds.length} 个视频候选移入回收站`);
      succeeded = true;
    });
    return succeeded;
  }

  async function restoreVideoCandidates(candidateIds) {
    if (!candidateIds?.length) return false;
    let succeeded = false;
    await executeAction(async () => {
      await request("/generation-candidates/batch-restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
          candidate_ids: candidateIds,
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
        onNotificationsChanged?.(),
      ]);
      onNotice(`已恢复 ${candidateIds.length} 个视频候选`);
      succeeded = true;
    });
    return succeeded;
  }

  async function selectVideoCandidate(candidateId) {
    await executeAction(async () => {
      await request(`/generation-candidates/${candidateId}/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      onNotice("视频候选已选择，请继续人工确认");
    });
  }

  async function restoreImageCandidate(candidateId, expectedRevisionId) {
    setBusy(true);
    setActionError("");
    try {
      await request("/generation-candidates/batch-restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: expectedRevisionId,
          candidate_ids: [candidateId],
        }),
      });
      await Promise.all([
        refreshProject(
          detail.project.id,
          selectedShotId,
          selectedVisualBeatId,
        ),
        onProjectsChanged(),
        onNotificationsChanged?.(),
      ]);
      onNotice("图片候选已恢复");
    } catch (requestError) {
      setActionError(requestError.message);
      onNotice({
        type: "error",
        title: "恢复失败",
        message: requestError.message,
      });
      throw requestError;
    } finally {
      setBusy(false);
    }
  }

  async function archiveImageCandidate(candidateId) {
    if (!candidateId) return false;
    let succeeded = false;
    await executeAction(async () => {
      const response = await request("/generation-candidates/batch-archive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
          candidate_ids: [candidateId],
        }),
      });
      await Promise.all([
        refreshProject(
          detail.project.id,
          selectedShotId,
          selectedVisualBeatId,
        ),
        onProjectsChanged(),
        onNotificationsChanged?.(),
      ]);
      onNotice({
        type: "success",
        message: "图片候选已删除，源文件仍保留",
        duration: 9000,
        actionLabel: "撤销",
        onAction: () => restoreImageCandidate(
          candidateId,
          response.current_revision_id,
        ),
      });
      succeeded = true;
    });
    return succeeded;
  }

  async function approveVideoCandidate(candidateId) {
    if (!shotDetail?.plan) return;
    const replacingApproved = (
      shotDetail.plan.video_status === "approved"
      && shotDetail.plan.approved_video_candidate_id !== candidateId
    );
    const hasDownstreamImpact = (
      replacingApproved
      && ["editing", "export"].includes(detail.project.active_step)
    );
    if (
      hasDownstreamImpact
      && !window.confirm("改用该视频会使剪辑或导出结果过期。是否继续？")
    ) {
      return;
    }
    await executeAction(async () => {
      await request(`/generation-candidates/${candidateId}/approvals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
          decision: "approved",
          confirm_downstream_stale: hasDownstreamImpact,
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      onNotice(replacingApproved
        ? "已改用所选视频，历史候选仍然保留"
        : "当前分镜视频已确认采用");
    });
  }

  async function rejectVideoCandidate(candidateId, reason) {
    await executeAction(async () => {
      await request(`/generation-candidates/${candidateId}/approvals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
          decision: "rejected",
          reason,
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      onNotice("视频候选已退回，可调整提示词后重新生成");
    });
  }

  async function revokeVideoApproval() {
    if (!shotDetail?.plan || shotDetail.plan.video_status !== "approved") return;
    const hasDownstreamImpact = ["editing", "export"].includes(
      detail.project.active_step,
    );
    if (
      hasDownstreamImpact
      && !window.confirm("取消采用会使剪辑或导出结果过期。是否继续？")
    ) {
      return;
    }
    await executeAction(async () => {
      await request(
        `/production-shots/${shotDetail.plan.id}/video-approval/revoke`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            reason: "用户重新打开视频审核",
            confirm_downstream_stale: hasDownstreamImpact,
          }),
        },
      );
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      setActiveSection("shot_videos");
      onNotice(`已取消采用分镜 ${shotDetail.plan.index} 的视频`);
    });
  }

  async function advanceToEditing() {
    await executeAction(async () => {
      const checkedReport = await request(
        `/productions/${detail.project.id}/continuity-reports`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
          }),
        },
      );
      setContinuityReport(checkedReport);
      const checkedGate = await request(
        `/productions/${detail.project.id}/gate-status`,
      );
      setGate(checkedGate);
      if (checkedReport.blocker_count > 0) {
        const message = `连续性质检仍有 ${checkedReport.blocker_count} 个阻断问题，请处理后再进入剪辑。`;
        setActionError(message);
        onNotice({
          type: "warning",
          title: "连续性质检未通过",
          message,
        });
        return;
      }
      await request(`/productions/${detail.project.id}/advance`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: detail.project.current_revision_id,
          target_step: "editing",
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      setActiveSection("editing");
      onNotice({
        type: "success",
        title: "已进入视频剪辑",
        message: "已采用的视频已加入初始时间线，可继续裁剪和调整轨道。",
      });
    });
  }

  async function runContinuityCheck() {
    await executeAction(async () => {
      const report = await request(
        `/productions/${detail.project.id}/continuity-reports`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
          }),
        },
      );
      const nextGate = await request(`/productions/${detail.project.id}/gate-status`);
      setContinuityReport(report);
      setGate(nextGate);
      onNotice({
        type: report.blocker_count > 0 ? "warning" : "success",
        title: report.blocker_count > 0 ? "发现连续性问题" : "连续性质检已完成",
        message: report.blocker_count > 0
          ? `有 ${report.blocker_count} 个阻断问题需要处理。`
          : report.verification_state === "verified"
            ? "相邻分镜未发现待处理问题。"
            : "结构规则已检查；当前尚未执行 VLM 视觉验证。",
      });
    });
  }

  async function decideContinuityFinding(finding, decision) {
    let reason = null;
    if (decision === "waive") {
      reason = window.prompt("请说明为什么这是有意变化", "剧情或镜头设计要求");
      if (!reason?.trim()) return;
    }
    await executeAction(async () => {
      const report = await request(
        `/productions/${detail.project.id}/continuity-reports/`
        + `${continuityReport.id}/findings/${finding.key}/decision`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            decision,
            reason: reason?.trim() || null,
          }),
        },
      );
      const nextGate = await request(`/productions/${detail.project.id}/gate-status`);
      setContinuityReport(report);
      setGate(nextGate);
    });
  }

  function openCreate() {
    setCreateDraft({
      ...EMPTY_CREATE_DRAFT,
      ...sourceProductionDefaults,
      name: defaultProductionName(sourceTitle),
    });
    setActionError("");
    setCreateOpen(true);
  }

  async function submitCreate(event) {
    event.preventDefault();
    setBusy(true);
    setActionError("");
    try {
      const created = await request(`/records/${recordId}/productions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_analysis_id: analysisId,
          name: createDraft.name.trim(),
          output_aspect_ratio: createDraft.outputAspectRatio,
          output_width: Number(createDraft.outputWidth),
          output_height: Number(createDraft.outputHeight),
          budget_limit_micros: budgetMicrosFromYuan(createDraft.budgetYuan),
        }),
      });
      setCreateOpen(false);
      await onProjectsChanged();
      await openProject(created.project.id);
      onNotice("创作方案已创建");
    } catch (requestError) {
      setActionError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitSettings(event) {
    event.preventDefault();
    const expectedRevisionId = detail.project.current_revision_id;
    const outputChanged = (
      settingsDraft.outputAspectRatio !== detail.project.output_aspect_ratio
      || Number(settingsDraft.outputWidth) !== detail.project.output_width
      || Number(settingsDraft.outputHeight) !== detail.project.output_height
    );
    const apply = async (confirmStale) => {
      await request(`/productions/${detail.project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: expectedRevisionId,
          confirm_stale: confirmStale,
          name: settingsDraft.name.trim(),
          output_aspect_ratio: settingsDraft.outputAspectRatio,
          output_width: Number(settingsDraft.outputWidth),
          output_height: Number(settingsDraft.outputHeight),
          budget_limit_micros: budgetMicrosFromYuan(settingsDraft.budgetYuan),
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      onNotice("方案设置已保存并创建新版本");
    };
    if (outputChanged) {
      await prepareImpact(
        {
          changeType: "project_settings",
          title: "修改全局输出规格",
        },
        apply,
      );
    } else {
      await executeAction(apply);
    }
  }

  async function openAssetPicker() {
    setAssetPickerOpen(true);
    setAssetPickerLoading(true);
    setAssetPickerError("");
    setSelectedLibraryAssetId(null);
    try {
      const context = await request("/context");
      const workspaceId = context?.active_workspace?.id;
      if (!workspaceId) throw new Error("当前工作区不可用");
      const result = await request(
        `/workspaces/${workspaceId}/assets?page=1&page_size=100`,
      );
      setLibraryAssets(result?.items || []);
    } catch (requestError) {
      setAssetPickerError(requestError.message);
    } finally {
      setAssetPickerLoading(false);
    }
  }

  async function confirmLibraryAsset() {
    if (!selectedLibraryAssetId) return;
    setBusy(true);
    setAssetPickerError("");
    try {
      await request(
        `/productions/${detail.project.id}/assets/${selectedLibraryAssetId}/link`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
          }),
        },
      );
      setAssetPickerOpen(false);
      setSelectedLibraryAssetId(null);
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      onNotice("资产已添加到当前项目");
    } catch (requestError) {
      setAssetPickerError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  function openReferenceUpload() {
    setReferenceMode("upload");
    setReferenceAsset(null);
    setReferenceFile(null);
    setReferenceDraft({ ...EMPTY_REFERENCE_DRAFT });
    setActionError("");
  }

  function openReferenceEdit(asset) {
    setReferenceMode("edit");
    setReferenceAsset(asset);
    setReferenceFile(null);
    setReferenceDraft({
      type: asset.type,
      name: asset.name,
      description: asset.description || "",
      tags: asset.tags.join("，"),
      rightsConfirmed: asset.rights_confirmed,
      rightsNote: asset.rights_note || "",
    });
    setActionError("");
  }

  function selectReferenceFile(nextFile) {
    setReferenceFile(nextFile);
    if (nextFile && !referenceDraft.name.trim()) {
      setReferenceDraft((state) => ({
        ...state,
        name: nextFile.name.replace(/\.[^.]+$/, ""),
      }));
    }
  }

  async function submitReference(event) {
    event.preventDefault();
    if (referenceMode === "upload") {
      await executeAction(async () => {
        if (!referenceFile) throw new Error("请选择要上传的参考图片");
        const form = new FormData();
        form.append("file", referenceFile);
        form.append("expected_revision_id", detail.project.current_revision_id);
        form.append("type", referenceDraft.type);
        form.append("name", referenceDraft.name.trim());
        form.append("description", referenceDraft.description.trim());
        form.append("tags", JSON.stringify(normalizeReferenceTags(referenceDraft.tags)));
        form.append("rights_confirmed", String(referenceDraft.rightsConfirmed));
        if (referenceDraft.rightsNote.trim()) form.append("rights_note", referenceDraft.rightsNote.trim());
        await request(`/productions/${detail.project.id}/references`, { method: "POST", body: form });
        setReferenceMode(null);
        await Promise.all([
          refreshProject(detail.project.id, selectedShotId),
          onProjectsChanged(),
        ]);
        onNotice("参考资产已上传");
      });
      return;
    }

    const assetId = referenceAsset.id;
    const expectedRevisionId = detail.project.current_revision_id;
    const apply = async (confirmStale) => {
        await request(`/references/${referenceAsset.id}?project_id=${detail.project.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: expectedRevisionId,
            confirm_stale: confirmStale,
            name: referenceDraft.name.trim(),
            description: referenceDraft.description.trim(),
            tags: normalizeReferenceTags(referenceDraft.tags),
            rights_confirmed: referenceDraft.rightsConfirmed,
            rights_note: referenceDraft.rightsNote.trim() || null,
          }),
        });
        setReferenceMode(null);
        await Promise.all([
          refreshProject(detail.project.id, selectedShotId),
          onProjectsChanged(),
        ]);
        onNotice("参考资产已更新");
    };
    await prepareImpact(
      {
        changeType: "reference_asset",
        referenceAssetIds: [assetId],
        title: "更新已绑定参考资产",
      },
      apply,
    );
  }

  async function confirmArchive() {
    const assetId = archiveAsset.id;
    const expectedRevisionId = detail.project.current_revision_id;
    const apply = async (confirmStale) => {
      const params = new URLSearchParams({
        expected_revision_id: expectedRevisionId,
        confirm_stale: String(confirmStale),
        project_id: detail.project.id,
      });
      await request(`/references/${assetId}?${params.toString()}`, { method: "DELETE" });
      setArchiveAsset(null);
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      onNotice("参考资产已从当前项目移出");
    };
    await prepareImpact(
      {
        changeType: "reference_asset",
        referenceAssetIds: [assetId],
        title: "移出已绑定参考资产",
      },
      apply,
    );
  }

  async function openRevisionPreview(revision) {
    setPreviewRevision(revision);
    setPreviewDetail(null);
    setPreviewError("");
    try {
      const next = await request(`/productions/${detail.project.id}/revisions/${revision.id}`);
      setPreviewDetail(next);
    } catch (requestError) {
      setPreviewError(requestError.message);
    }
  }

  function openBranch(revision) {
    setPreviewRevision(null);
    setBranchRevision(revision);
    setBranchName(`${detail.project.name} 分支`);
    setActionError("");
  }

  async function submitBranch(event) {
    event.preventDefault();
    setBusy(true);
    setActionError("");
    try {
      const created = await request(`/productions/${detail.project.id}/branches`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: branchName.trim(),
          source_revision_id: branchRevision.id,
        }),
      });
      setBranchRevision(null);
      await onProjectsChanged();
      await openProject(created.project.id);
      onNotice("版本分支已创建");
    } catch (requestError) {
      setActionError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  if (!selectedProjectId) {
    return (
      <>
        <ProductionList error={error} loading={loading} onCreate={openCreate} onOpen={openProject} projects={projects} />
        {createOpen && (
          <CreateProjectDialog
            busy={busy}
            draft={createDraft}
            error={actionError}
            onClose={() => setCreateOpen(false)}
            onSubmit={submitCreate}
            setDraft={setCreateDraft}
            sourceDefaultRatio={sourceProductionDefaults.outputAspectRatio}
          />
        )}
      </>
    );
  }

  return (
    <section className="production-workspace">
      <header className="production-workspace-header">
        <button className="production-back-button" onClick={() => setSelectedProjectId(null)} type="button"><ArrowLeft size={16} />所有方案</button>
        {detail && (
          <div className="production-workspace-title">
            <div><h3>{detail.project.name}</h3><p>{detail.project.output_aspect_ratio} · {detail.project.output_width} × {detail.project.output_height} · Revision {detail.current_revision?.revision_number || 1}</p></div>
            <button className="secondary-button compact" onClick={() => { setActionError(""); setActiveSection("revisions"); }} type="button"><ClockCounterClockwise size={16} />版本记录</button>
          </div>
        )}
      </header>

      {contentLoading && <div className="production-content-loading"><CircleNotch className="spin" size={24} /><span>正在打开创作方案</span></div>}
      {!contentLoading && contentError && <div className="production-inline-error production-content-error" role="alert"><WarningCircle size={18} />{contentError}</div>}
      {!contentLoading && !contentError && detail && (
        <>
          <ProductionSteps active={activeSection} gate={gate} onChange={(section) => { setActionError(""); setActiveSection(section); }} project={detail.project} referenceCount={assets.length} />
          <AnalysisUpdateBanner
            onOpen={() => {
              setAnalysisUpdateError("");
              setAnalysisUpdateOpen((value) => !value);
            }}
            open={analysisUpdateOpen}
            preview={analysisUpdatePreview}
          />
          {analysisUpdateOpen && analysisUpdatePreview && (
            <AnalysisUpdatePanel
              busy={busy}
              decisions={analysisUpdateDecisions}
              error={analysisUpdateError}
              onChangeDecision={(key, choice) => {
                setAnalysisUpdateDecisions((current) => ({ ...current, [key]: choice }));
              }}
              onClose={() => {
                setAnalysisUpdateError("");
                setAnalysisUpdateOpen(false);
              }}
              onSync={syncAnalysisPrompts}
              preview={analysisUpdatePreview}
            />
          )}
          <div className="production-stage-content">
            {activeSection === "project_setup" && <ProjectSettings busy={busy} detail={detail} draft={settingsDraft} error={actionError} onOpenReferences={() => setActiveSection("reference_assets")} onSave={submitSettings} setDraft={setSettingsDraft} />}
            {activeSection === "reference_assets" && <ReferenceAssets assets={assets} busy={busy} error={actionError} onArchive={(asset) => { setActionError(""); setArchiveAsset(asset); }} onContinue={() => { setActionError(""); setActiveSection("shot_images"); }} onEdit={openReferenceEdit} onOpenLibrary={openAssetPicker} onUpload={openReferenceUpload} resolveUrl={resolveUrl} />}
            {activeSection === "shot_images" && (
              <ShotImageWorkspace
                advanced={["shot_videos", "editing", "export"].includes(
                  detail.project.active_step,
                )}
                assets={assets}
                busy={busy}
                draft={shotDraft}
                error={actionError}
                gate={detail.project.active_step === "shot_images" ? gate : imageGate}
                generationCandidateCount={generationCandidateCount}
                generationEngine={generationEngine}
                generationInputMode={generationInputMode}
                generationSettings={generationSettings}
                onAdvance={advanceWorkflow}
                onApprove={approveCandidate}
                onApproveSource={approveSourceKeyframe}
                onCancelRun={cancelShotGeneration}
                onCreateShot={createShot}
                onCreateVisualBeat={createVisualBeat}
                onDeleteVisualBeat={deleteVisualBeat}
                onDiscardShot={discardShot}
                onArchiveCandidate={archiveImageCandidate}
                onGenerate={generateShotCandidates}
                onRevokeApproval={revokeImageApproval}
                onReorderShots={reorderShots}
                onReorderVisualBeats={reorderVisualBeats}
                onRetryRun={retryShotGeneration}
                onRestoreShot={restoreShot}
                onSave={submitShot}
                onSelectCandidate={selectCandidate}
                onSelectKeyframe={selectSourceKeyframe}
                onSelectShot={selectShot}
                onSelectVisualBeat={selectVisualBeat}
                onUpdateVisualBeat={updateVisualBeat}
                project={detail.project}
                resolveUrl={resolveUrl}
                selectedShotId={selectedShotId}
                setDraft={setShotDraft}
                setGenerationCandidateCount={setGenerationCandidateCount}
                setGenerationEngine={setGenerationEngine}
                setGenerationInputMode={setGenerationInputMode}
                shotDetail={shotDetail}
                shots={shots}
                sourceVideoUrl={resolveUrl(
                  "/api/v1/productions/" + detail.project.id + "/source-video",
                )}
              />
            )}
            {activeSection === "shot_videos" && (
              <ShotVideoWorkspace
                advanced={["editing", "export"].includes(detail.project.active_step)}
                busy={busy}
                continuityReport={continuityReport}
                error={actionError}
                gate={gate}
                initialCandidateId={focusedCandidateId}
                onAdvance={advanceToEditing}
                onApprove={approveVideoCandidate}
                onArchiveCandidates={archiveVideoCandidates}
                onCancelRun={cancelVideoGeneration}
                onCreateReferenceProxy={createReferenceProxy}
                onDecideContinuity={decideContinuityFinding}
                onDeleteReferenceProxy={deleteReferenceProxy}
                onDisableReferenceProxy={disableReferenceProxy}
                onEnableReferenceProxy={enableReferenceProxy}
                onGenerate={generateVideoCandidates}
                onManagedAssetChange={updateManagedAssetBinding}
                onNotice={onNotice}
                onNotificationsChanged={onNotificationsChanged}
                onOpenModelSettings={onOpenModelSettings}
                onReloadVideoGenerationSettings={onReloadVideoGenerationSettings}
                onReject={rejectVideoCandidate}
                onRetryRun={retryVideoGeneration}
                onRunContinuity={runContinuityCheck}
                onRestoreCandidates={restoreVideoCandidates}
                onRevokeApproval={revokeVideoApproval}
                onSelectCandidate={selectVideoCandidate}
                onSelectShot={selectShot}
                project={detail.project}
                request={request}
                resolveUrl={resolveUrl}
                selectedShotId={selectedShotId}
                selectedVisualBeatId={selectedVisualBeatId}
                setVideoDraft={setVideoDraft}
                shotDetail={shotDetail}
                shots={shots}
                videoDraft={videoDraft}
                videoGenerationSettings={videoGenerationSettings}
                videoGenerationSettingsError={videoGenerationSettingsError}
                videoGenerationSettingsStatus={videoGenerationSettingsStatus}
              />
            )}
            {activeSection === "editing" && (
              <VideoEditorWorkspace
                onNotice={onNotice}
                onNotificationsChanged={onNotificationsChanged}
                project={detail.project}
                request={request}
                resolveUrl={resolveUrl}
              />
            )}
            {activeSection === "export" && (
              <ProductionExportWorkspace
                onNotice={onNotice}
                onNotificationsChanged={onNotificationsChanged}
                onProjectChanged={async () => {
                  await refreshProject(detail.project.id);
                  await onProjectsChanged?.();
                }}
                project={detail.project}
                request={request}
                resolveUrl={resolveUrl}
              />
            )}
            {activeSection === "revisions" && <RevisionHistory busy={busy} currentRevisionId={detail.project.current_revision_id} onBranch={openBranch} onPreview={openRevisionPreview} revisions={revisions} />}
          </div>
        </>
      )}

      {createOpen && <CreateProjectDialog busy={busy} draft={createDraft} error={actionError} onClose={() => setCreateOpen(false)} onSubmit={submitCreate} setDraft={setCreateDraft} />}
      {referenceMode && <ReferenceAssetDialog busy={busy} draft={referenceDraft} error={actionError} file={referenceFile} mode={referenceMode} onClose={() => setReferenceMode(null)} onSubmit={submitReference} previewUrl={referencePreviewUrl} setDraft={setReferenceDraft} setFile={selectReferenceFile} />}
      {archiveAsset && <ArchiveDialog asset={archiveAsset} busy={busy} error={actionError} onClose={() => setArchiveAsset(null)} onConfirm={confirmArchive} />}
      {assetPickerOpen && (
        <AssetPickerDialog
          assets={libraryAssets}
          busy={busy}
          error={assetPickerError}
          linkedIds={new Set(assets.map((asset) => asset.id))}
          loading={assetPickerLoading}
          onClose={() => setAssetPickerOpen(false)}
          onConfirm={confirmLibraryAsset}
          resolveUrl={resolveUrl}
          selectedId={selectedLibraryAssetId}
          setSelectedId={setSelectedLibraryAssetId}
        />
      )}
      {previewRevision && <RevisionPreviewDialog busy={busy} detail={previewDetail} error={previewError} onBranch={() => openBranch(previewRevision)} onClose={() => setPreviewRevision(null)} revision={previewRevision} />}
      {branchRevision && <BranchDialog busy={busy} error={actionError} name={branchName} onClose={() => setBranchRevision(null)} onSubmit={submitBranch} revision={branchRevision} setName={setBranchName} />}
      <ChangeImpactPanel
        busy={busy}
        onCancel={() => setImpactReview(null)}
        onConfirm={confirmImpactReview}
        review={impactReview}
      />
    </section>
  );
}
