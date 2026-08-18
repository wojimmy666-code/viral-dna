import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowClockwise,
  CheckCircle,
  CircleNotch,
  Cpu,
  DownloadSimple,
  GraphicsCard,
  MagicWand,
} from "@phosphor-icons/react";
import "./depth-generation-settings.css";

const MODE_COPY = {
  auto: {
    title: "自动识别",
    description: "优先使用 NVIDIA CUDA；不可用时自动切换到 CPU ONNX。",
    Icon: MagicWand,
  },
  cpu: {
    title: "CPU",
    description: "逐帧 ONNX 深度推理，兼容性高，不需要独立显卡。",
    Icon: Cpu,
  },
  gpu: {
    title: "GPU",
    description: "使用 Video Depth Anything 时序模型，需要可用的 NVIDIA CUDA。",
    Icon: GraphicsCard,
  },
};

export function DepthGenerationSettings({ request }) {
  const [settings, setSettings] = useState(null);
  const [preference, setPreference] = useState("auto");
  const [busy, setBusy] = useState("loading");
  const [error, setError] = useState("");
  const [installation, setInstallation] = useState(null);

  const load = useCallback(async (probe = false) => {
    setBusy(probe ? "probing" : "loading");
    setError("");
    try {
      const next = await request(
        probe ? "/settings/depth-generation/probe" : "/settings/depth-generation",
        probe ? { method: "POST" } : undefined,
      );
      setSettings(next);
      setPreference(next.execution_preference || "auto");
    } catch (nextError) {
      setError(nextError.message || "读取深度生成设置失败");
    } finally {
      setBusy("");
    }
  }, [request]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!installation || !["queued", "running"].includes(installation.status)) return undefined;
    const timer = window.setTimeout(async () => {
      try {
        const next = await request(`/depth-controls/engines/installations/${installation.id}`);
        setInstallation(next);
        if (next.status === "succeeded") await load(true);
        if (next.status === "failed") setError(next.error || "CPU 深度引擎安装失败");
      } catch (nextError) {
        setError(nextError.message || "读取安装进度失败");
      }
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [installation, load, request]);

  const modes = useMemo(
    () => Object.fromEntries((settings?.modes || []).map((item) => [item.mode, item])),
    [settings],
  );

  async function save() {
    setBusy("saving");
    setError("");
    try {
      const next = await request("/settings/depth-generation", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ execution_preference: preference }),
      });
      setSettings(next);
      setPreference(next.execution_preference);
    } catch (nextError) {
      setError(nextError.message || "保存深度生成设置失败");
    } finally {
      setBusy("");
    }
  }

  async function installCpu() {
    setBusy("installing");
    setError("");
    try {
      const next = await request(
        "/depth-controls/engines/depth_anything_v2_onnx/installations",
        { method: "POST" },
      );
      setInstallation(next);
    } catch (nextError) {
      setError(nextError.message || "创建 CPU 深度引擎安装任务失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="settings-section depth-generation-settings" aria-labelledby="depth-generation-settings-title">
      <div className="settings-section-heading">
        <div>
          <h3 id="depth-generation-settings-title">深度视频生成</h3>
          <p>同一任务接口支持 CPU 与 GPU 两套引擎；设置只影响之后创建的新任务。</p>
        </div>
        <button
          className="secondary-button compact"
          disabled={Boolean(busy)}
          onClick={() => load(true)}
          type="button"
        >
          {busy === "probing" ? <CircleNotch className="spin" size={15} /> : <ArrowClockwise size={15} />}
          重新检测
        </button>
      </div>

      {busy === "loading" && !settings ? (
        <div className="settings-loading" role="status"><CircleNotch className="spin" size={18} />正在检测运行设备…</div>
      ) : (
        <div className="depth-mode-grid" role="radiogroup" aria-label="深度视频执行模式">
          {Object.entries(MODE_COPY).map(([mode, copy]) => {
            const status = modes[mode];
            const unavailable = mode === "gpu" && status && !status.available;
            const selected = preference === mode;
            const Icon = copy.Icon;
            return (
              <button
                aria-checked={selected}
                className={`depth-mode-option${selected ? " selected" : ""}${unavailable ? " unavailable" : ""}`}
                disabled={Boolean(busy) || unavailable}
                key={mode}
                onClick={() => setPreference(mode)}
                role="radio"
                type="button"
              >
                <span className="depth-mode-icon"><Icon size={20} weight="duotone" /></span>
                <span className="depth-mode-copy">
                  <strong>{copy.title}</strong>
                  <small>{status?.note || copy.description}</small>
                </span>
                <span className={`depth-mode-state ${status?.available ? "available" : ""}`}>
                  {status?.available ? "可用" : mode === "auto" ? "待安装" : "不可用"}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {settings?.resolved_engine && (
        <div className="depth-resolution-summary">
          <CheckCircle size={17} weight="fill" />
          <span><strong>当前解析：</strong>{settings.resolved_device_name} · {settings.resolved_engine}</span>
        </div>
      )}

      {installation && (
        <div className={`depth-installation ${installation.status}`} role="status">
          <div><span>{installation.message}</span><strong>{installation.progress_percent}%</strong></div>
          <progress max="100" value={installation.progress_percent} />
        </div>
      )}

      {error && <div className="settings-error" role="alert">{error}</div>}

      <div className="depth-settings-actions">
        {modes.cpu?.installable && (
          <button className="secondary-button compact" disabled={Boolean(busy) || installation?.status === "running"} onClick={installCpu} type="button">
            <DownloadSimple size={16} />安装 CPU 模型
          </button>
        )}
        <button className="primary-button compact" disabled={Boolean(busy) || !settings || preference === settings.execution_preference} onClick={save} type="button">
          {busy === "saving" ? <CircleNotch className="spin" size={16} /> : <CheckCircle size={16} />}
          应用深度设置
        </button>
      </div>
    </section>
  );
}
