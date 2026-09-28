import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import test from "node:test";
import { localBrowser } from "./helpers/local-browser.mjs";

// Isolated fixture: only synthetic data and loopback resources. No production API.
test("grouping, unified five-image editor, explicit paid confirmation, reviewed cuts and responsive layout", { timeout: 240000 }, async () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const bundle = await build({ absWorkingDir: root, bundle: true, write: false, outfile: "fixture.js", format: "esm", platform: "browser", jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' }, stdin: { resolveDir: root, loader: "jsx", contents: String.raw`
    import React, {useState} from 'react';
    import { createRoot } from 'react-dom/client';
    import { VideoGroupsPanel } from './src/video-groups/VideoGroupsPanel.jsx';
    import { ShotVideoList } from './src/ShotVideoWorkspace.jsx';
    import './src/styles.css';
    import './src/production-workflow.css';
    const shots=Array.from({length:5},(_,i)=>({id:'s'+i,index:i+1,start_seconds:i,end_seconds:i+1,duration_seconds:1,video_status:'ready',visual_beats:[{approved_image_candidate_id:'i'+i}]}));
    const image='/sample.jpg';
    const model={alias:'fixture',label:'验收模型（模拟）',available:true,capabilities:{multi_image_reference:true,ordered_reference_images:true,minimum_duration_seconds:4,maximum_duration_seconds:10,maximum_reference_images:5,supported_durations:[4,5,10],supported_resolutions:['720P','1080P']}};
    let state={expected_revision_id:'r1',groups:[]},runs=[];
    window.calls=[]; window.stale=false; window.groupError=false; window.failSave=false; window.unknownCost=false;
    const noop=()=>{};
    function project(group){const members=shots.filter(s=>group.shot_plan_ids.includes(s.id));const adopted=window.groupError?members.filter(s=>s.id!=='s1'):members;return {...group,input_fingerprint:JSON.stringify([group.video_prompt,group.shot_plan_ids]),anchor_shot_id:members[0].id,shots:members,images:adopted.map((s,i)=>({id:s.visual_beats[0].approved_image_candidate_id,index:i+1,url:image})),target_duration_seconds:members.length,input_plan:{input_policy:'adopted_images_v1',sources:['approved_images'],references:adopted.map((s,i)=>({reference_kind:'approved_image',reference_id:s.visual_beats[0].approved_image_candidate_id,label:'图'+(i+1),order:i+1,role:'composition'}))},compiled_prompt:(group.video_prompt||'')+'\n'+members.map((s,i)=>'成片分镜 '+s.index+'：参考图'+(i+1)+'。'+['巴黎铁塔前向左行走。','纽约自由女神像前继续向左行走。','伦敦大本钟前向左行走。','悉尼歌剧院前继续行走。','埃及金字塔前向左行走。'][s.index-1]).join('\n'),runs,stale_run_ids:window.stale||window.groupError?runs.map(r=>r.id):[],error:window.groupError?'分镜 2 尚未采用参考图片，请恢复图片后重试':null};}
    const request=async(path,options={})=>{
      const body=options.body&&JSON.parse(options.body);window.calls.push({path,method:options.method||'GET',body});
      if(path.endsWith('/video-groups')){if(options.method==='PUT'){if(window.failSave)throw new Error('模拟保存失败');state={expected_revision_id:'r'+window.calls.length,groups:body.groups};}return {...state,groups:state.groups.map(project)};}
      if(path.endsWith('/prompt-context'))return {id:'context1',common_image_prompt:'',common_video_prompt:'',common_image_mentions:[],common_video_mentions:[],visual_style:{preset:'travel_vlog'},visual_style_snapshot:{label:'旅行 Vlog',cover_url:image,applies_to:['image','video']},shot_styles:{},shot_style_snapshots:{}};
      if(path==='/me/settings/visual-styles')return {version:'visual-style-library-v1',items:[]};
      if(path.endsWith('/estimate'))return {estimate_known:!window.unknownCost,estimated_cost_micros:125000,currency:'CNY'};
      if(path.endsWith('/video-runs')){runs=[{id:'run1',status:'completed',created_at:new Date().toISOString(),actual_cost_known:true,actual_cost_micros:125000,candidates:[{id:'candidate1',status:'ready',content_url:'/sample.mp4',duration_seconds:5}]}];return runs[0];}
      if(path.endsWith('/adopt')){window.adopted=body;return {};}
      if(path.endsWith('/cancel')){runs=runs.map(r=>r.id==='active1'?{...r,status:'cancelled'}:r);return {};}
      throw new Error('Unexpected fixture request '+path);
    };
    const app=createRoot(document.getElementById('root'));
    function Fixture({revision}){const [shot,setShot]=useState('s0');return <main style={{maxWidth:'1180px',margin:'auto',padding:'16px'}}><h1>分镜视频</h1><p>交互验收 · 模拟分镜与模型，不会产生费用</p><VideoGroupsPanel project={{id:'project',current_revision_id:revision}} shots={shots} settings={{models:[model]}} request={request} resolveUrl={url=>url} onChanged={noop} selectedShotId={shot} onSelectShot={setShot}>{workspace=><section className="shot-video-workspace">{workspace.toolbar}<div className="shot-video-layout"><ShotVideoList shots={shots.map(plan=>({plan}))} selectedShotId={shot} onSelectShot={workspace.onSelectShot} groupWorkspace={workspace} resolveUrl={url=>url} busy={workspace.pending}/><div className="shot-video-editor">{workspace.editor||<p>当前分镜动作编辑 · {shot}</p>}</div></div></section>}</VideoGroupsPanel></main>}
    const render=(revision='r1')=>app.render(<Fixture revision={revision}/>);
    window.failInputs=()=>{window.groupError=true;runs=[{id:'active1',status:'running',created_at:new Date().toISOString(),candidates:[]},...runs];render('error1');};
    window.capacity=n=>{model.capabilities.maximum_reference_images=n;render('capacity'+n);};
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
  const artifactRoot = new URL(`../../../output/playwright/video-image-inputs-${Date.now()}/`, import.meta.url);
  const capture = async name => { const path = fileURLToPath(new URL(name, artifactRoot)); await browser.screenshot(path, true); console.info('Screenshot:', path); };
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
    await browser.evaluate("document.querySelector('details').open=true;[...document.querySelectorAll('.video-group-choices input')].forEach(i=>i.click())");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='合并选中分镜').click()");
    await browser.ready("document.querySelectorAll('.video-group .asset-reference-thumbnail').length===5");
    assert.deepEqual(await browser.evaluate("[...document.querySelectorAll('.video-group .asset-reference-thumbnail > span')].map(el=>el.textContent)"),['1','2','3','4','5']);
    assert.equal(await browser.evaluate("document.querySelectorAll('.asset-reference-pinned-tokens .asset-reference-token').length"),5);
    assert.equal(await browser.evaluate("document.querySelectorAll('.video-group .style-selected').length"),0);
    assert.equal(await browser.evaluate("document.body.textContent.includes('5 张分镜图 · 0 项附加参考 → 1 段视频')"),true);
    assert.equal(await browser.evaluate("document.querySelector('.video-group-script').textContent.includes('成片分镜 5')"),true);
    await browser.evaluate("window.failSave=true;const input=document.querySelector('[aria-label=\"本组补充要求\"]');input.focus();input.textContent='人物保持同一方向，背景按图切换';input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}))");
    await browser.ready("document.body.textContent.includes('模拟保存失败')");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='编辑分镜 2 动作').click()");
    await browser.ready("document.body.textContent.includes('请先处理未保存')");
    assert.equal(await browser.evaluate("document.querySelector('[aria-label=\"本组补充要求\"]').textContent"),'人物保持同一方向，背景按图切换');
    await browser.evaluate("window.failSave=false;[...document.querySelectorAll('button')].find(b=>b.textContent==='编辑分镜 2 动作').click()");
    await browser.ready("document.body.textContent.includes('当前分镜动作编辑 · s1')");
    await browser.evaluate("document.querySelector('.shot-video-group-link').click()");
    await browser.ready("document.querySelector('[aria-label=\"本组补充要求\"]')?.textContent==='人物保持同一方向，背景按图切换'");
    // A blur save and navigation in the same interaction share one in-flight save.
    await browser.evaluate("const blurInput=document.querySelector('[aria-label=\"本组补充要求\"]');blurInput.focus();blurInput.textContent+='，保持自然步速';blurInput.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));blurInput.blur();[...document.querySelectorAll('button')].find(b=>b.textContent==='编辑分镜 3 动作').click()");
    await browser.ready("document.body.textContent.includes('当前分镜动作编辑 · s2')");
    await browser.evaluate("document.querySelector('.shot-video-group-link').click()");
    await browser.ready("document.querySelector('[aria-label=\"本组补充要求\"]')?.textContent.includes('保持自然步速')");
    // Change five inputs to three, then restore five without altering shot definitions.
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='调整组合').click()");
    await browser.ready("document.querySelectorAll('.video-group-choices input:checked').length===5");
    await browser.evaluate("[...document.querySelectorAll('.video-group-choices input')].slice(3).forEach(input=>input.click());[...document.querySelectorAll('button')].find(b=>b.textContent==='应用组合').click()");
    await browser.ready("document.querySelectorAll('.video-group .asset-reference-thumbnail').length===3");
    assert.equal(await browser.evaluate("document.querySelector('.video-group-script').textContent.includes('成片分镜 5')"),false);
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='调整组合').click()");
    await browser.ready("document.querySelectorAll('.video-group-choices input').length===5");
    await browser.evaluate("[...document.querySelectorAll('.video-group-choices input')].filter(input=>!input.checked).forEach(input=>input.click());[...document.querySelectorAll('button')].find(b=>b.textContent==='应用组合').click()");
    await browser.ready("document.querySelectorAll('.video-group .asset-reference-thumbnail').length===5");
    await browser.evaluate("window.capacity(4)");
    await browser.ready("document.body.textContent.includes('模型上限 4 项')");
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='生成 1 段视频').disabled"),true);
    await browser.evaluate("window.capacity(5)");
    await browser.ready("![...document.querySelectorAll('button')].find(b=>b.textContent==='生成 1 段视频').disabled");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/video-runs')).length"),0);
    await capture('desktop.png');
    await browser.viewport(390,844);
    assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
    await capture('mobile.png');
    await browser.viewport(768);
    assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
    await browser.evaluate("window.unknownCost=true;[...document.querySelectorAll('button')].find(b=>b.textContent==='生成 1 段视频').click()");
    await browser.ready("document.body.textContent.includes('确认接受费用未知')");
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='确认费用并生成').disabled"),true);
    assert.equal(await browser.evaluate("document.body.textContent.includes('不代表免费')"),true);
    await browser.evaluate("[...document.querySelectorAll('.video-group-confirm button')].find(b=>b.textContent==='取消').click();window.unknownCost=false");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='生成 1 段视频').click()");
    await browser.ready("document.body.textContent.includes('确认费用并生成')");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/video-runs')).length"),0);
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='确认费用并生成').click()");
    await browser.ready("document.querySelector('.video-group-review')");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/video-runs')).length"),1);
    assert.deepEqual(await browser.evaluate("window.calls.find(c=>c.path.endsWith('/video-runs')).body.input_plan.references.map(r=>r.reference_id)"),['i0','i1','i2','i3','i4']);
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='采用这些片段').disabled"),true);
    // Membership changes after a result must reset review cuts, not retain five
    // stale entries and crash when the new group only has three members.
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='调整组合').click()");
    await browser.ready("document.querySelectorAll('.video-group-choices input:checked').length===5");
    await browser.evaluate("[...document.querySelectorAll('.video-group-choices input')].slice(3).forEach(input=>input.click());[...document.querySelectorAll('button')].find(b=>b.textContent==='应用组合').click()");
    await browser.ready("document.querySelectorAll('.video-group-review .video-group-cut').length===3");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='调整组合').click()");
    await browser.ready("document.querySelectorAll('.video-group-choices input').length===5");
    await browser.evaluate("[...document.querySelectorAll('.video-group-choices input')].filter(input=>!input.checked).forEach(input=>input.click());[...document.querySelectorAll('button')].find(b=>b.textContent==='应用组合').click()");
    await browser.ready("document.querySelectorAll('.video-group-review .video-group-cut').length===5");
    await browser.evaluate("document.querySelector('.video-group-review').parentElement.open=true;document.querySelector('.video-group-review .video-group-check input').click()");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='采用这些片段').click()");
    await browser.ready("Boolean(window.adopted)");
    assert.equal(await browser.evaluate("window.adopted.cuts.length"),5);
    assert.equal(await browser.evaluate("window.adopted.cuts[1].trim_in_seconds"),1);
    await browser.viewport(1440);
    await browser.evaluate("scrollTo(0,0)");
    await browser.ready("document.querySelector('video').readyState>=2");
    await capture('review-desktop.png');
    await browser.viewport(390,844);
    await browser.evaluate("scrollTo(0,0)");
    assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
    await capture('review-mobile.png');
    await browser.evaluate("window.stale=true;[...document.querySelectorAll('button')].find(b=>b.textContent==='采用这些片段').click()");
    await browser.ready("document.body.textContent.includes('历史结果仅供查看')");
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='采用这些片段').disabled"),true);
    await browser.evaluate("window.failInputs()");
    await browser.ready("document.body.textContent.includes('尚未采用参考图片') && document.body.textContent.includes('取消任务')");
    assert.equal(await browser.evaluate("document.querySelectorAll('.video-group .asset-reference-thumbnail').length"),4);
    assert.equal(await browser.evaluate("Boolean(document.querySelector('[aria-label=\"本组补充要求\"]'))"),true);
    assert.equal(await browser.evaluate("document.body.textContent.includes('4 张分镜图 · 0 项附加参考 → 1 段视频')"),true);
    assert.equal(await browser.evaluate("document.querySelectorAll('video[aria-label=\"生成组历史视频（只读）\"]').length"),1);
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].some(b=>b.textContent==='采用这些片段')"),false);
    assert.equal(await browser.evaluate("document.body.textContent.includes('已记录费用 ¥0.1250')"),true);
    await browser.viewport(1440);
    await browser.evaluate("scrollTo(0,0);document.querySelector('video').parentElement.parentElement.open=true");
    await browser.ready("document.querySelector('video').readyState>=2");
    await capture('error-desktop.png');
    await browser.viewport(390,844);
    await browser.evaluate("scrollTo(0,0)");
    assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
    await capture('error-mobile.png');
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='取消任务').click()");
    await browser.ready("!document.body.textContent.includes('取消任务')");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/cancel')).length"),1);
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='拆为独立生成').click()");
    await browser.ready("!document.querySelector('.video-group')");
    assert.equal(await browser.evaluate("document.querySelectorAll('.video-group-choices label').length"),5);
    assert.deepEqual(errors,[]);
  } finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
});
