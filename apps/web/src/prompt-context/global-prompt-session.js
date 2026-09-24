function promptValues(revision) {
  return {
    common_image_prompt: revision.common_image_prompt, common_video_prompt: revision.common_video_prompt,
    ...(Object.hasOwn(revision, "visual_style") ? {
      visual_style: revision.visual_style, visual_style_snapshot: revision.visual_style_snapshot || {},
      shot_styles: revision.shot_styles || {}, shot_style_snapshots: revision.shot_style_snapshots || {},
    } : {}),
  };
}

export function createGlobalPromptSession(initial, { save, onChange }) {
  let revision = initial;
  let values = promptValues(initial);
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
    restoreStyles(cached) {
      if (!Object.hasOwn(cached, "visual_style") || !Object.hasOwn(initial, "visual_style")) return;
      const restored = promptValues(cached);
      values = { ...values, visual_style: restored.visual_style, visual_style_snapshot: restored.visual_style_snapshot,
        shot_styles: restored.shot_styles, shot_style_snapshots: restored.shot_style_snapshots };
      edited++; status = "dirty"; error = ""; notify();
    },
    editStyle(value, compiled, shotKey) {
      if (shotKey) {
        const styles = { ...values.shot_styles }, snapshots = { ...values.shot_style_snapshots };
        if (value === null) { delete styles[shotKey]; delete snapshots[shotKey]; }
        else { styles[shotKey] = value; snapshots[shotKey] = compiled; }
        values = { ...values, shot_styles: styles, shot_style_snapshots: snapshots };
      } else values = { ...values, visual_style: value, visual_style_snapshot: compiled };
      edited++; status = "dirty"; error = ""; notify();
    },
    flush() {
      if (pending) return pending;
      if (edited === saved) return Promise.resolve(true);
      pending = Promise.resolve().then(async () => {
        try {
          while (edited !== saved) {
            const version = edited;
            const { visual_style_snapshot, shot_style_snapshots, ...fields } = values;
            const payload = { expected_revision_id: revision.id, ...fields };
            status = "saving"; error = ""; notify();
            revision = await save(payload);
            saved = version;
            if (edited === version) values = promptValues(revision);
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
