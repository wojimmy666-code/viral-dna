export function groupModelOptions(models = []) {
  return models.filter(model => model.available && model.capabilities?.multi_image_reference && model.capabilities?.ordered_reference_images);
}

export function groupDefinition(group) {
  return { id: group.id, shot_plan_ids: group.shot_plan_ids, video_prompt: group.video_prompt || "", transition: group.transition || "cut" };
}

export function suggestedGroups(shots, model, excluded = new Set()) {
  const cap = model?.capabilities;
  if (!cap?.ordered_reference_images) return [];
  const groups = [];
  let batch = [], seconds = 0, images = 0;
  const emit = () => { if (batch.length > 1) groups.push(batch); batch = []; seconds = 0; images = 0; };
  for (const row of shots) {
    const plan = row.plan || row;
    if (excluded.has(plan.id)) { emit(); continue; }
    const count = (plan.visual_beats || []).filter(beat => beat.approved_image_candidate_id).length;
    if (!count || count > cap.maximum_reference_images || plan.duration_seconds >= cap.minimum_duration_seconds) { emit(); continue; }
    if (seconds + plan.duration_seconds > cap.maximum_duration_seconds || images + count > cap.maximum_reference_images) emit();
    batch.push(plan.id); seconds += plan.duration_seconds; images += count;
    if (seconds >= cap.minimum_duration_seconds) emit();
  }
  emit();
  return groups;
}

export function plannedCuts(shots, actualDuration) {
  let cursor = 0;
  const target = shots.reduce((total, shot) => total + shot.duration_seconds, 0);
  return shots.map(shot => {
    const start = target > 0 ? cursor / target * actualDuration : 0;
    cursor += shot.duration_seconds;
    const segmentEnd = target > 0 ? cursor / target * actualDuration : 0;
    return { shot_plan_id: shot.id, trim_in_seconds: Number(start.toFixed(3)), trim_out_seconds: Number(Math.min(start + shot.duration_seconds, segmentEnd).toFixed(3)) };
  });
}

export function cutsValid(cuts, actualDuration) {
  let end = 0;
  return cuts.length > 0 && Number.isFinite(actualDuration) && cuts.every(cut => {
    const start = Number(cut.trim_in_seconds), stop = Number(cut.trim_out_seconds);
    const valid = cut.trim_in_seconds !== "" && cut.trim_out_seconds !== "" && Number.isFinite(start) && Number.isFinite(stop) && start >= end && stop > start && stop <= actualDuration;
    end = stop;
    return valid;
  });
}
