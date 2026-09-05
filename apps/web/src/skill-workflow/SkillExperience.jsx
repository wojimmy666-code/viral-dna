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
import { mainCreationStep, PREPARATION_SECTIONS, savedWorkspaceLocation } from "../creation-workspace/workspace-ui.js";
import { CategoryProfilePicker } from "../category-profiles/index.js";
import {
  InlineMessage,
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
  lookTestLayoutStyle,
  resolutionForRatio,
  REVIEW_LABELS,
  SKILL_WORKFLOW_STAGES,
  skillCreationNavigation,
  skillImageGenerationSettings,
  skillSectionEnabled,
  resolveSkillSection,
  stageState,
  validateSkillStartDraft,
  VALIDATION_LABELS,
} from "./skill-workflow-ui.js";
import { StoryboardPromptEditor } from "./StoryboardPromptEditor.jsx";
import { storyboardProgressState } from "./storyboard-progress.js";
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
  if (state.approved) return <StatusBadge tone="success">已确认</StatusBadge>;
  if (["failed", "blocked", "cancelled"].includes(state.execution)) return <StatusBadge tone="warning">{EXECUTION_LABELS[state.execution]}</StatusBadge>;
  return null;
}

function GateAction({ busy, gate, label, onDecide, relatedRevisionIds = [] }) {
  return (
    <div className="skill-gate-action">
      <div><span>{label}</span></div>
      <div>
        <button className="secondary-button compact" disabled={busy} onClick={() => onDecide(gate, "request_revision", relatedRevisionIds)} type="button">要求修改</button>
        <button className="primary-button compact" disabled={busy} onClick={() => onDecide(gate, "approve", relatedRevisionIds)} type="button">{gate === "delivery_approved" ? "确认交付" : "确认并继续"}</button>
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
          <div className="skill-look-grid" style={lookTestLayoutStyle(contract, candidates.length)}>
            {candidates.map((candidateId, index) => {
              const selected = selectedIds.includes(candidateId);
              return (
                <button
                  aria-label={`采用风格候选 ${index + 1}`}
                  aria-pressed={selected}
                  className={selected ? "is-selected" : ""}
                  disabled={running}
                  key={candidateId}
                  onClick={() => onSelect(candidateId)}
                  type="button"
                >
                  <img alt={`Look Test 候选 ${index + 1}`} src={resolveUrl(`/api/v1/generation-candidates/${candidateId}/thumbnail`)} />
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

function StoryboardProgress({ busy, clockNow, manifest, onCancel, onRetry, step }) {
  const state = storyboardProgressState(step, clockNow, manifest);
  const { running, failed, progress } = state;
  return (
    <section className={`skill-storyboard-progress ${failed ? "is-error" : ""}`} aria-live="polite">
      <div className="skill-storyboard-progress-summary">
        <div className="skill-storyboard-progress-heading">
          <div>
            {running ? <CircleNotch className="spin" size={18} /> : failed ? <WarningCircle size={18} /> : <XCircle size={18} />}
            <strong>{state.title}</strong>
          </div>
          <span>{progress}%</span>
        </div>
        <div className="skill-storyboard-progress-meta">
          <span>{state.model}</span>
          <span>{running ? "已用时" : "耗时"} {formatDurationMs(state.elapsedMs)}</span>
          <span>{running ? heartbeatLabel(step?.last_heartbeat_at, clockNow) : state.endedAt ? `结束于 ${state.endedAt}` : "任务已停止"}</span>
        </div>
        <div className="skill-storyboard-progress-actions">
          {running && <button className="secondary-button compact" disabled={busy} onClick={onCancel} type="button">停止生成</button>}
          {state.canRetry && <button className="primary-button compact" disabled={busy} onClick={onRetry} type="button">{state.retryLabel}</button>}
        </div>
      </div>
      <div className="skill-storyboard-progress-track" role="progressbar" aria-label="大纲与分镜生成进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div>
      {state.savedLabel && <p>{state.savedLabel}</p>}
      {!running && state.error && <p>{state.error}</p>}
      {state.resumeConflict && <p>草稿已有人工修改，请在当前草稿上继续编辑并确认，旧任务不会覆盖这些修改。</p>}
    </section>
  );
}

function SkillProjectReferences({ usages = [], request, resolveUrl }) {
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const usageKey = usages.map((item) => item.asset_id).join(",");
  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all(usages.map((usage) => request(`/assets/${usage.asset_id}`).catch(() => ({ id: usage.asset_id, name: "素材暂不可用" })))).then((items) => {
      if (active) { setAssets(items); setLoading(false); }
    });
    return () => { active = false; };
  }, [usageKey, request]);
  return <section><SectionHeader title="参考资产" />{loading ? <LoadingState label="正在读取项目素材" /> : <div className="skill-reference-list">{assets.map((asset) => <article key={asset.id}><div><ImageSquare size={24} />{asset.thumbnail_url && <img alt={asset.name} onError={(event) => { event.currentTarget.hidden = true; }} src={resolveUrl(asset.thumbnail_url)} />}</div><span>{asset.name}</span></article>)}{!assets.length && <p>尚未添加参考素材。</p>}</div>}</section>;
}

export function SkillProjectWorkspace({
  navigationTarget,
  onNotificationsChanged,
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
  const [selectedStage, setSelectedStage] = useState(() => savedWorkspaceLocation(projectId, globalThis.location?.search).section);
  const productionWorkspaceRef = useRef(null);
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
  const [clockNow, setClockNow] = useState(Date.now());
  const storyboardEditorRef = useRef(null);

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
    setSelectedStage((current) => workspace ? current : resolveSkillSection(nextWorkspace, current || nextWorkspace.run?.run?.current_stage));
    return nextWorkspace;
  }

  useEffect(() => {
    let active = true;
    if (!workspace) setLoading(true);
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
  }, [longTaskRunning, projectId, request]);

  async function perform(action, successMessage) {
    setBusy(true);
    setError("");
    try {
      await action();
      const next = await load();
      if (successMessage) onNotice?.(successMessage);
      return next;
    } catch (requestError) {
      setError(requestError.message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function decideGate(gate, decision, relatedRevisionIds = []) {
    const runId = workspace.run.run.id;
    const next = await perform(() => request(`/skill-runs/${runId}/gates/${gate}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, note: "", related_revision_ids: relatedRevisionIds }),
    }), decision === "approve" ? "审核决定已保存" : "已退回修改");
    if (next && decision === "approve") setSelectedStage(next.run.run.current_stage);
    return Boolean(next);
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
    if (storyboardEditorRef.current && !await storyboardEditorRef.current.flush()) return;
    await perform(() => request(`/skill-runs/${workspace.run.run.id}/storyboard/compile`, { method: "POST" }), storyboardStep?.resumable ? "已开始处理未完成部分" : "大纲与分镜已开始生成");
  }

  async function cancelStoryboard() {
    await perform(
      () => request(`/skill-runs/${workspace.run.run.id}/storyboard/cancel`, { method: "POST" }),
      "已停止大纲与分镜生成",
    );
  }

  function handleStoryboardSaved(manifest) {
    setWorkspace((current) => ({
      ...current,
      shot_manifest: manifest,
      run: {
        ...current.run,
        gates: current.run.gates.filter((gate) => ["brief_approved", "style_approved"].includes(gate.gate)),
      },
    }));
  }

  async function confirmStoryboard(manifest) {
    if (stageState(workspace, SKILL_WORKFLOW_STAGES[2]).approved && manifest.id === workspace.shot_manifest.id) {
      return productionWorkspaceRef.current?.navigate("shot_images");
    }
    return decideGate("storyboard_approved", "approve", [manifest.outline_revision_id, manifest.id]);
  }

  async function createPictureLock() {
    const productionId = workspace.production_project_id;
    const next = await perform(async () => {
      await productionWorkspaceRef.current?.flush();
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
    if (next) setSelectedStage("audio_caption");
  }

  async function finalizeAudioCaption() {
    const productionId = workspace.production_project_id;
    return perform(async () => {
      await productionWorkspaceRef.current?.flush();
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
    return perform(() => request(`/skill-runs/${workspace.run.run.id}/delivery-manifest/from-export`, {
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

  async function confirmDelivery(exportJob) {
    const next = await createDeliveryFromExport(exportJob);
    if (next?.delivery_manifest) await decideGate("delivery_approved", "approve", [next.delivery_manifest.id]);
  }

  async function confirmAudioCaption() {
    let currentTimeline;
    try {
      await productionWorkspaceRef.current?.flush();
      currentTimeline = await request(`/productions/${workspace.production_project_id}/timeline`);
      setProductionTimeline(currentTimeline);
    } catch (saveError) {
      setError(saveError.message);
      return;
    }
    if (workspace.mix_revision?.validation_status === "passed" && currentTimeline?.revision_id === workspace.timeline?.source_timeline_revision_id) {
      if (stageState(workspace, SKILL_WORKFLOW_STAGES[6]).approved) {
        await productionWorkspaceRef.current?.navigate("export");
      } else {
        await decideGate("audio_caption_approved", "approve", [workspace.timeline.id, workspace.mix_revision.id]);
      }
      return;
    }
    const next = await finalizeAudioCaption();
    if (next?.mix_revision?.validation_status === "passed") {
      await decideGate("audio_caption_approved", "approve", [next.timeline.id, next.mix_revision.id]);
    }
  }

  if (loading) return <PageShell className="skill-page"><LoadingState label="正在打开 Skill 项目" /></PageShell>;
  if (error && !workspace) return <PageShell className="skill-page"><ErrorState message={error} onRetry={() => setRefreshToken((value) => value + 1)} /></PageShell>;
  if (!workspace?.run) return <PageShell className="skill-page"><ErrorState message="项目尚未创建运行实例，请返回 Skill 广场重新开始。" /></PageShell>;
  const run = workspace.run.run;
  const stage = SKILL_WORKFLOW_STAGES.find((item) => item.id === selectedStage) || SKILL_WORKFLOW_STAGES[0];
  const state = stageState(workspace, stage);
  const currentGateApproved = state.approved;
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
  const lockedImageSettings = skillImageGenerationSettings(imageGenerationSettings, workspace.run_contract);
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
  const preparation = (
          <div className="skill-preparation-panel">
            <SectionHeader title={stage.label} />
            {stage.id !== "storyboard_design" && <StageAxes state={state} />}
            {!(stage.id === "storyboard_design" && workspace.shot_manifest) && <StageSummary stage={stage} workspace={workspace} />}

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
                {!currentGateApproved && ["running", "failed", "cancelled"].includes(storyboardStep?.execution_status) && (
                  <StoryboardProgress busy={busy} clockNow={clockNow} manifest={workspace.shot_manifest} onCancel={cancelStoryboard} onRetry={compileStoryboard} step={storyboardStep} />
                )}
                {!workspace.shot_manifest && !["running", "failed", "cancelled"].includes(storyboardStep?.execution_status) && (
                  <button className="primary-button" disabled={busy} onClick={compileStoryboard} type="button">生成大纲与分镜</button>
                )}
                {workspace.shot_manifest && <StoryboardPromptEditor
                  ref={storyboardEditorRef}
                  key={projectId}
                  approved={currentGateApproved}
                  busy={busy || storyboardRunning}
                  manifest={workspace.shot_manifest}
                  targetDurationFrames={workspace.brief?.target_duration_frames}
                  onComplete={confirmStoryboard}
                  onSaved={handleStoryboardSaved}
                  outline={workspace.outline}
                  projectId={projectId}
                  request={request}
                />}
              </div>
            )}


          </div>
  );
  const stageTools = <>
            {stage.id === "editing" && <div className="skill-stage-actions-stack"><span>画面剪辑</span><button className="primary-button compact" disabled={busy} onClick={currentGateApproved && !productionTimelineChanged ? () => goToSection("audio_caption") : createPictureLock} type="button">{currentGateApproved && !productionTimelineChanged ? "继续配乐与字幕" : "确认画面，继续配乐与字幕"}</button></div>}
            {budgetPercent >= 80 && <InlineMessage tone="warning"><WarningCircle size={18} /><span>本次运行已使用预算的 {budgetPercent}%，下一次付费调用前仍会执行硬预算检查。</span></InlineMessage>}
            {stage.id === "audio_caption" && (
              <div className="skill-stage-actions-stack">
                <details className="skill-audio-details">
                  <summary>声音设置与交付检查</summary>
                <div className="skill-mix-form">
                  {productionTimeline?.background_audio_track?.enabled && <label><span>附加音轨用途</span><select value={mixDraft.backgroundAudioKind} onChange={(event) => setMixDraft((current) => ({ ...current, backgroundAudioKind: event.target.value }))}><option value="music">全片配乐</option><option value="narration">旁白</option><option value="sfx">音效</option></select></label>}
                  <label><span>实测综合响度（LUFS）</span><input placeholder="例如 -14" step="0.1" type="number" value={mixDraft.integratedLoudnessLufs} onChange={(event) => setMixDraft((current) => ({ ...current, integratedLoudnessLufs: event.target.value }))} /></label>
                  <label><span>实测真峰值（dBTP）</span><input max="-1" placeholder="不高于 -1" step="0.1" type="number" value={mixDraft.truePeakDbtp} onChange={(event) => setMixDraft((current) => ({ ...current, truePeakDbtp: event.target.value }))} /></label>
                  {productionTimeline?.background_audio_track?.enabled && <label className="skill-confirm-row"><input checked={mixDraft.rightsConfirmed} onChange={(event) => setMixDraft((current) => ({ ...current, rightsConfirmed: event.target.checked }))} type="checkbox" /><span>我确认拥有该附加音频用于当前分发渠道的权利</span></label>}
                </div>
                </details>
                <button className="primary-button compact" disabled={busy} onClick={confirmAudioCaption} type="button">{currentGateApproved && !productionTimelineChanged ? "继续到导出成片" : "确认声音与字幕，进入导出"}</button>
                {workspace.mix_revision?.validation_status === "warning" && <InlineMessage tone="warning"><WarningCircle size={18} /><span>{workspace.mix_revision.validation_messages.join("；")}</span></InlineMessage>}
              </div>
            )}
            {stage.id === "export" && (
              <div className="skill-stage-actions-stack">
                {(workspace.timeline?.exact_overlays?.length || 0) > 0 && <label className="skill-confirm-row"><input checked={mixDraft.exactOverlayConfirmed} onChange={(event) => setMixDraft((current) => ({ ...current, exactOverlayConfirmed: event.target.checked }))} type="checkbox" /><span>我已在最终导出画面中逐项确认 {workspace.timeline.exact_overlays.length} 个品牌素材叠加</span></label>}
                {!workspace.delivery_manifest && latestMatchingExport && <button className="primary-button" disabled={busy} onClick={() => confirmDelivery(latestMatchingExport)} type="button">确认成片交付</button>}
                {workspace.delivery_manifest && !currentGateApproved && <GateAction busy={busy} gate={stage.gate} label="确认最终交付包" onDecide={decideGate} relatedRevisionIds={[workspace.delivery_manifest.id]} />}
              </div>
            )}

  </>;
  const navigationSteps = skillCreationNavigation(workspace);
  const preparationStage = PREPARATION_SECTIONS.some((item) => item.id === selectedStage);
  const editingStage = ["editing", "audio_caption"].includes(selectedStage);
  const subSections = preparationStage ? PREPARATION_SECTIONS : editingStage ? [
    { id: "editing", label: "画面剪辑" }, { id: "audio_caption", label: "配乐与字幕" },
  ] : [];
  const goToSection = (section) => productionWorkspaceRef.current?.navigate(section);
  return <ProductionHub
    workspaceRef={productionWorkspaceRef}
    allowProjectCreation={false}
    analysisId={null}
    error=""
    imageGenerationSettings={lockedImageSettings}
    lockedExportResolution={workspace.run_contract.video_resolution_label}
    loading={false}
    navigationTarget={navigationTarget}
    onNotificationsChanged={onNotificationsChanged}
    onNotice={onNotice}
    onOpenModelSettings={onOpenModelSettings}
    onProjectsChanged={async () => {
      const next = await request(`/records/${project.id}/productions`);
      setProductions(next || []);
      const refreshed = await request(`/projects/${project.id}/skill-workspace`);
      setWorkspace(refreshed);
      return next || [];
    }}
    projects={productions}
    recordId={project.id}
    request={request}
    resolveUrl={resolveUrl}
    sourceMedia={{ aspectRatio: workspace.brief.output_aspect_ratio, height: workspace.run_contract.video_height, hasAudio: false, hasSourceVideo: false, width: workspace.run_contract.video_width }}
    sourceTitle={project.name}
    videoGenerationSettings={lockedVideoSettings}
    workflow={{
      section: selectedStage,
      busy,
      canNavigate: (section) => skillSectionEnabled(workspace, section),
      onSectionChange: setSelectedStage,
      productionProjectId: workspace.production_project_id,
      title: project.name,
      source: skill.name,
      subtitle: `${workspace.brief.output_aspect_ratio} · ${workspace.brief.target_duration_seconds} 秒`,
      onBack: () => navigate("/projects"),
      beforeNavigate: () => storyboardEditorRef.current?.flush() ?? true,
      resolveSection: (section) => section === "project_setup" ? resolveSkillSection(workspace, section) : section,
      steps: navigationSteps,
      imagesApproved: stageState(workspace, SKILL_WORKFLOW_STAGES[3]).approved,
      videosApproved: stageState(workspace, SKILL_WORKFLOW_STAGES[4]).approved,
      onAdvance: (section) => decideGate(section === "shot_images" ? "images_approved" : "videos_approved", "approve"),
      onTimelineChanged: setProductionTimeline,
      exportTimelineRevisionId: workspace.timeline?.source_timeline_revision_id || "",
      onExportArtifactsChanged: setExportJobs,
      preparation,
      referenceContent: <SkillProjectReferences usages={workspace.asset_usages} request={request} resolveUrl={resolveUrl} />,
      stageTools: editingStage || selectedStage === "export" ? stageTools : null,
      message: error ? <ErrorState message={error} /> : null,
      subnavigation: subSections.length > 0 && <nav className="creation-subnav" aria-label={preparationStage ? "创作方案准备" : "剪辑内容"}>
        {subSections.map((item, index) => {
          const itemStage = SKILL_WORKFLOW_STAGES.find((entry) => entry.id === item.id);
          const itemState = stageState(workspace, itemStage);
          const preceding = preparationStage && index > 0 ? stageState(workspace, SKILL_WORKFLOW_STAGES[index - 1]).approved : true;
          return <button aria-current={selectedStage === item.id ? "page" : undefined} disabled={busy || !preceding || (item.id === "audio_caption" && !stageState(workspace, SKILL_WORKFLOW_STAGES[5]).approved)} key={item.id} onClick={() => void goToSection(item.id)} type="button">{item.label}{itemState.approved && <Check size={13} />}<small>{!itemState.approved && itemState.current ? "待确认" : ""}</small></button>;
        })}
      </nav>,
      metrics: <><span>实际成本 {formatMicros(actualCostMicros)}</span><details className="creation-metrics-detail"><summary>耗时与成本</summary><div><p>本阶段 {formatDurationMs(selectedStageMetrics.total)} · {formatMicros(selectedStageMetrics.cost)}</p><p>排队 {formatDurationMs(selectedStageMetrics.queue)}</p><p>模型 {formatDurationMs(selectedStageMetrics.provider)}</p><p>后处理 {formatDurationMs(selectedStageMetrics.postprocess)}</p>{budgetPercent != null && <p>预算已使用 {budgetPercent}%</p>}</div></details></>,
    }}
  />;
}
