import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowsClockwise,
  Camera,
  Check,
  CheckCircle,
  CircleNotch,
  Clock,
  FilmStrip,
  Heart,
  ImageSquare,
  Lock,
  MagicWand,
  MagnifyingGlass,
  MusicNotes,
  SpeakerHigh,
  ShieldCheck,
  Sparkle,
  Star,
  TextT,
  VideoCamera,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import { ProductionHub } from "../ProductionWorkflow.jsx";
import { CategoryProfilePicker } from "../category-profiles/index.js";
import {
  InlineMessage,
  AutosaveStatus,
  PageHeader,
  PageShell,
  SectionHeader,
  StatusBadge,
  SurfacePanel,
} from "../ui/system/index.js";
import {
  buildCategoryProfileCreativeInputs,
  buildRunContractPayload,
  dimensionsForResolutionLabel,
  EXECUTION_LABELS,
  formatMicros,
  resolutionForRatio,
  REVIEW_LABELS,
  SKILL_WORKFLOW_STAGES,
  stageState,
  validateSkillStartDraft,
  VALIDATION_LABELS,
} from "./skill-workflow-ui.js";
import "./skill-workflow.css";

const EMPTY_CATALOG = Object.freeze({ items: [], categories: [], total: 0 });
const WIZARD_STEPS = ["目标与品类", "基础素材", "生成配置", "确认创建"];

