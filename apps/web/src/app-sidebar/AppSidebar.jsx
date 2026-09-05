import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { CaretDown, Gear, LinkSimple, Play, ShieldCheck, SidebarSimple, X } from "@phosphor-icons/react";
import { RECORD_LIFECYCLES, RECORD_LIFECYCLE_META } from "../record-lifecycle-ui.js";
import "./app-sidebar.css";

function Brand() {
  return <div className="brand">
    <span className="brand-mark" aria-hidden="true"><Play size={18} weight="fill" /></span>
    <span className="brand-copy"><strong>ViralDNA</strong><small>视频逆向拆解系统</small></span>
  </div>;
}

function LifecycleLinks({ active, counts, onSelect, inProject }) {
  return <div className="history-lifecycle-nav" aria-label="项目范围">
    {RECORD_LIFECYCLES.map((lifecycle) => (
      <button
        aria-current={!inProject && active === lifecycle ? "page" : undefined}
        className={!inProject && active === lifecycle ? "active" : ""}
        key={lifecycle}
        onClick={() => onSelect(lifecycle)}
        type="button"
      >
        <span>{RECORD_LIFECYCLE_META[lifecycle].label}</span>
        <small>{counts?.[lifecycle] || 0}</small>
      </button>
    ))}
  </div>;
}

// The native popover stays next to its trigger in the keyboard order, while its
// top-layer rendering escapes the sidebar's scrolling container.
function NavigationItem({ item, active, collapsed, count, onSelect, children, routeKey }) {
  const Icon = item.icon;
  const groupRef = useRef(null);
  const buttonRef = useRef(null);
  const hintRef = useRef(null);
  const closeTimer = useRef(null);
  const hintId = useId();
  const [hintOpen, setHintOpen] = useState(false);

  function cancelClose() { window.clearTimeout(closeTimer.current); }
  function hideHint() {
    cancelClose();
    if (hintRef.current?.matches(":popover-open")) hintRef.current.hidePopover();
    setHintOpen(false);
  }
  function showHint(focusFirst = false) {
    if (!collapsed || !hintRef.current || !buttonRef.current) return;
    cancelClose();
    const hint = hintRef.current;
    if (!hint.matches(":popover-open")) hint.showPopover();
    const anchor = buttonRef.current.getBoundingClientRect();
    const railEdge = groupRef.current.closest(".sidebar").getBoundingClientRect().right;
    hint.style.left = `${Math.min(railEdge + 8, window.innerWidth - hint.offsetWidth - 8)}px`;
    hint.style.top = `${Math.max(8, Math.min(anchor.top, window.innerHeight - hint.offsetHeight - 8))}px`;
    if (focusFirst) hint.querySelector("button")?.focus();
  }
  function scheduleClose() {
    cancelClose();
    closeTimer.current = window.setTimeout(() => {
      if (!groupRef.current?.contains(document.activeElement)) hideHint();
    }, 150);
  }

  useEffect(() => {
    hideHint();
    // Route changes dismiss hints, but never reset the sidebar preference.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeKey, collapsed]);
  useEffect(() => {
    const dismiss = () => hideHint();
    window.addEventListener("resize", dismiss);
    // Only sidebar scrolling invalidates the anchor (not scrolling a flyout).
    const scrollContainer = groupRef.current?.closest(".side-nav");
    scrollContainer?.addEventListener("scroll", dismiss);
    return () => {
      cancelClose();
      window.removeEventListener("resize", dismiss);
      scrollContainer?.removeEventListener("scroll", dismiss);
    };
  }, []);

  return <div
    className={`nav-group ${item.id === "history" ? "history-nav-group" : ""}`}
    ref={groupRef}
    onPointerEnter={(event) => { if (event.pointerType !== "touch") showHint(); }}
    onPointerLeave={scheduleClose}
    onFocus={() => showHint()}
    onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) hideHint(); }}
  >
    <button
      aria-label={item.label}
      aria-current={active ? "page" : undefined}
      aria-expanded={collapsed && children ? hintOpen : undefined}
      aria-controls={collapsed && children ? hintId : undefined}
      className={`nav-item ${active ? "active" : ""} ${item.id === "new-analysis" ? "nav-create" : ""}`}
      onClick={() => { hideHint(); onSelect(item.id); }}
      onKeyDown={(event) => {
        if (collapsed && children && event.key === "ArrowRight") {
          event.preventDefault();
          showHint(true);
        }
      }}
      ref={buttonRef}
      type="button"
    >
      <Icon aria-hidden="true" size={20} weight={active ? "fill" : "regular"} />
      <span className="nav-label">{item.label}</span>
      {count !== undefined && <span className="nav-count" aria-hidden="true">{count || 0}</span>}
    </button>
    {collapsed && children && <button
      aria-label="选择项目范围"
      aria-controls={hintId}
      aria-expanded={hintOpen}
      className="nav-item nav-scope-toggle"
      onClick={() => showHint(true)}
      type="button"
    ><CaretDown aria-hidden="true" size={18} /></button>}
    {!collapsed && children}
    {collapsed && <div
      className={`sidebar-hint ${children ? "sidebar-project-flyout" : ""}`}
      id={hintId}
      popover="auto"
      ref={hintRef}
      role={children ? undefined : "tooltip"}
      onToggle={(event) => setHintOpen(event.newState === "open" || event.nativeEvent?.newState === "open")}
      onKeyDown={(event) => {
        if (children && ["ArrowLeft", "Escape"].includes(event.key)) {
          event.preventDefault();
          event.stopPropagation();
          buttonRef.current?.focus();
          hideHint();
        }
      }}
    >
      {children ? <><strong className="sidebar-flyout-title">项目</strong>{children}</> : item.label}
    </div>}
  </div>;
}

