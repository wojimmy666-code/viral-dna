export function parsePromptSource(value) {
  if (value === "scheme") return { kind: "scheme", id: "", key: "scheme" };
  const match = /^(production|concept):([0-9a-f-]{36})$/i.exec(value || "");
  return match ? { kind: match[1], id: match[2], key: value } : { kind: "source", id: "", key: "source" };
}

export function promptDocumentBody(document) {
  return {
    expected_token: document.token,
    common_image_prompt: document.common_image_prompt,
    common_video_prompt: document.common_video_prompt,
    shots: document.shots.map(shot => ({
      id: shot.id,
      images: shot.images.map(({ id, prompt, negative_constraints }) => ({ id, prompt, negative_constraints })),
      video_prompt: shot.video_prompt,
      video_negative_constraints: shot.video_negative_constraints,
    })),
  };
}

export function productionPromptsToText(document) {
  const lines = [document.name, `方案提示词 · ${document.shots.length} 个分镜`];
  if (document.common_image_prompt) lines.push("", "全局图片提示词", document.common_image_prompt);
  if (document.common_video_prompt) lines.push("", "全局视频提示词", document.common_video_prompt);
  for (const shot of document.shots) {
    lines.push("", `分镜 ${shot.index} · ${Number(shot.duration_seconds.toFixed(2))} 秒`);
    shot.images.forEach((image, index) => {
      lines.push(`图片提示词${shot.images.length > 1 ? ` ${index + 1}` : ""}`, image.prompt);
      if (image.negative_constraints.length) lines.push("图片负面约束：" + image.negative_constraints.join("；"));
    });
    if (!shot.video_group_id) {
      lines.push("视频提示词", shot.video_prompt);
      if (shot.video_negative_constraints.length) lines.push("视频负面约束：" + shot.video_negative_constraints.join("；"));
    } else lines.push("视频按生成组执行，见下方合并提示词");
  }
  for (const [index, group] of (document.video_groups || []).entries()) {
    lines.push("", `视频生成组 ${index + 1} · ${group.shot_plan_ids.length} 个分镜 → 1 段视频`, group.compiled_prompt);
    if (group.error) lines.push(`尚未就绪：${group.error}`);
    if (group.negative_constraints?.length) lines.push("视频负面约束：" + group.negative_constraints.join("；"));
  }
  return lines.join("\n");
}

export function downloadProductionPrompts(document) {
  const url = URL.createObjectURL(new Blob(["\uFEFF", productionPromptsToText(document)], { type: "text/plain;charset=utf-8" }));
  const link = window.document.createElement("a");
  link.href = url;
  link.download = `${document.name.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")}-方案提示词.txt`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
