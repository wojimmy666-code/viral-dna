import {
  ArrowRight,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react";
export function NewAnalysisPage({ children }) {
  return (
    <main className="workspace-main new-analysis-page">
      <section className="page-intro new-analysis-intro">
        <div>
          <div className="breadcrumb">
            <span>项目</span>
            <ArrowRight size={14} />
            <span className="breadcrumb-current">新建项目</span>
          </div>
          <h1>新建项目</h1>
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

export function RecordWorkspacePage({ children }) {
  return <main className="workspace-main detail-mode record-workspace-page">{children}</main>;
}

export function RecordWorkspaceState({ error = "", loading = false, onBack, onRetry }) {
  if (loading) {
    return (
      <section className="record-route-state loading" aria-label="正在加载项目" role="status">
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
        <h2>{error ? "无法打开项目" : "该项目还没有可查看的分析"}</h2>
        <p>{error || "可以返回项目列表选择其他项目，或为当前视频重新发起分析。"}</p>
      </div>
      <div className="record-route-actions">
        <button className="secondary-button compact" onClick={onBack} type="button">返回项目列表</button>
        {error && <button className="primary-button compact" onClick={onRetry} type="button">重新加载</button>}
      </div>
    </section>
  );
}
