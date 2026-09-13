import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

// Local acceptance only: fresh profile, installed browser, loopback CDP.
// Never attaches to an existing browser or reads a user's profile.
const repository = fileURLToPath(new URL("../../../../", import.meta.url));
const temporaryRoot = resolve(repository, ".tmp", "homepage-browser");
export const pause = ms => new Promise(resolvePause => setTimeout(resolvePause, ms));

export async function localBrowser() {
  const executable = [
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/usr/bin/chromium",
  ].find(existsSync);
  if (!executable) throw new Error("No installed browser for local acceptance");
  await mkdir(temporaryRoot, { recursive: true });
  const profile = await mkdtemp(join(temporaryRoot, "profile-"));
  const process = spawn(executable, ["--headless=new", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows", "--disable-sync", "--disable-extensions", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
  const exited = new Promise(resolveExit => process.once("exit", resolveExit));
  let socket;
  async function close() {
    socket?.close();
    process.kill();
    await Promise.race([exited, pause(5000)]);
    // Only the fresh directory created by this invocation can be removed.
    if (dirname(resolve(profile)) !== temporaryRoot) throw new Error("Unsafe browser profile cleanup path");
    await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 250 });
  }
  try {
    const endpoint = await new Promise((resolveEndpoint, reject) => {
      let log = "";
      const timer = setTimeout(() => reject(new Error("Local browser startup timed out")), 15000);
      process.once("error", error => { clearTimeout(timer); reject(error); });
      process.stderr.on("data", data => {
        log += data;
        const match = log.match(/DevTools listening on (ws:\/\/[^\s]+)/);
        if (match) { clearTimeout(timer); resolveEndpoint(match[1]); }
      });
    });
    const target = await fetch(`http://${new URL(endpoint).host}/json/new?about:blank`, { method: "PUT" }).then(response => response.json());
    socket = new WebSocket(target.webSocketDebuggerUrl);
    const pending = new Map(), listeners = new Map(); let nextId = 0;
    socket.addEventListener("message", event => {
      const message = JSON.parse(event.data), task = pending.get(message.id);
      if (task) {
        pending.delete(message.id); clearTimeout(task.timer);
        message.error ? task.reject(new Error(JSON.stringify(message.error))) : task.resolve(message.result);
      } else for (const listener of listeners.get(message.method) || []) listener(message.params);
    });
    await new Promise((resolveOpen, reject) => {
      socket.addEventListener("open", resolveOpen, { once: true });
      socket.addEventListener("error", reject, { once: true });
    });
    const send = (method, params = {}) => new Promise((resolveCall, reject) => {
      const id = ++nextId;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, method === "Page.captureScreenshot" ? 45000 : 15000);
      pending.set(id, { resolve: resolveCall, reject, timer });
      socket.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async expression => {
      const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }).catch(error => { throw new Error(`${error.message} while evaluating ${expression.slice(0, 160)}`); });
      if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
      return result.result.value;
    };
    const ready = async expression => {
      for (let attempt = 0; attempt < 200; attempt++) {
        if (await evaluate(`Boolean(${expression})`)) return;
        await pause(50);
      }
      throw new Error(`Browser condition timed out: ${expression}`);
    };
    await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");
    await send("Page.bringToFront");
    return {
      send, evaluate, ready, close,
      on(method, listener) { const list = listeners.get(method) || []; list.push(listener); listeners.set(method, list); },
      async viewport(width, height = 960) { await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false }); },
      async navigate(url) {
        const targetUrl = new URL(url);
        if (targetUrl.protocol !== "http:" || !["localhost", "127.0.0.1"].includes(targetUrl.hostname)) throw new Error("Local acceptance only");
        await send("Page.navigate", { url });
        await send("Page.bringToFront");
      },
      async screenshot(file, fullPage = false) {
        await mkdir(dirname(file), { recursive: true });
        await evaluate("new Promise(resolveFrame => requestAnimationFrame(() => requestAnimationFrame(resolveFrame)))");
        const metrics = fullPage ? await send("Page.getLayoutMetrics") : null;
        const result = await send("Page.captureScreenshot", { format: "png", optimizeForSpeed: true, captureBeyondViewport: fullPage,
          ...(metrics ? { clip: { x: 0, y: 0, width: metrics.cssContentSize.width, height: metrics.cssContentSize.height, scale: 1 } } : {}) });
        await writeFile(file, Buffer.from(result.data, "base64"));
      },
    };
  } catch (error) { await close(); throw error; }
}
