import { videoGenerationDiagnosticText, videoGenerationFailureDetails } from '../production-ui.js';
import './video-generation-failure.css';

export function VideoGenerationFailure({ run }) {
  const failure = videoGenerationFailureDetails(run);
  if (!failure) return null;
  const submission = {
    not_submitted: '未提交给 Provider；本次未调用生成模型。',
    rejected: 'Provider 已返回拒绝，本次未创建生成任务。',
    submitted: '已提交给 Provider，可用任务编号核对状态。',
    unknown: '提交状态尚未确认；请先核对 Provider 控制台，避免重复生成。',
  }[failure.submissionState];
  const cost = run.actual_cost_known
    ? `已记录费用 ¥${(Number(run.actual_cost_micros || 0) / 1000000).toFixed(4)}`
    : failure.submissionState === 'not_submitted'
      ? '未发起模型生成计费。'
      : '费用尚未确认，以 Provider 实际账单为准。';
  return <section className="video-generation-failure" aria-label="视频生成失败详情">
    <div role="alert">
      <strong>{failure.originLabel} · {failure.stageLabel}：{failure.title}</strong>
      <p>{failure.message}</p>
    </div>
    <p>{failure.modelLabel} · 错误码：<code>{failure.code}</code></p>
    <p>{submission} {cost}</p>
    <details>
      <summary>技术详情</summary>
      <pre>{videoGenerationDiagnosticText(failure)}</pre>
    </details>
  </section>;
}
