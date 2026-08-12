import { useCallback, useEffect, useState } from "react";

export const STRATEGY_META = Object.freeze({
  faithful: { label: "结构忠实复刻", tone: "faithful" },
  differentiated: { label: "差异化同构", tone: "differentiated" },
  enhanced: { label: "强化改进版", tone: "enhanced" },
});

export const ROLE_LABELS = Object.freeze({
  hook: "开场钩子",
  setup: "信息铺垫",
  retention: "留存推进",
  proof: "证据展示",
  payoff: "结果兑现",
  cta: "互动承接",
});

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

  const load = useCallback(async ({ refresh = false } = {}) => {
    if (!analysisId) return null;
    setLoading(true);
    setError("");
    try {
      const payload = await request(
        `/analyses/${analysisId}/viral-insight${refresh ? "/refresh" : ""}`,
        refresh ? { method: "POST" } : undefined,
      );
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
