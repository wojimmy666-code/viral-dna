import {
  ArrowClockwise,
  ArrowsLeftRight,
  CaretDown,
  CheckCircle,
  ShieldWarning,
  WarningCircle,
} from "@phosphor-icons/react";

const DIMENSION_LABELS = Object.freeze({
  identity: "人物身份",
  wardrobe: "服装",
  product: "产品",
  scene: "场景",
  action: "动作承接",
  screen_position: "画面位置",
  motion_direction: "运动方向",
  camera_axis: "镜头轴线",
  lighting: "光线",
  color: "色彩",
});

function reportPresentation(report) {
  if (!report) {
    return {
      tone: "neutral",
      label: "尚未检查",
      description: "采用完分镜视频后，检查人物、产品与镜头衔接。",
      icon: ArrowsLeftRight,
    };
  }
  if (report.status === "stale") {
    return {
      tone: "warning",
      label: "结果已过期",
      description: `有 ${report.stale_boundary_keys?.length || 0} 条相邻边界需要重新检查。`,
      icon: ArrowClockwise,
    };
  }
  if (report.blocker_count > 0) {
    return {
      tone: "danger",
      label: `${report.blocker_count} 个阻断问题`,
      description: "人物或产品连续性需要处理后才能进入视频剪辑。",
      icon: ShieldWarning,
    };
  }
  if (report.warning_count > 0) {
    return {
      tone: "warning",
      label: `${report.warning_count} 个提示`,
      description: "不阻断剪辑，建议在合成前复核衔接。",
      icon: WarningCircle,
    };
  }
  if (report.verification_state === "verified") {
    return {
      tone: "success",
      label: "连续性已验证",
      description: "相邻分镜未发现待处理的连续性问题。",
      icon: CheckCircle,
    };
  }
  return {
    tone: "neutral",
    label: "规则检查完成",
    description: "引用与锁定项已检查；当前尚未执行 VLM 视觉验证。",
    icon: ArrowsLeftRight,
  };
}

export function ContinuityQualityPanel({
  busy,
  onDecide,
  onRun,
  report,
}) {
  const presentation = reportPresentation(report);
  const StatusIcon = presentation.icon;
  const findings = (report?.boundaries || []).flatMap((boundary) => (
    (boundary.findings || []).map((finding) => ({
      ...finding,
      leftShotIndex: boundary.left_shot_index,
      rightShotIndex: boundary.right_shot_index,
    }))
  ));
  const openFindings = findings.filter((item) => item.state === "open");
  const decidedFindings = findings.filter((item) => item.state !== "open");
  const visibleFindingCount = openFindings.length + decidedFindings.length;

  return (
    <section
      aria-live="polite"
      className={`continuity-quality-panel tone-${presentation.tone}`}
    >
      <header>
        <span className="continuity-quality-icon" aria-hidden="true">
          <StatusIcon size={20} weight="duotone" />
        </span>
        <div className="continuity-quality-copy">
          <strong>跨分镜连续性</strong>
          <p>{presentation.description}</p>
        </div>
        <span className="continuity-quality-status">{presentation.label}</span>
        <button
          className="secondary-button compact"
          disabled={busy}
          onClick={onRun}
          type="button"
        >
          <ArrowClockwise size={16} />
          {report ? "重新检查" : "开始检查"}
        </button>
      </header>

      {visibleFindingCount > 0 && (
        <details
          className="continuity-quality-findings"
          open={report?.blocker_count > 0 || report?.status === "stale"}
        >
          <summary>
            <span>
              查看 {visibleFindingCount} 个连续性记录
              {decidedFindings.length > 0 && ` · ${decidedFindings.length} 个已处理`}
            </span>
            <CaretDown size={15} aria-hidden="true" />
          </summary>
          <div className="continuity-quality-list">
            {findings.map((finding) => (
              <article key={finding.key}>
                <div className="continuity-quality-finding-main">
                  <span className={`continuity-finding-severity severity-${finding.severity}`}>
                    {finding.severity === "blocker" ? "阻断" : "提示"}
                  </span>
                  <div>
                    <strong>
                      分镜 {finding.leftShotIndex} → {finding.rightShotIndex}
                      <span> · {DIMENSION_LABELS[finding.dimension] || finding.dimension}</span>
                    </strong>
                    <p>{finding.message}</p>
                    {finding.suggestion && <small>{finding.suggestion}</small>}
                    {finding.decision_reason && (
                      <small>处理说明：{finding.decision_reason}</small>
                    )}
                  </div>
                </div>
                {finding.state === "open" ? (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => onDecide(finding, "waive")}
                    type="button"
                  >
                    标记为有意变化
                  </button>
                ) : (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => onDecide(finding, "reopen")}
                    type="button"
                  >
                    重新打开
                  </button>
                )}
              </article>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}
