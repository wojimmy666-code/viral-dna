import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Play } from "@phosphor-icons/react";
import { flushAccountDrafts } from "./account-client.js";
import "./workbench-brand.css";

export function WorkbenchBrand({ onNavigate }) {
  const location = useLocation();
  const navigate = useNavigate();
  const pending = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const admin = location.pathname.startsWith("/admin");
  const destination = admin ? "/admin/accounts" : "/projects";
  const label = admin ? "返回账户管理" : "返回工作台";

  useEffect(() => {
    setBusy(false); setError("");
    return () => { pending.current = null; };
  }, [location.key]);

  async function goHome(event) {
    // A new-tab/window gesture leaves this page and its drafts in place.
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (pending.current || location.pathname === destination) return;
    const operation = Symbol("home-navigation");
    pending.current = operation;
    setBusy(true); setError("");
    try {
      await flushAccountDrafts();
      // A different navigation or unmount cancels this pending redirect.
      if (pending.current !== operation) return;
      onNavigate?.();
      navigate(destination);
    } catch (failure) {
      if (pending.current === operation) setError(failure.message || "保存未完成，请稍后再次点击返回工作台。");
    } finally {
      if (pending.current === operation) { pending.current = null; setBusy(false); }
    }
  }

  return <div className="workbench-brand">
    <Link className="workbench-brand-link" to={destination} onClick={goHome}
      aria-label={`ViralDNA，${label}`} title={busy ? "正在保存，请稍候" : label}
      aria-disabled={busy || undefined} aria-busy={busy || undefined}>
      <span className="workbench-brand-mark" aria-hidden="true"><Play size={18} weight="fill" /></span>
      <strong className="workbench-brand-name" aria-hidden="true">ViralDNA</strong>
    </Link>
    {error && <span className="workbench-brand-error" role="alert">{error}</span>}
  </div>;
}
