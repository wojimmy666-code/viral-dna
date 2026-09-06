import { useCallback, useEffect, useId, useRef, useState } from "react";
import { FilmStrip, Pause, Play } from "@phosphor-icons/react";
import { claimSkillPreview, releaseSkillPreview, resolveSkillMediaUrl, skillCoverSources } from "./skill-presentation-ui.js";
import "./skill-presentation.css";

export function SkillCover({ skill, compact = false, onOpen }) {
  const owner = useId();
  const container = useRef(null);
  const videoRef = useRef(null);
  const timer = useRef(null);
  const [active, setActive] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState("");
  const [failedImages, setFailedImages] = useState([]);
  const sources = skillCoverSources(skill);
  const poster = sources.find(source => !failedImages.includes(source));
  const videoUrl = !compact && skill?.presentation?.video_url;
  const clearTimer = useCallback(() => { clearTimeout(timer.current); timer.current = null; }, []);
  const stop = useCallback(() => {
    clearTimer();
    videoRef.current?.pause();
    setActive(false);
    setPlaying(false);
    releaseSkillPreview(owner);
  }, [clearTimer, owner]);

  function start() {
    if (!videoUrl || document.hidden) return;
    clearTimer();
    claimSkillPreview(owner, stop);
    setError("");
    setActive(true);
  }

  function hover(event) {
    if (event.pointerType === "touch" || !videoUrl) return;
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    clearTimer();
    timer.current = setTimeout(start, 200);
  }

  useEffect(() => {
    stop();
    setError("");
    setFailedImages([]);
  }, [videoUrl, sources.join("|"), stop]);

  useEffect(() => {
    const hidden = () => { if (document.hidden) stop(); };
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    const observer = new IntersectionObserver(entries => { if (!entries[0]?.isIntersecting) stop(); });
    if (container.current) observer.observe(container.current);
    document.addEventListener("visibilitychange", hidden);
    reduce.addEventListener("change", stop);
    return () => { observer.disconnect(); document.removeEventListener("visibilitychange", hidden); reduce.removeEventListener("change", stop); clearTimer(); releaseSkillPreview(owner); };
  }, [clearTimer, owner, stop]);

  useEffect(() => {
    if (!active) return;
    const video = videoRef.current;
    let disposed = false;
    const fail = () => { if (!disposed) { stop(); setError("预览暂不可用，点击重试"); } };
    const play = () => { video.play()?.catch(fail); };
    video.addEventListener("canplay", play, { once: true });
    video.addEventListener("error", fail);
    if (!video.getAttribute("src")) video.src = resolveSkillMediaUrl(videoUrl);
    if (video.readyState >= 3) play();
    return () => {
      disposed = true;
      video.removeEventListener("canplay", play);
      video.removeEventListener("error", fail);
      video.pause();
      video.removeAttribute("src");
      video.load();
    };
  }, [active, stop, videoUrl]);

  return <div className={`skill-cover skill-media-cover${compact ? " is-compact" : ""}`} ref={container}
    onPointerEnter={hover} onPointerLeave={event => { if (event.pointerType !== "touch") stop(); }} onPointerCancel={stop}
    onKeyDown={event => { if (event.key === "Escape") stop(); }}>
    {poster ? <img alt={`${skill.name || "Skill"} 封面`} decoding="async" loading="lazy" src={resolveSkillMediaUrl(poster)} onError={() => setFailedImages(current => [...current, poster])} />
      : <div className="skill-cover-fallback" aria-hidden="true"><FilmStrip size={compact ? 28 : 42} weight="duotone" /><span>{skill.category}</span></div>}
    {active && videoUrl && <video aria-hidden="true" className={playing ? "is-playing" : ""} loop muted playsInline preload="auto" ref={videoRef} src={resolveSkillMediaUrl(videoUrl)} tabIndex={-1} onPlaying={() => setPlaying(true)} />}
    {onOpen && <button type="button" className="skill-cover-open" aria-label={`查看${skill.name || "Skill"}详情`} onClick={onOpen} />}
    {videoUrl && <button className="skill-preview-toggle" type="button" aria-label={`${active ? "停止" : "播放"}${skill.name || "Skill"}预览`} aria-pressed={active}
      onClick={event => { event.stopPropagation(); active ? stop() : start(); }}>{active ? <Pause size={18} weight="fill" /> : <Play size={18} weight="fill" />}</button>}
    {error && <span className="skill-preview-message" role="status">{error}</span>}
    {active && !playing && !error && <span className="skill-preview-message" role="status">正在加载预览…</span>}
  </div>;
}
