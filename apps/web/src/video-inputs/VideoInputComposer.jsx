import {
  CheckCircle,
  FolderOpen,
  IdentificationCard,
  ImageSquare,
  Stack,
  TextT,
  VideoCamera,
} from "@phosphor-icons/react";
import "./video-input-composer.css";

const INPUTS = [
  {
    id: "approved_images",
    label: "分镜图片",
    description: "使用已确认画面控制构图与动作",
    icon: ImageSquare,
  },
  {
    id: "project_assets",
    label: "项目资产",
    description: "使用人物、场景、服装或产品图片",
    icon: FolderOpen,
  },
  {
    id: "provider_managed_assets",
    label: "托管人物",
    description: "使用 Seedance 等 Provider 的虚拟演员",
    icon: IdentificationCard,
  },
  {
    id: "reference_video",
    label: "动作/参考视频",
    description: "模型支持时提供动作或镜头参考",
    icon: VideoCamera,
  },
  {
    id: "depth_control",
    label: "深度控制",
    description: "可选的动作、空间与遮挡结构",
    icon: Stack,
  },
];

function sourceSupported(capabilities, source) {
  if (!capabilities) return false;
  if (Array.isArray(capabilities.supported_input_sources)) {
    return capabilities.supported_input_sources.includes(source);
  }
  if (["approved_images", "project_assets"].includes(source)) {
    return Boolean(capabilities.image_to_video);
  }
  if (source === "provider_managed_assets") {
    return Boolean(capabilities.managed_assets?.supported);
  }
  if (source === "reference_video") return Boolean(capabilities.reference_video);
  if (source === "depth_control") {
    return Boolean(
      capabilities.depth_control_video
      || capabilities.reference_route?.supports_depth_control_video,
    );
  }
  return false;
}

export function VideoInputComposer({
  managedAssetBinding,
  model,
  onChange,
  onOpenManagedAssets,
  projectAssetCount = 0,
  referenceFrameCount = 0,
  selectedSources = [],
}) {
  const selected = new Set(selectedSources);
  const capabilities = model?.capabilities || {};
  const textOnly = selected.size === 0;

  function toggle(source) {
    if (selected.has(source)) {
      const next = new Set(selected);
      next.delete(source);
      onChange?.([...next]);
      return;
    }
    if (!sourceSupported(capabilities, source)) return;
    if (source === "provider_managed_assets" && !managedAssetBinding) {
      onOpenManagedAssets?.();
      return;
    }
    const next = new Set(selected);
    if (next.has(source)) next.delete(source);
    else next.add(source);
    onChange?.([...next]);
  }

  return (
    <section className="video-input-composer" aria-label="生成输入">
      <header>
        <div>
          <strong>生成输入</strong>
          <span>提示词始终使用；图片、资产、参考视频和深度均为可选</span>
        </div>
        <span className="video-input-mode-label">
          {textOnly ? "文生视频" : `${selected.size} 项媒体输入`}
        </span>
      </header>

      <div className="video-input-grid">
        <article className="video-input-card selected static" aria-label="提示词已启用">
          <span className="video-input-icon"><TextT size={20} /></span>
          <div><strong>提示词</strong><small>必选 · 生成前自动保存</small></div>
          <CheckCircle size={18} weight="fill" />
        </article>
        {INPUTS.map((item) => {
          const Icon = item.icon;
          const supported = sourceSupported(capabilities, item.id);
          const active = selected.has(item.id);
          let detail = item.description;
          if (item.id === "approved_images") detail = `${referenceFrameCount} 张已确认画面`;
          if (item.id === "project_assets") detail = `${projectAssetCount} 项已关联图片资产`;
          if (item.id === "provider_managed_assets" && managedAssetBinding) {
            detail = managedAssetBinding.name;
          }
          return (
            <button
              aria-pressed={active}
              className={`video-input-card${active ? " selected" : ""}`}
              disabled={!supported && !active}
              key={item.id}
              onClick={() => toggle(item.id)}
              title={supported ? item.description : "当前模型不支持此输入"}
              type="button"
            >
              <span className="video-input-icon"><Icon size={20} /></span>
              <span><strong>{item.label}</strong><small>{supported ? detail : "当前模型不支持"}</small></span>
              {active && <CheckCircle size={18} weight="fill" />}
            </button>
          );
        })}
      </div>
      <p className="video-input-audio-note">音频不参与模型生成输入；原声、配乐和音量统一在视频剪辑阶段处理。</p>
    </section>
  );
}
