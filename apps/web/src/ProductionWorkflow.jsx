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
  productionChangeLabel,
  referenceTypeLabel,
} from "./production-ui.js";
import { ShotImageWorkspace } from "./ShotImageWorkspace.jsx";
import "./production-workflow.css";

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

function shotDraftFromDetail(detail) {
  if (!detail?.plan) return { ...EMPTY_SHOT_DRAFT };
  return {
    imagePrompt: detail.plan.image_prompt || "",
    imagePromptMentions: (detail.plan.image_prompt_mentions || []).map((item) => ({
      reference_asset_id: item.reference_asset_id,
      label: item.label,
    })),
    negativeConstraints: (detail.plan.image_negative_constraints || []).join("\n"),
    locks: [...(detail.plan.locks || [])],
    required: detail.plan.required !== false,
    referenceBindings: (detail.reference_bindings || []).map((item) => ({
      reference_asset_id: item.reference_asset_id,
      role: item.role,
      weight: item.weight,
      crop_hint: item.crop_hint,
      notes: item.notes,
    })),
  };
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
  const activeIndex = Math.max(0, PRODUCTION_STEPS.findIndex((step) => step.id === project.active_step));
  return (
    <nav aria-label="创作工作流" className="production-stepper">
      {PRODUCTION_STEPS.map((step, index) => {
        const locked = Boolean(step.locked);
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
                {step.id === "reference_assets" && referenceCount > 0
                  ? `${referenceCount} 项资产`
                  : step.id === "shot_images" && gate
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
}) {
  return (
    <section className="production-reference-view">
      <header className="production-section-header compact-heading">
        <div>
          <h3>参考资产</h3>
          <p>从工作区资产库添加，或快速上传新图片；项目只保存关联，不复制资产文件。</p>
        </div>
        <div className="production-reference-actions">
          <button className="secondary-button compact" disabled={busy} onClick={onUpload} type="button">
            <UploadSimple size={16} />
            快速上传
          </button>
          <button className="primary-button compact" disabled={busy} onClick={onOpenLibrary} type="button">
            <FolderOpen size={16} />
            从资产库添加
          </button>
        </div>
      </header>
      {error && <div className="production-inline-error" role="alert"><WarningCircle size={17} />{error}</div>}
      {assets.length === 0 ? (
        <div className="production-empty-state reference-empty">
          <span className="production-empty-icon"><ImageSquare size={28} /></span>
          <div>
            <h4>还没有参考资产</h4>
            <p>先从资产库添加关键人物或产品；也可以快速上传并自动加入资产库。</p>
          </div>
          <button className="primary-button compact" onClick={onOpenLibrary} type="button">打开资产库</button>
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

function CreateProjectDialog({ draft, setDraft, busy, error, onClose, onSubmit }) {
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
  projects,
  loading,
  error,
  createSignal,
  request,
  resolveUrl,
  imageGenerationSettings = DEFAULT_PRODUCTION_IMAGE_SETTINGS,
  listSignal = 0,
  onNavigationChange,
  onProjectsChanged,
  onNotice,
}) {
  const [selectedProjectId, setSelectedProjectId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [assets, setAssets] = useState([]);
  const [revisions, setRevisions] = useState([]);
  const [shots, setShots] = useState([]);
  const [gate, setGate] = useState(null);
  const [selectedShotId, setSelectedShotId] = useState(null);
  const [shotDetail, setShotDetail] = useState(null);
  const [shotDraft, setShotDraft] = useState({ ...EMPTY_SHOT_DRAFT });
  const [rejectReason, setRejectReason] = useState("");
  const [impactReview, setImpactReview] = useState(null);
  const [activeSection, setActiveSection] = useState("project_setup");
  const [contentLoading, setContentLoading] = useState(false);
  const [contentError, setContentError] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState({ ...EMPTY_CREATE_DRAFT });
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
  const referencePreviewUrl = useObjectUrl(referenceFile);

  useEffect(() => {
    setGenerationSettings(
      imageGenerationSettings || DEFAULT_PRODUCTION_IMAGE_SETTINGS,
    );
  }, [imageGenerationSettings]);

  useEffect(() => {
    if (!listSignal) return;
    setSelectedProjectId(null);
    setDetail(null);
    setContentError("");
    setActionError("");
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
    setAssets([]);
    setRevisions([]);
    setShots([]);
    setGate(null);
    setSelectedShotId(null);
    setShotDetail(null);
    setShotDraft({ ...EMPTY_SHOT_DRAFT });
    setRejectReason("");
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
  }, [recordId]);

  useEffect(() => {
    if (!createSignal) return;
    setCreateDraft({
      ...EMPTY_CREATE_DRAFT,
      name: defaultProductionName(sourceTitle),
    });
    setActionError("");
    setCreateOpen(true);
  }, [createSignal, sourceTitle]);

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

  async function refreshProject(projectId = selectedProjectId, preferredShotId = selectedShotId) {
    if (!projectId) return null;
    const [
      nextDetail,
      nextAssets,
      nextRevisions,
      nextShots,
      nextGate,
      nextGenerationSettings,
    ] = await Promise.all([
      request(`/productions/${projectId}`),
      request(`/productions/${projectId}/references`),
      request(`/productions/${projectId}/revisions`),
      request(`/productions/${projectId}/shots`),
      request(`/productions/${projectId}/gate-status`),
      request("/settings/image-generation"),
    ]);
    setDetail(nextDetail);
    setAssets(nextAssets || []);
    setRevisions(nextRevisions || []);
    setShots(nextShots || []);
    setGate(nextGate);
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
      const nextShotDetail = await request(`/production-shots/${targetShotId}`);
      setShotDetail(nextShotDetail);
      setShotDraft(shotDraftFromDetail(nextShotDetail));
    } else {
      setShotDetail(null);
      setShotDraft({ ...EMPTY_SHOT_DRAFT });
    }
    return nextDetail;
  }

  async function openProject(projectId) {
    setSelectedProjectId(projectId);
    setContentLoading(true);
    setContentError("");
    setActionError("");
    setActiveSection("project_setup");
    setSelectedShotId(null);
    setShotDetail(null);
    setImpactReview(null);
    try {
      await refreshProject(projectId, null);
    } catch (requestError) {
      setContentError(requestError.message);
    } finally {
      setContentLoading(false);
    }
  }

  async function selectShot(shotPlanId) {
    setSelectedShotId(shotPlanId);
    setActionError("");
    setRejectReason("");
    setImpactReview(null);
    setShotDetail(null);
    try {
      const nextShotDetail = await request(`/production-shots/${shotPlanId}`);
      setShotDetail(nextShotDetail);
      setShotDraft(shotDraftFromDetail(nextShotDetail));
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
    if (!shotDetail?.plan) return;
    const expectedRevisionId = detail.project.current_revision_id;
    const original = shotDraftFromDetail(shotDetail);
    const nextConstraints = constraintsFromText(shotDraft.negativeConstraints);
    const currentConstraints = constraintsFromText(original.negativeConstraints);
    const changes = {};
    if (shotDraft.imagePrompt.trim() !== original.imagePrompt.trim()) {
      changes.image_prompt = shotDraft.imagePrompt.trim();
    }
    if (
      JSON.stringify(shotDraft.imagePromptMentions)
      !== JSON.stringify(original.imagePromptMentions)
    ) {
      changes.image_prompt_mentions = shotDraft.imagePromptMentions;
    }
    if (JSON.stringify(nextConstraints) !== JSON.stringify(currentConstraints)) {
      changes.image_negative_constraints = nextConstraints;
    }
    if (JSON.stringify(shotDraft.locks) !== JSON.stringify(original.locks)) {
      changes.locks = shotDraft.locks;
    }
    if (shotDraft.required !== original.required) {
      changes.required = shotDraft.required;
    }
    if (
      JSON.stringify(shotDraft.referenceBindings)
      !== JSON.stringify(original.referenceBindings)
    ) {
      changes.reference_bindings = shotDraft.referenceBindings;
    }
    if (Object.keys(changes).length === 0) {
      onNotice("当前分镜没有需要保存的修改");
      return;
    }
    const apply = async (confirmStale) => {
      await request(`/production-shots/${shotDetail.plan.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: expectedRevisionId,
          confirm_stale: confirmStale,
          ...changes,
        }),
      });
      await Promise.all([
        refreshProject(detail.project.id, shotDetail.plan.id),
        onProjectsChanged(),
      ]);
      onNotice("分镜草稿已保存并创建新版本");
    };
    const changesImageInput = [
      "image_prompt",
      "image_prompt_mentions",
      "image_negative_constraints",
      "locks",
      "reference_bindings",
    ].some((field) => Object.hasOwn(changes, field));
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
    if (!shotDetail?.plan) return;
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
        `本机工具无法提供可验证的成本信息。是否仍要为分镜 ${shotDetail.plan.index} 生成 ${candidateCount} 张候选？`,
      )
    ) {
      return;
    }
    await executeAction(async () => {
      const run = await request(
        `/production-shots/${shotDetail.plan.id}/image-runs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            candidate_count: candidateCount,
            input_mode: generationInputMode,
            execution_mode: executionMode,
            allow_unknown_cost: acceptsUnknownCost,
            generation_intent: imageGenerationIntentForShot(shotDetail),
          }),
        },
      );
      setShotDetail((current) => upsertGenerationRun(current, run));
      await onProjectsChanged();
      onNotice(`分镜 ${shotDetail.plan.index} 的图片任务已加入队列`);
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
    if (!shotDetail?.plan) return;
    const hasReviewedOutput = (
      Boolean(shotDetail.plan.approved_image_candidate_id)
      || ["approved", "review_required", "stale"].includes(
        shotDetail.plan.image_status,
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
            timestamp_seconds: Number(timestampSeconds),
            confirm_stale: hasReviewedOutput,
          }),
        },
      );
      await Promise.all([
        refreshProject(detail.project.id, shotDetail.plan.id),
        onProjectsChanged(),
      ]);
      onNotice("分镜 " + shotDetail.plan.index + " 的关键帧已更新");
    });
  }

  async function approveSourceKeyframe() {
    if (!shotDetail?.plan) return;
    await executeAction(async () => {
      await request(
        "/production-shots/" + shotDetail.plan.id + "/source-keyframe/approval",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
          }),
        },
      );
      await Promise.all([
        refreshProject(detail.project.id, shotDetail.plan.id),
        onProjectsChanged(),
      ]);
      onNotice("已直接使用当前关键帧，未调用图片生成模型");
    });
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
    await executeAction(async () => {
      await request(
        `/generation-candidates/${candidateId}/approvals`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            decision: "approved",
          }),
        },
      );
      setRejectReason("");
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      onNotice("当前分镜图片已确认");
    });
  }

  async function revokeImageApproval() {
    if (!shotDetail?.plan || shotDetail.plan.image_status !== "approved") return;
    const shotPlanId = shotDetail.plan.id;
    const shotIndex = shotDetail.plan.index;
    const expectedRevisionId = detail.project.current_revision_id;
    const apply = async (confirmDownstreamStale) => {
      await request(
        `/production-shots/${shotPlanId}/image-approval/revoke`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: expectedRevisionId,
            reason: "用户重新打开图片审核",
            confirm_downstream_stale: confirmDownstreamStale,
          }),
        },
      );
      setRejectReason("");
      await Promise.all([
        refreshProject(detail.project.id, shotPlanId),
        onProjectsChanged(),
      ]);
      onNotice(`已取消采用分镜 ${shotIndex} 的图片，可重新选择或生成新候选`);
    };
    await prepareImpact(
      {
        changeType: "image_approval_revoke",
        shotPlanIds: [shotPlanId],
        title: "取消采用当前分镜图片",
      },
      apply,
    );
  }

  async function rejectCandidate(candidateId) {
    if (!rejectReason.trim()) {
      setActionError("退回候选时必须填写原因");
      return;
    }
    await executeAction(async () => {
      await request(
        `/generation-candidates/${candidateId}/approvals`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision_id: detail.project.current_revision_id,
            decision: "rejected",
            reason: rejectReason.trim(),
          }),
        },
      );
      setRejectReason("");
      await Promise.all([
        refreshProject(detail.project.id, selectedShotId),
        onProjectsChanged(),
      ]);
      onNotice("候选已退回，可修改提示词后重新生成");
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
      onNotice("图片阶段已完成，分段视频阶段将在 Batch 4.2 之后开放");
    });
  }

  function openCreate() {
    setCreateDraft({
      ...EMPTY_CREATE_DRAFT,
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
        {createOpen && <CreateProjectDialog busy={busy} draft={createDraft} error={actionError} onClose={() => setCreateOpen(false)} onSubmit={submitCreate} setDraft={setCreateDraft} />}
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
          <div className="production-stage-content">
            {activeSection === "project_setup" && <ProjectSettings busy={busy} detail={detail} draft={settingsDraft} error={actionError} onOpenReferences={() => setActiveSection("reference_assets")} onSave={submitSettings} setDraft={setSettingsDraft} />}
            {activeSection === "reference_assets" && <ReferenceAssets assets={assets} busy={busy} error={actionError} onArchive={(asset) => { setActionError(""); setArchiveAsset(asset); }} onEdit={openReferenceEdit} onOpenLibrary={openAssetPicker} onUpload={openReferenceUpload} resolveUrl={resolveUrl} />}
            {activeSection === "shot_images" && (
              <ShotImageWorkspace
                advanced={detail.project.active_step === "shot_videos"}
                assets={assets}
                busy={busy}
                draft={shotDraft}
                error={actionError}
                gate={gate}
                generationCandidateCount={generationCandidateCount}
                generationEngine={generationEngine}
                generationInputMode={generationInputMode}
                generationSettings={generationSettings}
                onAdvance={advanceWorkflow}
                onApprove={approveCandidate}
                onApproveSource={approveSourceKeyframe}
                onCancelRun={cancelShotGeneration}
                onCreateShot={createShot}
                onDiscardShot={discardShot}
                onGenerate={generateShotCandidates}
                onReject={rejectCandidate}
                onRevokeApproval={revokeImageApproval}
                onReorderShots={reorderShots}
                onRetryRun={retryShotGeneration}
                onRestoreShot={restoreShot}
                onSave={submitShot}
                onSelectCandidate={selectCandidate}
                onSelectKeyframe={selectSourceKeyframe}
                onSelectShot={selectShot}
                rejectReason={rejectReason}
                resolveUrl={resolveUrl}
                selectedShotId={selectedShotId}
                setDraft={setShotDraft}
                setGenerationCandidateCount={setGenerationCandidateCount}
                setGenerationEngine={setGenerationEngine}
                setGenerationInputMode={setGenerationInputMode}
                setRejectReason={setRejectReason}
                shotDetail={shotDetail}
                shots={shots}
                sourceVideoUrl={resolveUrl(
                  "/api/v1/productions/" + detail.project.id + "/source-video",
                )}
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
