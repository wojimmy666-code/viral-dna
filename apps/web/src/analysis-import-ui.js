export const MAX_ANALYSIS_VIDEO_SECONDS = 120;

export const ANALYSIS_VIDEO_DURATION_ERROR = "仅支持 2 分钟以内的视频，请裁剪后重新导入。";

export function validateAnalysisVideoDuration(durationSeconds) {
  const duration = Number(durationSeconds);
  if (!Number.isFinite(duration) || duration <= 0) {
    return { valid: true, durationSeconds: null, message: "" };
  }
  return duration <= MAX_ANALYSIS_VIDEO_SECONDS
    ? { valid: true, durationSeconds: duration, message: "" }
    : {
        valid: false,
        durationSeconds: duration,
        message: ANALYSIS_VIDEO_DURATION_ERROR,
      };
}

export function readLocalVideoDuration(file) {
  if (!file || typeof document === "undefined" || typeof URL === "undefined") {
    return Promise.resolve(null);
  }
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    const objectUrl = URL.createObjectURL(file);
    const cleanup = () => {
      video.removeAttribute("src");
      URL.revokeObjectURL(objectUrl);
    };
    video.preload = "metadata";
    video.onloadedmetadata = () => {
      const duration = Number(video.duration);
      cleanup();
      resolve(Number.isFinite(duration) ? duration : null);
    };
    video.onerror = () => {
      cleanup();
      reject(new Error("无法读取视频时长"));
    };
    video.src = objectUrl;
  });
}
