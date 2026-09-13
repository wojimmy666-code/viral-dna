import React, { lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, useLocation } from "react-router-dom";
import HomePage from "./landing/HomePage.jsx";
import "./entry.css";

const PrivateApplication = lazy(() => import("./accounts/PrivateApplication.jsx"));

function RootRoutes() {
  const location = useLocation();
  if (location.pathname === "/" || location.pathname === "/login") return <HomePage loginOpen={location.pathname === "/login"} />;
  return <Suspense fallback={<main className="entry-loading" role="status">正在打开 ViralDNA…</main>}><PrivateApplication /></Suspense>;
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <RootRoutes />
    </BrowserRouter>
  </React.StrictMode>,
);
