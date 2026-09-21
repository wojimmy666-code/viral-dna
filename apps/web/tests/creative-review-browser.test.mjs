import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import test from "node:test";
import { localBrowser } from "./helpers/local-browser.mjs";

// Isolated synthetic acceptance. No real account, backend, model or remote resources.
test("failed results, per-idea repair, manual drafts, paid consent and responsive layouts", { timeout: 90000 }, async () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const bundle = await build({ absWorkingDir: root, bundle: true, write: false, outfile: "fixture.js", format: "esm", platform: "browser", jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' }, stdin: { resolveDir: root, loader: "jsx", contents: `
    import React from 'react'; import {createRoot} from 'react-dom/client';
    import {ReplicationWorkspace} from './src/viral-report/ReplicationWorkspace.jsx';
    import './src/styles.css'; import './src/viral-report/viral-report.css';
    const feedback='女孩居中，向左走，5个场景切换，世界标志性场景';
    const scenes=['巴黎埃菲尔铁塔','纽约自由女神像','伦敦大本钟','悉尼歌剧院','吉萨金字塔'].map((name,i)=>({index:i+1,description:name+'的建筑轮廓与服装线条呼应。女孩居中，向左走，背景随步伐移动。',duration_seconds:1.2,transition:'cut'}));
    const ideas=['向左行走的时空折叠','定格动画里的世界巡礼','镜像折射的全球足迹'].map((name,i)=>({id:'idea'+i,name,summary:'以人物居中、背景流动的视觉关系，组织五个世界地标场景。',visual_memory:'人物与镜头相对位置固定，世界地标在身后切换。',key_scenes:scenes.slice(0,2).map(s=>s.description),scene_plan:scenes,rhythm:'硬切与平稳的行走节奏。',category_fit:'用服装线条连接空间',borrowed:'非线性蒙太奇',changed:'重新设计场景',creative_intent:'全球旅行',visual_organization:'动作匹配',product_role:'贯穿画面的服装',assumptions:[],brief_checks:[],common_rules:[],requirement_checks:[],review_state:i===0?'needs_review':i===1?'needs_revision':'ready',review_brief:feedback,review_issues:i===0?['要求「女孩居中」：场景 3、4、5 缺少核对依据']:i===1?['要求「背景移动」：场景 3 与共同调度冲突']:[]}));
    const original={id:'batch1',revision:1,phase:'ideas',status:'failed',operation:'generate',feedback,ideas,concepts:[],category_profile:{id:'jk',display_name:'JK'},created_at:'2026-09-21T11:43:04Z',completed_at:'2026-09-21T11:44:17Z',model_elapsed_ms:72703,resolved_model:'验收模型（模拟）',cost_status:'measured',model_cost_micros:56262,error_message:'旧版全场景引用校验失败',review_source_fingerprint:'a'.repeat(64),requirement_rules:[]};
    let history=[original]; window.calls=[]; window.saveFails=true;
    const request=async(path,options={})=>{
      const body=options.body&&JSON.parse(options.body);window.calls.push({path,method:options.method||'GET',body});
      if(path.endsWith('/viral-insight'))return {replacement_opportunities:[]};
      if(path==='/me/category-profiles')return {items:[{id:'jk',display_name:'JK',brand_name:'验收品牌',brief:'服装创意'}]};
      if(path.includes('/history'))return structuredClone(history);
      if(path.endsWith('/edit')){
        if(window.saveFails)throw new Error('模拟保存失败，草稿保留');
        const updated={...original,id:'batch2',status:'completed',operation:'edit',parent_set_id:'batch1',error_message:null,model_cost_micros:0,cost_status:'not_started',model_runs:[],resolved_model:null,ideas:original.ideas.map(i=>i.id==='idea0'?{...i,...body.idea,id:'edited',review_state:'ready',review_issues:[],human_review:{confirmed_requirements:body.confirmed_requirements}}:i)};
        history=[updated,...history];return structuredClone(updated);
      }
      if(path.endsWith('/regenerate')){window.generated=body;return {...original,id:'batch3',status:'completed',error_message:null};}
      throw new Error('Unexpected request '+path);
    };
    createRoot(document.getElementById('root')).render(<main style={{maxWidth:'1440px',margin:'auto'}}><ReplicationWorkspace analysisId="analysis1" recordId="record1" request={request}/></main>);
  ` } });
  const js = bundle.outputFiles.find(file => file.path.endsWith(".js")).text;
  const css = bundle.outputFiles.find(file => file.path.endsWith(".css")).text;
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
    await browser.viewport(1440);
    await browser.navigate("http://127.0.0.1:" + server.address().port);
    await browser.ready("document.querySelectorAll('.creative-idea').length===3");
    assert.match(await browser.evaluate("getComputedStyle(document.querySelector('.replication-workspace')).fontFamily"), /Segoe UI/);
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.method!=='GET').length"), 0);
    assert.equal(await browser.evaluate("[...document.querySelectorAll('.creative-idea-choice input')].filter(i=>!i.disabled).length"), 1);
    assert.equal(await browser.evaluate("document.body.textContent.includes('原批次失败记录和费用保留')"), true);
    await browser.evaluate("document.querySelector('.creative-review-note').open=true");
    for (const width of [1440, 768, 390]) {
      await browser.viewport(width, 960);
      assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true);
      await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/creative-review/results-" + width + ".png", import.meta.url)), true);
    }
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='修改与核对').click()");
    await browser.ready("document.querySelector('.creative-idea-editor')");
    assert.equal(await browser.evaluate("document.activeElement.tagName"), "H3");
    assert.equal(await browser.evaluate("document.querySelector('.creative-history select').disabled"), true);
    await browser.evaluate("document.querySelector('.creative-human-checks input').click()");
    assert.equal(await browser.evaluate("document.querySelector('.creative-human-checks input').checked"), true);
    await browser.evaluate("const input=document.querySelector('.creative-idea-editor textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'人工修订后的创意简述。');input.dispatchEvent(new Event('input',{bubbles:true}));");
    assert.equal(await browser.evaluate("document.querySelector('.creative-human-checks input').checked"), false);
    await browser.evaluate("document.querySelectorAll('.creative-human-checks input').forEach(input=>input.click())");
    for (const width of [1440, 390]) {
      await browser.viewport(width, 960);
      await browser.evaluate("document.querySelector('.creative-idea-editor').scrollIntoView({behavior:'instant',block:'start'})");
      assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true);
      await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/creative-review/editor-" + width + ".png", import.meta.url)));
    }
    await browser.evaluate("document.querySelector('.creative-idea-editor button[type=submit]').click()");
    await browser.ready("document.body.textContent.includes('模拟保存失败')");
    assert.equal(await browser.evaluate("document.querySelector('.creative-idea-editor textarea').value"), "人工修订后的创意简述。");
    await browser.evaluate("window.saveFails=false;[...document.querySelectorAll('button')].find(b=>b.textContent==='重试同一请求').click()");
    await browser.ready("!document.querySelector('.creative-idea-editor')");
    const saved = await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/edit'))");
    assert.equal(saved.length, 2);
    assert.equal(saved[0].body.request_id, saved[1].body.request_id);
    assert.equal(saved[1].body.confirmed_requirements.length, 4);
    assert.equal(await browser.evaluate("document.querySelectorAll('.creative-history option').length"), 2);
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='AI 修订本条').click()");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/regenerate')).length"), 0);
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='确认调用模型').click()");
    await browser.ready("Boolean(window.generated)");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/regenerate')).length"), 1);
    assert.equal(await browser.evaluate("window.generated.feedback"), "女孩居中，向左走，5个场景切换，世界标志性场景");
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
});
