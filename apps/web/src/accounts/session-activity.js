import { accountRequest, accountSessionPaused, currentAccountSession, pauseAccountSession, setAccountSession } from "./account-client.js";

export const RENEW_INTERVAL_MS = 5 * 60 * 1000;
const CHANNEL = "viraldna-session-activity-v1";
export const samePrincipal = (left, right, admin = false) => Boolean(left && right && (admin
  ? left.admin_id && left.admin_id === right.admin_id
  : left.user_id && left.user_id === right.user_id && left.account_id === right.account_id));

// Activity is a UX signal, not an authentication credential. The server alone
// decides expiry and revocation. Messages never contain cookies, CSRF or drafts.
export function startSessionActivity({ admin = false, onState = () => {}, onRecovered = () => {},
  request = accountRequest, now = Date.now, windowTarget = window, documentTarget = document,
  channelFactory = name => typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(name),
} = {}) {
  let expected = currentAccountSession(admin), stopped = false, pending = null, controller = null;
  let activeAt = -Infinity, retryAt = 0, failures = 0, lastProbe = -Infinity, health = "active";
  let offset = 0, renewAt = now() + RENEW_INTERVAL_MS, expiresAt = Infinity, epoch = 0;
  let channel;
  try { channel = channelFactory(CHANNEL); } catch { /* Older/private browsers use the server throttle. */ }
  const scope = admin ? `admin:${expected?.admin_id}` : `user:${expected?.account_id}:${expected?.user_id}`;
  const visible = () => documentTarget.visibilityState === "visible" && documentTarget.hasFocus();
  const notify = state => { if (!stopped && state !== health) { health = state; onState(state); } };
  function deadlines(session) {
    if (Number.isFinite(session?.session_server_time)) offset = session.session_server_time * 1000 - now();
    if (Number.isFinite(session?.session_expires_at)) expiresAt = session.session_expires_at * 1000;
    renewAt = Number.isFinite(session?.session_renew_after) ? session.session_renew_after * 1000 : now() + offset + RENEW_INTERVAL_MS;
  }
  deadlines(expected);
  function expire(changed = false) {
    if (stopped) return;
    epoch++;
    pauseAccountSession(admin); activeAt = -Infinity;
    notify(changed ? "changed" : "expired");
  }
  function accept(next, recovered = false) {
    if (stopped) return;
    if (!samePrincipal(expected, next, admin)) { expire(true); return; }
    const replaced = expected.csrf_token !== next.csrf_token;
    const wasPaused = accountSessionPaused(admin);
    expected = next; deadlines(next); retryAt = 0; failures = 0;
    setAccountSession(next, admin); notify("active");
    if (recovered || wasPaused || replaced) onRecovered(next);
  }
  const broadcast = type => {
    try { channel?.postMessage({ type, scope, started: expected.session_started_at }); } catch { /* No storage fallback with credentials. */ }
  };
  async function perform(probe = false) {
    if (stopped || pending) return pending;
    const captured = currentAccountSession(admin);
    const capturedEpoch = epoch;
    controller = new AbortController();
    const signal = controller.signal;
    const timer = windowTarget.setTimeout(() => controller?.abort(), 12000);
    const work = async () => {
      try {
        const next = await request(probe ? (admin ? "/admin/session" : "/session") : `${admin ? "/admin" : ""}/auth/refresh`, {
          ...(probe ? {} : { method: "POST" }), signal,
        });
        if (stopped || capturedEpoch !== epoch || captured !== currentAccountSession(admin)) return;
        // A revocation received while renewal was in flight cannot be undone by
        // its older response. Recovery requires a new explicit session probe.
        if (!probe && accountSessionPaused(admin)) return;
        accept(next);
        if (!probe && !accountSessionPaused(admin)) broadcast("renewed");
      } catch (error) {
        if (stopped || capturedEpoch !== epoch || captured !== currentAccountSession(admin)) return;
        if (error.status === 401) expire();
        else if (error.code === "session_changed") expire(true);
        else {
          failures++; retryAt = now() + Math.min(60000, 5000 * 2 ** Math.min(failures - 1, 4));
          if (!accountSessionPaused(admin)) notify("offline");
          // A same-user login in another tab changes CSRF. Read the current
          // authenticated identity before considering any further write.
          if (error.code === "csrf_invalid") lastProbe = -Infinity;
        }
      } finally { windowTarget.clearTimeout(timer); controller = null; }
    };
    pending = work();
    try { await pending; } finally { pending = null; }
  }
  async function probe(force = false) {
    if (stopped || pending || !visible() || now() < retryAt || (!force && now() - lastProbe < 30000)) return;
    lastProbe = now(); await perform(true);
  }
  async function tick() {
    if (stopped || pending || !visible() || accountSessionPaused(admin) || now() < retryAt) return;
    if (now() + offset >= expiresAt || health === "offline") { await probe(); return; }
    if (now() - activeAt > RENEW_INTERVAL_MS || now() + offset < renewAt) return;
    const renew = async () => {
      if (stopped || accountSessionPaused(admin) || now() + offset < renewAt) return;
      activeAt = -Infinity; await perform();
    };
    // Cross-tab lock prevents overlapping requests; the server's five-minute
    // window also handles browsers without Web Locks or BroadcastChannel.
    if (windowTarget.navigator?.locks?.request) {
      try { await windowTarget.navigator.locks.request(`viraldna-renew:${scope}`, { ifAvailable: true }, lock => lock && renew()); }
      catch { if (!stopped) await renew(); }
    } else await renew();
  }
  function activity(event) {
    if (event?.isTrusted === false || !visible() || accountSessionPaused(admin)) return;
    activeAt = now(); void tick();
  }
  function wake() { if (!visible()) activeAt = -Infinity; else void probe(); }
  function message(event) {
    const data = event.data;
    if (data?.scope !== scope || !["renewed", "recovered"].includes(data.type)) return;
    // Query server truth rather than trusting another tab's timing or identity.
    if (data.type === "recovered" || (!accountSessionPaused(admin) && data.started === expected.session_started_at)) void probe(true);
  }
  const events = ["pointerdown", "keydown", "input", "wheel", "touchstart", "touchmove", "dragend"];
  for (const name of events) documentTarget.addEventListener(name, activity, { passive: true, capture: true });
  documentTarget.addEventListener("visibilitychange", wake);
  for (const name of ["focus", "pageshow", "online"]) windowTarget.addEventListener(name, wake);
  channel?.addEventListener("message", message);
  const timer = windowTarget.setInterval(() => { void tick(); }, 15000);
  return {
    tick, expire, retry: () => { retryAt = 0; return probe(true); },
    recover(next) { epoch++; accept(next, true); if (!accountSessionPaused(admin)) broadcast("recovered"); },
    stop() {
      stopped = true; controller?.abort(); windowTarget.clearInterval(timer);
      for (const name of events) documentTarget.removeEventListener(name, activity, true);
      documentTarget.removeEventListener("visibilitychange", wake);
      for (const name of ["focus", "pageshow", "online"]) windowTarget.removeEventListener(name, wake);
      channel?.removeEventListener("message", message); channel?.close();
    },
  };
}
