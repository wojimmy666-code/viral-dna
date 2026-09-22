import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import test from "node:test";
import { localBrowser } from "./helpers/local-browser.mjs";

// Real components + production styles, synthetic requests, isolated browser.
// No accounts, remote APIs or billable generation calls.
test("button states, task cancellation and responsive workbench contexts", { timeout: 90000 }, async () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const bundle = await build({ absWorkingDir: root, bundle: true, write: false, outfile: "fixture.js", format: "esm", platform: "browser", jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' }, stdin: { resolveDir: root, loader: "jsx", contents: `
    import React, {useState, useRef} from 'react'; import {createRoot} from 'react-dom/client';
    import './src/styles.css';
    import './src/production-workflow.css'; import './src/platform-connections.css';
    import './src/accounts/accounts.css'; import './src/viral-report/viral-report.css';
    import './src/prompt-context/prompt-context.css';
    import {Button, IconButton} from './src/ui/system/Button.jsx';
    import {ReplicationWorkspace} from './src/viral-report/ReplicationWorkspace.jsx';
    import {Stop, Copy, X, ArrowClockwise} from '@phosphor-icons/react';
    const active={id:'running',phase:'ideas',status:'running',requested_model:'本地验收（模拟）',category_profile:{id:'jk',display_name:'JK'},ideas:[],concepts:[],created_at:new Date().toISOString()};
    let latest=active; window.cancelCalls=0; window.clicks=0; window.submits=0;
    async function request(path,options={}) {
      if(path.endsWith('/viral-insight'))return {replacement_opportunities:[]};
      if(path==='/me/category-profiles')return {items:[{id:'jk',display_name:'JK'}]};
      if(path.includes('/history'))return [latest];
      if(path.endsWith('/cancel')){window.cancelCalls++;return new Promise((resolve,reject)=>{
        window.rejectCancel=()=>reject(new Error('模拟网络中断，请恢复查询'));
        window.finishCancel=()=>{latest={...active,status:'cancelled',completed_at:new Date().toISOString()};resolve(latest)};
      })}
      if(path==='/viral-concept-sets/running')return latest;
      throw new Error('Unexpected fixture request '+path);
    }
    function Showcase(){
      const [loading,setLoading]=useState(false); const lock=useRef(false);
      window.finishLoading=()=>{lock.current=false;setLoading(false)};
      return <main className="button-fixture">
        <h1>工作台按钮 · 本地验收</h1>
        <section className="fixture-section"><h2>操作层级</h2><div className="fixture-row" id="roles">
          <Button id="primary" variant="primary">生成创意</Button><Button id="secondary">刷新</Button>
          <Button variant="text" icon={<Copy/>}>复制</Button><Button variant="warning" icon={<Stop/>}>停止任务</Button>
          <Button variant="danger">确认永久删除</Button><IconButton id="close" label="关闭" title="关闭"><X/></IconButton>
        </div></section>
        <section className="fixture-section"><h2>尺寸与处理中状态</h2><div className="fixture-row">
          <Button id="compact" size="compact">紧凑操作</Button><Button id="default">默认操作</Button><Button id="prominent" size="prominent" variant="primary">确认创建</Button>
          <Button id="disabled" variant="primary" disabled onClick={()=>window.clicks++}>暂不可生成</Button>
          <Button id="loading" variant="warning" loading={loading} loadingLabel="正在停止…" icon={<Stop/>} onClick={()=>{if(lock.current)return;lock.current=true;window.clicks++;setLoading(true)}}>停止任务</Button>
        </div></section>
        <section className="fixture-section"><h2>设置与表单</h2><form onSubmit={e=>{e.preventDefault();window.submits++}}><div className="fixture-row account-actions">
          <Button id="form-submit" type="submit" variant="primary">保存设置</Button><Button id="form-cancel" onClick={()=>window.clicks++}>取消</Button>
          <a id="download" className="secondary-button" href="data:text/plain,fixture" download="fixture.txt">下载 TXT</a>
        </div></form><div className="fixture-row platform-card-actions"><Button variant="secondary" size="compact" icon={<ArrowClockwise/>}>检查本机信息</Button><Button variant="warning" size="compact">断开</Button></div></section>
        <section className="fixture-section production-workspace"><h2>制作工作台</h2><div className="fixture-row"><Button variant="primary" size="compact">生成视频</Button><Button size="compact">重新分析</Button><Button variant="warning" size="compact">取消任务</Button></div><div className="prompt-preview"><Button variant="quiet" size="compact" className="text-button">复制局部</Button><details><summary>查看完整提示词</summary></details></div></section>
        <section className="fixture-section" id="real-workspace"><ReplicationWorkspace analysisId="fixture" recordId="fixture" request={request}/></section>
      </main>
    }
    createRoot(document.getElementById('root')).render(<Showcase/>);
  ` } });
  const js = bundle.outputFiles.find(file => file.path.endsWith(".js")).text;
  const css = bundle.outputFiles.find(file => file.path.endsWith(".css")).text + `
    .button-fixture{max-width:1100px;margin:auto;padding:24px;min-width:0}
    .fixture-section{padding:20px 0;border-bottom:1px solid var(--border-default)}
    .fixture-section h2{font-size:var(--type-heading-size);margin:0 0 16px}
    .fixture-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-block:12px}
    .button-fixture .production-workspace{display:block;min-height:0}
    @media(max-width:600px){.button-fixture{padding:16px}.fixture-section{padding-block:16px}}
  `;
  const server = createServer((req, res) => {
    res.setHeader("Content-Type", req.url === "/fixture.js" ? "text/javascript" : req.url === "/fixture.css" ? "text/css" : "text/html; charset=utf-8");
    res.end(req.url === "/fixture.js" ? js : req.url === "/fixture.css" ? css : '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/fixture.css"></head><body><div id="root"></div><script type="module" src="/fixture.js"></script></body></html>');
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await localBrowser();
    const errors = [];
    browser.on("Runtime.exceptionThrown", event => errors.push(event.exceptionDetails.text));
    await browser.viewport(1440, 1100);
    await browser.navigate("http://127.0.0.1:" + server.address().port);
    await browser.ready("document.querySelector('#real-workspace .warning-button')");
    const geometry = await browser.evaluate(`['compact','default','prominent'].map(id=>{const el=document.getElementById(id),css=getComputedStyle(el);return [el.offsetHeight,css.borderRadius,css.fontSize]})`);
    assert.deepEqual(geometry, [[36, "8px", "14px"], [40, "8px", "14px"], [44, "8px", "14px"]]);
    assert.equal(await browser.evaluate("getComputedStyle(document.querySelector('#primary')).backgroundColor"), "rgb(91, 77, 245)");
    assert.equal(await browser.evaluate("getComputedStyle(document.querySelector('.prompt-preview button')).fontSize"), "12px");
    await browser.evaluate("document.getElementById('primary').focus()");
    assert.equal(await browser.evaluate("getComputedStyle(document.getElementById('primary')).outlineStyle"), "solid");
    await browser.send("Input.dispatchKeyEvent", {type:"keyDown",key:"Tab",code:"Tab",windowsVirtualKeyCode:9});
    await browser.send("Input.dispatchKeyEvent", {type:"keyUp",key:"Tab",code:"Tab",windowsVirtualKeyCode:9});
    assert.equal(await browser.evaluate("document.activeElement.id"), "secondary");
    await browser.evaluate("document.getElementById('disabled').click(); document.getElementById('form-cancel').click()");
    assert.equal(await browser.evaluate("window.clicks"), 1);
    assert.equal(await browser.evaluate("window.submits"), 0);
    await browser.evaluate("document.getElementById('form-submit').focus()");
    await browser.send("Input.dispatchKeyEvent", {type:"keyDown",key:"Enter",code:"Enter",windowsVirtualKeyCode:13,text:"\r",unmodifiedText:"\r"});
    await browser.send("Input.dispatchKeyEvent", {type:"keyUp",key:"Enter",code:"Enter",windowsVirtualKeyCode:13});
    assert.equal(await browser.evaluate("window.submits"), 1);
    assert.equal(await browser.evaluate("document.getElementById('download').tagName"), "A");
    const width = await browser.evaluate("document.getElementById('loading').offsetWidth");
    await browser.evaluate("document.getElementById('loading').click(); document.getElementById('loading').click()");
    await browser.ready("document.getElementById('loading').disabled");
    assert.equal(await browser.evaluate("window.clicks"), 2);
    assert.equal(await browser.evaluate("document.getElementById('loading').offsetWidth"), width);
    assert.equal(await browser.evaluate("document.getElementById('loading').getAttribute('aria-busy')"), "true");
    const ax = await browser.send("Accessibility.getFullAXTree");
    assert.ok(ax.nodes.some(node => node.role?.value === "button" && node.name?.value === "关闭"));
    // A native-looking stop button must never return; only a confirmed response ends the task.
    await browser.evaluate("document.querySelector('#real-workspace .warning-button').click(); document.querySelector('#real-workspace .warning-button').click()");
    await browser.ready("window.cancelCalls===1 && document.querySelector('#real-workspace button[aria-busy=true]')");
    assert.equal(await browser.evaluate("document.querySelector('#real-workspace .creative-task-status strong').textContent"), "正在构思不同方向");
    await browser.evaluate("window.rejectCancel()");
    await browser.ready("document.querySelector('#real-workspace [role=alert]')");
    assert.equal(await browser.evaluate("document.querySelector('#real-workspace .warning-button').disabled"), false);
    for (const viewport of [1440, 1280, 1024, 768, 390]) {
      await browser.viewport(viewport, 1100);
      assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true, `overflow at ${viewport}`);
      if (viewport === 390) assert.ok(await browser.evaluate("[...document.querySelectorAll('.ui-button')].every(b=>b.offsetHeight>=44)"));
      if ([1440, 390].includes(viewport)) await browser.screenshot(fileURLToPath(new URL(`../../../.impeccable/review/button-system/buttons-${viewport}.png`, import.meta.url)), true);
    }
    await browser.evaluate("document.querySelector('#real-workspace .warning-button').click()");
    await browser.ready("window.cancelCalls===2");
    await browser.evaluate("window.finishCancel()");
    await browser.ready("!document.querySelector('#real-workspace .warning-button')");
    await browser.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
    assert.equal(await browser.evaluate("getComputedStyle(document.querySelector('#loading .ui-button-spinner')).animationName"), "none");
    assert.deepEqual(errors, []);
  } finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
});
