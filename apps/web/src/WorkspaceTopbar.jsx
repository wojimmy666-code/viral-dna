import { IconButton, Button } from "./ui/system/Button.jsx";
import { useEffect, useRef, useState } from "react";
import { Bell, List, MagnifyingGlass, Plus, SidebarSimple } from "@phosphor-icons/react";
import { AccountHeaderToolbar } from "./accounts/AccountHeader.jsx";

export function Topbar({
  navigationOpen = false, onOpenNavigation, assetMode = false, focusMode = false,
  sidebarCollapsed = false, onToggleSidebar,
  hideCreate = false, notificationOpen = false, notificationUnreadCount = 0,
  onCreate, onSearch, onToggleNotifications, searchValue,
}) {
  const primaryActionsHidden = assetMode || focusMode;
  const [searchOpen, setSearchOpen] = useState(false);
  const searchElement = useRef(null);
  useEffect(() => {
    if (!searchOpen) return;
    searchElement.current?.querySelector("input")?.focus();
    const outside = event => { if (!searchElement.current?.contains(event.target)) setSearchOpen(false); };
    const escape = event => {
      if (event.key !== "Escape") return;
      setSearchOpen(false); searchElement.current?.querySelector("button")?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [searchOpen]);
  useEffect(() => { if (primaryActionsHidden) setSearchOpen(false); }, [primaryActionsHidden]);

  const navigation = <>
    {onToggleSidebar && <IconButton className="icon-button desktop-sidebar-toggle" type="button"
      aria-label={sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"} aria-expanded={!sidebarCollapsed}
      aria-controls="app-primary-navigation" title={sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}
      onClick={onToggleSidebar}><SidebarSimple size={20} aria-hidden="true" /></IconButton>}
    <IconButton aria-label="打开导航" aria-expanded={navigationOpen}
    aria-controls="app-navigation-drawer" className="icon-button mobile-navigation-toggle"
    onClick={onOpenNavigation} type="button"><List size={22} aria-hidden="true" /></IconButton>
  </>;
  const search = !primaryActionsHidden ? <div ref={searchElement} className={`global-search ${searchOpen ? "search-expanded" : ""}`}>
    <MagnifyingGlass size={18} className="global-search-mark" aria-hidden="true" />
    <IconButton className="icon-button global-search-toggle" aria-label="打开项目搜索" aria-expanded={searchOpen}
      onClick={() => setSearchOpen(!searchOpen)} type="button"><MagnifyingGlass size={19} aria-hidden="true" /></IconButton>
    <input aria-label="搜索项目" onChange={event => onSearch(event.target.value)} placeholder="搜索项目或报告" value={searchValue} />
    <kbd>⌘ K</kbd>
  </div> : null;
  const actions = <div className="topbar-actions">
    <IconButton aria-expanded={notificationOpen}
      aria-label={notificationUnreadCount ? `通知，${notificationUnreadCount} 条未读` : "通知"}
      className={`icon-button notification-bell ${notificationOpen ? "active" : ""}`}
      onClick={onToggleNotifications} type="button">
      <Bell size={19} aria-hidden="true" />
      {notificationUnreadCount > 0 && <span className="notification-badge">{notificationUnreadCount > 9 ? "9+" : notificationUnreadCount}</span>}
    </IconButton>
    {!primaryActionsHidden && !hideCreate && <Button className="primary-button compact" type="button" onClick={onCreate}>
      <Plus size={17} weight="bold" />新建项目
    </Button>}
  </div>;
  return <AccountHeaderToolbar navigation={navigation} search={search} actions={actions}
    className={`topbar ${assetMode ? "asset-mode" : ""} ${focusMode ? "focus-mode" : ""}`} />;
}