function clientToken() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatDurationMs(value) {
  const milliseconds = Math.max(0, Number(value) || 0);
  if (milliseconds < 1000) return `${milliseconds} ms`;
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} 秒`;
  return `${Math.floor(milliseconds / 60_000)} 分 ${Math.round((milliseconds % 60_000) / 1000)} 秒`;
}

function elapsedSince(value, now = Date.now()) {
  const startedAt = Date.parse(value || "");
  return Number.isFinite(startedAt) ? Math.max(0, now - startedAt) : 0;
}

function heartbeatLabel(value, now = Date.now()) {
  if (!value) return "等待首次心跳";
  const seconds = Math.floor(elapsedSince(value, now) / 1000);
  if (seconds < 10) return "心跳正常";
  if (seconds < 60) return `${seconds} 秒前有心跳`;
  return `${Math.floor(seconds / 60)} 分钟前有心跳`;
}

const LOOK_ITEM_LABELS = Object.freeze({
  pending: "等待生成",
  running: "生成中",
  succeeded: "已完成",
  failed: "生成失败",
  blocked: "待确认",
  cancelled: "已停止",
});

function useRemote(load, dependencies) {
  const [state, setState] = useState({ loading: true, error: "", data: null });
  useEffect(() => {
    let active = true;
    setState((current) => ({ ...current, loading: true, error: "" }));
    Promise.resolve(load())
      .then((data) => {
        if (active) setState({ loading: false, error: "", data });
      })
      .catch((error) => {
        if (active) setState({ loading: false, error: error.message, data: null });
      });
    return () => {
      active = false;
    };
  }, dependencies); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}

function LoadingState({ label = "正在加载" }) {
  return <div className="skill-loading"><CircleNotch className="spin" size={22} /><span>{label}</span></div>;
}

function ErrorState({ message, onRetry }) {
  return (
    <InlineMessage tone="danger">
      <WarningCircle size={18} />
      <span>{message}</span>
      {onRetry && <button className="text-button" onClick={onRetry} type="button">重试</button>}
    </InlineMessage>
  );
}

function SkillCover({ skill, compact = false }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className={`skill-cover ${compact ? "is-compact" : ""}`}>
      {!failed && skill.cover_url ? (
        <img alt="" onError={() => setFailed(true)} src={skill.cover_url} />
      ) : (
        <div className="skill-cover-fallback" aria-hidden="true">
          <FilmStrip size={compact ? 28 : 42} weight="duotone" />
          <span>{skill.category}</span>
        </div>
      )}
    </div>
  );
}

function SkillCard({ skill, onFavorite, onOpen, onStart }) {
  return (
    <article className="skill-card">
      <button className="skill-card-main" onClick={() => onOpen(skill)} type="button">
        <SkillCover skill={skill} />
        <div className="skill-card-copy">
          <div className="skill-card-heading">
            <h2>{skill.name}</h2>
            <span>{skill.category}</span>
          </div>
          <p>{skill.summary}</p>
          <div className="skill-card-meta">
            <span><Clock size={14} />{skill.duration_seconds.min}–{skill.duration_seconds.max} 秒</span>
            <span>{skill.aspect_ratios.slice(0, 3).join(" / ")}</span>
          </div>
        </div>
      </button>
      <div className="skill-card-actions">
        <button
          aria-label={skill.favorited ? `取消收藏 ${skill.name}` : `收藏 ${skill.name}`}
          className={`skill-favorite-button ${skill.favorited ? "is-active" : ""}`}
          onClick={() => onFavorite(skill)}
          type="button"
        >
          <Heart size={18} weight={skill.favorited ? "fill" : "regular"} />
        </button>
        <button className="primary-button compact" onClick={() => onStart(skill)} type="button">
          用这个 Skill <ArrowRight size={15} />
        </button>
      </div>
    </article>
  );
}

export function SkillPlaza({ navigate, request, onNotice }) {
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const params = useMemo(() => {
    const value = new URLSearchParams();
    if (query) value.set("query", query);
    if (category) value.set("category", category);
    if (favoritesOnly) value.set("favorites_only", "true");
    return value;
  }, [category, favoritesOnly, query]);
  const catalog = useRemote(
    () => request(`/skills${params.toString() ? `?${params}` : ""}`),
    [request, params.toString(), refreshToken],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(queryInput.trim()), 220);
    return () => window.clearTimeout(timer);
  }, [queryInput]);

  async function toggleFavorite(skill) {
    try {
      await request(`/skills/${encodeURIComponent(skill.id)}/favorite`, {
        method: skill.favorited ? "DELETE" : "POST",
      });
      setRefreshToken((value) => value + 1);
    } catch (error) {
      onNotice?.({ type: "error", title: "收藏操作失败", message: error.message });
    }
  }

  const payload = catalog.data || EMPTY_CATALOG;
  return (
    <PageShell className="skill-plaza-page">
      <section className="skill-plaza-hero">
        <div className="skill-plaza-hero-copy">
          <span className="skill-eyebrow"><Sparkle size={15} weight="fill" />平台创作能力</span>
          <h1>从一种成熟风格开始创作</h1>
          <p>选择平台 Skill，把品牌、基础素材和目标转化为从大纲到成片的完整工作流。</p>
        </div>
        <div className="skill-plaza-search">
          <MagnifyingGlass size={19} />
          <input
            aria-label="搜索 Skill"
            onChange={(event) => setQueryInput(event.target.value)}
            placeholder="搜索风格、用途或发布渠道"
            value={queryInput}
          />
        </div>
      </section>

      <div className="skill-catalog-toolbar" aria-label="Skill 分类">
        <button className={!category && !favoritesOnly ? "is-active" : ""} onClick={() => { setCategory(""); setFavoritesOnly(false); }} type="button">全部</button>
        {(payload.categories || []).map((item) => (
          <button className={category === item ? "is-active" : ""} key={item} onClick={() => { setCategory(item); setFavoritesOnly(false); }} type="button">{item}</button>
        ))}
        <button className={favoritesOnly ? "is-active" : ""} onClick={() => { setFavoritesOnly(true); setCategory(""); }} type="button"><Star size={15} />收藏</button>
      </div>

      {catalog.loading ? <LoadingState label="正在加载 Skill" /> : catalog.error ? (
        <ErrorState message={catalog.error} onRetry={() => setRefreshToken((value) => value + 1)} />
      ) : payload.items.length ? (
        <div className="skill-card-grid">
          {payload.items.map((skill) => (
            <SkillCard
              key={skill.id}
              onFavorite={toggleFavorite}
              onOpen={(item) => navigate(`/skills/${item.slug}`)}
              onStart={(item) => navigate(`/skills/${item.slug}/start`)}
              skill={skill}
            />
          ))}
        </div>
      ) : (
        <SurfacePanel className="skill-empty-state">
          <MagicWand size={30} />
          <h2>没有匹配的 Skill</h2>
          <p>试试更宽泛的关键词，或切换到其他分类。</p>
        </SurfacePanel>
      )}
    </PageShell>
  );
}

export function SkillDetail({ navigate, request, skillSlug }) {
  const [refreshToken, setRefreshToken] = useState(0);
  const state = useRemote(
    () => request(`/skills/${encodeURIComponent(skillSlug)}`),
    [request, skillSlug, refreshToken],
  );
  if (state.loading) return <PageShell className="skill-page"><LoadingState label="正在打开 Skill" /></PageShell>;
  if (state.error) return <PageShell className="skill-page"><ErrorState message={state.error} onRetry={() => setRefreshToken((value) => value + 1)} /></PageShell>;
  const skill = state.data;
  const spec = skill.current_version.manifest.spec;
  return (
    <PageShell className="skill-page skill-detail-page">
      <button className="skill-back-button" onClick={() => navigate("/skills")} type="button"><ArrowLeft size={16} />Skill 广场</button>
      <div className="skill-detail-hero">
        <SkillCover skill={skill} />
        <div className="skill-detail-copy">
          <span className="skill-eyebrow">{skill.category} · v{skill.current_version.version}</span>
          <h1>{skill.name}</h1>
          <p>{skill.summary}</p>
          <div className="skill-detail-meta">
            <span><Clock size={15} />{skill.duration_seconds.min}–{skill.duration_seconds.max} 秒</span>
            <span>{skill.aspect_ratios.join(" / ")}</span>
            <span>{skill.supported_channels.join(" · ")}</span>
          </div>
          <button className="primary-button" onClick={() => navigate(`/skills/${skill.slug}/start`)} type="button">开始创作 <ArrowRight size={16} /></button>
        </div>
      </div>

      <div className="skill-detail-grid">
        <SurfacePanel className="skill-detail-panel">
          <SectionHeader description="每一步都有独立的执行、系统校验和人工审核状态。" title="工作流" />
          <ol className="skill-stage-preview">
            {SKILL_WORKFLOW_STAGES.map((stage, index) => (
              <li key={stage.id}><span>{index + 1}</span><div><strong>{stage.label}</strong><small>{stage.gateLabel}</small></div></li>
            ))}
          </ol>
        </SurfacePanel>
        <div className="skill-detail-side">
          <SurfacePanel className="skill-detail-panel">
            <SectionHeader title="需要准备" />
            <ul className="skill-requirement-list">
              {skill.asset_roles.map((role) => (
                <li key={role.role}><ImageSquare size={17} /><span><strong>{role.label}</strong><small>{role.min_count ? `至少 ${role.min_count} 个` : "可选"} · {role.fidelity}</small></span></li>
              ))}
            </ul>
          </SurfacePanel>
          <SurfacePanel className="skill-detail-panel">
            <SectionHeader title="风格约束" />
            <div className="skill-keyword-list">{spec.style.visual_keywords.map((item) => <span key={item}>{item}</span>)}</div>
            <p className="skill-panel-note">模型与输出分辨率由你在创建时主动选择，平台不会自动切换到更便宜的模型或先生成低清草稿。</p>
          </SurfacePanel>
        </div>
      </div>
    </PageShell>
  );
}

function WizardField({ children, className = "", hint, label, required = false }) {
  return (
    <label className={`skill-field ${className}`.trim()}>
      <span>{label}{required && <em>必填</em>}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

function WizardStepRail({ current }) {
  return (
    <ol className="skill-wizard-steps">
      {WIZARD_STEPS.map((label, index) => (
        <li className={index < current ? "is-complete" : index === current ? "is-current" : ""} key={label}>
          <span>{index < current ? <Check size={13} weight="bold" /> : index + 1}</span>
          <strong>{label}</strong>
        </li>
      ))}
    </ol>
  );
}

function ratioResolutionOptions(ratio, model) {
  const capabilities = model?.capabilities;
  return [1024, 1536, 2048]
    .map((edge) => resolutionForRatio(ratio, edge))
    .filter((value) => {
      if (!capabilities) return true;
      const [width, height] = value.split("x").map(Number);
      return width <= capabilities.maximum_width
        && height <= capabilities.maximum_height
        && width * height <= capabilities.maximum_pixels;
    });
}

function videoResolutionOptions(ratio, model) {
  return (model?.capabilities?.supported_resolutions || [])
    .map((label) => dimensionsForResolutionLabel(ratio, label))
    .filter(Boolean);
}

export function SkillStartWizard({ navigate, onNotice, request, skillSlug }) {
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState({
    projectName: "",
    categoryProfileId: "",
    objective: "",
    durationSeconds: 15,
    aspectRatio: "",
    skillAnswers: {},
    selectedAssetIds: [],
    assetRoleById: {},
    imageModel: "",
    imageResolution: "",
    videoModel: "",
    videoResolution: "",
    fps: 30,
    textModel: "workspace_default",
    generateVideoAudio: false,
    musicStrategy: "select",
    narrationStrategy: "none",
    subtitleStrategy: "final_speech",
    automationMode: "guided",
    budgetCny: "",
  });
  const [selectedCategoryProfile, setSelectedCategoryProfile] = useState(null);
  const [assets, setAssets] = useState([]);
  const [settings, setSettings] = useState({ image: null, video: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [createdProjectId, setCreatedProjectId] = useState("");
  const idempotencyKey = useRef(`skill-start-${clientToken()}`);
  const skillState = useRemote(
    () => request(`/skills/${encodeURIComponent(skillSlug)}`),
    [request, skillSlug],
  );
  const skill = skillState.data;

  useEffect(() => {
    if (!skill) return;
    setDraft((current) => ({
      ...current,
      projectName: current.projectName || `${skill.name}项目`,
      aspectRatio: current.aspectRatio || skill.aspect_ratios[0] || "",
      durationSeconds: Math.max(skill.duration_seconds.min, Math.min(15, skill.duration_seconds.max)),
    }));
  }, [skill]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([
      request("/context"),
      request("/settings/image-generation"),
      request("/settings/video-generation"),
    ])
      .then(async ([context, image, video]) => {
        const workspaceId = context?.active_workspace?.id;
        const assetPayload = workspaceId
          ? await request(`/workspaces/${workspaceId}/assets?page=1&page_size=100`)
          : { items: [] };
        if (!active) return;
        setAssets(assetPayload.items || []);
        setSettings({ image, video });
      })
      .catch((requestError) => {
        if (active) setError(requestError.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [request]);

  function update(key, value) {
    setDraft((current) => {
      const next = { ...current, [key]: value };
      if (key === "aspectRatio") {
        next.imageResolution = "";
        next.videoResolution = "";
      }
      if (key === "imageModel") next.imageResolution = "";
      if (key === "videoModel") next.videoResolution = "";
      return next;
    });
    setError("");
  }

  function updateSkillAnswer(key, value) {
    update("skillAnswers", { ...draft.skillAnswers, [key]: value });
  }

  function chooseCategoryProfile(profileId, profile = null) {
    setSelectedCategoryProfile(profile);
    update("categoryProfileId", profileId);
  }

  function toggleAsset(assetId) {
    const asset = assets.find((item) => item.id === assetId);
    const selected = draft.selectedAssetIds.includes(assetId);
    const compatibleRole = skill?.asset_roles.find((item) => item.media_types.includes(asset?.media_kind));
    setDraft((current) => ({
      ...current,
      selectedAssetIds: selected
        ? current.selectedAssetIds.filter((value) => value !== assetId)
        : [...current.selectedAssetIds, assetId],
      assetRoleById: selected
        ? Object.fromEntries(Object.entries(current.assetRoleById).filter(([key]) => key !== assetId))
        : { ...current.assetRoleById, [assetId]: compatibleRole?.role || "" },
    }));
    setError("");
  }

  function updateAssetRole(assetId, role) {
    setDraft((current) => ({
      ...current,
      assetRoleById: { ...current.assetRoleById, [assetId]: role },
    }));
    setError("");
  }

  function toggleMultiAnswer(questionKey, option) {
    const current = Array.isArray(draft.skillAnswers[questionKey])
      ? draft.skillAnswers[questionKey]
      : [];
    updateSkillAnswer(
      questionKey,
      current.includes(option)
        ? current.filter((item) => item !== option)
        : [...current, option],
    );
  }

  function validateStep(nextStep = step) {
    if (!skill) return ["Skill 尚未加载完成"];
    if (nextStep === 0) return validateSkillStartDraft({ ...draft, imageModel: "ready", imageResolution: "ready", videoModel: "ready", videoResolution: "ready" }, skill)
      .filter((item) => !item.includes("模型") && !item.includes("分辨率"));
    if (nextStep === 1) {
      const selected = assets.filter((asset) => draft.selectedAssetIds.includes(asset.id));
      const issues = [];
      for (const role of skill.asset_roles) {
        const count = selected.filter((asset) => draft.assetRoleById[asset.id] === role.role).length;
        if (count < role.min_count) issues.push(`${role.label}至少需要 ${role.min_count} 个`);
      }
      if (selected.some((asset) => !draft.assetRoleById[asset.id])) issues.push("请为每个所选素材指定用途");
      if (selected.some((asset) => !asset.rights_confirmed)) issues.push("所选素材必须先确认使用权利");
      return issues;
    }
    if (nextStep === 2 || nextStep === 3) return validateSkillStartDraft(draft, skill);
    return [];
  }

  function goNext() {
    const issues = validateStep();
    if (issues.length) {
      setError(issues[0]);
      return;
    }
    setStep((value) => Math.min(WIZARD_STEPS.length - 1, value + 1));
  }

  async function createProject() {
    const issues = [
      ...validateSkillStartDraft(draft, skill),
      ...validateStep(1),
    ];
    if (issues.length) {
      setError(issues[0]);
      return;
    }
    if (!selectedCategoryProfile || selectedCategoryProfile.id !== draft.categoryProfileId) {
      setError("无法读取所选品类档案，请重新选择");
      return;
    }
    const selectedCreativeInputs = buildCategoryProfileCreativeInputs({
      objective: draft.objective,
      profile: selectedCategoryProfile,
      skill,
      skillAnswers: draft.skillAnswers,
    });
    const preview = buildRunContractPayload({
      draft,
      imageModels: settings.image?.models,
      videoModels: settings.video?.models,
    });
    const videoModel = settings.video?.models?.find((item) => item.alias === draft.videoModel);
    if (draft.generateVideoAudio && !videoModel?.capabilities?.native_audio) {
      setError("当前视频模型不支持生成新音频，请关闭新音频或选择支持原生音频的模型");
      return;
    }
    if (!preview.video_resolution_label) {
      setError("当前视频模型不支持所选分辨率");
      return;
    }
    if (preview.estimate_status !== "known") {
      setError("当前模型组合缺少明确价格，不能开始付费生成");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      let projectId = createdProjectId;
      if (!projectId) {
        const project = await request("/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "skill", name: draft.projectName.trim(), skill_version_id: skill.current_version.id }),
        });
        projectId = project.id;
        setCreatedProjectId(projectId);
      }
      let workspace = await request(`/projects/${projectId}/skill-workspace`);
      let brand = workspace.brand_snapshot;
      if (!brand) {
        brand = await request(`/projects/${projectId}/brand-snapshot`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_category_profile_id: draft.categoryProfileId,
            name: selectedCreativeInputs.brandName,
            description: selectedCreativeInputs.brandDescription,
            values: selectedCreativeInputs.values,
            voice: [],
            visual_identity: selectedCreativeInputs.visualIdentity,
          }),
        });
      }
      const frozenIdentity = brand.visual_identity || {};
      const creativeInputs = buildCategoryProfileCreativeInputs({
        objective: draft.objective,
        profile: {
          ...selectedCategoryProfile,
          brand_name: brand.name,
          brief: brand.description?.split("\n").find(Boolean) || selectedCategoryProfile.brief,
          audiences: frozenIdentity.audiences || selectedCategoryProfile.audiences,
          selling_points: brand.values?.length ? brand.values : selectedCategoryProfile.selling_points,
          scenes: frozenIdentity.scenes || selectedCategoryProfile.scenes,
          forbidden_claims: frozenIdentity.forbidden_claims || selectedCategoryProfile.forbidden_claims,
          visual_style: frozenIdentity.visual_style || selectedCategoryProfile.visual_style,
          revision: frozenIdentity.profile_revision || selectedCategoryProfile.revision,
        },
        skill,
        skillAnswers: draft.skillAnswers,
      });
      const selectedAssets = assets.filter((asset) => draft.selectedAssetIds.includes(asset.id));
      const usages = await request(`/projects/${projectId}/asset-usages`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items: selectedAssets.map((asset) => {
            const role = skill.asset_roles.find((item) => item.role === draft.assetRoleById[asset.id]);
            return {
              asset_id: asset.id,
              role: role?.role || "reference_asset",
              fidelity: role?.fidelity || "loose_reference",
              rights_status: asset.rights_confirmed ? "confirmed" : "unknown",
              allowed_distribution: [creativeInputs.channel],
              consent_status: asset.type === "person" ? "confirmed" : "not_applicable",
              allowed_transformations: ["crop", "color_adjust", "composite"],
              snapshot_sha256: asset.sha256,
            };
          }),
        }),
      });
      const brief = await request(`/projects/${projectId}/brief`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_snapshot_id: brand.id,
          objective: draft.objective.trim(),
          audience: creativeInputs.audience,
          distribution_channel: creativeInputs.channel,
          target_duration_seconds: Number(draft.durationSeconds),
          output_aspect_ratio: draft.aspectRatio,
          fps: Number(draft.fps),
          language: "中文",
          locale: "zh-CN",
          creative_basis: creativeInputs.creativeBasis,
          call_to_action: "",
          required_messages: creativeInputs.requiredMessages,
          forbidden_messages: creativeInputs.forbiddenMessages,
          selected_asset_usage_ids: usages.map((item) => item.id),
          skill_answers: creativeInputs.skillAnswers,
          notes: `创作依据：品类档案“${selectedCategoryProfile.display_name}”第 ${selectedCategoryProfile.revision} 版 + 用户创作目标`,
        }),
      });
      const contract = await request(`/projects/${projectId}/run-contract`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildRunContractPayload({ draft, imageModels: settings.image?.models, videoModels: settings.video?.models })),
      });
      const preflight = await request(`/projects/${projectId}/preflight`, { method: "POST" });
      if (!preflight.can_start) throw new Error(preflight.issues[0]?.message || "创建前检查未通过");
      await request(`/projects/${projectId}/skill-runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey.current },
        body: JSON.stringify({ run_contract_revision_id: contract.id, idempotency_key: idempotencyKey.current }),
      });
      onNotice?.("Skill 项目已创建，等待你批准创作简报");
      navigate(`/projects/${projectId}/skill`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (skillState.loading || loading) return <PageShell className="skill-page"><LoadingState label="正在准备创建向导" /></PageShell>;
  if (skillState.error) return <PageShell className="skill-page"><ErrorState message={skillState.error} /></PageShell>;
  const selectedAssets = assets.filter((asset) => draft.selectedAssetIds.includes(asset.id));
  const imageModels = (settings.image?.models || []).filter((item) => (
    item.available !== false
    && (item.capabilities?.text_to_image === true || item.capabilities?.image_to_image === true)
  ));
  const videoModels = (settings.video?.models || []).filter((item) => (
    item.available !== false
    && (
      !item.capabilities?.supported_aspect_ratios?.length
      || !draft.aspectRatio
      || item.capabilities.supported_aspect_ratios.includes(draft.aspectRatio)
    )
  ));
  const selectedImageModel = imageModels.find((item) => item.alias === draft.imageModel);
  const selectedVideoModel = videoModels.find((item) => item.alias === draft.videoModel);
  const visibleSkillQuestions = skill.current_version.manifest.spec.intake.questions
    .filter((question) => question.key !== "primary_message");
  const contractPreview = buildRunContractPayload({ draft, imageModels, videoModels });
  return (
    <PageShell className="skill-page skill-wizard-page">
      <button className="skill-back-button" onClick={() => navigate(`/skills/${skill.slug}`)} type="button"><ArrowLeft size={16} />{skill.name}</button>
      <PageHeader description="项目会锁定当前 Skill 版本；模型、分辨率与音频策略由你明确决定。" title="创建 Skill 项目" />
      <WizardStepRail current={step} />
      {error && <ErrorState message={error} />}
      <SurfacePanel className="skill-wizard-panel">
        {step === 0 && (
          <div className="skill-form-grid">
            <WizardField label="项目名称" required><input onChange={(event) => update("projectName", event.target.value)} value={draft.projectName} /></WizardField>
            <div className="skill-field skill-category-profile-field">
              <span>从品类库选择<em>必填</em></span>
              <CategoryProfilePicker
                onChange={chooseCategoryProfile}
                onManage={() => navigate("/category-profiles")}
                request={request}
                value={draft.categoryProfileId}
              />
            </div>
            <WizardField className="skill-field-wide" label="创作目标" required><textarea onChange={(event) => update("objective", event.target.value)} rows={4} value={draft.objective} /></WizardField>
            <WizardField label="画幅" required><select onChange={(event) => update("aspectRatio", event.target.value)} value={draft.aspectRatio}><option value="">请选择</option>{skill.aspect_ratios.map((item) => <option key={item} value={item}>{item}</option>)}</select></WizardField>
            <WizardField hint={`${skill.duration_seconds.min}–${skill.duration_seconds.max} 秒`} label="目标时长" required><input max={skill.duration_seconds.max} min={skill.duration_seconds.min} onChange={(event) => update("durationSeconds", event.target.value)} type="number" value={draft.durationSeconds} /></WizardField>
            {visibleSkillQuestions.map((question) => (
              <WizardField key={question.key} label={question.label} required={question.required}>
                {question.type === "single_select" ? (
                  <select onChange={(event) => updateSkillAnswer(question.key, event.target.value)} value={draft.skillAnswers[question.key] || ""}>
                    <option value="">请选择</option>
                    {question.options.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                ) : question.type === "multi_select" ? (
                  <div className="skill-option-checks">
                    {question.options.map((option) => (
                      <label key={option}>
                        <input
                          checked={(draft.skillAnswers[question.key] || []).includes(option)}
                          onChange={() => toggleMultiAnswer(question.key, option)}
                          type="checkbox"
                        />
                        <span>{option}</span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <textarea
                    maxLength={question.max_length || undefined}
                    onChange={(event) => updateSkillAnswer(question.key, event.target.value)}
                    rows={question.type === "short_text" ? 2 : 3}
                    value={draft.skillAnswers[question.key] || ""}
                  />
                )}
              </WizardField>
            ))}
          </div>
        )}
        {step === 1 && (
          <div className="skill-asset-step">
            <SectionHeader description="素材用途、保真级别和授权状态会写入项目快照，并参与生成前检查。" title="选择基础素材" />
            <div className="skill-asset-requirements">{skill.asset_roles.map((role) => <span key={role.role}>{role.label} · {role.min_count ? `至少 ${role.min_count}` : "可选"} · {role.fidelity}</span>)}</div>
            {assets.length ? <div className="skill-asset-grid">{assets.map((asset) => {
              const selected = draft.selectedAssetIds.includes(asset.id);
              const compatibleRoles = skill.asset_roles.filter((role) => role.media_types.includes(asset.media_kind));
              return (
                <article className={selected ? "is-selected" : ""} key={asset.id}>
                  <button onClick={() => toggleAsset(asset.id)} type="button">
                    <img alt="" src={asset.thumbnail_url} />
                    <span><strong>{asset.name}</strong><small>{asset.rights_confirmed ? "权利已确认" : "权利未确认"}</small></span>
                    {selected && <CheckCircle size={19} weight="fill" />}
                  </button>
                  {selected && (
                    <label>
                      <span>素材用途</span>
                      <select onChange={(event) => updateAssetRole(asset.id, event.target.value)} value={draft.assetRoleById[asset.id] || ""}>
                        <option value="">请选择</option>
                        {compatibleRoles.map((role) => <option key={role.role} value={role.role}>{role.label} · {role.fidelity}</option>)}
                      </select>
                    </label>
                  )}
                </article>
              );
            })}</div> : <div className="skill-empty-inline">资产库中暂无素材。请先到资产库上传品牌、产品或人物素材。</div>}
          </div>
        )}
        {step === 2 && (
          <div className="skill-form-grid">
            <WizardField hint="不会自动替换为其他模型" label="图片模型" required><select onChange={(event) => update("imageModel", event.target.value)} value={draft.imageModel}><option value="">主动选择模型</option>{imageModels.map((item) => <option key={item.alias} value={item.alias}>{item.label} · {item.provider}</option>)}</select></WizardField>
            <WizardField label="图片分辨率" required><select onChange={(event) => update("imageResolution", event.target.value)} value={draft.imageResolution}><option value="">主动选择分辨率</option>{ratioResolutionOptions(draft.aspectRatio, selectedImageModel).map((item) => <option key={item} value={item}>{item}</option>)}</select></WizardField>
            <WizardField hint="不会自动替换为更便宜的模型" label="视频模型" required><select onChange={(event) => update("videoModel", event.target.value)} value={draft.videoModel}><option value="">主动选择模型</option>{videoModels.map((item) => <option key={item.alias} value={item.alias}>{item.label} · {item.provider}</option>)}</select></WizardField>
            <WizardField label="视频分辨率" required><select onChange={(event) => update("videoResolution", event.target.value)} value={draft.videoResolution}><option value="">主动选择分辨率</option>{videoResolutionOptions(draft.aspectRatio, selectedVideoModel).map((item) => <option key={item} value={item}>{item}</option>)}</select></WizardField>
            <WizardField label="视频帧率"><select onChange={(event) => update("fps", event.target.value)} value={draft.fps}><option value="24">24 FPS</option><option value="25">25 FPS</option><option value="30">30 FPS</option></select></WizardField>
            <WizardField label="运行方式"><select onChange={(event) => update("automationMode", event.target.value)} value={draft.automationMode}><option value="guided">引导模式</option><option value="full_auto">全自动执行（仍保留人工门禁）</option></select></WizardField>
            <WizardField hint={draft.automationMode === "full_auto" ? "全自动模式必填" : "可选；达到上限时暂停"} label="预算上限（元）"><input min="0.01" onChange={(event) => update("budgetCny", event.target.value)} step="0.01" type="number" value={draft.budgetCny} /></WizardField>
            <WizardField label="配乐"><select onChange={(event) => update("musicStrategy", event.target.value)} value={draft.musicStrategy}><option value="none">不添加</option><option value="select">从资产库选择</option><option value="generate">生成新配乐</option></select></WizardField>
            <WizardField label="旁白"><select onChange={(event) => update("narrationStrategy", event.target.value)} value={draft.narrationStrategy}><option value="none">不添加</option><option value="recorded">使用录音</option><option value="generated">生成旁白</option></select></WizardField>
            <WizardField label="字幕"><select onChange={(event) => update("subtitleStrategy", event.target.value)} value={draft.subtitleStrategy}><option value="none">不添加</option><option value="final_speech">从最终语音生成</option><option value="manual">手工字幕</option></select></WizardField>
            <label className="skill-check-field"><input checked={draft.generateVideoAudio} onChange={(event) => update("generateVideoAudio", event.target.checked)} type="checkbox" /><span><strong>分镜视频生成新音频</strong><small>{selectedVideoModel && !selectedVideoModel.capabilities?.native_audio ? "当前模型不支持原生音频，请关闭或更换模型。" : "关闭时分镜视频静音，声音在画面锁定后统一处理。"}</small></span></label>
          </div>
        )}
        {step === 3 && (
          <div className="skill-confirm-grid">
            <section><h2>项目</h2><dl><div><dt>Skill</dt><dd>{skill.name} v{skill.current_version.version}</dd></div><div><dt>品类档案</dt><dd>{selectedCategoryProfile?.display_name || "未选择"}</dd></div><div><dt>目标</dt><dd>{draft.objective}</dd></div><div><dt>成片</dt><dd>{draft.durationSeconds} 秒 · {draft.aspectRatio} · {draft.fps} FPS</dd></div><div><dt>素材</dt><dd>{selectedAssets.length} 个</dd></div></dl></section>
            <section><h2>生成契约</h2><dl><div><dt>图片</dt><dd>{draft.imageModel} · {draft.imageResolution}</dd></div><div><dt>视频</dt><dd>{draft.videoModel} · {draft.videoResolution}</dd></div><div><dt>分镜音频</dt><dd>{draft.generateVideoAudio ? "生成" : "不生成"}</dd></div><div><dt>运行方式</dt><dd>{draft.automationMode === "full_auto" ? "全自动执行" : "引导模式"}</dd></div><div><dt>当前估算</dt><dd>{contractPreview.estimate_status === "known" ? formatMicros(contractPreview.estimated_cost_micros) : "未知（不能开始付费生成）"}</dd></div><div><dt>预算上限</dt><dd>{draft.budgetCny ? `¥${Number(draft.budgetCny).toFixed(2)}` : "未设置"}</dd></div></dl></section>
            <InlineMessage><ShieldCheck size={18} /><span>创建后 Skill 版本、品牌和素材用途将冻结为可追溯快照；所有 G0–G7 审核都需要你明确确认。</span></InlineMessage>
          </div>
        )}
        <footer className="skill-wizard-actions">
          <button className="secondary-button" disabled={step === 0 || submitting} onClick={() => { setError(""); setStep((value) => value - 1); }} type="button">上一步</button>
          {step < WIZARD_STEPS.length - 1 ? <button className="primary-button" onClick={goNext} type="button">下一步 <ArrowRight size={16} /></button> : <button className="primary-button" disabled={submitting} onClick={createProject} type="button">{submitting ? <CircleNotch className="spin" size={17} /> : <MagicWand size={17} />}创建项目</button>}
        </footer>
      </SurfacePanel>
    </PageShell>
  );
}

function axisTone(value) {
  if (["succeeded", "passed", "approved"].includes(value)) return "success";
  if (["failed", "needs_revision"].includes(value)) return "danger";
  if (["blocked", "warning", "stale"].includes(value)) return "warning";
  if (value === "running") return "active";
  return "neutral";
}

function StageAxes({ state }) {
  return (
    <div className="skill-stage-axes">
      <div><span>执行</span><StatusBadge tone={axisTone(state.execution)}>{EXECUTION_LABELS[state.execution] || state.execution}</StatusBadge></div>
      <div><span>系统校验</span><StatusBadge tone={axisTone(state.validation)}>{VALIDATION_LABELS[state.validation] || state.validation}</StatusBadge></div>
      <div><span>人工审核</span><StatusBadge tone={axisTone(state.review)}>{REVIEW_LABELS[state.review] || state.review}</StatusBadge></div>
    </div>
  );
}

function GateAction({ busy, gate, label, onDecide, relatedRevisionIds = [] }) {
  return (
    <div className="skill-gate-action">
      <div><ShieldCheck size={19} /><span><strong>{label}</strong><small>系统检查通过不代表人工批准。</small></span></div>
      <div>
        <button className="secondary-button compact" disabled={busy} onClick={() => onDecide(gate, "request_revision", relatedRevisionIds)} type="button">要求修改</button>
        <button className="primary-button compact" disabled={busy} onClick={() => onDecide(gate, "approve", relatedRevisionIds)} type="button">确认批准</button>
      </div>
    </div>
  );
}

function StageSummary({ stage, workspace }) {
  if (stage.id === "creative_brief") return <dl className="skill-summary-list"><div><dt>目标</dt><dd>{workspace.brief?.objective}</dd></div><div><dt>受众</dt><dd>{workspace.brief?.audience}</dd></div><div><dt>渠道</dt><dd>{workspace.brief?.distribution_channel}</dd></div><div><dt>输出</dt><dd>{workspace.brief?.target_duration_seconds} 秒 · {workspace.brief?.output_aspect_ratio}</dd></div></dl>;
  if (stage.id === "style_confirmation") return <div className="skill-style-summary"><p>{workspace.treatment?.core_idea || "批准简报后即可编译风格方案。"}</p>{workspace.style_bible && <div className="skill-keyword-list">{workspace.style_bible.positive_lock.map((item) => <span key={item}>{item}</span>)}</div>}</div>;
  if (stage.id === "storyboard_design") return workspace.outline ? <ol className="skill-outline-list">{workspace.outline.beats.map((beat) => <li key={beat.stable_beat_key}><span>{beat.order}</span><div><strong>{beat.title}</strong><p>{beat.message || beat.purpose}</p><small>{beat.target_duration_frames} 帧</small></div></li>)}</ol> : <p className="skill-panel-note">风格确认后，系统会生成可编辑的大纲、分镜提示词和视频提示词。</p>;
  return null;
}

function LookTestWorkspace({
  busy,
  clockNow,
  contract,
  lookTest,
  modelOption,
  onCancel,
  onGenerate,
  onRefresh,
  onSelect,
  resolveUrl,
}) {
  const items = lookTest?.items || [];
  const status = lookTest?.execution_status || "pending";
  const candidates = lookTest?.candidate_ids || [];
  const emptySuccess = status === "succeeded" && candidates.length === 0;
  const displayStatus = emptySuccess ? "failed" : status;
  const running = displayStatus === "running";
  const finishedItems = items.filter((item) => item.execution_status === "succeeded").length;
  const totalItems = items.length || lookTest?.representative_shot_keys?.length || 0;
  const elapsed = elapsedSince(lookTest?.started_at, clockNow);
  const selectedIds = lookTest?.selected_candidate_ids || [];
  const retryable = emptySuccess || (["failed", "cancelled"].includes(displayStatus)
    && items.some((item) => item.retryable)
    && !items.some((item) => item.execution_status === "blocked"));
  const modelLabel = modelOption?.label || contract?.image_model_id || "未指定";
  const providerLabel = modelOption?.provider || contract?.image_provider_connection_id || "未指定";

  return (
    <section className="skill-look-workspace" aria-live="polite">
      <SectionHeader
        description={`${modelLabel} · ${providerLabel} · ${contract?.image_width} × ${contract?.image_height}`}
        title="Look Test"
      />

      {(running || ["failed", "cancelled", "blocked"].includes(displayStatus)) && (
        <div className={`skill-look-progress is-${displayStatus}`}>
          <div className="skill-look-progress-heading">
            <div>
              <strong>{running ? "正在并行生成" : LOOK_ITEM_LABELS[displayStatus]}</strong>
              <span>{finishedItems}/{totalItems} 组完成 · {formatDurationMs(elapsed)}</span>
            </div>
            <StatusBadge tone={running ? "info" : displayStatus === "blocked" ? "warning" : "danger"}>
              {LOOK_ITEM_LABELS[displayStatus] || EXECUTION_LABELS[displayStatus]}
            </StatusBadge>
          </div>
          <progress max="100" value={lookTest?.progress || 0}>{lookTest?.progress || 0}%</progress>
          <div className="skill-look-heartbeat">
            <span className={elapsedSince(lookTest?.last_heartbeat_at, clockNow) > 20_000 ? "is-delayed" : ""}>
              <span aria-hidden="true" className="skill-heartbeat-dot" />
              {heartbeatLabel(lookTest?.last_heartbeat_at, clockNow)}
            </span>
            <span>已完成图片会即时保留</span>
          </div>
          {running && elapsed >= 180_000 && (
            <InlineMessage tone="warning">
              <Clock size={18} />
              <span>当前模型响应较慢，但任务仍有心跳。你可以继续等待，或停止后保留已完成图片。</span>
            </InlineMessage>
          )}
          {(lookTest?.error_message || emptySuccess) && !running && (
            <InlineMessage tone={displayStatus === "blocked" ? "warning" : "danger"}>
              <WarningCircle size={18} />
              <span>{lookTest?.error_message || "上一轮没有生成有效图片，请重新生成。"}</span>
            </InlineMessage>
          )}
          {items.length > 0 && (
            <div className="skill-look-item-list">
              {items.map((item, index) => (
                <div className={`is-${item.execution_status}`} key={item.shot_key}>
                  <span className="skill-look-item-index">{index + 1}</span>
                  <div>
                    <strong>代表画面 {index + 1}</strong>
                    <small>
                      {LOOK_ITEM_LABELS[item.execution_status] || EXECUTION_LABELS[item.execution_status]}
                      {item.started_at && ` · ${formatDurationMs(elapsedSince(item.started_at, item.completed_at ? Date.parse(item.completed_at) : clockNow))}`}
                    </small>
                    {item.error_message && <small className="skill-look-item-error">{item.error_message}</small>}
                  </div>
                  {item.execution_status === "running" && <CircleNotch className="spin" size={18} />}
                  {item.execution_status === "succeeded" && <CheckCircle size={18} weight="fill" />}
                  {["failed", "blocked", "cancelled"].includes(item.execution_status) && <WarningCircle size={18} />}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {candidates.length > 0 && (
        <div className="skill-look-results">
          <p>{running ? "已生成的图片会继续保留，其他图片仍在后台生成。" : "选择一张作为全片的人工风格基准。"}</p>
          <div className="skill-look-grid">
            {candidates.map((candidateId) => {
              const selected = selectedIds.includes(candidateId);
              return (
                <button
                  className={selected ? "is-selected" : ""}
                  disabled={running}
                  key={candidateId}
                  onClick={() => onSelect(candidateId)}
                  type="button"
                >
                  <img alt="Look Test 候选" src={resolveUrl(`/api/v1/generation-candidates/${candidateId}/thumbnail`)} />
                  {selected && <span><CheckCircle size={17} weight="fill" />已采纳</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="skill-look-actions">
        {displayStatus === "pending" && <button className="primary-button" disabled={busy} onClick={onGenerate} type="button">生成 Look Test</button>}
        {running && <button className="secondary-button" disabled={busy} onClick={onCancel} type="button">停止等待</button>}
        {retryable && <button className="primary-button" disabled={busy} onClick={onGenerate} type="button">继续生成未完成项</button>}
        {displayStatus === "blocked" && <button className="secondary-button" disabled={busy} onClick={onRefresh} type="button">重新检查状态</button>}
      </div>
    </section>
  );
}

function StoryboardProgress({ clockNow, onCancel, onRetry, step }) {
  const running = step?.execution_status === "running";
  const failed = step?.execution_status === "failed";
  const cancelled = step?.execution_status === "cancelled";
  const progress = Math.max(0, Math.min(100, Number(step?.progress || 0)));
  const phase = progress < 18
    ? "整理品牌、品类和素材事实"
    : progress < 55
      ? "导演模型规划大纲与镜头"
      : progress < 90
        ? "编译逐镜头图片与视频提示词"
        : "检查连续性与提示词质量";
  return (
    <section className={`skill-storyboard-progress ${failed ? "is-error" : ""}`} aria-live="polite">
      <div className="skill-storyboard-progress-heading">
        <div>
          {running ? <CircleNotch className="spin" size={18} /> : failed ? <WarningCircle size={18} /> : <XCircle size={18} />}
          <strong>{running ? phase : failed ? "大纲与分镜生成失败" : "大纲与分镜生成已停止"}</strong>
        </div>
        <span>{progress}%</span>
      </div>
      <div className="skill-storyboard-progress-track"><span style={{ width: `${progress}%` }} /></div>
      <div className="skill-storyboard-progress-meta">
        <span>{step?.model || "正在确定文案模型"}</span>
        <span>{heartbeatLabel(step?.last_heartbeat_at, clockNow)}</span>
      </div>
      {(failed || cancelled) && step?.error_message && <p>{step.error_message}</p>}
      <div className="skill-storyboard-progress-actions">
        {running && <button className="secondary-button compact" onClick={onCancel} type="button">停止生成</button>}
        {(failed || cancelled) && step?.retryable !== false && <button className="primary-button compact" onClick={onRetry} type="button">继续生成</button>}
      </div>
    </section>
  );
}

function ContinuitySummary({ manifest }) {
  const continuity = manifest?.continuity_bible || {};
  const labels = {
    world: "世界与空间",
    product: "产品身份",
    character: "人物",
    palette: "主色",
    lighting: "光线",
    cinematography: "摄影",
    texture: "质感",
    sound: "声音",
    typography: "字体与图形",
  };
  const items = Object.entries(continuity).filter(([, value]) => value);
  if (!items.length) return null;
  return (
    <section className="skill-continuity-summary">
      <SectionHeader description="这些规则会按镜头需要完整展开，保证独立生成时仍属于同一支影片。" title="全片连续性基准" />
      <dl>
        {items.map(([key, value]) => <div key={key}><dt>{labels[key] || key}</dt><dd>{String(value)}</dd></div>)}
      </dl>
    </section>
  );
}

function StoryboardReview({ busy, manifest, outline, onEdit, onRewrite, rewritingShotKey }) {
  const editPlan = manifest?.edit_plan || {};
  const fps = Number(manifest?.fps || 24);
  return (
    <div className="skill-storyboard-review">
      <div className="skill-storyboard-toolbar">
        <div>
          <strong>{manifest.shots.length} 个分镜</strong>
          <span>{editPlan.transition === "hard_cut" ? "全片硬切" : editPlan.transition || "按镜头设计转场"} · 文案模型 {manifest.authoring_model || "本地导演编译器"}</span>
        </div>
        <button className="secondary-button compact" disabled={busy} onClick={onEdit} type="button">编辑大纲与提示词</button>
      </div>
      <ContinuitySummary manifest={manifest} />
      {Object.keys(editPlan).length > 0 && <section className="skill-edit-recipe">
        <SectionHeader description="生成长度与成片保留长度分开管理。" title="剪辑节奏" />
        <dl>
          <div><dt>成片</dt><dd>{Number(editPlan.target_duration_seconds || 0).toFixed(2)} 秒</dd></div>
          <div><dt>细节 / 环境</dt><dd>{Math.round(Number(editPlan.detail_ratio || 0) * 100)}% / {Math.round(Number(editPlan.environment_ratio || 0) * 100)}%</dd></div>
          <div><dt>配乐节拍</dt><dd>{editPlan.music_bpm || "—"} BPM</dd></div>
          <div><dt>转场</dt><dd>{editPlan.transition === "hard_cut" ? "直接硬切" : editPlan.transition || "—"}</dd></div>
        </dl>
      </section>}
      <section className="skill-outline-review">
        <SectionHeader description="每个段落都明确观众收获、镜头数量和声音衔接。" title="导演大纲" />
        <ol>
          {(outline?.beats || []).map((beat) => (
            <li key={beat.stable_beat_key}>
              <span>{String(beat.order).padStart(2, "0")}</span>
              <div><strong>{beat.title}</strong><p>{beat.purpose}</p><small>{beat.suggested_shot_count} 个镜头 · {(beat.target_duration_frames / fps).toFixed(2)} 秒 · {beat.rhythm}</small></div>
              <p>{beat.audience_takeaway || beat.message}</p>
            </li>
          ))}
        </ol>
      </section>
      <section className="skill-shot-manifest">
        <SectionHeader description="每个镜头包含可检查的导演设计，以及独立完整的图片与视频提示词。" title="结构化分镜" />
        {manifest.shots.map((shot) => {
          const spec = shot.creative_spec || {};
          const camera = spec.camera || {};
          const sound = spec.sound || {};
          const transition = spec.transition || {};
          return (
            <article key={shot.stable_shot_key}>
              <header>
                <span>{String(shot.order).padStart(2, "0")}</span>
                <div><strong>{spec.title || shot.narrative_role}</strong><small>{shot.narrative_role}</small></div>
                <div className="skill-shot-timing"><span>成片 {(shot.duration_frames / fps).toFixed(2)} 秒</span><span>生成 {shot.generation_duration_seconds} 秒</span></div>
                {Object.keys(shot.prompt_quality?.checks || {}).length > 0 && <StatusBadge tone={shot.prompt_quality?.passed ? "success" : "warning"}>提示词 {shot.prompt_quality?.score || 0} 分</StatusBadge>}
              </header>
              <p>{spec.narrative_purpose || shot.description}</p>
              <div className="skill-shot-facts">
                <span><Camera size={15} />{camera.lens_mm ? `${camera.lens_mm}mm · ` : ""}{camera.framing || "景别待确认"} · {camera.motion || "机位待确认"}</span>
                <span><SpeakerHigh size={15} />{(sound.synchronous_foley || []).join("、") || "拟音待确认"}</span>
                <span><ArrowRight size={15} />{transition.cut_out || "动作完成点切出"}</span>
              </div>
              <details>
                <summary>查看导演设计与完整提示词</summary>
                <div className="skill-shot-detail-grid">
                  <section><strong>动作设计</strong><p>{spec.initial_state}</p><ol>{(spec.action_phases || []).map((phase) => <li key={phase.order}>{phase.description}</li>)}</ol><p>{spec.end_state}</p></section>
                  <section><strong>图片提示词</strong><p>{shot.image_prompt}</p></section>
                  <section><strong>视频提示词</strong><p>{shot.video_prompt}</p></section>
                  <section><strong>镜头负面约束</strong><p>{(shot.video_negative_constraints || []).join("；")}</p></section>
                </div>
              </details>
              <div className="skill-shot-actions">
                <button className="text-button" disabled={busy || rewritingShotKey === shot.stable_shot_key} onClick={() => onRewrite(shot)} type="button">
                  {rewritingShotKey === shot.stable_shot_key ? <CircleNotch className="spin" size={15} /> : <ArrowsClockwise size={15} />}AI 优化此镜头
                </button>
                {(shot.locked_fields || []).length > 0 && <span><Lock size={14} />已锁定 {shot.locked_fields.length} 项</span>}
              </div>
            </article>
          );
        })}
      </section>
      {(manifest.project_negative_constraints || []).length > 0 && (
        <details className="skill-project-negative"><summary>全片负面约束</summary><p>{manifest.project_negative_constraints.join("；")}</p></details>
      )}
    </div>
  );
}

export function SkillProjectWorkspace({
  imageGenerationSettings,
  navigate,
  onNotice,
  onOpenModelSettings,
  request,
  resolveUrl,
  videoGenerationSettings,
  projectId,
}) {
  const [project, setProject] = useState(null);
  const [workspace, setWorkspace] = useState(null);
  const [runMetrics, setRunMetrics] = useState(null);
  const [skill, setSkill] = useState(null);
  const [productions, setProductions] = useState([]);
  const [productionTimeline, setProductionTimeline] = useState(null);
  const [exportJobs, setExportJobs] = useState([]);
  const [selectedStage, setSelectedStage] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refreshToken, setRefreshToken] = useState(0);
  const [mixDraft, setMixDraft] = useState({
    integratedLoudnessLufs: "",
    truePeakDbtp: "",
    backgroundAudioKind: "music",
    rightsConfirmed: false,
    exactOverlayConfirmed: false,
  });
  const [storyboardEditing, setStoryboardEditing] = useState(false);
  const [outlineDraft, setOutlineDraft] = useState([]);
  const [shotDraft, setShotDraft] = useState([]);
  const [storyboardSaveState, setStoryboardSaveState] = useState("saved");
  const [rewritingShotKey, setRewritingShotKey] = useState("");
  const [clockNow, setClockNow] = useState(Date.now());
  const storyboardEditRevision = useRef(0);
  const outlineDraftRef = useRef([]);
  const shotDraftRef = useRef([]);
  const storyboardSaveTimer = useRef(null);
  const storyboardSaveInFlight = useRef(false);
  const storyboardSaveQueued = useRef(false);

  async function load() {
    const nextProject = await request(`/projects/${projectId}`);
    const [nextWorkspace, nextSkill, nextProductions] = await Promise.all([
      request(`/projects/${projectId}/skill-workspace`),
      request(`/skills/${encodeURIComponent(nextProject.skill_slug)}`),
      request(`/records/${projectId}/productions`).catch(() => []),
    ]);
    const nextRunMetrics = nextWorkspace.run?.run?.id
      ? await request(`/skill-runs/${nextWorkspace.run.run.id}/metrics`).catch(() => null)
      : null;
    let nextTimeline = null;
    let nextExportJobs = [];
    if (nextWorkspace.production_project_id) {
      const [timelineResult, exportResult] = await Promise.all([
        request(`/productions/${nextWorkspace.production_project_id}/timeline`).catch(() => null),
        request(`/productions/${nextWorkspace.production_project_id}/timeline/final-renders`).catch(() => ({ items: [] })),
      ]);
      nextTimeline = timelineResult;
      nextExportJobs = exportResult.items || [];
    }
    setProject(nextProject);
    setWorkspace(nextWorkspace);
    setRunMetrics(nextRunMetrics);
    setSkill(nextSkill);
    setProductions(nextProductions || []);
    setProductionTimeline(nextTimeline);
    setExportJobs(nextExportJobs);
    if (!storyboardEditing) {
      const nextOutlineDraft = (nextWorkspace.outline?.beats || []).map((item) => ({ ...item }));
      const nextShotDraft = (nextWorkspace.shot_manifest?.shots || []).map((item) => ({ ...item }));
      outlineDraftRef.current = nextOutlineDraft;
      shotDraftRef.current = nextShotDraft;
      setOutlineDraft(nextOutlineDraft);
      setShotDraft(nextShotDraft);
      setStoryboardSaveState("saved");
    }
    setSelectedStage((current) => current || nextWorkspace.run?.run?.current_stage || "creative_brief");
    return nextWorkspace;
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    load().catch((requestError) => {
      if (active) setError(requestError.message);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [projectId, refreshToken]); // eslint-disable-line react-hooks/exhaustive-deps

  const lookTestRunning = workspace?.look_test?.execution_status === "running";
  const storyboardStep = [...(workspace?.run?.steps || [])]
    .filter((item) => item.operation === "compile_storyboard")
    .sort((left, right) => Number(right.attempt || 0) - Number(left.attempt || 0))[0] || null;
  const storyboardRunning = storyboardStep?.execution_status === "running";
  const longTaskRunning = lookTestRunning || storyboardRunning;

  useEffect(() => {
    if (!longTaskRunning) return undefined;
    let active = true;
    let refreshing = false;
    const refreshProgress = async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        const nextWorkspace = await request(`/projects/${projectId}/skill-workspace`);
        if (!active) return;
        setWorkspace(nextWorkspace);
        if (!storyboardEditing && nextWorkspace.shot_manifest) {
          const nextOutlineDraft = (nextWorkspace.outline?.beats || []).map((item) => ({ ...item }));
          const nextShotDraft = (nextWorkspace.shot_manifest?.shots || []).map((item) => ({ ...item }));
          outlineDraftRef.current = nextOutlineDraft;
          shotDraftRef.current = nextShotDraft;
          setOutlineDraft(nextOutlineDraft);
          setShotDraft(nextShotDraft);
        }
        const runId = nextWorkspace.run?.run?.id;
        if (runId) {
          const metrics = await request(`/skill-runs/${runId}/metrics`).catch(() => null);
          if (active && metrics) setRunMetrics(metrics);
        }
      } catch (requestError) {
        if (active) setError(requestError.message);
      } finally {
        refreshing = false;
      }
    };
    const progressTimer = window.setInterval(refreshProgress, 2_000);
    const clockTimer = window.setInterval(() => setClockNow(Date.now()), 1_000);
    return () => {
      active = false;
      window.clearInterval(progressTimer);
      window.clearInterval(clockTimer);
    };
  }, [longTaskRunning, projectId, request, storyboardEditing]);

  async function perform(action, successMessage) {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
      if (successMessage) onNotice?.(successMessage);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function decideGate(gate, decision, relatedRevisionIds = []) {
    const runId = workspace.run.run.id;
    await perform(() => request(`/skill-runs/${runId}/gates/${gate}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, note: "", related_revision_ids: relatedRevisionIds }),
    }), decision === "approve" ? "审核决定已保存" : "已退回修改");
  }

  async function compileStyle() {
    await perform(() => request(`/skill-runs/${workspace.run.run.id}/style/compile`, { method: "POST" }), "风格方案已编译");
  }

  async function generateLookTest() {
    await perform(() => request(`/skill-runs/${workspace.run.run.id}/look-test/generate`, { method: "POST" }), "Look Test 已开始生成");
  }

  async function cancelLookTest() {
    await perform(() => request(`/skill-runs/${workspace.run.run.id}/look-test/cancel`, { method: "POST" }), "已停止未完成的 Look Test；完成图片已保留");
  }

  async function selectLook(candidateId) {
    await perform(() => request(`/skill-runs/${workspace.run.run.id}/look-test/select`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected_candidate_ids: [candidateId], decision_note: "人工选定的风格基准" }),
    }), "Look Test 已采纳");
  }

  async function compileStoryboard() {
    await perform(() => request(`/skill-runs/${workspace.run.run.id}/storyboard/compile`, { method: "POST" }), "大纲与分镜已开始生成");
  }

  async function cancelStoryboard() {
    await perform(
      () => request(`/skill-runs/${workspace.run.run.id}/storyboard/cancel`, { method: "POST" }),
      "已停止大纲与分镜生成",
    );
  }

  function scheduleStoryboardSave() {
    storyboardEditRevision.current += 1;
    setStoryboardSaveState("dirty");
    window.clearTimeout(storyboardSaveTimer.current);
    storyboardSaveTimer.current = window.setTimeout(() => {
      void saveStoryboard();
    }, 900);
  }

  function updateOutlineBeat(index, key, value) {
    const next = outlineDraftRef.current.map((item, itemIndex) => (
      itemIndex === index ? { ...item, [key]: value } : item
    ));
    outlineDraftRef.current = next;
    setOutlineDraft(next);
    scheduleStoryboardSave();
  }

  function updateShot(index, key, value) {
    const next = shotDraftRef.current.map((item, itemIndex) => (
      itemIndex === index ? { ...item, [key]: value } : item
    ));
    shotDraftRef.current = next;
    setShotDraft(next);
    scheduleStoryboardSave();
  }

  function toggleShotLock(index, lockKey) {
    const shot = shotDraftRef.current[index];
    const locked = new Set(shot?.locked_fields || []);
    if (locked.has(lockKey)) locked.delete(lockKey);
    else locked.add(lockKey);
    updateShot(index, "locked_fields", [...locked]);
  }

  async function saveStoryboard() {
    window.clearTimeout(storyboardSaveTimer.current);
    if (storyboardSaveInFlight.current) {
      storyboardSaveQueued.current = true;
      return false;
    }
    const saveRevision = storyboardEditRevision.current;
    const targetFrames = Number(workspace.brief?.target_duration_frames || 0);
    const normalizedOutline = outlineDraftRef.current.map((item, index) => ({
      ...item,
      order: index + 1,
      target_duration_frames: Number(item.target_duration_frames),
    }));
    let cursor = 0;
    const normalizedShots = shotDraftRef.current.map((item, index) => {
      const durationFrames = Number(item.duration_frames);
      const next = {
        ...item,
        order: index + 1,
        start_frame: cursor,
        duration_frames: durationFrames,
      };
      cursor += durationFrames;
      return next;
    });
    if (!normalizedOutline.length || normalizedOutline.some((item) => !item.title?.trim() || !item.purpose?.trim() || !(item.target_duration_frames > 0))) {
      setError("大纲标题、目的和帧数必须完整");
      setStoryboardSaveState("error");
      return false;
    }
    if (normalizedOutline.reduce((total, item) => total + item.target_duration_frames, 0) !== targetFrames) {
      setError(`大纲总帧数必须保持为 ${targetFrames}`);
      setStoryboardSaveState("error");
      return false;
    }
    if (!normalizedShots.length || normalizedShots.some((item) => !item.description?.trim() || !item.image_prompt?.trim() || !item.video_prompt?.trim() || !(item.duration_frames > 0))) {
      setError("每个分镜的画面说明、图片提示词、视频提示词和帧数都必须完整");
      setStoryboardSaveState("error");
      return false;
    }
    if (cursor !== targetFrames) {
      setError(`分镜总帧数必须保持为 ${targetFrames}`);
      setStoryboardSaveState("error");
      return false;
    }
    storyboardSaveInFlight.current = true;
    setStoryboardSaveState("saving");
    setError("");
    try {
      const outline = await request(`/projects/${projectId}/outline`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ beats: normalizedOutline }),
      });
      const manifest = await request(`/projects/${projectId}/shot-manifest`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          outline_revision_id: outline.id,
          style_bible_revision_id: workspace.style_bible.id,
          fps: workspace.shot_manifest.fps,
          shots: normalizedShots,
          continuity_bible: workspace.shot_manifest.continuity_bible || {},
          edit_plan: workspace.shot_manifest.edit_plan || {},
          project_negative_constraints: workspace.shot_manifest.project_negative_constraints || [],
        }),
      });
      setWorkspace((current) => ({ ...current, outline, shot_manifest: manifest }));
      if (storyboardEditRevision.current === saveRevision) {
        outlineDraftRef.current = normalizedOutline;
        shotDraftRef.current = normalizedShots;
        setOutlineDraft(normalizedOutline);
        setShotDraft(normalizedShots);
        setStoryboardSaveState("saved");
      } else {
        setStoryboardSaveState("dirty");
      }
      return true;
    } catch (requestError) {
      setError(requestError.message);
      setStoryboardSaveState("error");
      return false;
    } finally {
      storyboardSaveInFlight.current = false;
      if (storyboardSaveQueued.current || storyboardEditRevision.current !== saveRevision) {
        storyboardSaveQueued.current = false;
        storyboardSaveTimer.current = window.setTimeout(() => void saveStoryboard(), 50);
      }
    }
  }

  async function finishStoryboardEditing() {
    if (storyboardSaveState === "saving") return;
    const saved = storyboardSaveState === "saved" ? true : await saveStoryboard();
    if (saved) {
      setStoryboardEditing(false);
      onNotice?.("大纲与分镜已自动保存");
    }
  }

  async function rewriteStoryboardShot(shot) {
    setRewritingShotKey(shot.stable_shot_key);
    setError("");
    try {
      const manifest = await request(`/skill-runs/${workspace.run.run.id}/storyboard/shots/${shot.stable_shot_key}/rewrite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instruction: "提高镜头叙事清晰度、动作可生成性和提示词完整度，同时保持全片视觉连续性。",
          locked_fields: shot.locked_fields || [],
        }),
      });
      const nextShots = (manifest.shots || []).map((item) => ({ ...item }));
      shotDraftRef.current = nextShots;
      setShotDraft(nextShots);
      setWorkspace((current) => ({ ...current, shot_manifest: manifest }));
      onNotice?.(`分镜 ${shot.order} 已优化`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setRewritingShotKey("");
    }
  }

  useEffect(() => () => window.clearTimeout(storyboardSaveTimer.current), []);

  async function createPictureLock() {
    const productionId = workspace.production_project_id;
    await perform(async () => {
      const currentTimeline = await request(`/productions/${productionId}/timeline`);
      const timeline = await request(`/skill-runs/${workspace.run.run.id}/picture-lock/from-production`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          production_project_id: productionId,
          expected_timeline_revision_id: currentTimeline.revision_id,
        }),
      });
      await request(`/skill-runs/${workspace.run.run.id}/gates/picture_locked/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approve", note: "人工确认画面锁定", related_revision_ids: [timeline.id] }),
      });
    }, "画面版本已锁定");
  }

  async function finalizeAudioCaption() {
    const productionId = workspace.production_project_id;
    await perform(async () => {
      const currentTimeline = await request(`/productions/${productionId}/timeline`);
      setProductionTimeline(currentTimeline);
      const hasAudio = currentTimeline.clips.some((item) => item.enabled && item.audio_mode !== "muted")
        || currentTimeline.background_audio_track?.enabled;
      if (hasAudio && (!mixDraft.integratedLoudnessLufs || !mixDraft.truePeakDbtp)) {
        throw new Error("有声音的时间线必须填写实测综合响度和真峰值");
      }
      if (currentTimeline.background_audio_track?.enabled && !mixDraft.rightsConfirmed) {
        throw new Error("请确认附加音频的使用权利");
      }
      await request(`/skill-runs/${workspace.run.run.id}/audio-caption/from-production`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          production_project_id: productionId,
          expected_timeline_revision_id: currentTimeline.revision_id,
          background_audio_kind: mixDraft.backgroundAudioKind,
          background_audio_rights_status: mixDraft.rightsConfirmed ? "confirmed" : "unknown",
          integrated_loudness_lufs: mixDraft.integratedLoudnessLufs === "" ? null : Number(mixDraft.integratedLoudnessLufs),
          true_peak_dbtp: mixDraft.truePeakDbtp === "" ? null : Number(mixDraft.truePeakDbtp),
        }),
      });
    }, "声音、字幕和混音版本已创建");
  }

  async function refreshProductionArtifacts() {
    await perform(async () => undefined);
  }

  async function createDeliveryFromExport(exportJob) {
    const exactOverlays = workspace.timeline?.exact_overlays || [];
    if (exactOverlays.length && !mixDraft.exactOverlayConfirmed) {
      setError("请先在最终成片中逐项确认 exact 素材已经正确叠加");
      return;
    }
    await perform(() => request(`/skill-runs/${workspace.run.run.id}/delivery-manifest/from-export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        production_project_id: workspace.production_project_id,
        export_job_id: exportJob.id,
        exact_overlay_evidence: exactOverlays.map((item) => ({
          ...item,
          export_job_id: exportJob.id,
          timeline_revision_id: workspace.timeline.id,
          verification: "user_confirmed_in_final_export",
        })),
      }),
    }), "交付清单已生成");
  }

  if (loading) return <PageShell className="skill-page"><LoadingState label="正在打开 Skill 项目" /></PageShell>;
  if (error && !workspace) return <PageShell className="skill-page"><ErrorState message={error} onRetry={() => setRefreshToken((value) => value + 1)} /></PageShell>;
  if (!workspace?.run) return <PageShell className="skill-page"><ErrorState message="项目尚未创建运行实例，请返回 Skill 广场重新开始。" /></PageShell>;
  const run = workspace.run.run;
  const stage = SKILL_WORKFLOW_STAGES.find((item) => item.id === selectedStage) || SKILL_WORKFLOW_STAGES[0];
  const state = stageState(workspace, stage);
  const currentGateApproved = state.approved;
  const productionMode = ["shot_images", "shot_videos", "editing", "audio_caption", "export"].includes(stage.id) && workspace.production_project_id;
  const matchingExportJobs = exportJobs.filter((item) => (
    item.status === "succeeded"
    && item.timeline_revision_id === workspace.timeline?.source_timeline_revision_id
  ));
  const latestMatchingExport = matchingExportJobs[0] || null;
  const actualCostMicros = runMetrics?.actual_cost_micros ?? run.actual_cost_micros;
  const budgetPercent = workspace.run_contract?.budget_limit_micros
    ? Math.round((actualCostMicros / workspace.run_contract.budget_limit_micros) * 100)
    : null;
  const selectedStageSteps = workspace.run.steps.filter((item) => item.stage === stage.id);
  const fallbackStageMetrics = selectedStageSteps.reduce((result, item) => ({
    total: result.total + item.total_ms,
    queue: result.queue + item.queue_wait_ms,
    provider: result.provider + item.provider_ms,
    postprocess: result.postprocess + item.postprocess_ms,
    cost: result.cost + item.actual_cost_micros,
  }), { total: 0, queue: 0, provider: 0, postprocess: 0, cost: 0 });
  const persistedStageMetrics = runMetrics?.stages?.find((item) => item.stage === stage.id);
  const selectedStageMetrics = persistedStageMetrics ? {
    total: persistedStageMetrics.total_ms,
    queue: persistedStageMetrics.queue_wait_ms,
    provider: persistedStageMetrics.provider_ms,
    postprocess: persistedStageMetrics.postprocess_ms,
    cost: persistedStageMetrics.actual_cost_micros,
  } : fallbackStageMetrics;
  const lockedImageSettings = {
    ...imageGenerationSettings,
    default_candidate_count: workspace.run_contract.candidate_count_by_stage?.shot_image || 1,
    remote_model_alias: workspace.run_contract.image_model_id,
    models: (imageGenerationSettings?.models || []).filter((item) => item.alias === workspace.run_contract.image_model_id),
  };
  const lockedImageModel = (imageGenerationSettings?.models || [])
    .find((item) => item.alias === workspace.run_contract.image_model_id);
  const lockedVideoSettings = {
    ...videoGenerationSettings,
    default_model_alias: workspace.run_contract.video_model_id,
    default_resolution: workspace.run_contract.video_resolution_label,
    models: (videoGenerationSettings?.models || []).filter((item) => item.alias === workspace.run_contract.video_model_id),
  };
  const productionTimelineChanged = Boolean(
    productionTimeline?.revision_id
    && workspace.timeline?.source_timeline_revision_id
    && productionTimeline.revision_id !== workspace.timeline.source_timeline_revision_id,
  );
  return (
    <PageShell className="skill-project-page">
      <div className="skill-project-header">
        <button className="skill-back-button" onClick={() => navigate("/projects")} type="button"><ArrowLeft size={16} />项目</button>
        <div className="skill-project-title"><SkillCover compact skill={skill} /><div><span>{skill.name} · v{skill.current_version.version}</span><h1>{project.name}</h1><p>{workspace.brief?.objective}</p></div></div>
        <div className="skill-project-metrics"><div><span>当前阶段</span><strong>{SKILL_WORKFLOW_STAGES.find((item) => item.id === run.current_stage)?.label}</strong></div><div><span>实际成本</span><strong>{formatMicros(actualCostMicros)}{budgetPercent != null ? ` · ${budgetPercent}%` : ""}</strong></div><div title={`排队 ${formatDurationMs(selectedStageMetrics.queue)} · 模型 ${formatDurationMs(selectedStageMetrics.provider)} · 后处理 ${formatDurationMs(selectedStageMetrics.postprocess)}`}><span>本阶段耗时 / 成本</span><strong>{formatDurationMs(selectedStageMetrics.total)} · {formatMicros(selectedStageMetrics.cost)}</strong></div><div><span>运行状态</span><StatusBadge tone={axisTone(run.execution_status)}>{EXECUTION_LABELS[run.execution_status]}</StatusBadge></div></div>
      </div>

      <div className="skill-project-layout">
        <nav className="skill-stage-nav" aria-label="Skill 工作流阶段">
          {SKILL_WORKFLOW_STAGES.map((item, index) => {
            const itemState = stageState(workspace, item);
            return <button className={`${item.id === stage.id ? "is-active" : ""} ${itemState.complete ? "is-complete" : ""}`} key={item.id} onClick={() => setSelectedStage(item.id)} type="button"><span>{itemState.complete ? <Check size={13} weight="bold" /> : index + 1}</span><strong>{item.label}</strong>{itemState.current && <small>当前</small>}</button>;
          })}
        </nav>

        <main className="skill-stage-main">
          {error && <ErrorState message={error} />}
          <SurfacePanel className="skill-stage-panel">
            <PageHeader description={`门禁：${stage.gateLabel}`} title={stage.label} />
            <StageAxes state={state} />
            <StageSummary stage={stage} workspace={workspace} />

            {stage.id === "creative_brief" && !currentGateApproved && <GateAction busy={busy} gate={stage.gate} label="确认目标、品牌、素材权利和生成契约" onDecide={decideGate} relatedRevisionIds={[workspace.brief.id, workspace.run_contract.id]} />}

            {stage.id === "style_confirmation" && (
              <div className="skill-stage-actions-stack">
                {!workspace.style_bible && <button className="primary-button" disabled={busy} onClick={compileStyle} type="button">{busy ? <CircleNotch className="spin" size={17} /> : <Sparkle size={17} />}编译风格方案</button>}
                {workspace.style_bible && workspace.look_test && (
                  <LookTestWorkspace
                    busy={busy}
                    clockNow={clockNow}
                    contract={workspace.run_contract}
                    lookTest={workspace.look_test}
                    modelOption={lockedImageModel}
                    onCancel={cancelLookTest}
                    onGenerate={generateLookTest}
                    onRefresh={() => setRefreshToken((value) => value + 1)}
                    onSelect={selectLook}
                    resolveUrl={resolveUrl}
                  />
                )}
                {workspace.look_test?.review_status === "approved" && !currentGateApproved && <GateAction busy={busy} gate={stage.gate} label="确认全片风格基准" onDecide={decideGate} relatedRevisionIds={[workspace.style_bible.id, workspace.look_test.id]} />}
              </div>
            )}

            {stage.id === "storyboard_design" && (
              <div className="skill-stage-actions-stack">
                {!workspace.shot_manifest && ["running", "failed", "cancelled"].includes(storyboardStep?.execution_status) && (
                  <StoryboardProgress clockNow={clockNow} onCancel={cancelStoryboard} onRetry={compileStoryboard} step={storyboardStep} />
                )}
                {!workspace.shot_manifest && !["running", "failed", "cancelled"].includes(storyboardStep?.execution_status) && (
                  <button className="primary-button" disabled={busy} onClick={compileStoryboard} type="button">生成大纲与分镜</button>
                )}
                {workspace.shot_manifest && !storyboardEditing && (
                  <StoryboardReview
                    busy={busy}
                    manifest={workspace.shot_manifest}
                    onEdit={() => {
                      setStoryboardSaveState("saved");
                      setStoryboardEditing(true);
                    }}
                    onRewrite={rewriteStoryboardShot}
                    outline={workspace.outline}
                    rewritingShotKey={rewritingShotKey}
                  />
                )}
                {workspace.shot_manifest && storyboardEditing && (
                  <div className="skill-storyboard-editor">
                    <div className="skill-storyboard-editor-toolbar">
                      <div><strong>编辑大纲与分镜</strong><span>修改会自动保存</span></div>
                      <div><AutosaveStatus onRetry={() => void saveStoryboard()} state={storyboardSaveState} /><button className="secondary-button compact" disabled={storyboardSaveState === "saving"} onClick={() => void finishStoryboardEditing()} type="button">完成编辑</button></div>
                    </div>
                    <SectionHeader description={`总时长保持 ${workspace.brief.target_duration_frames} 帧。大纲负责叙事节奏，分镜负责可执行画面。`} title="导演大纲" />
                    <div className="skill-outline-editor-list">
                      {outlineDraft.map((beat, index) => (
                        <article key={beat.stable_beat_key}>
                          <span>{String(index + 1).padStart(2, "0")}</span>
                          <label><span>段落标题</span><input onChange={(event) => updateOutlineBeat(index, "title", event.target.value)} value={beat.title} /></label>
                          <label><span>叙事目的</span><textarea onChange={(event) => updateOutlineBeat(index, "purpose", event.target.value)} rows={2} value={beat.purpose} /></label>
                          <label><span>核心信息</span><textarea onChange={(event) => updateOutlineBeat(index, "message", event.target.value)} rows={2} value={beat.message} /></label>
                          <label><span>观众收获</span><textarea onChange={(event) => updateOutlineBeat(index, "audience_takeaway", event.target.value)} rows={2} value={beat.audience_takeaway || ""} /></label>
                          <label><span>节奏</span><input onChange={(event) => updateOutlineBeat(index, "rhythm", event.target.value)} value={beat.rhythm || ""} /></label>
                          <label className="is-compact"><span>帧数</span><input min="1" onChange={(event) => updateOutlineBeat(index, "target_duration_frames", event.target.value)} type="number" value={beat.target_duration_frames} /></label>
                        </article>
                      ))}
                    </div>
                    <SectionHeader description="图片提示词锁定首帧；视频提示词完整描述首帧绑定、动作节拍、运镜、同步声音和硬约束。" title="结构化分镜" />
                    <div className="skill-shot-editor-list">
                      {shotDraft.map((shot, index) => (
                        <article key={shot.stable_shot_key}>
                          <header><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{shot.creative_spec?.title || shot.narrative_role}</strong><small>{shot.narrative_role}</small></div><label><span>成片帧数</span><input min="1" onChange={(event) => updateShot(index, "duration_frames", event.target.value)} type="number" value={shot.duration_frames} /></label><label><span>生成秒数</span><input min="1" onChange={(event) => updateShot(index, "generation_duration_seconds", Number(event.target.value))} step="1" type="number" value={shot.generation_duration_seconds || ""} /></label></header>
                          <div className="skill-shot-locks" aria-label={`分镜 ${index + 1} 字段锁定`}>
                            {[["subject", "主体"], ["camera", "机位"], ["lighting", "光线"], ["continuity_locks", "连续性"]].map(([key, label]) => {
                              const selected = (shot.locked_fields || []).includes(key);
                              return <button aria-pressed={selected} className={selected ? "is-locked" : ""} key={key} onClick={() => toggleShotLock(index, key)} type="button"><Lock size={13} weight={selected ? "fill" : "regular"} />{label}</button>;
                            })}
                          </div>
                          <label><span>画面说明</span><textarea onChange={(event) => updateShot(index, "description", event.target.value)} rows={3} value={shot.description} /></label>
                          <label><span>图片提示词</span><textarea onChange={(event) => updateShot(index, "image_prompt", event.target.value)} rows={9} value={shot.image_prompt} /></label>
                          <label><span>视频提示词</span><textarea onChange={(event) => updateShot(index, "video_prompt", event.target.value)} rows={13} value={shot.video_prompt} /></label>
                        </article>
                      ))}
                    </div>
                  </div>
                )}
                {workspace.shot_manifest && !storyboardEditing && !currentGateApproved && <GateAction busy={busy} gate={stage.gate} label="确认大纲、时长和全部分镜提示词" onDecide={decideGate} relatedRevisionIds={[workspace.outline.id, workspace.shot_manifest.id]} />}
              </div>
            )}

            {["shot_images", "shot_videos"].includes(stage.id) && workspace.production_project_id && !currentGateApproved && <GateAction busy={busy} gate={stage.gate} label={stage.id === "shot_images" ? "确认所有必需分镜图片已采纳" : "确认所有必需分镜视频已采纳"} onDecide={decideGate} />}
            {stage.id === "editing" && !currentGateApproved && <div className="skill-stage-actions-stack"><InlineMessage><FilmStrip size={18} /><span>先在下方剪辑区检查分镜顺序、入出点和转场，再将当前版本锁定为声音与字幕的唯一画面基准。</span></InlineMessage><button className="primary-button" disabled={busy} onClick={createPictureLock} type="button">锁定当前画面版本</button></div>}
            {budgetPercent >= 80 && <InlineMessage tone="warning"><WarningCircle size={18} /><span>本次运行已使用预算的 {budgetPercent}%，下一次付费调用前仍会执行硬预算检查。</span></InlineMessage>}
            {stage.id === "audio_caption" && (
              <div className="skill-stage-actions-stack">
                <InlineMessage tone="warning"><MusicNotes size={18} /><span>在下方剪辑区完成分镜音频、全片配乐和字幕。画面如果变化，必须返回 G5 重新锁定。</span></InlineMessage>
                <div className="skill-mix-form">
                  {productionTimeline?.background_audio_track?.enabled && <label><span>附加音轨用途</span><select value={mixDraft.backgroundAudioKind} onChange={(event) => setMixDraft((current) => ({ ...current, backgroundAudioKind: event.target.value }))}><option value="music">全片配乐</option><option value="narration">旁白</option><option value="sfx">音效</option></select></label>}
                  <label><span>实测综合响度（LUFS）</span><input placeholder="例如 -14" step="0.1" type="number" value={mixDraft.integratedLoudnessLufs} onChange={(event) => setMixDraft((current) => ({ ...current, integratedLoudnessLufs: event.target.value }))} /></label>
                  <label><span>实测真峰值（dBTP）</span><input max="-1" placeholder="不高于 -1" step="0.1" type="number" value={mixDraft.truePeakDbtp} onChange={(event) => setMixDraft((current) => ({ ...current, truePeakDbtp: event.target.value }))} /></label>
                  {productionTimeline?.background_audio_track?.enabled && <label className="skill-confirm-row"><input checked={mixDraft.rightsConfirmed} onChange={(event) => setMixDraft((current) => ({ ...current, rightsConfirmed: event.target.checked }))} type="checkbox" /><span>我确认拥有该附加音频用于当前分发渠道的权利</span></label>}
                </div>
                {(workspace.mix_revision?.validation_status !== "passed" || productionTimelineChanged) && <button className="primary-button" disabled={busy} onClick={finalizeAudioCaption} type="button">{workspace.mix_revision ? "更新声音与字幕版本" : "创建声音与字幕版本"}</button>}
                {workspace.mix_revision?.validation_status === "warning" && <InlineMessage tone="warning"><WarningCircle size={18} /><span>{workspace.mix_revision.validation_messages.join("；")}</span></InlineMessage>}
                {workspace.mix_revision?.validation_status === "passed" && !productionTimelineChanged && !currentGateApproved && <GateAction busy={busy} gate={stage.gate} label="确认最终声音、混音和字幕" onDecide={decideGate} relatedRevisionIds={[workspace.timeline.id, workspace.mix_revision.id]} />}
              </div>
            )}
            {stage.id === "export" && (
              <div className="skill-stage-actions-stack">
                <InlineMessage><ShieldCheck size={18} /><span>下方导出必须使用 G6 对应的时间线版本；系统会校验文件哈希、媒体参数、权利和质检结果。</span></InlineMessage>
                <button className="secondary-button compact" disabled={busy} onClick={refreshProductionArtifacts} type="button">刷新导出结果</button>
                {(workspace.timeline?.exact_overlays?.length || 0) > 0 && <label className="skill-confirm-row"><input checked={mixDraft.exactOverlayConfirmed} onChange={(event) => setMixDraft((current) => ({ ...current, exactOverlayConfirmed: event.target.checked }))} type="checkbox" /><span>我已在最终导出画面中逐项确认 {workspace.timeline.exact_overlays.length} 个 exact 素材叠加</span></label>}
                {!workspace.delivery_manifest && latestMatchingExport && <button className="primary-button" disabled={busy} onClick={() => createDeliveryFromExport(latestMatchingExport)} type="button">为当前成片生成交付清单</button>}
                {!workspace.delivery_manifest && !latestMatchingExport && <p className="skill-panel-note">尚无与当前 G6 时间线匹配的成功导出，请在下方完成导出后刷新。</p>}
                {workspace.delivery_manifest && !currentGateApproved && <GateAction busy={busy} gate={stage.gate} label="确认最终交付包" onDecide={decideGate} relatedRevisionIds={[workspace.delivery_manifest.id]} />}
              </div>
            )}
          </SurfacePanel>

          {productionMode && (
            <section className="skill-production-bridge">
              <SectionHeader description="沿用现有创作方案的图片生成、视频生成、剪辑与导出能力。" title="创作方案" />
              <ProductionHub
                allowProjectCreation={false}
                analysisId={null}
                error=""
                imageGenerationSettings={lockedImageSettings}
                lockedExportResolution={workspace.run_contract.video_resolution_label}
                loading={false}
                navigationTarget={{ token: `${workspace.production_project_id}:${stage.id}`, projectId: workspace.production_project_id, recordId: project.id, step: stage.id === "audio_caption" ? "editing" : stage.id }}
                onNavigationChange={() => undefined}
                onNotice={onNotice}
                onOpenModelSettings={onOpenModelSettings}
                onProjectsChanged={async () => { const next = await request(`/records/${project.id}/productions`); setProductions(next || []); return next || []; }}
                projects={productions}
                recordId={project.id}
                request={request}
                resolveUrl={resolveUrl}
                sourceMedia={{ aspectRatio: workspace.brief?.output_aspect_ratio, height: workspace.run_contract?.video_height, hasAudio: false, width: workspace.run_contract?.video_width }}
                sourceTitle={project.name}
                videoGenerationSettings={lockedVideoSettings}
              />
            </section>
          )}
        </main>
      </div>
    </PageShell>
  );
}
