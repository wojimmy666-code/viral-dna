import { forwardRef, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwise,
  Bell,
  BracketsCurly,
  CaretDown,
  CaretRight,
  ChartBar,
  Check,
  CheckCircle,
  CircleNotch,
  ClockCounterClockwise,
  Copy,
  DownloadSimple,
  FileVideo,
  FilmStrip,
  Gear,
  LinkSimple,
  ListBullets,
  LockSimple,
  MagnifyingGlass,
  MagicWand,
  Pause,
  Play,
  Plus,
  Question,
  ShieldCheck,
  Sparkle,
  SquaresFour,
  Swap,
  Target,
  TextT,
  UploadSimple,
  VideoCamera,
  X,
} from "@phosphor-icons/react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

const stageLabels = {
  queued: "排队中",
  ingesting: "读取来源",
  preprocessing: "媒体预处理",
  segmenting: "分镜检测",
  transcribing: "语音与字幕",
  understanding: "画面理解",
  reasoning: "爆点分析",
  compiling_prompts: "提示词编译",
  validating: "结果校验",
  completed: "已完成",
  failed: "失败",
};

const navItems = [
  { id: "workspace", label: "工作台", icon: SquaresFour },
  { id: "new-analysis", label: "新建分析", icon: Plus },
  { id: "history", label: "分析记录", icon: ClockCounterClockwise },
  { id: "templates", label: "提示词模板", icon: BracketsCurly },
];

const reportTabs = [
  { id: "overview", label: "总览", icon: ChartBar },
  { id: "shots", label: "分镜拆解", icon: FilmStrip },
  { id: "viral", label: "爆点分析", icon: Target },
  { id: "replace", label: "元素替换", icon: Swap },
  { id: "prompts", label: "提示词", icon: TextT },
];

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(payload?.detail || "请求失败，请稍后重试");
  }
  return payload;
}

function formatTime(seconds = 0) {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.max(0, seconds - minutes * 60);
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
}

