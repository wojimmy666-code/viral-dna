// Membership is frozen by the server on explicit image -> video entry. Never
// infer it from the current thumbnails, previews, required flags or adoptions.
export function videoStageShots(shots, project) {
  const ids = Array.isArray(project?.video_stage_shot_ids)
    ? new Set(project.video_stage_shot_ids) : null;
  return (shots || []).filter(item => item.plan.lifecycle_status !== "discarded"
    && (!ids || ids.has(item.plan.id)));
}

export function workspaceShotId(shots, project, section, preferredShotId) {
  const available = section === "shot_videos" ? videoStageShots(shots, project)
    : (shots || []).filter(item => item.plan.lifecycle_status !== "discarded");
  return available.some(item => item.plan.id === preferredShotId)
    ? preferredShotId : available[0]?.plan.id || null;
}
