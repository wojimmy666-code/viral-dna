import { useCallback, useEffect, useState } from "react";

export const STRATEGY_META = Object.freeze({
  faithful: {
    label: "结构迁移",
    tone: "faithful",
    changeLevel: "低",
  },
  scenario: {
    label: "场景叙事",
    tone: "scenario",
    changeLevel: "中",
  },
  proof: {
    label: "证据说服",
    tone: "proof",
    changeLevel: "中高",
  },
  differentiated: {
    label: "差异化同构",
    tone: "differentiated",
    changeLevel: "中",
  },
  enhanced: {
    label: "强化改进版",
    tone: "enhanced",
    changeLevel: "高",
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
    ["创意主张", (item) => normalizeConceptText(item.thesis)],
    ["开场钩子", (item) => normalizeConceptText(item.hook)],
    ["叙事结构", (item) => normalizeConceptText(item.narrative_structure)],
    ["视觉记忆点", (item) => normalizeConceptText(item.visual_memory)],
    ["结尾兑现", (item) => normalizeConceptText(item.payoff)],
    ["核心改动", (item) => normalizeConceptList(item.changed_elements)],
    ["有效性说明", (item) => normalizeConceptText(item.why_it_can_work)],
    ["重点改进", (item) => normalizeConceptList(item.improvements)],
    ["制作风险", (item) => normalizeConceptList(item.risks)],
    ["DNA 保留策略", (item) => normalizeConceptList(item.retained_dna)],
    ["逐镜头图片提示词", (item) => (item.shots || []).map((shot) => normalizeConceptText(shot.image_prompt)).join("|")],
    ["逐镜头视频提示词", (item) => (item.shots || []).map((shot) => normalizeConceptText(shot.video_prompt)).join("|")],
  ];
  return fields
    .filter(([, selector]) => {
      const values = concepts.map(selector);
      return values.some(Boolean) && new Set(values).size !== concepts.length;
    })
    .map(([label]) => label);
}
