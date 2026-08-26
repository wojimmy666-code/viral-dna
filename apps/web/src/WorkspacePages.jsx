import {
  ArrowRight,
  CheckCircle,
  ClockCounterClockwise,
  FileVideo,
  Plus,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react";

const STATUS_META = Object.freeze({
  ready: { label: "待分析", tone: "neutral" },
  analyzing: { label: "分析中", tone: "active" },
  completed: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
});

function formatUpdatedAt(value) {
  if (!value) return "尚未更新";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "尚未更新";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
export function NewAnalysisPage({ children }) {
  return (
    <main className="workspace-main new-analysis-page">
      <section className="page-intro new-analysis-intro">
        <div>
          <div className="breadcrumb">
            <span>工作台</span>
            <ArrowRight size={14} />
            <span className="breadcrumb-current">新建分析</span>
          </div>
          <h1>新建视频分析</h1>
        </div>
        <div className="intro-status">
          <ShieldCheck size={17} weight="fill" />
          Phase 1 · 单视频模式
        </div>
      </section>
      {children}
    </main>
  );
}

export function WorkbenchHomePage({
  loading,
  onCreate,
  onOpenHistory,
  onOpenRecord,
  records,
  total,
}) {
  const recentRecords = (records || []).slice(0, 6);
  return (
    <main className="workspace-main workbench-home-page">
      <section className="page-intro workbench-home-intro">
        <div>
          <div className="breadcrumb">
            <span className="breadcrumb-current">工作台</span>
          </div>
          <h1>继续最近的创作研究</h1>
          <p>从最近任务继续分析或创作，也可以创建一个新的视频拆解。</p>
        </div>
      </section>

      <section className="workbench-recent" aria-labelledby="workbench-recent-title">
        <header className="workbench-section-heading">
          <div>
            <h2 id="workbench-recent-title">最近分析</h2>
            <p>{total ? `当前共有 ${total} 条分析记录` : "最近更新的任务会显示在这里"}</p>
          </div>
          <button className="secondary-button compact" onClick={onOpenHistory} type="button">
            <ClockCounterClockwise size={17} />
            查看全部记录
          </button>
        </header>

        {loading && !recentRecords.length ? (
          <div className="workbench-record-skeletons" aria-label="正在加载最近分析" role="status">
            {[0, 1, 2].map((item) => <span key={item} />)}
          </div>
        ) : recentRecords.length ? (
          <div className="workbench-record-list">
            {recentRecords.map((record) => {
              const status = STATUS_META[record.status] || STATUS_META.ready;
              return (
                <button
                  className="workbench-record-row"
                  key={record.id}
                  onClick={() => onOpenRecord(record.id)}
                  type="button"
                >
                  <span className="workbench-record-icon"><FileVideo size={20} /></span>
                  <span className="workbench-record-copy">
                    <strong>{record.name || "未命名分析"}</strong>
                    <small>更新于 {formatUpdatedAt(record.updated_at)}</small>
                  </span>
                  <span className={`workbench-record-status ${status.tone}`}>
                    {status.tone === "success" && <CheckCircle size={15} weight="fill" />}
                    {status.tone === "danger" && <WarningCircle size={15} weight="fill" />}
                    {status.label}
                  </span>
                  <ArrowRight className="workbench-record-arrow" size={18} />
                </button>
              );
            })}
          </div>
        ) : (
          <div className="workbench-empty">
            <span><FileVideo size={26} /></span>
            <div>
              <h2>还没有分析任务</h2>
              <p>导入第一个视频后，可以随时从这里继续分析和创作。</p>
            </div>
            <button className="primary-button compact" onClick={onCreate} type="button">
              <Plus size={17} weight="bold" />
              新建分析
            </button>
          </div>
        )}
      </section>
    </main>
  );
}

export function RecordWorkspacePage({ children }) {
  return <main className="workspace-main detail-mode record-workspace-page">{children}</main>;
}

export function RecordWorkspaceState({ error = "", loading = false, onBack, onRetry }) {
  if (loading) {
    return (
      <section className="record-route-state loading" aria-label="正在加载记录工作台" role="status">
        <div className="record-route-skeleton heading" />
        <div className="record-route-skeleton line" />
        <div className="record-route-skeleton panel" />
      </section>
    );
  }
  return (
    <section className="record-route-state error" role="alert">
      <span><WarningCircle size={25} weight="fill" /></span>
      <div>
        <h2>{error ? "无法打开分析工作台" : "该记录还没有可查看的分析"}</h2>
        <p>{error || "可以返回分析记录选择其他任务，或为当前视频重新发起分析。"}</p>
      </div>
      <div className="record-route-actions">
        <button className="secondary-button compact" onClick={onBack} type="button">返回分析记录</button>
        {error && <button className="primary-button compact" onClick={onRetry} type="button">重新加载</button>}
      </div>
    </section>
  );
}
