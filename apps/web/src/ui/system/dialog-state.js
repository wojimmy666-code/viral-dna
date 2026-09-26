// A dialog owns one explicit decision, never a queue of stale confirmations.
// Kept DOM-free so request counts, cancellation and late responses are testable.
export function createDialogController({ getScope, getInput, captureAuthority, checkAuthority, notify, timeoutMs = 60000 }) {
  let current = null;
  let alive = true;
  const publish = () => { if (alive) notify(current ? { ...current } : null); };
  function finish(decision, result) {
    if (current !== decision) return;
    current = null;
    decision.resolve(result);
    publish();
  }
  function assertCurrent(decision, includeInput = false) {
    if (!alive || current !== decision || decision.scope !== getScope()
      || (includeInput && decision.input !== getInput()) || !checkAuthority(decision.authority)) {
      throw new Error('页面、输入或编辑权限已变化，请取消后重新打开并核对。');
    }
  }
  return {
    activate() { alive = true; },
    open(options) {
      if (!alive || current) return Promise.resolve(false);
      return new Promise(resolve => {
        current = { ...options, scope: getScope(), input: getInput(), authority: captureAuthority(),
          resolve, busy: false, error: '', uncertain: false, accepted: false };
        publish();
      });
    },
    cancel() { if (current && !current.busy) finish(current, false); },
    async submit(value) {
      const decision = current;
      if (!decision || decision.busy || decision.uncertain) return;
      try { assertCurrent(decision, true); }
      catch (failure) { decision.error = failure.message; publish(); return; }
      decision.busy = true; decision.error = ''; publish();
      try {
        const result = await decision.onConfirm({ value, assertCurrent: () => assertCurrent(decision),
          // Only the final business write uses mutate. Draft saves retain their
          // existing guards. A lost reply must never become a fresh paid request.
          mutate: async (request, { retrySafe = false } = {}) => {
            assertCurrent(decision);
            let timer;
            try {
              const response = await Promise.race([
                Promise.resolve().then(() => { assertCurrent(decision); return request(); }),
                new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('等待提交结果超时，请先核对任务或列表。')), timeoutMs); }),
              ]);
              decision.accepted = true;
              assertCurrent(decision);
              return response;
            } catch (failure) {
              if (!retrySafe && !(failure.status >= 400 && failure.status < 500)) decision.uncertain = true;
              throw failure;
            } finally { clearTimeout(timer); }
          },
        });
        if (result === false && !decision.accepted) throw new Error('操作未完成，请核对后重试。');
        finish(decision, result === undefined ? true : result);
      } catch (failure) {
        if (alive && current === decision) decision.onError?.(failure);
        // A successful write followed by a refresh failure is not permission to
        // send the write again. The caller continues to report refresh failures.
        if (decision.accepted) { finish(decision, true); return; }
        if (current === decision) {
          decision.error = failure.message || '操作未完成，请重试。';
          decision.busy = false; publish();
        }
      }
    },
    dispose() {
      alive = false;
      if (current) { current.resolve(false); current = null; }
    },
  };
}