function resolveArtifactUrl(path) {
  if (!path || /^https?:\/\//i.test(path) || !API_BASE.startsWith("http")) return path || "";
  return new URL(path, API_BASE).toString();
}

function resolveApiUrl(path) {
  return `${API_BASE.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;
}

function useFilePreview(file) {
  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : ""), [file]);
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);
  return previewUrl;
}

export function App() {
  const [activeNav, setActiveNav] = useState("workspace");
  const [sourceMode, setSourceMode] = useState("link");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState(null);
  const [targetModel, setTargetModel] = useState("seedance");
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [video, setVideo] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [report, setReport] = useState(null);
  const [activeReportTab, setActiveReportTab] = useState("overview");
  const [activeShotId, setActiveShotId] = useState(null);
  const [replacementVersion, setReplacementVersion] = useState(null);
  const [notice, setNotice] = useState("");
  const eventSourceRef = useRef(null);
  const importSectionRef = useRef(null);
  const reportSectionRef = useRef(null);
  const videoRef = useRef(null);
  const filePreview = useFilePreview(file);

  useEffect(() => {
    return () => eventSourceRef.current?.close();
  }, []);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = window.setTimeout(() => setNotice(""), 2200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  function selectNav(id) {
    setActiveNav(id);
    if (id === "new-analysis") {
      importSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  async function pollAnalysis(analysisId) {
    for (let index = 0; index < 60; index += 1) {
      const next = await apiRequest(`/analyses/${analysisId}`);
      setAnalysis(next);
      if (next.stage === "completed") {
        await loadReport(next.video_id);
        return;
      }
      if (next.stage === "failed") {
        setError(next.error?.message || next.message || "分析失败");
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    }
    setError("分析仍在后台运行，请稍后刷新状态");
  }

  function connectToProgress(analysisId) {
    eventSourceRef.current?.close();
    const source = new EventSource(`${API_BASE}/analyses/${analysisId}/events`);
    eventSourceRef.current = source;
    source.addEventListener("progress", async (event) => {
      const next = JSON.parse(event.data);
      setAnalysis(next);
      if (next.stage === "completed") {
        source.close();
        await loadReport(next.video_id);
      }
      if (next.stage === "failed") {
        setError(next.error?.message || next.message || "分析失败");
        source.close();
      }
    });
    source.onerror = () => {
      source.close();
      pollAnalysis(analysisId).catch((requestError) => setError(requestError.message));
    };
  }

  async function loadReport(videoId) {
    const [nextReport, processedVideo] = await Promise.all([
      apiRequest(`/videos/${videoId}/report`),
      apiRequest(`/videos/${videoId}`),
    ]);
    setReport(nextReport);
    setVideo(processedVideo);
    setActiveShotId(nextReport.shots[0]?.id || null);
    setActiveReportTab("overview");
    window.setTimeout(() => {
      reportSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 120);
  }

  async function startAnalysis() {
    setError("");
    setNotice("");
    if (!rightsConfirmed) {
      setError("请先确认拥有视频分析和使用权限");
      return;
    }
    if (sourceMode === "link" && !url.trim()) {
      setError("请粘贴抖音或小红书公开链接");
      return;
    }
    if (sourceMode === "file" && !file) {
      setError("请选择一个视频文件");
      return;
    }

    setSubmitting(true);
    setReport(null);
    setReplacementVersion(null);
    setAnalysis(null);
    try {
      let createdVideo;
      if (sourceMode === "link") {
        createdVideo = await apiRequest("/videos/link", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: url.trim(),
            target_model: targetModel,
            rights_confirmed: true,
          }),
        });
      } else {
        const form = new FormData();
        form.append("file", file);
        form.append("title", file.name.replace(/\.[^.]+$/, ""));
        form.append("target_model", targetModel);
        form.append("rights_confirmed", "true");
        createdVideo = await apiRequest("/videos/upload", { method: "POST", body: form });
      }

      setVideo(createdVideo);
      const createdAnalysis = await apiRequest(`/videos/${createdVideo.id}/analyses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ granularity: "fine", include_audio: true, include_ocr: true }),
      });
      setAnalysis(createdAnalysis);
      connectToProgress(createdAnalysis.id);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  function seekToShot(shot) {
    setActiveShotId(shot.id);
    if (videoRef.current && Number.isFinite(shot.start_seconds)) {
      videoRef.current.currentTime = shot.start_seconds;
      videoRef.current.play().catch(() => undefined);
    }
  }

  const currentPromptPackage = replacementVersion?.prompt_package || report?.prompt_package;

  async function copyText(text, message = "已复制") {
    await navigator.clipboard.writeText(text);
    setNotice(message);
  }

  function downloadPromptPackage() {
    if (!currentPromptPackage) return;
    const blob = new Blob([JSON.stringify(currentPromptPackage, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `viral-dna-prompt-v${currentPromptPackage.version}.json`;
    anchor.click();
    URL.revokeObjectURL(href);
    setNotice("提示词包已下载");
  }

  return (
    <div className="app-shell">
      <Sidebar activeNav={activeNav} onSelect={selectNav} />

      <div className="app-body">
        <Topbar onCreate={() => selectNav("new-analysis")} />

        <div className="workspace-layout">
          <main className="workspace-main">
            <section className="page-intro">
              <div>
                <div className="breadcrumb">
                  <span>工作台</span>
                  <CaretRight size={14} />
                  <span className="breadcrumb-current">单视频拆解</span>
                </div>
                <h1>把一个视频拆成可复用的创作指令</h1>
                <p>识别分镜、主体、服装、场景和爆点，输出可编辑的复刻提示词包。</p>
              </div>
              <div className="intro-status">
                <ShieldCheck size={17} weight="fill" />
                Phase 1 · 单视频模式
              </div>
            </section>

            <ImportPanel
              ref={importSectionRef}
              sourceMode={sourceMode}
              setSourceMode={setSourceMode}
              url={url}
              setUrl={setUrl}
              file={file}
              setFile={setFile}
              targetModel={targetModel}
              setTargetModel={setTargetModel}
              rightsConfirmed={rightsConfirmed}
              setRightsConfirmed={setRightsConfirmed}
              submitting={submitting}
              error={error}
              onStart={startAnalysis}
            />

            {analysis && analysis.stage !== "completed" && (
              <AnalysisProgress analysis={analysis} video={video} />
            )}

            {!analysis && !report && <EmptyWorkspace />}

            {report && (
              <section className="report-card" ref={reportSectionRef}>
                <ReportHeader
                  video={video}
                  report={report}
                  promptPackage={currentPromptPackage}
                  onDownload={downloadPromptPackage}
                  onRestart={() => selectNav("new-analysis")}
                />
                <ReportTabs active={activeReportTab} onChange={setActiveReportTab} mode={report.analysis_mode} />
                <div className="report-content">
                  {activeReportTab === "overview" && (
                    <OverviewTab
                      report={report}
                      filePreview={filePreview}
                      videoRef={videoRef}
                      onOpenShots={() => setActiveReportTab("shots")}
                    />
                  )}
                  {activeReportTab === "shots" && (
                    <ShotsTab
                      shots={report.shots}
                      activeShotId={activeShotId}
                      onSelect={seekToShot}
                      analysisMode={report.analysis_mode}
                      onCopy={copyText}
                    />
                  )}
                  {activeReportTab === "viral" && <ViralTab report={report} />}
                  {activeReportTab === "replace" && (
                    <ReplacementTab
                      videoId={report.video_id}
                      entities={report.entities}
                      replacementVersion={replacementVersion}
                      onCreated={setReplacementVersion}
                      onError={setError}
                    />
                  )}
                  {activeReportTab === "prompts" && (
                    <PromptsTab
                      promptPackage={currentPromptPackage}
                      onCopy={copyText}
                      onDownload={downloadPromptPackage}
                    />
                  )}
                </div>
              </section>
            )}
          </main>

          <InsightsPanel report={report} analysis={analysis} onOpenTab={setActiveReportTab} />
        </div>
      </div>

      {notice && (
        <div className="toast" role="status">
          <CheckCircle size={18} weight="fill" />
          {notice}
        </div>
      )}
    </div>
  );
}

function Sidebar({ activeNav, onSelect }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">
          <Play size={18} weight="fill" />
        </span>
        <span>
          <strong>ViralDNA</strong>
          <small>视频逆向拆解系统</small>
        </span>
      </div>

      <nav className="side-nav" aria-label="主导航">
        <p className="nav-section-label">创作研究</p>
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={`nav-item ${activeNav === item.id ? "active" : ""}`}
              key={item.id}
              onClick={() => onSelect(item.id)}
              type="button"
            >
              <Icon size={18} weight={activeNav === item.id ? "fill" : "regular"} />
              <span>{item.label}</span>
              {item.id === "history" && <span className="nav-count">0</span>}
            </button>
          );
        })}

        <div className="nav-divider" />
        <p className="nav-section-label">系统</p>
        <button className="nav-item" type="button">
          <Gear size={18} />
          <span>模型与设置</span>
        </button>
      </nav>

      <div className="sidebar-footer">
        <span className="environment-icon">
          <ShieldCheck size={18} />
        </span>
        <span>
          <strong>内测环境</strong>
          <small>混合分析引擎已启用</small>
        </span>
      </div>
    </aside>
  );
}

