import { lazy, Suspense, useEffect } from "react";
import { AccountRoot } from "./AccountRoot.jsx";
import "../styles.css";

const Workbench = lazy(() => import("../App.jsx").then(module => ({ default: module.App })));

export default function PrivateApplication() {
  useEffect(() => { document.title = "ViralDNA · 视频创作工作台"; }, []);
  return <AccountRoot><Suspense fallback={<main className="account-loading" role="status">正在打开创作台…</main>}><Workbench /></Suspense></AccountRoot>;
}
