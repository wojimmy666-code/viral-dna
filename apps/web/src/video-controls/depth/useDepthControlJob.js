import { useCallback, useEffect, useRef, useState } from "react";

const ACTIVE_STATUSES = new Set([
  "queued",
  "running",
  "cancellation_requested",
]);

const DEPTH_GENERATION_PRESETS = new Set([
  "auto",
  "cpu_fast",
  "balanced",
  "quality",
]);

function normalizePreset(value) {
  return typeof value === "string" && DEPTH_GENERATION_PRESETS.has(value)
    ? value
    : "auto";
}

function jobFromResponse(payload) {
  return payload?.job || payload || null;
}

function errorMessage(error) {
  return error?.message || "深度生成任务请求失败，请稍后重试。";
}

export function useDepthControlJob({
  expectedRevisionId,
  onTerminal,
  request,
  shotPlanId,
}) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const terminalCallbackRef = useRef(onTerminal);
  const terminalJobRef = useRef("");

  useEffect(() => {
    terminalCallbackRef.current = onTerminal;
  }, [onTerminal]);

  useEffect(() => {
    let disposed = false;
    let timer = null;

    async function loadLatest() {
      if (!shotPlanId) {
        setJob(null);
        return;
      }
      try {
        const payload = await request(`/depth-controls/shots/${shotPlanId}/jobs`);
        if (disposed) return;
        const items = payload?.items || [];
        const latest = items.at(-1) || null;
        if (latest && !ACTIVE_STATUSES.has(latest.status)) {
          terminalJobRef.current = `${latest.id}:${latest.status}`;
        }
        setJob(latest);
        setError("");
      } catch (loadError) {
        if (!disposed) setError(errorMessage(loadError));
      }
    }

    setJob(null);
    setError("");
    terminalJobRef.current = "";
    void loadLatest();
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [request, shotPlanId]);

  useEffect(() => {
    if (!job?.id || !ACTIVE_STATUSES.has(job.status)) return undefined;
    let disposed = false;
    let timer = null;
    let networkFailures = 0;

    async function poll() {
      try {
        const payload = await request(`/depth-controls/jobs/${job.id}`);
        if (disposed) return;
        const nextJob = jobFromResponse(payload);
        networkFailures = 0;
        setJob(nextJob);
        setError("");
        if (nextJob && ACTIVE_STATUSES.has(nextJob.status)) {
          timer = window.setTimeout(poll, 1000);
        }
      } catch (pollError) {
        if (disposed) return;
        networkFailures += 1;
        setError(errorMessage(pollError));
        timer = window.setTimeout(poll, Math.min(5000, 1500 * networkFailures));
      }
    }

    timer = window.setTimeout(poll, 700);
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [job?.id, job?.status, request]);

  useEffect(() => {
    if (!job?.id || ACTIVE_STATUSES.has(job.status)) return;
    if (terminalJobRef.current === `${job.id}:${job.status}`) return;
    terminalJobRef.current = `${job.id}:${job.status}`;
    void terminalCallbackRef.current?.(job);
  }, [job]);

  const start = useCallback(async (preset = "auto") => {
    if (!shotPlanId || submitting) return null;
    const normalizedPreset = normalizePreset(preset);
    setSubmitting(true);
    setError("");
    try {
      const payload = await request(`/depth-controls/shots/${shotPlanId}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision_id: expectedRevisionId || null,
          preset: normalizedPreset,
        }),
      });
      const nextJob = jobFromResponse(payload);
      setJob(nextJob);
      return nextJob;
    } catch (startError) {
      setError(errorMessage(startError));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, [expectedRevisionId, request, shotPlanId, submitting]);

  const cancel = useCallback(async () => {
    if (!job?.id || !ACTIVE_STATUSES.has(job.status)) return null;
    try {
      const payload = await request(`/depth-controls/jobs/${job.id}/cancel`, {
        method: "POST",
      });
      const nextJob = jobFromResponse(payload);
      setJob(nextJob);
      return nextJob;
    } catch (cancelError) {
      setError(errorMessage(cancelError));
      return null;
    }
  }, [job?.id, job?.status, request]);

  const retry = useCallback(async () => {
    if (!job?.id || ACTIVE_STATUSES.has(job.status)) return null;
    setSubmitting(true);
    setError("");
    try {
      const payload = await request(`/depth-controls/jobs/${job.id}/retry`, {
        method: "POST",
      });
      const nextJob = jobFromResponse(payload);
      setJob(nextJob);
      return nextJob;
    } catch (retryError) {
      setError(errorMessage(retryError));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, [job?.id, job?.status, request]);

  return {
    active: Boolean(job && ACTIVE_STATUSES.has(job.status)),
    cancel,
    error,
    job,
    retry,
    start,
    submitting,
  };
}