function Topbar({ onCreate }) {
  return (
    <header className="topbar">
      <div className="global-search">
        <MagnifyingGlass size={18} />
        <input aria-label="搜索分析记录" placeholder="搜索视频或报告" />
        <kbd>⌘ K</kbd>
      </div>
      <div className="topbar-actions">
        <button className="icon-button" type="button" aria-label="通知">
          <Bell size={19} />
          <span className="notification-dot" />
        </button>
        <button className="icon-button" type="button" aria-label="帮助">
          <Question size={19} />
        </button>
        <button className="primary-button compact" type="button" onClick={onCreate}>
          <Plus size={17} weight="bold" />
          新建分析
        </button>
      </div>
    </header>
  );
}

const ImportPanel = forwardRef(function ImportPanel({
  sourceMode,
  setSourceMode,
  url,
  setUrl,
  file,
  setFile,
  targetModel,
  setTargetModel,
  rightsConfirmed,
  setRightsConfirmed,
  submitting,
  error,
  onStart,
}, ref) {
  return (
    <section className="import-card" id="new-analysis" ref={ref}>
      <div className="card-heading">
        <div>
          <span className="eyebrow">新建任务</span>
          <h2>导入一个短视频</h2>
          <p>支持本地文件，以及公开的抖音、小红书视频链接。</p>
        </div>
        <span className="supported-formats">MP4 · MOV · WebM · 最长 5 分钟</span>
      </div>

      <div className="source-tabs" role="tablist" aria-label="视频来源">
        <button
          type="button"
          className={sourceMode === "link" ? "active" : ""}
          onClick={() => setSourceMode("link")}
          role="tab"
          aria-selected={sourceMode === "link"}
        >
          <LinkSimple size={17} />
          视频链接
        </button>
        <button
          type="button"
          className={sourceMode === "file" ? "active" : ""}
          onClick={() => setSourceMode("file")}
          role="tab"
          aria-selected={sourceMode === "file"}
        >
          <UploadSimple size={17} />
          本地文件
        </button>
      </div>

      {sourceMode === "link" ? (
        <div className="link-input-row">
          <div className="input-with-icon">
            <LinkSimple size={19} />
            <input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="粘贴抖音或小红书公开分享链接"
              aria-label="视频链接"
            />
            {url && (
              <button type="button" onClick={() => setUrl("")} aria-label="清空链接">
                <X size={16} />
              </button>
            )}
          </div>
          <p className="link-ingestion-hint">
            <DownloadSimple size={15} />
            系统会采集公开源视频并进入真实分镜流程；平台验证、私密或失效链接会明确报错。
          </p>
        </div>
      ) : (
        <label className={`upload-dropzone ${file ? "has-file" : ""}`}>
          <input
            type="file"
            accept="video/mp4,video/quicktime,video/webm"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
          <span className="upload-icon">
            {file ? <FileVideo size={26} weight="fill" /> : <UploadSimple size={26} />}
          </span>
          {file ? (
            <span>
              <strong>{file.name}</strong>
              <small>{(file.size / 1024 / 1024).toFixed(1)} MB · 点击重新选择</small>
            </span>
          ) : (
            <span>
              <strong>点击选择或拖入视频文件</strong>
              <small>单个文件不超过 500 MB</small>
            </span>
          )}
        </label>
      )}

      <div className="import-options">
        <label className="field-group">
          <span>目标提示词模型</span>
          <span className="select-wrap">
            <select value={targetModel} onChange={(event) => setTargetModel(event.target.value)}>
              <option value="seedance">Seedance</option>
              <option value="generic">通用视频模型</option>
            </select>
            <CaretDown size={15} />
          </span>
        </label>
        <label className="rights-check">
          <input
            type="checkbox"
            checked={rightsConfirmed}
            onChange={(event) => setRightsConfirmed(event.target.checked)}
          />
          <span className="checkbox-visual">{rightsConfirmed && <Check size={13} weight="bold" />}</span>
          <span>我确认拥有该视频的分析、复刻和素材使用权限</span>
        </label>
      </div>

      {error && (
        <div className="inline-error" role="alert">
          <X size={17} weight="bold" />
          {error}
        </div>
      )}

      <div className="import-actions">
        <button className="primary-button" type="button" onClick={() => onStart()} disabled={submitting}>
          {submitting ? <CircleNotch className="spin" size={18} /> : <Sparkle size={18} weight="fill" />}
          {submitting ? "正在创建任务" : "开始精细拆解"}
        </button>
      </div>
    </section>
  );
});

function AnalysisProgress({ analysis, video }) {
  const stages = [
    "ingesting",
    "preprocessing",
    "segmenting",
    "transcribing",
    "understanding",
    "reasoning",
    "compiling_prompts",
    "validating",
  ];
  const activeIndex = stages.indexOf(analysis.stage);
  return (
    <section className={`progress-card ${analysis.stage === "failed" ? "failed" : ""}`} aria-live="polite">
      <div className="progress-header">
        <span className="progress-icon">
          {analysis.stage === "failed" ? (
            <X size={22} weight="bold" />
          ) : (
            <CircleNotch className="spin" size={22} />
          )}
        </span>
        <div>
          <span className="eyebrow">分析任务</span>
          <h2>{video?.title || "正在拆解视频"}</h2>
          <p>{analysis.message}</p>
        </div>
        <strong>{analysis.progress}%</strong>
      </div>
      <div className="progress-track">
        <span style={{ width: `${analysis.progress}%` }} />
      </div>
      <div className="stage-list">
        {stages.map((stage, index) => {
          const isDone = index < activeIndex;
          const isActive = index === activeIndex;
          return (
            <div className={`${isDone ? "done" : ""} ${isActive ? "active" : ""}`} key={stage}>
              <span>{isDone ? <Check size={12} weight="bold" /> : index + 1}</span>
              <small>{stageLabels[stage]}</small>
            </div>
          );
        })}
      </div>
      {analysis.simulated && (
        <div className="simulation-note">
          <ShieldCheck size={16} />
          当前服务运行在模拟分析模式，不会下载或处理真实媒体。
        </div>
      )}
      {!analysis.simulated && analysis.stage !== "failed" && (
        <div className="evidence-note compact">
          <ShieldCheck size={16} weight="fill" />
          {video?.source_type === "upload"
            ? "正在从真实视频提取编码信息、镜头边界、关键帧和音频证据，不生成虚构语义结果。"
            : "正在解析平台链接并下载源视频；下载完成后会继续提取真实镜头、关键帧和音频证据。"}
        </div>
      )}
    </section>
  );
}

