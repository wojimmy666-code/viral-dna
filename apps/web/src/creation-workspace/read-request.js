// Only coalesce concurrent reads. Do not cache mutations, failures or data across sessions.
const pendingByClient = new WeakMap();
export function readOnce(request, path) {
  let pending = pendingByClient.get(request);
  if (!pending) { pending = new Map(); pendingByClient.set(request, pending); }
  if (pending.has(path)) return pending.get(path);
  const promise = Promise.resolve().then(() => request(path)).finally(() => pending.delete(path));
  pending.set(path, promise);
  return promise;
}
