import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const ACTIVE_STATUSES = new Set(["queued", "running", "cancellation_requested"]);

export function useVideoEnhancement({
  candidateId,
  enabled,
  expectedRevisionId,
  onChanged,
  onNotificationsChanged,
  request,
}) {
  const [settings, setSettings] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [source, setSource] = useState(null);
  const [installation, setInstallation] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const pollTimer = useRef(null);
  const installTimer = useRef(null);
  const onChangedRef = useRef(onChanged);
  const onNotificationsChangedRef = useRef(onNotificationsChanged);

  useEffect(() => {
    onChangedRef.current = onChanged;
    onNotificationsChangedRef.current = onNotificationsChanged;
  }, [onChanged, onNotificationsChanged]);

  const clearTimers = useCallback(() => {
    if (pollTimer.current) window.clearTimeout(pollTimer.current);
    if (installTimer.current) window.clearTimeout(installTimer.current);
    pollTimer.current = null;
    installTimer.current = null;
  }, []);

  const load = useCallback(async ({ probe = false, quiet = false } = {}) => {
    if (!enabled || !candidateId) return;
    if (!quiet) setBusy(probe ? "probing" : "loading");
    setError("");
    try {
      const [nextSettings, nextJobs] = await Promise.all([
        request(
          probe
            ? "/settings/video-enhancement/probe"
            : "/settings/video-enhancement",
          probe ? { method: "POST" } : undefined,
        ),
        request(`/video-enhancements/candidates/${candidateId}/jobs`),
      ]);
      setSettings(nextSettings);
      setJobs(nextJobs.items || []);
      setSource(nextJobs.source || null);
    } catch (nextError) {
      setError(nextError.message || "读取视频清晰化状态失败");
    } finally {
      if (!quiet) setBusy("");
    }
  }, [candidateId, enabled, request]);

  useEffect(() => {
    clearTimers();
    setSettings(null);
    setJobs([]);
    setSource(null);
    setInstallation(null);
    setError("");
    if (enabled && candidateId) load();
    return clearTimers;
  }, [candidateId, clearTimers, enabled, load]);

  const activeView = useMemo(
    () => [...jobs].reverse().find((item) => ACTIVE_STATUSES.has(item.job.status)) || null,
    [jobs],
  );

  useEffect(() => {
    if (!activeView?.job?.id || !enabled) return undefined;
    let disposed = false;
    async function poll() {
      try {
        const next = await request(`/video-enhancements/jobs/${activeView.job.id}`);
        if (disposed) return;
        setJobs((current) => {
          const found = current.some((item) => item.job.id === next.job.id);
          return found
            ? current.map((item) => (item.job.id === next.job.id ? next : item))
            : [...current, next];
        });
        if (ACTIVE_STATUSES.has(next.job.status)) {
          pollTimer.current = window.setTimeout(poll, 1000);
          return;
        }
        await onNotificationsChangedRef.current?.();
        if (next.job.status === "succeeded") {
          onChangedRef.current?.({ kind: "completed", job: next.job });
        }
      } catch {
        if (!disposed) pollTimer.current = window.setTimeout(poll, 2000);
      }
    }
    pollTimer.current = window.setTimeout(poll, 500);
    return () => {
      disposed = true;
      if (pollTimer.current) window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    };
  }, [activeView?.job?.id, enabled, request]);

  useEffect(() => {
    if (!installation || !["queued", "running"].includes(installation.status)) {
      return undefined;
    }
    let disposed = false;
    async function pollInstallation() {
      try {
        const next = await request(
          `/video-enhancements/engine/installations/${installation.id}`,
        );
        if (disposed) return;
        setInstallation(next);
        if (["queued", "running"].includes(next.status)) {
          installTimer.current = window.setTimeout(pollInstallation, 900);
          return;
        }
        if (["succeeded", "failed"].includes(next.status)) {
          await load({ probe: true, quiet: true });
        }
        if (next.status === "succeeded") {
          await onNotificationsChangedRef.current?.();
        } else {
          setError(next.error || "Real-ESRGAN 快速引擎安装失败");
        }
      } catch (nextError) {
        if (!disposed) {
          setError(nextError.message || "读取引擎安装进度失败");
        }
      }
    }
    installTimer.current = window.setTimeout(pollInstallation, 600);
    return () => {
      disposed = true;
      if (installTimer.current) window.clearTimeout(installTimer.current);
      installTimer.current = null;
    };
  }, [installation?.id, installation?.status, load, request]);

  const runAction = useCallback(async (name, action) => {
    setBusy(name);
    setError("");
    try {
      return await action();
    } catch (nextError) {
      setError(nextError.message || "视频清晰化操作失败");
      return null;
    } finally {
      setBusy("");
    }
  }, []);

  const install = useCallback(() => runAction("installing", async () => {
    const next = await request("/video-enhancements/engine/installations", {
      method: "POST",
    });
    setInstallation(next);
    return next;
  }), [request, runAction]);

  const start = useCallback((target) => runAction("starting", async () => {
    const next = await request(`/video-enhancements/candidates/${candidateId}/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_revision_id: expectedRevisionId,
        target,
      }),
    });
    setJobs((current) => [...current.filter((item) => item.job.id !== next.job.id), next]);
    return next;
  }), [candidateId, expectedRevisionId, request, runAction]);

  const cancel = useCallback((jobId) => runAction("cancelling", async () => {
    const next = await request(`/video-enhancements/jobs/${jobId}/cancel`, {
      method: "POST",
    });
    setJobs((current) => current.map((item) => (item.job.id === jobId ? next : item)));
    return next;
  }), [request, runAction]);

  const retry = useCallback((jobId) => runAction("retrying", async () => {
    const next = await request(`/video-enhancements/jobs/${jobId}/retry`, {
      method: "POST",
    });
    setJobs((current) => [...current.filter((item) => item.job.id !== next.job.id), next]);
    return next;
  }), [request, runAction]);

  const useForFinal = useCallback((jobId) => runAction("activating", async () => {
    const next = await request(`/video-enhancements/jobs/${jobId}/use-for-final`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision_id: expectedRevisionId }),
    });
    setJobs((current) => current.map((item) => ({
      ...item,
      job: { ...item.job, active_for_final: item.job.id === jobId },
    })));
    await onChangedRef.current?.({ kind: "active-version", jobId });
    return next;
  }), [expectedRevisionId, request, runAction]);

  const useOriginal = useCallback(() => runAction("activating", async () => {
    const next = await request(
      `/video-enhancements/candidates/${candidateId}/use-original`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision_id: expectedRevisionId }),
      },
    );
    setJobs((current) => current.map((item) => ({
      ...item,
      job: { ...item.job, active_for_final: false },
    })));
    await onChangedRef.current?.({ kind: "active-version", jobId: null });
    return next;
  }), [candidateId, expectedRevisionId, request, runAction]);

  return {
    activeView,
    busy,
    cancel,
    error,
    install,
    installation,
    jobs,
    load,
    retry,
    settings,
    source,
    start,
    useForFinal,
    useOriginal,
  };
}
