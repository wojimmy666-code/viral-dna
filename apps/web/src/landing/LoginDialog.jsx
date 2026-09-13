import { Component, lazy, Suspense, useEffect, useRef } from "react";
import { X } from "@phosphor-icons/react";
import "./login.css";

const PublicLoginForm = lazy(() => import("./PublicLoginForm.jsx"));

class LoginLoadBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <div className="vd-login-status" role="alert"><p>登录组件暂时无法加载，请重新加载页面。</p><button type="button" className="vd-login-retry" onClick={() => window.location.reload()}>重新加载</button></div> : this.props.children;
  }
}

export default function LoginDialog({ onClose }) {
  const dialog = useRef(null), heading = useRef(null), close = useRef(onClose);
  const backdropPress = useRef(false);
  close.current = onClose;
  useEffect(() => {
    const element = dialog.current;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    const canvas = document.documentElement;
    const previousGutter = canvas.style.scrollbarGutter;
    const previousBackground = canvas.style.backgroundColor;
    const previousScheme = canvas.style.colorScheme;
    // A reserved scrollbar gutter belongs to the root canvas, not the homepage.
    // Keep it dark while locked, then restore the independent app's canvas.
    canvas.style.backgroundColor = getComputedStyle(element).getPropertyValue("--home-ground");
    canvas.style.colorScheme = "dark";
    canvas.style.scrollbarGutter = "stable";
    document.body.style.overflow = "hidden";
    element.showModal();
    heading.current.focus({ preventScroll: true });
    const viewport = window.visualViewport;
    const resize = () => {
      element.style.setProperty("--login-viewport-height", `${viewport?.height ?? window.innerHeight}px`);
      element.style.setProperty("--login-viewport-top", `${viewport?.offsetTop ?? 0}px`);
    };
    resize(); viewport?.addEventListener("resize", resize); viewport?.addEventListener("scroll", resize);
    return () => {
      viewport?.removeEventListener("resize", resize); viewport?.removeEventListener("scroll", resize);
      element.close();
      document.body.style.overflow = previousOverflow;
      canvas.style.scrollbarGutter = previousGutter;
      canvas.style.backgroundColor = previousBackground;
      canvas.style.colorScheme = previousScheme;
      if (window.location.pathname === "/") {
        const target = previousFocus?.isConnected && previousFocus !== document.body ? previousFocus : document.querySelector(".vd-nav-cta");
        target?.focus({ preventScroll: true });
      }
    };
  }, []);
  const outside = event => {
    const rect = dialog.current.getBoundingClientRect();
    return event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom;
  };
  const trapTab = event => {
    if (event.key !== "Tab") return;
    const items = [...dialog.current.querySelectorAll('button, input, a[href], [tabindex="0"]')]
      .filter(item => !item.matches(":disabled") && item.getClientRects().length);
    const first = items[0], last = items.at(-1), active = document.activeElement;
    if (!first) { event.preventDefault(); heading.current.focus(); return; }
    if (!items.includes(active) || (event.shiftKey ? active === first : active === last)) {
      event.preventDefault(); (event.shiftKey ? last : first).focus();
    }
  };
  return <dialog ref={dialog} className="vd-login" aria-labelledby="vd-login-title" aria-describedby="vd-login-help"
    onKeyDown={trapTab}
    onCancel={event => { event.preventDefault(); close.current(); }}
    onPointerDown={event => { backdropPress.current = event.target === dialog.current && outside(event); }}
    onClick={event => { if (backdropPress.current && event.target === dialog.current && outside(event)) close.current(); backdropPress.current = false; }}>
    <header className="vd-login-heading"><span className="vd-login-brand"><img src="/favicon.svg" width="32" height="32" alt="" />ViralDNA</span><button type="button" className="vd-icon-button vd-login-close" aria-label="关闭登录" onClick={() => close.current()}><X size={22} /></button></header>
    <h2 ref={heading} tabIndex={-1} id="vd-login-title">登录创作台</h2>
    <LoginLoadBoundary><Suspense fallback={<p className="vd-login-status" role="status">正在加载登录…</p>}><PublicLoginForm /></Suspense></LoginLoadBoundary>
    <p className="vd-login-help" id="vd-login-help">开通或重置密码，请联系管理员。</p>
  </dialog>;
}
