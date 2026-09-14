import { createContext, useContext, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { WorkbenchBrand } from "./WorkbenchBrand.jsx";

const HeaderSlots = createContext(null);

// The account shell owns the only header. Workbench controls keep their state
// and event handlers in the workbench, including its original inert boundary.
export function AccountHeader({ identity, accountMenu, toolbarDisabled, onHomeNavigation, children }) {
  const [navigation, setNavigation] = useState(null);
  const [search, setSearch] = useState(null);
  const [actions, setActions] = useState(null);
  const slots = useMemo(() => ({ navigation, search, actions }), [navigation, search, actions]);
  return <HeaderSlots.Provider value={slots}>
    <header className="account-session-bar" aria-label="账户与工作台">
      <WorkbenchBrand onNavigate={onHomeNavigation} />
      <div className="account-header-navigation" ref={setNavigation} inert={toolbarDisabled} />
      {identity}
      <div className="account-header-search" ref={setSearch} inert={toolbarDisabled} />
      <div className="account-header-actions" ref={setActions} inert={toolbarDisabled} />
      {accountMenu}
    </header>
    {children}
  </HeaderSlots.Provider>;
}

export function AccountHeaderToolbar({ navigation, search, actions, className }) {
  const slots = useContext(HeaderSlots);
  // Standalone/legacy workbenches do not have a password-account shell.
  if (!slots) return <header className={className}><WorkbenchBrand />{navigation}{search}{actions}</header>;
  if (!slots.navigation || !slots.search || !slots.actions) return null;
  return <>
    {createPortal(navigation, slots.navigation, "navigation")}
    {createPortal(search, slots.search, "search")}
    {createPortal(actions, slots.actions, "actions")}
  </>;
}
