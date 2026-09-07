export function createGlobalPromptSession(initial, { save, onChange }) {
  let revision = initial;
  let values = { common_image_prompt: initial.common_image_prompt, common_video_prompt: initial.common_video_prompt };
  let edited = 0;
  let saved = 0;
  let pending;
  let status = "saved";
  let error = "";
  const snapshot = () => ({ revision, values, status, error, dirty: edited !== saved });
  const notify = () => onChange?.(snapshot());
  return {
    snapshot,
    edit(part, value) { values = { ...values, [`common_${part}_prompt`]: value }; edited++; status = "dirty"; error = ""; notify(); },
    flush() {
      if (pending) return pending;
      if (edited === saved) return Promise.resolve(true);
      pending = Promise.resolve().then(async () => {
        try {
          while (edited !== saved) {
            const version = edited;
            const payload = { expected_revision_id: revision.id, ...values };
            status = "saving"; error = ""; notify();
            revision = await save(payload);
            saved = version;
            if (edited === version) values = { common_image_prompt: revision.common_image_prompt, common_video_prompt: revision.common_video_prompt };
          }
          status = "saved"; notify(); return true;
        } catch (failure) {
          status = "error"; error = failure.message || "保存失败，请重试"; notify(); return false;
        }
      }).finally(() => { pending = null; });
      return pending;
    },
  };
}

export function combinePrompt(global, local) {
  return [global, local].map(value => (value || "").trim()).filter(Boolean).join("\n\n");
}
