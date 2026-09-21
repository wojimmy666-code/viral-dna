import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import test from "node:test";
import { localBrowser } from "./helpers/local-browser.mjs";

// Isolated fixture: only synthetic data and loopback resources. No production API.
test("grouping, explicit paid confirmation, reviewed cuts, stale results and responsive layout", { timeout: 90000 }, async () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const bundle = await build({ absWorkingDir: root, bundle: true, write: false, outfile: "fixture.js", format: "esm", platform: "browser", jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' }, stdin: { resolveDir: root, loader: "jsx", contents: `
    import React from 'react';
    import { createRoot } from 'react-dom/client';
    import { VideoGroupsPanel } from './src/video-groups/VideoGroupsPanel.jsx';
    import './src/styles.css';
    const shots=Array.from({length:5},(_,i)=>({id:'s'+i,index:i+1,duration_seconds:1,visual_beats:[{approved_image_candidate_id:'i'+i}]}));
    const image='/sample.jpg';
    const model={alias:'fixture',label:'验收模型（模拟）',available:true,capabilities:{multi_image_reference:true,ordered_reference_images:true,minimum_duration_seconds:4,maximum_duration_seconds:10,maximum_reference_images:5,supported_durations:[4,5,10],supported_resolutions:['720P','1080P']}};
    let state={expected_revision_id:'r1',groups:[]},runs=[];
    window.calls=[]; window.stale=false; window.groupError=false;
    const noop=()=>{};
    function project(group){if(window.groupError)return {...group,runs,stale_run_ids:runs.map(r=>r.id),error:'分镜 2 尚未采用参考图片，请恢复图片后重试'};const members=shots.filter(s=>group.shot_plan_ids.includes(s.id));return {...group,input_fingerprint:group.video_prompt||'f1',anchor_shot_id:members[0].id,shots:members,images:members.map((s,i)=>({id:'i'+i,index:i+1,url:image})),target_duration_seconds:members.length,input_plan:{sources:['approved_images'],references:members.map(s=>({reference_kind:'approved_image',reference_id:'i'+s.index}))},compiled_prompt:'成片分镜 1：巴黎铁塔前向左行走。硬切到分镜 2：京都伏见稻荷大社的朱红鸟居。',runs,stale_run_ids:window.stale?runs.map(r=>r.id):[],error:null};}
    const request=async(path,options={})=>{
      const body=options.body&&JSON.parse(options.body);window.calls.push({path,method:options.method||'GET',body});
      if(path.endsWith('/video-groups')){if(options.method==='PUT')state={expected_revision_id:'r'+window.calls.length,groups:body.groups};return {...state,groups:state.groups.map(project)};}
      if(path.endsWith('/estimate'))return {estimate_known:true,estimated_cost_micros:125000,currency:'CNY'};
      if(path.endsWith('/video-runs')){runs=[{id:'run1',status:'completed',created_at:new Date().toISOString(),actual_cost_known:true,actual_cost_micros:125000,candidates:[{id:'candidate1',status:'ready',content_url:'/sample.mp4',duration_seconds:5}]}];return runs[0];}
      if(path.endsWith('/adopt')){window.adopted=body;return {};}
      if(path.endsWith('/cancel')){runs=runs.map(r=>r.id==='active1'?{...r,status:'cancelled'}:r);return {};}
      throw new Error('Unexpected fixture request '+path);
    };
    const app=createRoot(document.getElementById('root'));
    const render=(revision='r1')=>app.render(<main style={{maxWidth:'1180px',margin:'auto',padding:'16px'}}><h1>分镜视频</h1><p>交互验收 · 以下为模拟分镜与模型，不会产生费用</p><VideoGroupsPanel project={{id:'project',current_revision_id:revision}} shots={shots} settings={{models:[model]}} request={request} resolveUrl={url=>url} onChanged={noop} onAdvance={noop}/></main>);
    window.failInputs=()=>{window.groupError=true;runs=[{id:'active1',status:'running',created_at:new Date().toISOString(),candidates:[]},...runs];render('error1');};
    render();
  ` } });
  const js = bundle.outputFiles.find(file => file.path.endsWith(".js")).text;
  const css = bundle.outputFiles.find(file => file.path.endsWith(".css")).text;
  const { readFile } = await import("node:fs/promises");
  // Existing repository image, purely illustrative; do not fetch remote media.
  const sample = await readFile(fileURLToPath(new URL("../public/home/video/amber-01.webp", import.meta.url)));
  const video = await readFile(fileURLToPath(new URL("../public/home/video/amber-film-v1.mp4", import.meta.url)));
  const server = createServer((req, res) => {
    if (req.url === "/sample.jpg") { res.setHeader("Content-Type", "image/webp"); res.end(sample); return; }
    if (req.url === "/sample.mp4") { res.setHeader("Content-Type", "video/mp4"); res.end(video); return; }
    res.setHeader("Content-Type", req.url === "/fixture.js" ? "text/javascript" : req.url === "/fixture.css" ? "text/css" : "text/html; charset=utf-8");
    res.end(req.url === "/fixture.js" ? js : req.url === "/fixture.css" ? css : '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/fixture.css"></head><body><div id="root"></div><script type="module" src="/fixture.js"></script></body></html>');
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await localBrowser();
    const errors = [];
    browser.on("Runtime.exceptionThrown", event => errors.push(event.exceptionDetails.text));
    await browser.viewport(1440);
    await browser.navigate('http://127.0.0.1:'+server.address().port);
    await browser.ready("document.querySelectorAll('.video-group-choices label').length===5");
    assert.equal(await browser.evaluate("document.compatMode"), "CSS1Compat");
    assert.match(await browser.evaluate("getComputedStyle(document.querySelector('.video-groups-panel')).fontFamily"), /Segoe UI/);
    await browser.send("DOM.enable"); await browser.send("CSS.enable");
    const documentNode = await browser.send("DOM.getDocument");
    const headingNode = await browser.send("DOM.querySelector", { nodeId: documentNode.root.nodeId, selector: ".video-groups-panel h3" });
    const renderedFonts = await browser.send("CSS.getPlatformFontsForNode", { nodeId: headingNode.nodeId });
    console.info("Rendered group heading fonts:", renderedFonts.fonts.map(font => font.familyName).join(", "));
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.method!=='GET').length"),0);
    await browser.evaluate("document.querySelector('details').open=true;[...document.querySelectorAll('.video-group-choices input')].slice(0,2).forEach(i=>i.click())");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='合并选中分镜').click()");
    await browser.ready("document.querySelector('.video-group-images')");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/video-runs')).length"),0);
    await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/video-groups/desktop.png", import.meta.url)), true);
    await browser.viewport(390,844);
    assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
    await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/video-groups/mobile.png", import.meta.url)), true);
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='预览生成费用').click()");
    await browser.ready("document.body.textContent.includes('确认费用并生成')");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/video-runs')).length"),0);
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='确认费用并生成').click()");
    await browser.ready("document.querySelector('.video-group-review')");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/video-runs')).length"),1);
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='采用这些片段').disabled"),true);
    await browser.evaluate("document.querySelector('.video-group-review').parentElement.open=true;document.querySelector('.video-group-check input').click()");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='采用这些片段').click()");
    await browser.ready("Boolean(window.adopted)");
    assert.equal(await browser.evaluate("window.adopted.cuts.length"),2);
    assert.equal(await browser.evaluate("window.adopted.cuts[1].trim_in_seconds"),2.5);
    await browser.viewport(1440);
    await browser.evaluate("scrollTo(0,0)");
    await browser.ready("document.querySelector('video').readyState>=2");
    await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/video-groups/review-desktop.png", import.meta.url)), true);
    await browser.viewport(390,844);
    await browser.evaluate("scrollTo(0,0)");
    assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
    await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/video-groups/review-mobile.png", import.meta.url)), true);
    await browser.evaluate("window.stale=true;[...document.querySelectorAll('button')].find(b=>b.textContent==='采用这些片段').click()");
    await browser.ready("document.body.textContent.includes('历史结果仅供查看')");
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='采用这些片段').disabled"),true);
    await browser.evaluate("window.failInputs()");
    await browser.ready("document.body.textContent.includes('尚未采用参考图片') && document.body.textContent.includes('取消任务')");
    assert.equal(await browser.evaluate("document.querySelectorAll('video[aria-label=\"生成组历史视频（只读）\"]').length"),1);
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].some(b=>b.textContent==='采用这些片段')"),false);
    assert.equal(await browser.evaluate("document.body.textContent.includes('已记录费用 ¥0.1250')"),true);
    await browser.viewport(1440);
    await browser.evaluate("scrollTo(0,0);document.querySelector('video').parentElement.parentElement.open=true");
    await browser.ready("document.querySelector('video').readyState>=2");
    await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/video-groups/error-desktop.png", import.meta.url)), true);
    await browser.viewport(390,844);
    await browser.evaluate("scrollTo(0,0)");
    assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
    await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/video-groups/error-mobile.png", import.meta.url)), true);
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='取消任务').click()");
    await browser.ready("!document.body.textContent.includes('取消任务')");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/cancel')).length"),1);
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='拆为独立生成').click()");
    await browser.ready("!document.querySelector('.video-group')");
    assert.equal(await browser.evaluate("document.querySelectorAll('.video-group-choices label').length"),5);
    assert.deepEqual(errors,[]);
  } finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
});
