import { useCallback, useEffect, useState } from "react";

export const STRATEGY_META = Object.freeze({
  faithful: {
    label: "结构忠实复刻",
    tone: "faithful",
    changeLevel: "低",
    goal: "最大限度复现原片的观看节奏和镜头关系",
  },
  differentiated: {
    label: "差异化同构",
    tone: "differentiated",
    changeLevel: "中",
    goal: "保留流量功能，建立新的视觉记忆点",
  },
  enhanced: {
    label: "强化改进版",
    tone: "enhanced",
    changeLevel: "高",
    goal: "重排信息密度，强化首屏钩子与结尾兑现",
  },
});

export const ROLE_LABELS = Object.freeze({
  hook: "开场钩子",
  setup: "信息铺垫",
  retention: "留存推进",
  proof: "证据展示",
  payoff: "结果兑现",
  cta: "互动承接",
});

const REPORT_NARRATIVE_PLACEHOLDERS = new Set([
  "逐镜头视觉事实已生成；全局叙事与爆点待下一阶段推理",
  "真实分镜时间线已生成；叙事结构待 VLM 分析",
]);

export function hasReportableNarrativeStructure(value) {
  const normalized = String(value || "").trim();
  return Boolean(normalized) && !REPORT_NARRATIVE_PLACEHOLDERS.has(normalized);
}

export function formatInsightTime(seconds = 0) {
  const safe = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
}

export function useViralInsight({ analysisId, request }) {
  const [insight, setInsight] = useState(null);
  const [loading, setLoading] = useState(Boolean(analysisId));
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!analysisId) return null;
    setLoading(true);
    setError("");
    try {
      const payload = await request(`/analyses/${analysisId}/viral-insight`);
      setInsight(payload);
      return payload;
    } catch (requestError) {
      setError(requestError.message);
      return null;
    } finally {
      setLoading(false);
    }
  }, [analysisId, request]);

  useEffect(() => {
    load();
  }, [load]);

  return { insight, loading, error, reload: load };
}

export function confidenceLabel(value = 0) {
  if (value >= 0.78) return "较高";
  if (value >= 0.55) return "中等";
  return "有限";
}

export function difficultyLabel(value) {
  return { low: "较低", medium: "中等", high: "较高" }[value] || "中等";
}

function normalizeConceptText(value) {
  return String(value || "").replace(/\s+/g, "").toLocaleLowerCase();
}

function normalizeConceptList(values = []) {
  return [...values].map(normalizeConceptText).sort().join("|");
}

export function findConceptDuplicateFields(concepts = []) {
  if (concepts.length < 2) return [];
  const fields = [
    ["有效性说明", (item) => normalizeConceptText(item.why_it_can_work)],
    ["重点改进", (item) => normalizeConceptList(item.improvements)],
    ["制作风险", (item) => normalizeConceptList(item.risks)],
    ["DNA 保留策略", (item) => normalizeConceptList(item.retained_dna)],
    ["逐镜头图片提示词", (item) => (item.shots || []).map((shot) => normalizeConceptText(shot.image_prompt)).join("|")],
    ["逐镜头视频提示词", (item) => (item.shots || []).map((shot) => normalizeConceptText(shot.video_prompt)).join("|")],
  ];
  return fields
    .filter(([, selector]) => new Set(concepts.map(selector)).size !== concepts.length)
    .map(([label]) => label);
}
