export function storyboardDraftShots(manifest) {
  return (manifest?.shots || []).map((shot) => ({
    stable_shot_key: shot.stable_shot_key,
    image_prompt_body: shot.image_prompt_body ?? shot.image_prompt ?? "",
    video_prompt_body: shot.video_prompt_body ?? shot.video_prompt ?? "",
  }));
}

export function storyboardDraftIssues(shots) {
  if (!shots.length) return ["请至少添加一个分镜"];
  return shots.flatMap((shot, index) => [
    !shot.image_prompt_body.trim() && `分镜 ${index + 1} 的图片提示词尚未填写`,
    !shot.video_prompt_body.trim() && `分镜 ${index + 1} 的视频提示词尚未填写`,
  ].filter(Boolean));
}

export function newStoryboardShot() {
  const token = globalThis.crypto?.randomUUID?.().replaceAll("-", "")
    || `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}${Math.random().toString(16).slice(2)}`;
  return {
    stable_shot_key: `shot_${token}`,
    image_prompt_body: "",
    video_prompt_body: "",
  };
}

// One serialized writer. A flush waits for *all* edits made during an in-flight save.
// A failed request retains the draft and its base revision, and never retries in a loop.
export function createStoryboardDraftSession(initialManifest, { save, onChange, onSaved }) {
  let manifest = initialManifest;
  let shots = storyboardDraftShots(manifest);
  let editVersion = 0;
  let savedVersion = 0;
  let status = "saved";
  let error = "";
  let pending = null;
  const snapshot = () => ({ manifest, shots, status, error, dirty: editVersion !== savedVersion });
  const notify = () => onChange?.(snapshot());
  return {
    snapshot,
    hydrate(next) {
      if (editVersion !== savedVersion || pending || next.id === manifest.id || next.revision_number < manifest.revision_number) return;
      manifest = next;
      shots = storyboardDraftShots(next);
      notify();
    },
    edit(update) {
      shots = typeof update === "function" ? update(shots) : update;
      editVersion += 1;
      status = "dirty";
      error = "";
      notify();
    },
    flush() {
      if (pending) return pending;
      if (editVersion === savedVersion) return Promise.resolve(true);
      pending = Promise.resolve().then(async () => {
        try {
          while (editVersion !== savedVersion) {
            const version = editVersion;
            const payload = { expected_revision_id: manifest.id, shots };
            status = "saving";
            error = "";
            notify();
            manifest = await save(payload);
            savedVersion = version;
            if (editVersion === version) shots = storyboardDraftShots(manifest);
            onSaved?.(manifest);
          }
          status = "saved";
          notify();
          return true;
        } catch (failure) {
          error = failure.message || "保存失败，请重试";
          status = "error";
          notify();
          return false;
        }
      }).finally(() => { pending = null; });
      return pending;
    },
  };
}
