export function latestAnalysis(current, incoming) {
  if (!current || !incoming || current.id !== incoming.id) return incoming;
  if (["failed", "completed"].includes(current.stage)
    && !["failed", "completed"].includes(incoming.stage)) return current;
  return Date.parse(current.updated_at) > Date.parse(incoming.updated_at) ? current : incoming;
}

// SSE is an optimization, not the only source of truth. Proxies can keep an
// apparently healthy event stream open without delivering another progress event.
export function watchAnalysis({
  analysisId,
  request,
  eventsUrl,
  onUpdate,
  onComplete,
  onConnectionError,
  EventSourceImpl = globalThis.EventSource,
  pollIntervalMs = 2000,
  requestTimeoutMs = 10000,
}) {
  let active = true;
  let terminal = false;
  let source;
  let pollTimer;
  let requestAbort;
  let latestTimestamp = -1;
  const isCurrent = () => active;

  function closeTransport() {
    source?.close();
    clearTimeout(pollTimer);
    requestAbort?.abort();
  }

  async function accept(next) {
    if (!active || terminal) return;
    if (!next || next.id !== analysisId || !next.stage) throw new Error("分析状态返回异常");
    const timestamp = Date.parse(next.updated_at || next.created_at) || 0;
    if (timestamp < latestTimestamp) return;
    latestTimestamp = timestamp;
    terminal = ["completed", "failed"].includes(next.stage);
    if (terminal) closeTransport();
    onConnectionError("");
    onUpdate(next);
    if (next.stage === "completed") {
      try {
        await onComplete(next, isCurrent);
      } catch (error) {
        if (active) onConnectionError(error.message || "报告读取失败，请刷新状态");
      }
    }
  }

  async function poll() {
    if (!active || terminal) return;
    const controller = new AbortController();
    requestAbort = controller;
    let timeout;
    try {
      const expired = new Promise((_, reject) => {
        timeout = setTimeout(() => {
          reject(new Error("状态查询超时"));
          controller.abort();
        }, requestTimeoutMs);
      });
      const next = await Promise.race([
        request(`/analyses/${analysisId}`, { signal: controller.signal }), expired,
      ]);
      await accept(next);
    } catch {
      if (active && !terminal) {
        onConnectionError("暂时无法获取分析状态，正在重新连接。尚不能确认任务是否结束，请勿重复提交。");
      }
    } finally {
      clearTimeout(timeout);
      if (requestAbort === controller) requestAbort = null;
      if (active && !terminal) pollTimer = setTimeout(poll, pollIntervalMs);
    }
  }

  try {
    if (EventSourceImpl) {
      source = new EventSourceImpl(eventsUrl, { withCredentials: true });
      source.addEventListener("progress", (event) => {
        try {
          accept(JSON.parse(event.data)).catch(() => source?.close());
        } catch {
          source.close();
        }
      });
      source.onerror = () => source.close();
    }
  } catch {
    // Polling also covers browsers without EventSource and blocked connections.
  }
  void poll();
  return () => {
    active = false;
    closeTransport();
  };
}
