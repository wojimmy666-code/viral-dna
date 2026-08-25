import { useCallback, useEffect, useState } from "react";
import {
  ArrowClockwise,
  CheckCircle,
  CircleNotch,
  DownloadSimple,
  MagicWand,
} from "@phosphor-icons/react";
import "./video-enhancement-settings.css";

export function VideoEnhancementSettings({ request }) {
  const [settings, setSettings] = useState(null);
  const [target, setTarget] = useState("1080p");
  const [busy, setBusy] = useState("loading");
  const [error, setError] = useState("");
  const [installation, setInstallation] = useState(null);

  const load = useCallback(async (probe = false) => {
    if (!request) return;
    setBusy(probe ? "probing" : "loading");
    setError("");
    try {
      const next = await request(
        probe
          ? "/settings/video-enhancement/probe"
          : "/settings/video-enhancement",
        probe ? { method: "POST" } : undefined,
      );
      setSettings(next);
      setTarget(next.default_target || "1080p");
    } catch (nextError) {
      setError(nextError.message || "读取视频清晰化设置失败");
    } finally {
      setBusy("");
    }
  }, [request]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!installation || !["queued", "running"].includes(installation.status)) {
      return undefined;
    }
    const timer = window.setTimeout(async () => {
      try {
        const next = await request(
          `/video-enhancements/engine/installations/${installation.id}`,
        );
        setInstallation(next);
        if (["succeeded", "failed"].includes(next.status)) await load(true);
        if (next.status === "failed") {
          setError(next.error || "Real-ESRGAN 快速引擎安装失败");
        }
      } catch (nextError) {
        setError(nextError.message || "读取引擎安装进度失败");
      }
    }, 900);
    return () => window.clearTimeout(timer);
  }, [installation, load, request]);

  async function save() {
    setBusy("saving");
    setError("");
    try {
      const next = await request("/settings/video-enhancement", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ default_target: target }),
      });
      setSettings(next);
      setTarget(next.default_target);
    } catch (nextError) {
      setError(nextError.message || "保存视频清晰化设置失败");
    } finally {
      setBusy("");
    }
  }

  async function install() {
    setBusy("installing");
    setError("");
    try {
      const next = await request("/video-enhancements/engine/installations", {
        method: "POST",
      });
      setInstallation(next);
    } catch (nextError) {
      setError(nextError.message || "创建引擎安装任务失败");
    } finally {
      setBusy("");
    }
  }

  const installing = ["queued", "running"].includes(installation?.status);

  return (
    <section className="video-enhancement-settings" aria-labelledby="video-enhancement-settings-title">
      <header>
        <div>
          <h3 id="video-enhancement-settings-title"><MagicWand size={18} />视频 AI 清晰化</h3>
          <p>已采用的低清候选可在本地提升到 1080p 或 4K，不消耗视频生成额度。</p>
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
      </header>

      {busy === "loading" && !settings ? (
        <div className="video-enhancement-settings-loading" role="status">
          <CircleNotch className="spin" size={17} />正在检测本地引擎
        </div>
      ) : settings && (
        <div className="video-enhancement-settings-grid">
          <label className="settings-field">
            <span>默认输出</span>
            <select
              disabled={Boolean(busy)}
              onChange={(event) => setTarget(event.target.value)}
              value={target}
            >
              <option value="1080p">1080p（推荐）</option>
              <option value="4k">4K</option>
            </select>
          </label>
          <dl>
            <div><dt>引擎</dt><dd>Real-ESRGAN 快速</dd></div>
            <div><dt>设备</dt><dd>自动选择 Vulkan</dd></div>
            <div><dt>并发</dt><dd>1 个本地任务</dd></div>
          </dl>
        </div>
      )}

      {settings && (
        <div className={`video-enhancement-engine-state ${settings.capability.available ? "available" : "missing"}`}>
          {settings.capability.available
            ? <CheckCircle size={17} weight="fill" />
            : <DownloadSimple size={17} />}
          <span>
            <strong>{settings.capability.available ? "本地引擎可用" : "本地引擎未安装"}</strong>
            <small>{settings.capability.availability_note}</small>
            <small
              className="video-enhancement-install-path"
              title={settings.capability.installation_path}
            >安装位置：<code>{settings.capability.installation_path}</code></small>
          </span>
          {!settings.capability.available && settings.capability.installable && (
            <button
              className="secondary-button compact"
              disabled={Boolean(busy) || installing}
              onClick={install}
              type="button"
            >
              {installing ? <CircleNotch className="spin" size={15} /> : <DownloadSimple size={15} />}
              {installing ? "安装中" : "安装引擎"}
            </button>
          )}
        </div>
      )}

      {installation && (
        <div className="video-enhancement-settings-progress" role="status">
          <div><span>{installation.message}</span><strong>{installation.progress_percent}%</strong></div>
          <progress max="100" value={installation.progress_percent} />
        </div>
      )}

      {error && <p className="settings-page-error" role="alert">{error}</p>}

      {settings && (
        <footer>
          <span>4K 更耗时；480p 放大不会产生原生 4K 细节。</span>
          <button
            className="primary-button compact"
            disabled={Boolean(busy) || target === settings.default_target}
            onClick={save}
            type="button"
          >保存清晰化设置</button>
        </footer>
      )}
    </section>
  );
}
