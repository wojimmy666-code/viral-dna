import { Button } from "./ui/system/Button.jsx";
import { useEffect, useRef, useState } from "react";
import { ArrowSquareOut, CircleNotch } from "@phosphor-icons/react";
import "./browser-assist.css";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export function BrowserAssistControls({ session, request, onChange }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { setError(""); }, [session?.id]);
  if (!session?.id || TERMINAL.has(session.state)) return null;

  async function act(action) {
    setBusy(action);
    setError("");
    try {
      const next = await request(`/settings/browser-assist/${session.id}/control`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }), signal: AbortSignal.timeout(10000),
      });
      onChange?.(next);
    } catch (failure) {
      setError(failure.message || "操作未完成，请刷新任务状态后重试。");
    } finally {
      setBusy("");
    }
  }

  const waiting = session.state === "waiting_user";
  return (
    <div className="browser-assist-controls">
      <div className="browser-assist-actions">
        <Button className="secondary-button compact" type="button" disabled={Boolean(busy) || session.state === "starting"} onClick={() => act("focus")}>
          <ArrowSquareOut size={16} aria-hidden="true" />
          {waiting ? "打开验证窗口" : "查看采集窗口"}
        </Button>
        {waiting && (
          <Button className="primary-button compact" type="button" disabled={Boolean(busy)} onClick={() => act("continue")}>
            {busy === "continue" ? "正在继续" : session.mode === "connect" ? "已完成登录" : "我已完成，继续读取"}
          </Button>
        )}
        <Button className="text-button" type="button" disabled={Boolean(busy) || session.state === "starting"} onClick={() => act("cancel")}>
          {busy === "cancel" ? "正在取消" : "取消采集"}
        </Button>
      </div>
      {waiting && <p>请在本机专用窗口操作，不是在日常浏览器中。验证完成后继续同一任务；等待超时会自动停止。</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}
    </div>
  );
}

export function BrowserAssistConnection({ request }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const revision = useRef(0);
  const connecting = useRef(false);
  useEffect(() => {
    let alive = true;
    let timer;
    let controller;
    async function refresh() {
      const currentRevision = revision.current;
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const next = await request("/settings/browser-assist", { signal: controller.signal });
        if (alive && currentRevision === revision.current && !connecting.current) {
          setStatus(next);
          setPollError("");
        }
      } catch (failure) {
        if (alive && currentRevision === revision.current && !connecting.current) {
          setPollError(failure.message || "暂时无法获取浏览器状态。");
        }
      } finally {
        clearTimeout(timeout);
        if (alive) timer = setTimeout(refresh, 2000);
      }
    }
    refresh();
    return () => { alive = false; clearTimeout(timer); controller?.abort(); };
  }, [request]);

  async function connect() {
    if (connecting.current) return;
    connecting.current = true;
    revision.current += 1;
    setBusy(true);
    setError("");
    try {
      const session = await request("/settings/browser-assist/connect", {
        method: "POST", signal: AbortSignal.timeout(10000),
      });
      setStatus((previous) => ({ ...previous, session }));
    } catch (failure) {
      setError(failure.message || "无法打开专用浏览器，请重试。");
    } finally {
      connecting.current = false;
      revision.current += 1;
      setBusy(false);
    }
  }

  function updateSession(session) {
    revision.current += 1;
    setStatus((previous) => ({ ...previous, session }));
  }

  if (!status?.available) return pollError ? <p className="browser-assist-unavailable" role="status">{pollError}</p> : null;
  const active = status.session && !TERMINAL.has(status.session.state);
  return (
    <section className="browser-assist-connection" aria-label="抖音专用采集浏览器">
      <h3>专用采集浏览器</h3>
      <p>普通下载受限时自动使用。登录状态仅供当前用户在此设备使用，不接管日常浏览器。</p>
      {status.session && <p role="status">{status.session.message}</p>}
      {active ? (
        <BrowserAssistControls session={status.session} request={request} onChange={updateSession} />
      ) : (
        <Button className="secondary-button compact" type="button" disabled={busy} onClick={connect}>
          {busy && <CircleNotch size={16} className="spin" aria-hidden="true" />}
          {busy ? "正在打开" : "连接专用浏览器"}
        </Button>
      )}
      {error && <p className="inline-error" role="alert">{error}</p>}
      {pollError && <p className="inline-error" role="status">{pollError}</p>}
    </section>
  );
}
