import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { setTimeout as pause } from "node:timers/promises";
import { build } from "esbuild";
import test from "node:test";
import { appHandlerSource } from "./helpers/app-handlers.mjs";
import { localBrowser } from "./helpers/local-browser.mjs";

// Real App event handlers and AccountRoot, isolated session/lease API. No user data.
test("cold project entry waits for its lease and retains destinations across remounts", { timeout: 90000 }, async () => {
  const projectId = "11111111-1111-4111-8111-111111111111";
  const root = fileURLToPath(new URL("..", import.meta.url));
  const handlers = ["openHistoryRecord", "openHistoryProductions", "openNotificationAction", "restoreRecordEntry", "loadRecordWorkspace"].map(appHandlerSource).join("\n");
  const bundle = await build({ absWorkingDir: root, write: false, bundle: true, outfile: "fixture.js", jsx: "automatic", format: "esm", platform: "browser", define: { "process.env.NODE_ENV": '"development"', "import.meta.env.VITE_API_BASE_URL": "undefined" }, stdin: { resolveDir: root, loader: "jsx", contents: `
    import React,{useEffect,useRef,useState} from 'react'; import {createRoot} from 'react-dom/client';
    import {BrowserRouter,useLocation,useNavigate} from 'react-router-dom';
    import {AccountRoot} from './src/accounts/AccountRoot.jsx';
    import {accountRequest,flushAccountDrafts} from './src/accounts/account-client.js';
    import {recordWorkspacePath,skillProjectWorkspacePath,resolveAppRoute} from './src/app-routing.js';
    import './src/styles.css';
    function EntryFixture(){
      const location=useLocation(),navigate=useNavigate(),appRoute=resolveAppRoute(location.pathname);
      const routeLocationRef=useRef(location);routeLocationRef.current=location;
      const projectEntryRequestIdRef=useRef(0),recordRouteRequestIdRef=useRef(0);
      const [historyError,setHistoryError]=useState(''),[recordRouteError,setRecordRouteError]=useState('');
      const [recordRouteLoading,setRecordRouteLoading]=useState(false),[detail,setDetail]=useState(null);
      const [mode,setRecordWorkspaceMode]=useState('analysis'),[target,setNotificationTarget]=useState(null);
      const records=[{id:'${projectId}',kind:'analysis'}],apiRequest=accountRequest;
      const showNotice=notice=>setHistoryError(notice.message),setNotificationOpen=()=>{},markNotificationRead=async()=>{};
      function applyRecordWorkspaceDetail(next){setDetail(next);setRecordWorkspaceMode('analysis');setNotificationTarget(null);restoreRecordEntry(next.record.id);}
      ${handlers}
      useEffect(()=>()=>{++projectEntryRequestIdRef.current;},[]);
      useEffect(()=>{restoreRecordEntry(appRoute.recordId);if(appRoute.name==='record-workspace')void loadRecordWorkspace(appRoute.recordId).catch(()=>{});},[appRoute.recordId,location.key]);
      return <main>
        {historyError&&<p role="alert">{historyError}</p>}
        {appRoute.name==='history'?<>
          <button className="fixture-record" onClick={()=>void openHistoryRecord('${projectId}')}>项目名称</button>
          <button className="fixture-production" onClick={()=>void openHistoryProductions('${projectId}')}>1 个方案</button>
          <button className="fixture-notification" onClick={()=>void openNotificationAction({id:'notification',action_kind:'production_shot',action_payload:{record_id:'${projectId}',project_id:'production-1',shot_plan_id:'shot-1',candidate_id:'candidate-1',step:'shot_videos'}})}>分镜通知</button>
        </>:<>
          <button className="fixture-back" onClick={()=>navigate('/projects')}>返回列表</button>
          {recordRouteLoading?<p>读取项目</p>:recordRouteError?<p role="alert">{recordRouteError}</p>:detail&&<div className="fixture-workspace" data-mode={mode} data-shot={target?.shotPlanId||''} data-candidate={target?.candidateId||''}>已进入项目</div>}
        </>}
      </main>;
    }
    createRoot(document.getElementById('root')).render(<React.StrictMode><BrowserRouter><AccountRoot><EntryFixture/></AccountRoot></BrowserRouter></React.StrictMode>);
  ` } });
  const js = bundle.outputFiles.find(file => file.path.endsWith(".js")).text;
  const css = bundle.outputFiles.find(file => file.path.endsWith(".css")).text;
  const user = { auth_mode: "password", user_id: "fixture-user", account_id: "fixture-account", role: "owner", account_kind: "enterprise", account_name: "隔离验收账户", display_name: "测试成员", csrf_token: "fixture-csrf" };
  const state = { lease: null, holdAcquire: false, occupied: false, holdRelease: false, requests: [], prematureReads: 0 };
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, "http://fixture").pathname;
    if (!path.startsWith("/api/")) {
      response.setHeader("Content-Type", path === "/fixture.js" ? "text/javascript" : path === "/fixture.css" ? "text/css" : "text/html; charset=utf-8");
      response.end(path === "/fixture.js" ? js : path === "/fixture.css" ? css : '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><link rel="stylesheet" href="/fixture.css"><div id="root"></div><script type="module" src="/fixture.js"></script></html>');
      return;
    }
    let raw = ""; for await (const chunk of request) raw += chunk;
    const body = raw ? JSON.parse(raw) : {};
    state.requests.push({ path, method: request.method });
    const send = (payload, status = 200) => { response.statusCode = status; response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify(payload)); };
    if (path.endsWith("/auth/status")) return send({ auth_mode: "password", initialized: true });
    if (path.endsWith("/session") || path.endsWith("/auth/refresh")) return send(user);
    if (path.endsWith("/edit-lease")) return send({ editable: false, occupied: state.occupied || Boolean(state.lease), display_name: "其他成员" });
    if (path.includes("/edit-lease/")) {
      const owns = state.lease?.editor_id === body.editor_id && state.lease?.token === body.token;
      if (path.endsWith("/release")) {
        if (state.holdRelease) await new Promise(resolve => { state.finishRelease = resolve; });
        if (state.lease?.editor_id === body.editor_id && state.lease?.token === body.token) state.lease = null;
        return send({ editable: false });
      }
      if (path.endsWith("/acquire") && state.holdAcquire) await new Promise(resolve => { state.finishAcquire = resolve; });
      if (state.occupied || (state.lease && !owns)) return send({ editable: false, occupied: true, display_name: "其他成员" });
      state.lease = body;
      state.requests.push({ path: "lease-granted" });
      return send({ editable: true, occupied: true });
    }
    if (path === '/api/v1/records/'+projectId) {
      if (!state.lease || request.headers['x-editor-id'] !== state.lease.editor_id || request.headers['x-edit-token'] !== state.lease.token) {
        ++state.prematureReads;
        return send({ detail: { code: "project_read_only", message: "当前项目为只读，请先取得编辑权" } }, 423);
      }
      return send({ record: { id: projectId }, video: { record_id: projectId }, analyses: [], latest_report: null });
    }
    if (path.endsWith("/readonly")) return send({ name: "只读验收项目", productions: [] });
    return send({ detail: { message: "未配置的验收接口" } }, 404);
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = "http://127.0.0.1:"+server.address().port;
  const readCount = () => state.requests.filter(item => item.path === '/api/v1/records/'+projectId).length;
  const waitForHeldRequest = async key => {
    for (let attempt = 0; attempt < 100 && typeof state[key] !== "function"; attempt++) await pause(20);
    assert.equal(typeof state[key], "function", `${key}: request reached the mock server`);
  };
  let browser;
  try {
    browser = await localBrowser();
    const errors = [];
    browser.on("Runtime.exceptionThrown", event => errors.push(event.exceptionDetails.text));
    await browser.navigate(base+"/projects");
    await browser.ready("document.querySelector('.fixture-record')");
    assert.equal(readCount(), 0);
    state.holdAcquire = true;
    await browser.evaluate("document.querySelector('.fixture-record').click()");
    await browser.ready("document.body.innerText.includes('正在检查项目编辑状态')");
    assert.equal(readCount(), 0, "no project detail request while lease acquisition is pending");
    await waitForHeldRequest("finishAcquire");
    state.holdAcquire = false; state.finishAcquire();
    await browser.ready("document.querySelector('.fixture-workspace')");
    assert.equal(await browser.evaluate("document.querySelector('.fixture-workspace').dataset.mode"), "analysis");
    assert.ok(state.requests.findIndex(item => item.path === "lease-granted") < state.requests.findIndex(item => item.path === '/api/v1/records/'+projectId));

    // Fresh browser document with an expired/mock-server-reset lease.
    state.lease = null;
    await browser.navigate(base+"/projects/"+projectId);
    await browser.ready("document.querySelector('.fixture-workspace')");
    assert.equal(state.prematureReads, 0);

    // Reload can acquire before the old document's pagehide release arrives.
    // Keep that old lease alive until the new page has shown its readonly view.
    state.holdRelease = true;
    await browser.navigate(base+"/projects/"+projectId);
    await browser.ready("document.querySelector('.account-readonly')");
    assert.equal(await browser.evaluate("document.querySelector('.fixture-workspace')===null"), true);
    await waitForHeldRequest("finishRelease");
    state.holdRelease = false; state.finishRelease();
    await browser.ready("document.querySelector('.fixture-workspace')");
    assert.equal(state.prematureReads, 0, "recovered entry still waits for a real grant");

    for (const [entry, shot] of [["production", ""], ["notification", "shot-1"]]) {
      await browser.evaluate("document.querySelector('.fixture-back').click()");
      await browser.ready("document.querySelector('.fixture-record')");
      await browser.evaluate("document.querySelector('.fixture-"+entry+"').click()");
      await browser.ready("document.querySelector('.fixture-workspace')?.dataset.mode==='production'");
      assert.equal(await browser.evaluate("document.querySelector('.fixture-workspace').dataset.shot"), shot);
      if (shot) assert.equal(await browser.evaluate("document.querySelector('.fixture-workspace').dataset.candidate"), "candidate-1");
    }

    await browser.evaluate("document.querySelector('.fixture-back').click()");
    await browser.ready("document.querySelector('.fixture-record')");
    state.occupied = true;
    const beforeBusy = readCount();
    await browser.evaluate("document.querySelector('.fixture-notification').click()");
    await browser.ready("document.body.innerText.includes('只读验收项目')");
    assert.equal(await browser.evaluate("document.querySelector('.fixture-workspace')===null"), true);
    assert.equal(readCount(), beforeBusy, "occupied projects use the readonly snapshot, not editor APIs");
    assert.equal(await browser.evaluate("document.body.innerText.includes('其他成员 正在编辑')"), true);
    await browser.viewport(1440, 960);
    await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/project-lease/readonly-1440.png", import.meta.url)));
    await browser.viewport(390, 844);
    assert.equal(await browser.evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/project-lease/readonly-390.png", import.meta.url)));
    state.occupied = false;
    // No manual click or refresh: expiry/release is picked up by the observer.
    await browser.ready("document.querySelector('.fixture-workspace')?.dataset.shot==='shot-1'");
    assert.equal(await browser.evaluate("document.querySelector('.fixture-workspace').dataset.mode"), "production");
    assert.equal(state.prematureReads, 0);
    assert.deepEqual(errors, []);
  } finally {
    state.finishAcquire?.();
    state.finishRelease?.();
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
});