export function AppSidebar({
  activeNav, historyLifecycle, historyLifecycleCounts, historyCount, navItems,
  onSelect, onSelectHistoryLifecycle, collapsed, onToggle, routeKey, inProject,
  mobileOpen, onCloseMobile,
}) {
  const dialogRef = useRef(null);
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 820px)").matches);
  const compact = collapsed && !narrow;

  useEffect(() => {
    const query = window.matchMedia("(max-width: 820px)");
    const update = () => setNarrow(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!narrow) onCloseMobile();
  }, [narrow, onCloseMobile]);

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (narrow && mobileOpen) {
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) dialog.close();
  }, [narrow, mobileOpen]);

  useEffect(() => {
    if (!narrow || !mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, [narrow, mobileOpen]);

  function select(id) { onCloseMobile(); onSelect(id); }
  function selectLifecycle(lifecycle) { onCloseMobile(); onSelectHistoryLifecycle(lifecycle); }
  const lifecycleLinks = <LifecycleLinks active={historyLifecycle} counts={historyLifecycleCounts} onSelect={selectLifecycle} inProject={inProject} />;
  const contents = <>
    <div className="sidebar-heading">
      <Brand />
      <button
        aria-label={narrow ? "关闭导航" : compact ? "展开侧边栏" : "收起侧边栏"}
        aria-expanded={narrow ? mobileOpen : !compact}
        aria-controls="app-primary-navigation"
        className="sidebar-toggle"
        onClick={narrow ? onCloseMobile : onToggle}
        title={narrow ? "关闭导航" : compact ? "展开侧边栏" : "收起侧边栏"}
        type="button"
      >
        {narrow ? <X size={20} /> : <SidebarSimple size={20} />}
      </button>
    </div>
    <nav className="side-nav" id="app-primary-navigation" aria-label="主导航">
      <p className="nav-section-label">创作研究</p>
      {navItems.map((item) => <NavigationItem
        active={activeNav === item.id}
        collapsed={compact}
        count={item.id === "history" ? historyCount : undefined}
        item={item}
        key={item.id}
        onSelect={select}
        routeKey={routeKey}
      >
        {item.id === "history" && (compact || narrow || activeNav === "history") ? lifecycleLinks : null}
      </NavigationItem>)}
      <div className="nav-divider" />
      <p className="nav-section-label">系统</p>
      <NavigationItem active={activeNav === "platform-connections"} collapsed={compact} item={{ id: "platform-connections", label: "平台连接", icon: LinkSimple }} onSelect={select} routeKey={routeKey} />
      <NavigationItem active={activeNav === "settings"} collapsed={compact} item={{ id: "settings", label: "模型与设置", icon: Gear }} onSelect={select} routeKey={routeKey} />
    </nav>
    <div className="sidebar-footer" title={compact ? "内测环境 · 混合分析引擎已启用" : undefined}>
      <span className="environment-icon" role="img" aria-label="内测环境，混合分析引擎已启用"><ShieldCheck size={20} /></span>
      <span className="sidebar-footer-copy"><strong>内测环境</strong><small>混合分析引擎已启用</small></span>
    </div>
  </>;

  if (narrow) return <dialog
    aria-label="主导航"
    className="app-navigation-drawer"
    id="app-navigation-drawer"
    onCancel={onCloseMobile}
    onClose={onCloseMobile}
    onKeyDown={(event) => {
      if (event.key !== "Tab") return;
      const controls = [...event.currentTarget.querySelectorAll("button:not(:disabled), a[href]")]
        .filter((element) => element.getClientRects().length > 0);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }}
    onClick={(event) => {
      if (event.target !== event.currentTarget) return;
      const box = event.currentTarget.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) onCloseMobile();
    }}
    ref={dialogRef}
  ><aside className="sidebar sidebar-mobile">{contents}</aside></dialog>;

  return <aside className={`sidebar ${compact ? "sidebar-collapsed" : ""}`}>{contents}</aside>;
}