function EmptyWorkspace() {
  return (
    <section className="empty-workspace">
      <span className="empty-icon">
        <VideoCamera size={30} />
      </span>
      <div>
        <h2>分析结果会在这里展开</h2>
        <p>上传视频文件或粘贴公开平台链接后，可以查看真实镜头时间线、关键帧和媒体证据。</p>
      </div>
    </section>
  );
}

function ReportHeader({ video, report, promptPackage, onDownload, onRestart }) {
  return (
    <div className="report-header">
      <div className="report-title-wrap">
        <span className="report-video-icon">
          <FileVideo size={21} weight="fill" />
        </span>
        <div>
          <div className="report-title-line">
            <h2>{video?.title || "视频拆解报告"}</h2>
            {report.analysis_mode === "simulated" && <span className="simulation-badge">模拟分析</span>}
            {report.analysis_mode === "media_evidence" && (
              <span className="evidence-badge">真实媒体证据</span>
            )}
          </div>
          {report.analysis_mode === "media_evidence" ? (
            <p>{report.shots.length} 个真实镜头 · FFmpeg 证据层 · 语义分析待接入</p>
          ) : (
            <p>
              {report.shots.length} 个镜头 · {report.entities.length} 个可替换元素 · Prompt v{promptPackage.version}
            </p>
          )}
        </div>
      </div>
      <div className="report-actions">
        <button className="secondary-button compact" type="button" onClick={onRestart}>
          <ArrowClockwise size={16} />
          新任务
        </button>
        <button
          className="primary-button compact"
          type="button"
          onClick={
            report.analysis_mode === "media_evidence"
              ? () => window.open(resolveArtifactUrl(report.media_evidence?.manifest_url), "_blank")
              : onDownload
          }
        >
          <DownloadSimple size={16} />
          {report.analysis_mode === "media_evidence" ? "证据清单" : "导出"}
        </button>
      </div>
    </div>
  );
}

