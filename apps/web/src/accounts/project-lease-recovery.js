import { accountRequest } from "./account-client.js";

export const LEASE_CHECK_INTERVAL_MS = 5000;
const REQUEST_TIMEOUT_MS = 10000;

// Read-only pages must not remain stuck on an expired occupancy snapshot.
// This only observes availability: the ordinary atomic acquire endpoint still
// decides who may edit. Hidden tabs and editors with retained drafts never race
// to take a newly available lease.
export function startProjectLeaseRecovery({
  projectId,
  onState,
  onAvailable,
  onError,
  isCurrent = () => true,
  request = accountRequest,
  windowTarget = window,
  documentTarget = document,
}) {
  let stopped = false;
  let pending = null;
  let controller = null;
  const visible = () => documentTarget.visibilityState !== "hidden";
  const active = () => !stopped && isCurrent() && visible();

  async function check() {
    if (!active() || pending) return;
    controller = new AbortController();
    const signal = controller.signal;
    const timeout = windowTarget.setTimeout(() => controller?.abort(), REQUEST_TIMEOUT_MS);
    const work = async () => {
      try {
        const state = await request(`/projects/${projectId}/edit-lease`, { signal });
        if (!active() || signal.aborted) return;
        // Fail closed on a malformed response, not just a falsey property.
        if (!state || typeof state.occupied !== "boolean") {
          throw new Error("无法确认项目编辑状态");
        }
        onState(state);
        if (state.occupied === false && active()) await onAvailable();
      } catch (error) {
        if (!active()) return;
        onError(error);
        if ([401, 403, 404].includes(error.status) || error.code === "session_changed") stop();
      } finally {
        windowTarget.clearTimeout(timeout);
        controller = null;
      }
    };
    pending = work();
    try { await pending; } finally { pending = null; }
  }

  function stop() {
    if (stopped) return;
    stopped = true;
    windowTarget.clearInterval(timer);
    controller?.abort();
    windowTarget.removeEventListener("focus", check);
    windowTarget.removeEventListener("online", check);
    windowTarget.removeEventListener("pageshow", check);
    documentTarget.removeEventListener("visibilitychange", check);
  }

  const timer = windowTarget.setInterval(check, LEASE_CHECK_INTERVAL_MS);
  windowTarget.addEventListener("focus", check);
  windowTarget.addEventListener("online", check);
  windowTarget.addEventListener("pageshow", check);
  documentTarget.addEventListener("visibilitychange", check);
  // The initial acquisition has already checked availability. Waiting for the
  // first tick also prevents an acquire failure from becoming a tight retry loop.
  return { check, stop };
}
