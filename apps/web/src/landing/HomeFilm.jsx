import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { FILM_SCENES, HOME_FILM, filmSceneAtTime } from "./home-media.js";

// One continuous, stream-copy film avoids loading another file at each cut.
// The decoded frame replaces the visible poster, never an empty black canvas.
export default forwardRef(function HomeFilm({
  playing, initialScene = 0, className = "", poster, posterUrl, controls = false,
  onSceneChange, onPlaybackChange, onBlocked, onFailure, onUserIntent,
}, ref) {
  const video = useRef(null);
  const pendingSeek = useRef(FILM_SCENES[initialScene]?.start ?? 0);
  const callbacks = useRef({});
  const [activated, setActivated] = useState(false);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  callbacks.current = { onSceneChange, onPlaybackChange, onBlocked, onFailure, onUserIntent, playing };

  function applySeek() {
    const element = video.current;
    if (pendingSeek.current === null || !element || element.readyState < 1) return;
    try {
      element.currentTime = pendingSeek.current;
      pendingSeek.current = null;
    } catch { /* Keep the requested chapter until metadata becomes available. */ }
  }

  useImperativeHandle(ref, () => ({
    seekToScene(index) {
      if (!FILM_SCENES[index]) return;
      pendingSeek.current = FILM_SCENES[index].start;
      // In reduced-motion/data-saving mode selecting a poster does not load video.
      applySeek();
    },
    retry() {
      setFailed(false);
      callbacks.current.onFailure?.(false);
      setActivated(true);
      setAttempt(current => current + 1);
    },
  }), []);

  useEffect(() => { if (playing) setActivated(true); }, [playing]);
  useEffect(() => {
    const element = video.current;
    let cancelled = false;
    if (!element || !activated || !playing || failed) {
      element?.pause();
      return;
    }
    element.muted = true;
    if (attempt && element.error) element.load();
    applySeek();
    const play = async () => {
      try { await element.play(); }
      catch (error) {
        if (cancelled || error?.name === "AbortError") return;
        callbacks.current.onPlaybackChange?.(false);
        callbacks.current.onBlocked?.();
      }
    };
    void play();
    return () => { cancelled = true; element.pause(); };
  }, [activated, playing, failed, attempt]);

  return <div className={`vd-film ${className}`} data-ready={ready && !failed ? "true" : "false"} data-failed={failed ? "true" : "false"}>
    {poster}
    <video ref={video} src={activated ? HOME_FILM.src : undefined} poster={posterUrl}
      width={HOME_FILM.width} height={HOME_FILM.height} muted playsInline loop preload="none"
      controls={controls} aria-label={controls ? "琥珀瓶视觉示意短片，静音" : "首页琥珀瓶视觉示意视频"}
      aria-hidden={controls ? undefined : true} tabIndex={controls ? 0 : -1}
      onLoadedMetadata={applySeek}
      onLoadedData={() => { applySeek(); setReady(true); }}
      onSeeked={() => { setReady(true); callbacks.current.onSceneChange?.(filmSceneAtTime(video.current.currentTime)); }}
      onTimeUpdate={() => { if (pendingSeek.current === null) callbacks.current.onSceneChange?.(filmSceneAtTime(video.current.currentTime)); }}
      onPlaying={() => { setReady(true); callbacks.current.onPlaybackChange?.(true); if (controls) callbacks.current.onUserIntent?.(true); }}
      onPause={() => { callbacks.current.onPlaybackChange?.(false); if (controls && callbacks.current.playing) callbacks.current.onUserIntent?.(false); }}
      onError={() => { setFailed(true); setReady(false); callbacks.current.onPlaybackChange?.(false); callbacks.current.onFailure?.(true); callbacks.current.onBlocked?.(); }} />
  </div>;
});
