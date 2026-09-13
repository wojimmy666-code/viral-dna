// Explicitly published homepage media. Never resolve from private account data.
// Each supplied shot has 121 frames at 24 fps; keep every original video frame.
export const HOME_FILM = Object.freeze({
  src: "/home/video/amber-film-v1.mp4",
  width: 1280,
  height: 720,
  frameRate: 24,
  duration: 363 / 24,
});

export const FILM_SCENES = Object.freeze([
  { label: "光线唤醒", image: "film-01", thumbnail: "film-01", start: 0, alt: "暖金侧光下，完整琥珀玻璃瓶立于黑色岩石上", detail: "缓慢推进，沿玻璃边缘发现产品的轮廓与光线。" },
  { label: "材质特写", image: "film-02", thumbnail: "film-02", start: 121 / 24, alt: "拉丝银色瓶盖与厚琥珀玻璃肩部的近景", detail: "靠近金属与玻璃，让细腻的材质成为画面主角。" },
  { label: "英雄定格", image: "film-03", thumbnail: "film-03", start: 242 / 24, alt: "暖金光线中的完整琥珀瓶，镜头缓缓退回岩石场景", detail: "回到完整产品，在稳定的画面中收束故事。" },
]);

export function filmSceneAtTime(time) {
  const seconds = Number.isFinite(time) ? Math.max(0, time) : 0;
  for (let index = FILM_SCENES.length - 1; index > 0; index--) {
    if (seconds >= FILM_SCENES[index].start) return index;
  }
  return 0;
}
