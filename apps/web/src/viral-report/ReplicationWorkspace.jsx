import {
  ArrowClockwise,
  CaretDown,
  Check,
  CircleNotch,
  LockSimple,
  MagicWand,
  ShieldWarning,
  Sparkle,
  Swap,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ConceptComparison } from "./ConceptComparison.jsx";
import { useViralInsight } from "./viral-report-ui.js";

export function ReplicationWorkspace({ analysisId, recordId, request, onPublished, onNotice }) {
  const { insight, loading, error, reload } = useViralInsight({ analysisId, request });
  const [replacementValues, setReplacementValues] = useState({});
  const [conceptSet, setConceptSet] = useState(null);
  const [conceptLoading, setConceptLoading] = useState(false);
  const [conceptError, setConceptError] = useState("");
  const [publishingId, setPublishingId] = useState("");

  const loadLatest = useCallback(async () => {
    if (!analysisId) return;
    try {
      const payload = await request(`/analyses/${analysisId}/viral-concepts/latest`);
      setConceptSet(payload);
    } catch {
      // The latest batch is optional; generation remains available.
    }
  }, [analysisId, request]);

  useEffect(() => { loadLatest(); }, [loadLatest]);

  const selectedReplacements = useMemo(
    () => Object.entries(replacementValues)
      .filter(([, value]) => value.trim())
      .map(([entity_id, replacement]) => ({ entity_id, replacement: replacement.trim() })),
    [replacementValues],
  );

  async function generateConcepts() {
    setConceptLoading(true);
    setConceptError("");
    try {
      const payload = await request(`/analyses/${analysisId}/viral-concepts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategies: ["faithful", "differentiated", "enhanced"],
          replacements: selectedReplacements,
        }),
      });
      setConceptSet(payload);
      onNotice?.({ type: "success", message: "三套新视频方案已生成" });
    } catch (requestError) {
      setConceptError(requestError.message);
    } finally {
      setConceptLoading(false);
    }
  }

  async function publishConcept(concept) {
    setPublishingId(concept.id);
    setConceptError("");
    try {
      const result = await request(`/viral-concept-sets/${conceptSet.id}/concepts/${concept.id}/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: recordId, name: concept.name }),
      });
      onNotice?.({ type: "success", message: `已创建“${result.project_name}”` });
      await onPublished?.(result);
    } catch (requestError) {
      setConceptError(requestError.message);
    } finally {
      setPublishingId("");
    }
  }

  if (loading && !insight) return <div className="viral-loading-state"><CircleNotch className="spin" size={22} />正在读取复刻决策信息…</div>;
  if (error && !insight) return <div className="viral-error-state"><ShieldWarning size={22} /><div><strong>无法读取复刻信息</strong><p>{error}</p></div><button type="button" onClick={() => reload()}><ArrowClockwise size={17} />重试</button></div>;
  if (!insight) return null;

  return (
    <div className="viral-report-page replication-workspace">
      <header className="viral-section-header">
        <div><h2>复刻与改进工作台</h2><p>锁定有效结构，再替换人物、产品或场景。参考资产不是必填项。</p></div>
        <span className="viral-basis-badge"><Sparkle size={15} />不会调用视频生成模型</span>
      </header>

      <div className={`replication-preparation-grid ${insight.replacement_opportunities.length ? "" : "dna-only"}`}>
        <details className="replication-dna-locks">
          <summary className="replication-section-title"><LockSimple size={20} /><div><strong>内容 DNA 已锁定</strong><p>{insight.dna.invariants.length} 项机制会自动写入新方案，点击查看</p></div><CaretDown size={17} /></summary>
          <div className="dna-lock-list">{insight.dna.invariants.map((item) => <span key={item}><Check size={14} weight="bold" />{item}</span>)}</div>
        </details>

        {insight.replacement_opportunities.length > 0 && <section className="replacement-opportunities">
          <div className="replication-section-title"><Swap size={20} /><div><strong>元素替换</strong><p>留空表示继续使用原描述；填写后会同步进入三套方案的逐镜头提示词。</p></div></div>
          <div className="replacement-opportunity-list">
            {insight.replacement_opportunities.map((item) => (
              <label key={item.entity_id}>
                <span className="replacement-entity-meta"><strong>{item.label}</strong><small>{item.entity_type} · 影响 {item.affected_shot_ids.length} 个分镜 · {item.risk === "high" ? "高一致性风险" : item.risk === "medium" ? "中等风险" : "低风险"}</small></span>
                <span className="replacement-current">{item.current_description}</span>
                <input value={replacementValues[item.entity_id] || ""} onChange={(event) => setReplacementValues((current) => ({ ...current, [item.entity_id]: event.target.value }))} placeholder={`替换为，例如：${item.suggested_alternatives[0] || "同功能新元素"}`} />
              </label>
            ))}
          </div>
        </section>}
      </div>

      <section className="replication-generate-bar">
        <div><strong>{selectedReplacements.length ? `已设置 ${selectedReplacements.length} 项替换` : "直接沿用原元素"}</strong><span>一次生成忠实复刻、差异化同构、强化改进三套方案 · 额外成本 ¥0.00</span></div>
        <button className="primary-button" type="button" onClick={generateConcepts} disabled={conceptLoading}>
          {conceptLoading ? <CircleNotch className="spin" size={19} /> : <MagicWand size={19} weight="fill" />}
          {conceptSet ? "重新生成三套方案" : "生成三套方案"}
        </button>
      </section>

      {conceptError && <div className="viral-error-state compact" role="alert"><ShieldWarning size={19} />{conceptError}</div>}
      {conceptSet?.status === "stale" && (
        <section className="concept-stale-notice" role="status">
          <ShieldWarning size={20} />
          <div>
            <strong>现有三套方案需要更新</strong>
            <p>{conceptSet.stale_reason || "方案来自旧版生成规则，请重新生成后再创建创作方案。"}</p>
          </div>
          <button type="button" onClick={generateConcepts} disabled={conceptLoading}>
            {conceptLoading ? <CircleNotch className="spin" size={17} /> : <ArrowClockwise size={17} />}
            重新生成
          </button>
        </section>
      )}
      <ConceptComparison conceptSet={conceptSet} publishingId={publishingId} onPublish={publishConcept} />
    </div>
  );
}