function ReportTabs({ active, onChange, mode }) {
  const visibleTabs = mode === "media_evidence" ? reportTabs.slice(0, 2) : reportTabs;
  return (
    <div className="report-tabs" role="tablist" aria-label="分析报告">
      {visibleTabs.map((tab) => {
        const Icon = tab.icon;
        return (
          <button
            type="button"
            key={tab.id}
            className={active === tab.id ? "active" : ""}
            onClick={() => onChange(tab.id)}
            role="tab"
            aria-selected={active === tab.id}
          >
            <Icon size={17} weight={active === tab.id ? "fill" : "regular"} />
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

function VideoPlayer({ src, videoRef, fallbackDuration, downloadUrl }) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(fallbackDuration || 0);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    const player = videoRef.current;
    if (player) {
      player.pause();
      player.currentTime = 0;
    }
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(fallbackDuration || 0);
    setLoadError(false);
  }, [fallbackDuration, src, videoRef]);

  function syncDuration(player) {
    if (Number.isFinite(player.duration) && player.duration > 0) {
      setDuration(player.duration);
    }
  }

  function togglePlayback() {
    const player = videoRef.current;
    if (!player) return;
    if (player.paused || player.ended) {
      player.play().catch(() => setLoadError(true));
    } else {
      player.pause();
    }
  }

  function seekVideo(event) {
    const player = videoRef.current;
    const nextTime = Number(event.target.value);
    setCurrentTime(nextTime);
    if (player && Number.isFinite(nextTime)) {
      player.currentTime = nextTime;
    }
  }

  const resolvedDuration = duration > 0 ? duration : fallbackDuration || 0;
  const progressValue = Math.min(currentTime, resolvedDuration || 0);

  return (
    <div className="video-player">
      <div className="video-stage">
        <video
          ref={videoRef}
          src={src}
          playsInline
          preload="metadata"
          onClick={togglePlayback}
          onLoadedMetadata={(event) => syncDuration(event.currentTarget)}
          onDurationChange={(event) => syncDuration(event.currentTarget)}
          onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={() => setIsPlaying(false)}
          onError={() => setLoadError(true)}
        />
        {!isPlaying && !loadError && (
          <button
            className="video-center-play"
            type="button"
            aria-label="播放视频"
            onClick={togglePlayback}
          >
            <Play size={28} weight="fill" />
          </button>
        )}
        {loadError && <span className="video-load-error">视频加载失败，可尝试下载后播放</span>}
      </div>
      <div className="video-controls">
        <button
          className="video-control-button"
          type="button"
          aria-label={isPlaying ? "暂停视频" : "播放视频"}
          title={isPlaying ? "暂停" : "播放"}
          onClick={togglePlayback}
          disabled={loadError}
        >
          {isPlaying ? <Pause size={17} weight="fill" /> : <Play size={17} weight="fill" />}
        </button>
        <span className="video-time">{formatTime(currentTime)}</span>
        <input
          className="video-progress"
          type="range"
          min="0"
          max={Math.max(resolvedDuration, 0.1)}
          step="0.1"
          value={progressValue}
          aria-label="视频进度"
          aria-valuetext={`${formatTime(currentTime)} / ${formatTime(resolvedDuration)}`}
          onChange={seekVideo}
          disabled={loadError || resolvedDuration <= 0}
        />
        <span className="video-time">{formatTime(resolvedDuration)}</span>
        <a className="video-download-button" href={downloadUrl} download>
          <DownloadSimple size={16} />
          下载视频
        </a>
      </div>
    </div>
  );
}

function OverviewTab({ report, filePreview, videoRef, onOpenShots }) {
  const overview = report.overview;
  const evidence = report.media_evidence;
  const timeline = report.evidence_timeline;
  const metadata = evidence?.metadata;
  const isMediaEvidence = report.analysis_mode === "media_evidence";
  const mediaAvailable = isMediaEvidence || Boolean(filePreview);
  const playbackUrl =
    filePreview ||
    (isMediaEvidence
      ? resolveApiUrl(`/videos/${report.video_id}/media`)
      : resolveArtifactUrl(evidence?.proxy_url));
  const downloadUrl = mediaAvailable
    ? resolveApiUrl(`/videos/${report.video_id}/download`)
    : "";
  return (
    <div className="overview-grid">
      <div className="overview-primary">
        {playbackUrl ? (
          <VideoPlayer
            src={playbackUrl}
            videoRef={videoRef}
            fallbackDuration={overview.duration_seconds}
            downloadUrl={downloadUrl}
          />
        ) : (
          <div className="video-stage">
            <div className="video-empty-state">
              <span>
                <Play size={25} weight="fill" />
              </span>
              <strong>暂无可播放视频</strong>
              <small>当前报告没有关联的源视频文件</small>
            </div>
          </div>
        )}

        <div className="section-block">
          <span className="eyebrow">{isMediaEvidence ? "媒体证据概览" : "视频概览"}</span>
          <h3>{overview.summary}</h3>
          <p>{overview.narrative_structure}</p>
          <div className="tag-row">
            <span>{overview.content_type}</span>
            <span>{overview.aspect_ratio}</span>
            <span>{overview.visual_style.split("、")[0]}</span>
          </div>
        </div>

        <div className="structure-strip">
          {overview.narrative_structure.split("→").map((part, index, parts) => (
            <div key={part.trim()}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{part.trim()}</strong>
              {index < parts.length - 1 && <CaretRight size={15} />}
            </div>
          ))}
        </div>
      </div>

      <aside className="overview-sidebar">
        {isMediaEvidence ? (
          <div className="media-evidence-card">
            <span className="media-evidence-icon">
              <ShieldCheck size={20} weight="fill" />
            </span>
            <div>
              <span className="eyebrow">真实媒体已验证</span>
              <strong>
                {metadata?.width} × {metadata?.height} · {metadata?.fps?.toFixed(2)} FPS
              </strong>
              <p>编码、时长、分镜和关键帧均来自真实源视频，不包含模型臆测。</p>
            </div>
          </div>
        ) : (
          <div className="score-card">
            <span className="eyebrow">内容爆点潜力</span>
            <div className="score-value">
              <strong>{overview.viral_potential_score}</strong>
              <span>/100</span>
            </div>
            <div className="score-track">
              <span style={{ width: `${overview.viral_potential_score}%` }} />
            </div>
            <p>基于视频内容结构的启发式评分，不代表真实平台播放表现。</p>
          </div>
        )}
        <dl className="overview-facts">
          <div>
            <dt>时长</dt>
            <dd>{overview.duration_seconds.toFixed(1)} 秒</dd>
          </div>
          <div>
            <dt>镜头</dt>
            <dd>{report.shots.length} 个</dd>
          </div>
          {isMediaEvidence ? (
            <>
              <div>
                <dt>视频编码</dt>
                <dd>{metadata?.video_codec?.toUpperCase() || "—"}</dd>
              </div>
              <div>
                <dt>音轨</dt>
                <dd>{metadata?.has_audio ? metadata.audio_codec?.toUpperCase() : "无"}</dd>
              </div>
            </>
          ) : (
            <>
              <div>
                <dt>主体元素</dt>
                <dd>{report.entities.length} 个</dd>
              </div>
              <div>
                <dt>分析置信度</dt>
                <dd>{Math.round(overview.confidence * 100)}%</dd>
              </div>
            </>
          )}
        </dl>
        <div className="audience-card">
          <span className="eyebrow">{isMediaEvidence ? "语义分析状态" : "受众推断"}</span>
          {isMediaEvidence ? (
            <>
              <p>
                {timeline
                  ? `统一证据时间线已生成：${timeline.transcript_segments.length} 条转写、${timeline.ocr_observations.length} 条 OCR；VLM、爆点判断和复刻提示词待下一批接入。`
                  : "当前是旧版媒体报告，ASR、OCR 和多模态语义分析尚未运行。"}
              </p>
              {timeline?.provider_runs?.length > 0 && (
                <div className="provider-status-list" aria-label="证据 Provider 状态">
                  {timeline.provider_runs.map((run) => (
                    <span className={`provider-status ${run.status}`} key={run.kind}>
                      <strong>{run.kind.toUpperCase()}</strong>
                      {run.status === "completed"
                        ? `完成 · ${run.item_count} 条`
                        : run.status === "skipped"
                          ? "未配置"
                          : run.status === "unavailable"
                            ? "不可用"
                            : "失败"}
                    </span>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p>{overview.audience_inference}</p>
          )}
          {isMediaEvidence && metadata?.sha256 && (
            <code className="media-hash">SHA-256 {metadata.sha256.slice(0, 12)}…</code>
          )}
        </div>
        <button className="secondary-button full" type="button" onClick={onOpenShots}>
          {isMediaEvidence ? "查看真实分镜证据" : "查看逐镜头拆解"}
          <CaretRight size={16} />
        </button>
      </aside>
    </div>
  );
}

function ShotsTab({ shots, activeShotId, onSelect, onCopy, analysisMode }) {
  const activeShot = shots.find((shot) => shot.id === activeShotId) || shots[0];
  const isMediaEvidence = analysisMode === "media_evidence";
  return (
    <div className="shots-layout">
      <div className="shot-list">
        <div className="shot-list-header">
          <span>分镜时间线</span>
          <small>{shots.length} 个镜头</small>
        </div>
        {shots.map((shot) => (
          <button
            className={`shot-row ${activeShot?.id === shot.id ? "active" : ""}`}
            type="button"
            key={shot.id}
            onClick={() => onSelect(shot)}
          >
            {shot.keyframe_url ? (
              <img
                className="shot-row-thumb"
                src={resolveArtifactUrl(shot.keyframe_url)}
                alt={`${shot.title} 关键帧`}
              />
            ) : (
              <span className="shot-index">{String(shot.index).padStart(2, "0")}</span>
            )}
            <span className="shot-row-copy">
              <strong>{shot.title}</strong>
              <small>
                {formatTime(shot.start_seconds)} — {formatTime(shot.end_seconds)}
              </small>
            </span>
            <CaretRight size={16} />
          </button>
        ))}
      </div>

      {activeShot && (
        <article className="shot-detail">
          <div className="shot-detail-heading">
            <div>
              <span className="eyebrow">镜头 {String(activeShot.index).padStart(2, "0")}</span>
              <h3>{activeShot.title}</h3>
              <p>
                {formatTime(activeShot.start_seconds)} — {formatTime(activeShot.end_seconds)} · {isMediaEvidence ? "真实时间边界" : `置信度 ${Math.round(activeShot.confidence * 100)}%`}
              </p>
            </div>
            {!isMediaEvidence && (
              <button className="icon-button bordered" type="button" onClick={() => onCopy(activeShot.prompt, "镜头提示词已复制")} aria-label="复制镜头提示词">
                <Copy size={17} />
              </button>
            )}
          </div>

          {activeShot.keyframe_url && (
            <figure className="shot-keyframe">
              <img src={resolveArtifactUrl(activeShot.keyframe_url)} alt={`${activeShot.title} 代表关键帧`} />
              <figcaption>代表关键帧 · 截取自该镜头时间区间中点</figcaption>
            </figure>
          )}

          {isMediaEvidence ? (
            <>
              <div className="evidence-note">
                <ShieldCheck size={18} weight="fill" />
                这里只展示可验证的媒体和 Provider 证据。主体、服装、场景、爆点和提示词将在多模态分析接入后生成。
              </div>
              <div className="shot-facts-grid">
                <Fact label="开始时间" value={`${activeShot.start_seconds.toFixed(3)} 秒`} />
                <Fact label="结束时间" value={`${activeShot.end_seconds.toFixed(3)} 秒`} />
                <Fact label="镜头时长" value={`${(activeShot.end_seconds - activeShot.start_seconds).toFixed(3)} 秒`} />
                <Fact label="边界依据" value={activeShot.transition} />
                <Fact label="音频证据" value={activeShot.audio} />
                <Fact label="证据类型" value="FFmpeg 实测" />
              </div>
              {(activeShot.dialogue || activeShot.ocr_text) && (
                <div className="transcript-box">
                  {activeShot.dialogue && (
                    <div>
                      <span>ASR 转写</span>
                      <p>{activeShot.dialogue}</p>
                    </div>
                  )}
                  {activeShot.ocr_text && (
                    <div>
                      <span>OCR 画面文字</span>
                      <p>{activeShot.ocr_text}</p>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="shot-facts-grid">
                <Fact label="主体动作" value={activeShot.action} />
                <Fact label="场景" value={activeShot.scene} />
                <Fact label="机位与运镜" value={activeShot.camera} />
                <Fact label="构图" value={activeShot.composition} />
                <Fact label="灯光" value={activeShot.lighting} />
                <Fact label="色彩" value={activeShot.color} />
                <Fact label="声音" value={activeShot.audio} />
                <Fact label="转场" value={activeShot.transition} />
              </div>
              {(activeShot.dialogue || activeShot.ocr_text) && (
            <div className="transcript-box">
              {activeShot.dialogue && (
                <div>
                  <span>旁白</span>
                  <p>{activeShot.dialogue}</p>
                </div>
              )}
              {activeShot.ocr_text && (
                <div>
                  <span>画面文字</span>
                  <p>{activeShot.ocr_text}</p>
                </div>
              )}
            </div>
              )}

              <div className="prompt-box">
                <div>
                  <MagicWand size={17} weight="fill" />
                  <strong>逐镜头复刻提示词</strong>
                </div>
                <p>{activeShot.prompt}</p>
              </div>
            </>
          )}
        </article>
      )}
    </div>
  );
}

function Fact({ label, value }) {
  return (
    <div className="fact-card">
      <span>{label}</span>
      <p>{value}</p>
    </div>
  );
}

function ViralTab({ report }) {
  return (
    <div className="viral-layout">
      <div className="viral-summary">
        <span className="target-icon">
          <Target size={25} weight="fill" />
        </span>
        <div>
          <span className="eyebrow">内容潜力评分</span>
          <h3>{report.overview.viral_potential_score} / 100</h3>
          <p>所有判断均来自当前视频的画面、字幕和结构证据，不等同于实际平台表现。</p>
        </div>
      </div>
      <div className="finding-list">
        {report.viral_findings.map((finding, index) => (
          <article className="finding-card" key={finding.id}>
            <div className="finding-rank">{String(index + 1).padStart(2, "0")}</div>
            <div className="finding-content">
              <div className="finding-heading">
                <div>
                  <span>
                    {formatTime(finding.start_seconds)} — {formatTime(finding.end_seconds)}
                  </span>
                  <h3>{finding.title}</h3>
                </div>
                <strong>{finding.score}</strong>
              </div>
              <p>{finding.observation}</p>
              <dl>
                <div>
                  <dt>生效机制</dt>
                  <dd>{finding.mechanism}</dd>
                </div>
                <div>
                  <dt>预期作用</dt>
                  <dd>{finding.expected_effect}</dd>
                </div>
                <div>
                  <dt>复用建议</dt>
                  <dd>{finding.recommendation}</dd>
                </div>
              </dl>
              <span className="confidence">置信度 {Math.round(finding.confidence * 100)}%</span>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function ReplacementTab({ videoId, entities, replacementVersion, onCreated, onError }) {
  const [entityId, setEntityId] = useState(entities[0]?.id || "");
  const [description, setDescription] = useState("");
  const [locks, setLocks] = useState(["timing", "camera", "composition", "action"]);
  const [loading, setLoading] = useState(false);
  const currentEntity = entities.find((entity) => entity.id === entityId);
  const lockOptions = [
    ["timing", "时长节奏"],
    ["camera", "机位运镜"],
    ["composition", "画面构图"],
    ["action", "主体动作"],
    ["lighting", "灯光"],
    ["audio", "音频结构"],
  ];

  function toggleLock(value) {
    setLocks((current) =>
      current.includes(value) ? current.filter((item) => item !== value) : [...current, value],
    );
  }

  async function submitReplacement() {
    if (!description.trim()) {
      onError("请输入替换后的元素描述");
      return;
    }
    setLoading(true);
    onError("");
    try {
      const version = await apiRequest(`/videos/${videoId}/replacement-versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          replacements: [{ entity_id: entityId, description: description.trim() }],
          locks,
        }),
      });
      onCreated(version);
    } catch (requestError) {
      onError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="replacement-layout">
      <div className="entity-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">元素资产</span>
            <h3>选择需要替换的元素</h3>
          </div>
          <span>{entities.length} 项</span>
        </div>
        <div className="entity-list">
          {entities.map((entity) => (
            <button
              type="button"
              className={entity.id === entityId ? "active" : ""}
              key={entity.id}
              onClick={() => setEntityId(entity.id)}
            >
              <span className={`entity-type ${entity.type}`}>
                {entity.type === "person" ? <Target size={17} /> : <SquaresFour size={17} />}
              </span>
              <span>
                <strong>{entity.name}</strong>
                <small>{entity.id}</small>
              </span>
              <span className="entity-confidence">{Math.round(entity.confidence * 100)}%</span>
            </button>
          ))}
        </div>
      </div>

      <div className="replacement-editor">
        <div className="current-entity">
          <span>当前描述</span>
          <p>{currentEntity?.description}</p>
          <div className="tag-row">
            {currentEntity?.replaceable_fields.map((field) => <span key={field}>{field}</span>)}
          </div>
        </div>

        <label className="textarea-field">
          <span>替换为</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="例如：35 岁中国男厨师，黑色短发，穿白色亚麻厨师服，沉稳专业"
            rows={5}
          />
        </label>

        <div className="lock-options">
          <div>
            <LockSimple size={17} />
            <span>保持不变</span>
          </div>
          <div className="lock-grid">
            {lockOptions.map(([value, label]) => (
              <label key={value}>
                <input
                  type="checkbox"
                  checked={locks.includes(value)}
                  onChange={() => toggleLock(value)}
                />
                <span>{locks.includes(value) && <Check size={12} weight="bold" />}</span>
                {label}
              </label>
            ))}
          </div>
        </div>

        <button className="primary-button full" type="button" onClick={submitReplacement} disabled={loading}>
          {loading ? <CircleNotch className="spin" size={18} /> : <MagicWand size={18} weight="fill" />}
          生成替换版提示词
        </button>

        {replacementVersion && (
          <div className="replacement-result">
            <div>
              <CheckCircle size={19} weight="fill" />
              <strong>Prompt v{replacementVersion.prompt_package.version} 已生成</strong>
            </div>
            {replacementVersion.diffs.map((diff) => (
              <div className="diff-card" key={diff.entity_id}>
                <span>{diff.entity_id}</span>
                <p><del>{diff.before}</del></p>
                <p><ins>{diff.after}</ins></p>
                <small>影响 {diff.affected_shot_ids.length} 个镜头</small>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PromptsTab({ promptPackage, onCopy, onDownload }) {
  return (
    <div className="prompts-layout">
      <div className="prompt-global-card">
        <div className="prompt-card-header">
          <div>
            <span className="eyebrow">全局视觉圣经</span>
            <h3>{promptPackage.target_model} · Prompt v{promptPackage.version}</h3>
          </div>
          <button className="icon-button bordered" type="button" onClick={() => onCopy(promptPackage.global_prompt, "全局提示词已复制")} aria-label="复制全局提示词">
            <Copy size={17} />
          </button>
        </div>
        <p>{promptPackage.global_prompt}</p>
      </div>

      <div className="prompt-two-column">
        <div className="continuity-card">
          <div className="mini-heading">
            <LockSimple size={17} />
            <strong>连续性锁</strong>
          </div>
          <ul>
            {promptPackage.continuity_locks.map((lock) => <li key={lock}>{lock}</li>)}
          </ul>
        </div>
        <div className="continuity-card negative">
          <div className="mini-heading">
            <ShieldCheck size={17} />
            <strong>负面约束</strong>
          </div>
          <ul>
            {promptPackage.negative_constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}
          </ul>
        </div>
      </div>

      <div className="prompt-shot-list">
        {promptPackage.shots.map((shot, index) => (
          <article key={shot.shot_id}>
            <div>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{shot.shot_id}</strong>
                <small>{shot.duration_seconds.toFixed(1)} 秒</small>
              </div>
            </div>
            <p>{shot.prompt}</p>
            <button type="button" onClick={() => onCopy(shot.prompt, `${shot.shot_id} 已复制`)}>
              <Copy size={16} />
              复制
            </button>
          </article>
        ))}
      </div>

      <div className="export-bar">
        <div>
          <BracketsCurly size={21} />
          <span>
            <strong>机器可读 Prompt Package</strong>
            <small>包含实体、时间线、逐镜头指令与约束</small>
          </span>
        </div>
        <button className="primary-button compact" type="button" onClick={onDownload}>
          <DownloadSimple size={17} />
          下载 JSON
        </button>
      </div>
    </div>
  );
}

function InsightsPanel({ report, analysis, onOpenTab }) {
  const progressMessage = analysis && analysis.stage !== "completed" ? analysis.message : null;
  const isMediaEvidence = report?.analysis_mode === "media_evidence";
  const metadata = report?.media_evidence?.metadata;
  return (
    <aside className="insights-panel">
      <div className="insights-heading">
        <div>
          {isMediaEvidence ? (
            <ShieldCheck size={18} weight="fill" />
          ) : (
            <Sparkle size={18} weight="fill" />
          )}
          <strong>{isMediaEvidence ? "真实分析状态" : "AI 助手建议"}</strong>
        </div>
        <button className="icon-button" type="button" aria-label="刷新建议">
          <ArrowClockwise size={17} />
        </button>
      </div>

      {progressMessage ? (
        <div className="assistant-progress">
          {analysis.stage === "failed" ? (
            <X size={24} weight="bold" />
          ) : (
            <CircleNotch className="spin" size={24} />
          )}
          <strong>{stageLabels[analysis.stage]}</strong>
          <p>{progressMessage}</p>
          <div className="assistant-progress-track">
            <span style={{ width: `${analysis.progress}%` }} />
          </div>
        </div>
      ) : isMediaEvidence ? (
        <>
          <div className="insight-card purple">
            <span className="insight-icon"><ShieldCheck size={20} weight="fill" /></span>
            <div>
              <strong>媒体探测与代理文件已完成</strong>
              <p>
                {metadata?.width} × {metadata?.height} · {report.overview.duration_seconds.toFixed(1)} 秒 · {metadata?.video_codec?.toUpperCase()}
              </p>
            </div>
          </div>
          <div className="insight-card orange">
            <span className="insight-icon"><FilmStrip size={20} weight="fill" /></span>
            <div>
              <strong>检测到 {report.shots.length} 个真实镜头</strong>
              <p>每个时间区间都已生成代表关键帧，可回到原视频对应时间点核验。</p>
            </div>
          </div>
          <div className="insight-card green">
            <span className="insight-icon"><MagicWand size={20} weight="fill" /></span>
            <div>
              <strong>语义层将在下一批接入</strong>
              <p>接入 ASR、OCR 与多模态模型后，再生成主体、场景、爆点和 Seedance 提示词。</p>
            </div>
          </div>
          <button className="assistant-action" type="button" onClick={() => onOpenTab("shots")}>
            查看真实分镜证据
            <CaretRight size={16} />
          </button>
        </>
      ) : report ? (
        <>
          <div className="insight-card purple">
            <span className="insight-icon"><Target size={20} weight="fill" /></span>
            <div>
              <strong>{report.viral_findings[0]?.title}</strong>
              <p>{report.viral_findings[0]?.recommendation}</p>
            </div>
          </div>
          <div className="insight-card orange">
            <span className="insight-icon"><FilmStrip size={20} weight="fill" /></span>
            <div>
              <strong>结构可直接复用</strong>
              <p>{report.overview.narrative_structure}</p>
            </div>
          </div>
          <div className="insight-card green">
            <span className="insight-icon"><Swap size={20} weight="fill" /></span>
            <div>
              <strong>{report.entities.length} 个元素可替换</strong>
              <p>优先替换人物或场景，同时锁定动作、机位和节奏。</p>
            </div>
          </div>
          <button className="assistant-action" type="button" onClick={() => onOpenTab("replace")}>
            生成元素替换方案
            <CaretRight size={16} />
          </button>
        </>
      ) : (
        <div className="assistant-empty">
          <span><Sparkle size={24} /></span>
          <strong>等待视频分析</strong>
          <p>完成导入后，这里会汇总最值得复用的 Hook、结构和视觉元素。</p>
        </div>
      )}

      <div className="phase-note">
        <ShieldCheck size={17} />
        <div>
          <strong>一期边界</strong>
          <p>只分析单条视频，不读取账号，不调用视频生成模型。</p>
        </div>
      </div>
    </aside>
  );
}
