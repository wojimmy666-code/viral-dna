import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import test from "node:test";
import { localBrowser } from "./helpers/local-browser.mjs";

// Isolated synthetic acceptance. No real account, backend, model or remote resources.
test("concise cards, per-idea revision notes, retry safety and responsive layouts", { timeout: 90000 }, async () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const bundle = await build({ absWorkingDir: root, bundle: true, write: false, outfile: "fixture.js", format: "esm", platform: "browser", jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' }, stdin: { resolveDir: root, loader: "jsx", contents: `
    import React from 'react'; import {createRoot} from 'react-dom/client';
    import {ReplicationWorkspace} from './src/viral-report/ReplicationWorkspace.jsx';
    import './src/styles.css'; import './src/viral-report/viral-report.css';
    const feedback='女孩居中，向左走，5个场景切换，世界标志性场景';
    const scenes=['巴黎埃菲尔铁塔','纽约自由女神像','伦敦大本钟','悉尼歌剧院','吉萨金字塔'].map((name,i)=>({index:i+1,description:name+'的建筑轮廓与服装线条呼应。女孩居中，向左走，背景随步伐移动。',duration_seconds:1.2,transition:'cut'}));
    const ideas=['向左行走的时空折叠','定格动画里的世界巡礼','镜像折射的全球足迹'].map((name,i)=>({id:'idea'+i,name,summary:'以人物居中、背景流动的视觉关系，组织五个世界地标场景。',visual_memory:'人物与镜头相对位置固定，世界地标在身后切换。',key_scenes:scenes.slice(0,2).map(s=>s.description),scene_plan:scenes,rhythm:'硬切与平稳的行走节奏。',category_fit:'用服装线条连接空间',borrowed:'非线性蒙太奇',changed:'重新设计场景',creative_intent:'全球旅行',visual_organization:'动作匹配',product_role:'贯穿画面的服装',assumptions:[],brief_checks:[],common_rules:[],requirement_checks:[],review_state:i===0?'needs_review':i===1?'needs_revision':'ready',review_brief:feedback,review_issues:i===0?['要求「女孩居中」：场景 3、4、5 缺少核对依据']:i===1?['要求「背景移动」：场景 3 与共同调度冲突']:[]}));
    const original={id:'batch1',revision:1,phase:'ideas',status:'failed',operation:'generate',feedback,ideas,concepts:[],category_profile:{id:'jk',display_name:'JK'},created_at:'2026-09-21T11:43:04Z',completed_at:'2026-09-21T11:44:17Z',model_elapsed_ms:72703,resolved_model:'验收模型（模拟）',cost_status:'measured',model_cost_micros:56262,error_message:'旧版全场景引用校验失败',review_source_fingerprint:'a'.repeat(64),requirement_rules:[]};
    if(!location.search.includes('legacy-api'))original.revision_notes=null;
    let history=[original], expansion=null; window.calls=[]; window.revisionFails=true; window.historyFails=location.search.includes('history-error'); window.pollFails=false; window.original=structuredClone(original);
    const request=async(path,options={})=>{
      const body=options.body&&JSON.parse(options.body);window.calls.push({path,method:options.method||'GET',body});
      if(path.endsWith('/viral-insight'))return {replacement_opportunities:[]};
      if(path==='/me/category-profiles')return {items:[{id:'jk',display_name:'JK',brand_name:'验收品牌',brief:'服装创意'}]};
      if(path.includes('/history')){
        if(window.historyFails)throw new Error('模拟历史连接中断');
        return structuredClone(history);
      }
      if(path==='/viral-concept-sets/expanded'){
        if(window.pollFails)throw new Error('模拟状态查询中断');
        return structuredClone(expansion);
      }
      if(path.endsWith('/publish')){
        await new Promise(resolve=>{window.finishPublish=resolve;});
        return {project_id:'project-from-plan',project_name:'验收方案'};
      }
      if(path.endsWith('/expand')){
        if(path.includes('/idea1/')){
          const error=new Error('这条创意需要修订后再展开：场景 3 与背景移动要求冲突。请使用 AI 修订本条。');
          error.status=409; error.code='idea_review_required'; throw error;
        }
        expansion={...original,id:'expanded',phase:'expanded',operation:'expand',status:'queued',parent_set_id:original.id,source_idea_id:'idea0',feedback:body.feedback,ideas:[],concepts:[],error_message:null,completed_at:null,model_cost_micros:0,cost_status:'not_started'};
        history=[expansion,...history]; return structuredClone(expansion);
      }
      if(path.endsWith('/regenerate')){
        if(window.revisionFails)throw new Error('模拟提交失败，修改意见保留');
        const updated={...original,id:'batch2',status:'completed',operation:'regenerate',parent_set_id:'batch1',revision_notes:body.revision_notes,error_message:null,ideas:original.ideas.map(i=>i.id==='idea0'?{...i,id:'revised',summary:'按修改意见呈现雨夜地标与裙摆灯光的呼应。',review_state:'ready',review_issues:[]}:i)};
        window.generated=body; window.updated=structuredClone(updated); history=[updated,...history];return structuredClone(updated);
      }
      throw new Error('Unexpected request '+path);
    };
    const shotTitles=['巴黎铁塔下的起步','纽约自由女神像前的跨越','伦敦大本钟旁的漫步','悉尼歌剧院前的轻盈','金字塔夕阳下的终章'];
    const shotDescriptions=[
      '女孩身穿深蓝格纹制服，位于画面正中心，向左侧匀速行走。背景为法国巴黎埃菲尔铁塔，采用广角镜头，铁塔占据背景主要位置，随着女孩步伐背景产生水平视差移动效果。光线明亮自然，裙摆随风轻轻摆动。',
      '女孩保持完全相同的行走姿态和画面中心位置，背景硬切为美国纽约自由女神像及哈德逊河。背景中的船只和波浪快速向后掠过，女孩面部表情平静，目光向前，制服在自然光下呈现细腻质感。',
      '女孩继续向左行走，位置不变。背景切换为英国伦敦大本钟及议会大厦。背景中的红色双层巴士模糊闪过，阴天的柔和光线均匀打在女孩制服上，凸显面料纹理与褶皱细节，整体色调偏冷灰。',
      '女孩动作连贯，背景切换为澳大利亚悉尼歌剧院。白色帆形建筑在蓝天背景下格外醒目，背景中海鸥飞过产生动态模糊，女孩发丝微动，保持向左行进动势，整体氛围轻松明快。',
      '女孩最后一步迈出，背景切换为埃及吉萨金字塔群。金色沙丘与巨石在夕阳下呈现暖金色调，与女孩冷色调制服形成强烈对比。背景沙尘随风向后飘动，强化向左行走的视觉惯性，画面逐渐稳定。'
    ];
    const plan={id:'plan1',name:'世界地标里的行走',thesis:'以人物居中与背景硬切串联不同地理空间。人物始终保持在画面中心，连续向左行走，五个世界地标在身后切换，以服装的统一轮廓连接变化的建筑、光线与色彩。',narrative_structure:'非线性场景蒙太奇',payoff:'以背影结束世界巡礼。',category_fit_summary:'服装线条与地标轮廓呼应。',changed_elements:['重新设计五个世界地标场景'],required_assets:['人物与服装参考图'],retained_dna:['硬切连接'],brief_checks:[{requirement:'女孩居中',explanation:'验收落实说明不应展示'}],risks:['验收制作提醒不应展示'],shots:scenes.map((scene,index)=>({...scene,duration_seconds:1.5,traffic_role:'视觉吸引',title:shotTitles[index],description:shotDescriptions[index],image_prompt:shotDescriptions[index],video_prompt:'人物向左匀速行走，背景硬切。'}))};
    if(location.search.includes('expanded-plan')){
      const expanded={...original,id:'expanded',phase:'expanded',status:'completed',operation:'expand',parent_set_id:'batch1',source_idea_id:'idea0',concepts:[plan],ideas:[],error_message:null,created_at:'2026-09-22T08:59:22Z',started_at:'2026-09-22T08:59:22Z',completed_at:'2026-09-22T09:00:41Z',model_elapsed_ms:79000,model_cost_micros:57500};
      if(location.search.includes('published'))expanded.published_result={project_id:'project-from-plan'};
      if(location.search.includes('language-error'))Object.assign(expanded,{status:'failed',error_code:'creative_prompt_language_invalid',language_issues:['旧方案含英文'],error_message:'请先将提示词转为中文'});
      if(location.search.includes('long-content')){
        expanded.resolved_model='验收模型（模拟）'+ 'very-long-model-version-'.repeat(8);
        plan.name='世界地标里的行走：'+ '长标题与窄屏排版验收'.repeat(8);
        plan.shots[0].title='完整分镜名称'+ '长标题验收'.repeat(10);
        plan.shots[0].description='女孩保持在画面中心向左行走，背景从巴黎切换到纽约。'.repeat(12);
        plan.required_assets=[];expanded.cost_status='unreported';expanded.model_cost_micros=0;
      }
      history=location.search.includes('no-parent')?[expanded]:[expanded,original];
    }
    createRoot(document.getElementById('root')).render(<main style={{maxWidth:'1440px',margin:'auto'}}><ReplicationWorkspace analysisId="analysis1" recordId="record1" request={request} onPromptPreview={batch=>{window.previewed=batch.id;}} onPublished={result=>{window.published=result.project_id;}}/></main>);
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
    assert.equal(await browser.evaluate("[...document.querySelectorAll('.creative-idea-choice input')].filter(i=>!i.disabled).length"), 3);
    assert.equal(await browser.evaluate("document.querySelector('.creative-expand-action button').disabled"), true);
    assert.equal(await browser.evaluate("document.querySelector('.creative-expand-action span').textContent"), "选择一个喜欢的方向后，再展开完整分镜");
    for (const index of [0, 1, 2]) {
      await browser.evaluate("document.querySelectorAll('.creative-idea-choice')[" + index + "].click()");
      await browser.ready("document.querySelectorAll('.creative-idea-choice input')[" + index + "].checked");
      assert.equal(await browser.evaluate("document.querySelector('.creative-expand-action button').disabled"), false);
      assert.equal(await browser.evaluate("document.querySelectorAll('.creative-idea.is-selected').length"), 1);
      assert.equal(await browser.evaluate("document.querySelector('.creative-expand-action').textContent"), "展开这个创意");
      assert.equal(await browser.evaluate("document.querySelector('.creative-expand-action').childElementCount"), 1);
    }
    await browser.evaluate("document.querySelector('.creative-idea-choice input').focus()");
    await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key: " ", code: "Space", windowsVirtualKeyCode: 32 });
    await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: " ", code: "Space", windowsVirtualKeyCode: 32 });
    await browser.ready("document.querySelector('.creative-idea-choice input').checked");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.method!=='GET').length"), 0);
    for (const copy of ["原批次失败记录和费用保留", "待核对", "待修订", "项具体问题", "记忆画面", "关键画面与品类适配", "修改与核对"]) {
      assert.equal(await browser.evaluate("document.body.textContent.includes(" + JSON.stringify(copy) + ")"), false, copy);
    }
    for (const width of [1440, 1280, 1024, 768, 390]) {
      await browser.viewport(width, 960);
      assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true);
      const alignment = await browser.evaluate("(()=>{const row=document.querySelector('.creative-expand-action').getBoundingClientRect();const button=document.querySelector('.creative-expand-action button').getBoundingClientRect();return {right:Math.abs(row.right-button.right),left:Math.abs(row.left-button.left)}})()");
      assert.ok(alignment.right < 1, "expand button stays right-aligned at " + width);
      if (width <= 760) assert.ok(alignment.left < 1, "mobile expand button keeps full width");
      if ([1440, 390].includes(width)) await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/creative-review/selectable-results-" + width + ".png", import.meta.url)), true);
    }
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='AI 修订本条').click()");
    await browser.ready("document.querySelector('.creative-revision-notes textarea')");
    assert.equal(await browser.evaluate("document.activeElement.tagName"), "TEXTAREA");
    assert.equal(await browser.evaluate("document.querySelector('.creative-history select').disabled"), true);
    assert.equal(await browser.evaluate("document.querySelector('.creative-category-lock').disabled"), true);
    assert.equal(await browser.evaluate("document.querySelector('.creative-feedback textarea').disabled"), true);
    assert.equal(await browser.evaluate("[...document.querySelectorAll('.creative-idea-choice input')].filter(i=>!i.disabled).length"), 0);
    const setNotes = async notes => {
      await browser.evaluate("var field=document.querySelector('.creative-revision-notes textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(field," + JSON.stringify(notes) + ");field.dispatchEvent(new Event('input',{bubbles:true}));");
    };
    assert.equal(await browser.evaluate("document.querySelector('.creative-rewrite-confirm button[type=submit]').disabled"), true);
    await setNotes("   ");
    assert.equal(await browser.evaluate("document.querySelector('.creative-rewrite-confirm button[type=submit]').disabled"), true);
    const notes = "保留人物居中与向左走，把五个地标都改为雨夜，加强裙摆与灯光的呼应。";
    await setNotes(notes);
    assert.equal(await browser.evaluate("document.querySelector('.creative-rewrite-confirm button[type=submit]').disabled"), false);
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.method!=='GET').length"), 0);
    await browser.evaluate("document.querySelector('.creative-rewrite-confirm button[type=button]').click()");
    await browser.ready("!document.querySelector('.creative-rewrite-confirm')");
    assert.equal(await browser.evaluate("document.activeElement.textContent"), "AI 修订本条");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='AI 修订本条').click()");
    await browser.ready("document.querySelector('.creative-revision-notes textarea')");
    assert.equal(await browser.evaluate("document.querySelector('.creative-revision-notes textarea').value"), notes);
    assert.equal(await browser.evaluate("document.querySelector('.creative-revision-cost').textContent"), "将调用文案模型并计费，仅修改本条。");
    for (const width of [1440, 1280, 1024, 768, 390]) {
      await browser.viewport(width, 960);
      await browser.evaluate("document.querySelector('.creative-rewrite-confirm').scrollIntoView({behavior:'instant',block:'center'})");
      assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true);
      if ([1440, 390].includes(width)) await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/creative-review/revision-notes-" + width + ".png", import.meta.url)));
    }
    await browser.evaluate("document.querySelector('.creative-rewrite-confirm button[type=submit]').click()");
    await browser.ready("document.body.textContent.includes('模拟提交失败')");
    assert.equal(await browser.evaluate("document.querySelector('.creative-revision-notes textarea').value"), notes);
    assert.equal(await browser.evaluate("document.querySelector('.creative-revision-notes textarea').disabled"), true);
    await browser.evaluate("window.revisionFails=false;[...document.querySelectorAll('button')].find(b=>b.textContent==='重试同一请求').click()");
    await browser.ready("!document.querySelector('.creative-rewrite-confirm')");
    const saved = await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/regenerate'))");
    assert.equal(saved.length, 2);
    assert.equal(saved[0].body.request_id, saved[1].body.request_id);
    assert.equal(saved[1].body.revision_notes, notes);
    assert.equal(saved[1].body.feedback, "女孩居中，向左走，5个场景切换，世界标志性场景");
    assert.equal(saved[1].path, "/viral-concept-sets/batch1/ideas/idea0/regenerate");
    assert.equal(await browser.evaluate("JSON.stringify(window.original.ideas.slice(1))===JSON.stringify(window.updated.ideas.slice(1))"), true);
    assert.equal(await browser.evaluate("document.querySelectorAll('.creative-history option').length"), 2);
    assert.equal(await browser.evaluate("document.querySelector('.creative-history select').disabled"), false);
    assert.equal(await browser.evaluate("document.querySelector('.creative-feedback textarea').value"), saved[1].body.feedback);
    await browser.navigate("http://127.0.0.1:" + server.address().port + "/?selection-flow");
    await browser.ready("document.querySelectorAll('.creative-idea').length===3");
    await browser.evaluate("document.querySelectorAll('.creative-idea-choice')[1].click()");
    await browser.ready("!document.querySelector('.creative-expand-action button').disabled");
    await browser.evaluate("document.querySelector('.creative-expand-action button').click()");
    await browser.ready("document.body.textContent.includes('场景 3 与背景移动要求冲突')");
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].some(b=>b.textContent==='重试同一请求')"), false);
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].some(b=>b.textContent==='恢复查询')"), false);
    assert.equal(await browser.evaluate("document.querySelectorAll('.viral-error-state button').length"), 0);
    assert.equal(await browser.evaluate("[...document.querySelectorAll('.creative-idea-choice input')].filter(i=>!i.disabled).length"), 3);
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='AI 修订本条').disabled"), false);
    for (const width of [1440, 390]) {
      await browser.viewport(width, 960);
      await browser.evaluate("document.querySelector('.viral-error-state').scrollIntoView({behavior:'instant',block:'center'})");
      assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true);
      await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/creative-review/expansion-validation-" + width + ".png", import.meta.url)));
    }
    await browser.evaluate("document.querySelector('.creative-idea-choice').click()");
    await browser.ready("document.querySelector('.creative-idea-choice input').checked");
    assert.equal(await browser.evaluate("document.body.textContent.includes('场景 3 与背景移动要求冲突')"), false);
    const changedBrief = "女孩居中，向左匀速走，5个场景切换，世界标志性场景";
    await browser.evaluate("var briefField=document.querySelector('.creative-feedback textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(briefField," + JSON.stringify(changedBrief) + ");briefField.dispatchEvent(new Event('input',{bubbles:true}));");
    assert.equal(await browser.evaluate("document.querySelector('.creative-expand-action button').disabled"), false);
    await browser.evaluate("window.pollFails=true;var expandButton=document.querySelector('.creative-expand-action button');expandButton.click();expandButton.click();");
    await browser.ready("document.querySelector('.creative-task-status strong')?.textContent==='正在展开选定创意'");
    const expanded = await browser.evaluate("window.calls.filter(c=>c.path==='/viral-concept-sets/batch1/ideas/idea0/expand')");
    assert.equal(expanded.length, 1);
    assert.equal(expanded[0].body.feedback, changedBrief);
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/regenerate')).length"), 0);
    await browser.ready("document.body.textContent.includes('模拟状态查询中断')");
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].some(b=>b.textContent==='恢复查询')"), true);
    await browser.evaluate("window.pollFails=false;[...document.querySelectorAll('button')].find(b=>b.textContent==='恢复查询').click()");
    await browser.ready("window.calls.filter(c=>c.path==='/viral-concept-sets/expanded').length>=2");
    assert.equal(await browser.evaluate("document.querySelector('.viral-error-state')===null"), true);
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.method==='POST'&&c.path.endsWith('/expand')).length"), 2);
    await browser.navigate("http://127.0.0.1:" + server.address().port + "/?history-error=1");
    await browser.ready("document.body.textContent.includes('模拟历史连接中断')");
    assert.equal(await browser.evaluate("[...document.querySelectorAll('button')].some(b=>b.textContent==='恢复查询')"), true);
    await browser.evaluate("window.historyFails=false;[...document.querySelectorAll('button')].find(b=>b.textContent==='恢复查询').click()");
    await browser.ready("document.querySelectorAll('.creative-idea').length===3");
    assert.equal(await browser.evaluate("document.querySelector('.viral-error-state')===null"), true);
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.method!=='GET').length"), 0);
    await browser.navigate("http://127.0.0.1:" + server.address().port + "/?legacy-api=1");
    await browser.ready("document.querySelectorAll('.creative-idea').length===3");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='AI 修订本条').click()");
    await browser.ready("document.querySelector('.creative-rewrite-confirm')");
    await setNotes(notes);
    assert.equal(await browser.evaluate("document.querySelector('.creative-rewrite-confirm button[type=submit]').disabled"), true);
    assert.equal(await browser.evaluate("document.querySelector('.creative-rewrite-confirm').textContent.includes('服务版本尚未更新')"), true);
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.method!=='GET').length"), 0);
    await browser.navigate("http://127.0.0.1:" + server.address().port + "/?expanded-plan");
    await browser.ready("document.querySelector('.creative-plan-footer button')");
    for (const copy of ["补充想法落实说明", "制作提醒", "验收落实说明不应展示", "验收制作提醒不应展示"]) {
      assert.equal(await browser.evaluate("document.body.textContent.includes(" + JSON.stringify(copy) + ")"), false, copy);
    }
    assert.equal(await browser.evaluate("document.querySelectorAll('.creative-plan-review .primary-button').length"), 1);
    assert.equal(await browser.evaluate("document.querySelectorAll('.creative-plan-shot').length"), 5);
    assert.equal(await browser.evaluate("[...document.querySelectorAll('.creative-plan-shot-toggle')].every(toggle=>toggle.textContent.trim()==='' && toggle.querySelector('svg') && toggle.getAttribute('aria-hidden')==='true')"), true);
    assert.equal(await browser.evaluate("getComputedStyle(document.querySelector('.creative-plan-shot-toggle svg')).transform"), "none");
    assert.equal(await browser.evaluate("document.querySelectorAll('.creative-plan-review details[open]').length"), 0);
    assert.equal(await browser.evaluate("document.querySelector('.creative-plan-assets summary').textContent"), "所需资产 · 1 项");
    assert.equal(await browser.evaluate("document.querySelector('.creative-plan-footer button').disabled"), false);
    assert.equal(await browser.evaluate("document.querySelector('.creative-plan-review').lastElementChild.className"), "creative-plan-footer");
    assert.equal(await browser.evaluate("getComputedStyle(document.querySelector('.creative-plan-overview p')).fontWeight"), "400");
    assert.equal(await browser.evaluate("document.querySelector('.creative-plan-review').textContent.includes('方案详情')"), false);
    assert.equal(await browser.evaluate("document.querySelector('.creative-plan-details').hidden"), true);
    assert.equal(await browser.evaluate("document.querySelector('.creative-plan-overview-heading button').getAttribute('aria-controls')===document.querySelector('.creative-plan-details').id"), true);
    await browser.evaluate("document.querySelector('.creative-plan-overview-heading button').focus()");
    await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r", unmodifiedText: "\r" });
    await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    await browser.ready("!document.querySelector('.creative-plan-details').hidden");
    assert.equal(await browser.evaluate("document.querySelector('.creative-plan-overview-heading button').getAttribute('aria-expanded')"), "true");
    assert.match(await browser.evaluate("document.querySelector('.creative-plan-details').innerText"), /叙事结构[\s\S]*结尾兑现[\s\S]*品类适配[\s\S]*核心改动[\s\S]*保留 1 项 DNA/);
    await browser.evaluate("document.querySelector('.creative-plan-overview-heading button').click()");
    await browser.ready("document.querySelector('.creative-plan-details').hidden");
    assert.match(await browser.evaluate("document.querySelector('.creative-run-summary').textContent"), /总计 79 秒.*¥0.0575/);
    assert.equal(await browser.evaluate("document.querySelector('.creative-plan-run-meta').open"), false);
    await browser.evaluate("document.querySelector('.creative-plan-header button').click()");
    assert.equal(await browser.evaluate("window.previewed"), "expanded");
    await browser.evaluate("document.querySelector('.creative-plan-run-meta summary').click()");
    assert.match(await browser.evaluate("document.querySelector('.creative-plan-run-meta dl').innerText"), /排队[\s\S]*0 秒[\s\S]*模型[\s\S]*79 秒/);
    await browser.evaluate("document.querySelector('.creative-plan-run-meta summary').click()");
    for (const width of [1440, 1024, 768, 390, 320]) {
      await browser.viewport(width, 960);
      await browser.evaluate("document.querySelector('.creative-batch-context').scrollIntoView({behavior:'instant',block:'start'})");
      assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true);
      const rows = await browser.evaluate("[...document.querySelectorAll('.creative-plan-shot')].map(shot=>{const title=shot.querySelector('.creative-plan-shot-title').getBoundingClientRect();const heading=shot.querySelector('.creative-plan-shot-heading').getBoundingClientRect();const duration=shot.querySelector('.creative-plan-shot-duration').getBoundingClientRect();const summary=shot.querySelector('summary');const description=shot.querySelector('.creative-plan-shot-excerpt');const excerpt=description.getBoundingClientRect();const style=getComputedStyle(description);return {left:Math.abs(title.left-excerpt.left),right:Math.abs(summary.getBoundingClientRect().right-excerpt.right),verticalGap:excerpt.top-heading.bottom,durationGap:duration.left-title.right,maxWidth:style.maxWidth,clamp:style.webkitLineClamp,visibleLines:excerpt.height/parseFloat(style.lineHeight),clipped:description.scrollHeight>description.clientHeight+1,paddingTop:parseFloat(getComputedStyle(summary).paddingTop),paddingBottom:parseFloat(getComputedStyle(summary).paddingBottom)};})");
      for (const row of rows) {
        assert.ok(row.left < 1, 'description aligns with title at '+width);
        assert.ok(row.right < 1, 'description uses the full available row width at '+width);
        assert.equal(row.maxWidth, 'none', 'no character-width cap at '+width);
        assert.equal(row.clamp, '3');
        assert.ok(row.visibleLines <= 3.05, 'long collapsed descriptions use at most three lines at '+width);
        assert.equal(row.paddingTop, 12);
        assert.equal(row.paddingBottom, 12);
        assert.ok(row.verticalGap >= 7, 'description sits below heading at '+width);
        if (width >= 768) assert.ok(row.durationGap >= 8 && row.durationGap <= 16, 'duration stays beside title at '+width);
        if (width >= 1024) assert.equal(row.clipped, false, 'typical descriptions are complete at '+width);
      }
      if ([1440, 390].includes(width)) await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/creative-review/expanded-plan-fullwidth-" + width + ".png", import.meta.url)));
    }
    await browser.evaluate("document.querySelector('.creative-plan-shot summary').focus()");
    await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r", unmodifiedText: "\r" });
    await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    await browser.ready("document.querySelector('.creative-plan-shot').open");
    assert.equal(await browser.evaluate("document.querySelector('.creative-plan-shot[open] .creative-plan-shot-toggle').textContent.trim()"), "");
    assert.equal(await browser.evaluate("getComputedStyle(document.querySelector('.creative-plan-shot[open] .creative-plan-shot-toggle svg')).transform"), "matrix(-1, 0, 0, -1, 0, 0)");
    assert.equal(await browser.evaluate("document.querySelectorAll('.creative-plan-shot[open] .creative-plan-prompts > section').length"), 2);
    assert.equal(await browser.evaluate("document.querySelectorAll('.creative-plan-shot summary button').length"), 0);
    assert.equal(await browser.evaluate("document.querySelectorAll('.creative-plan-shot-description').length"), 0);
    assert.equal(await browser.evaluate("(()=>{const description=document.querySelector('.creative-plan-shot[open] .creative-plan-shot-excerpt');return description.scrollHeight<=description.clientHeight+1 && getComputedStyle(description).webkitLineClamp==='none';})()"), true);
    for (const width of [1440, 390]) {
      await browser.viewport(width, 960);
      await browser.evaluate("document.querySelector('.creative-plan-shot[open]').scrollIntoView({behavior:'instant',block:'start'})");
      const prompts = await browser.evaluate("[...document.querySelectorAll('.creative-plan-shot[open] .creative-plan-prompts > section')].map(section=>{const rect=section.getBoundingClientRect();return {left:rect.left,top:rect.top,bottom:rect.bottom};})");
      if (width === 1440) {
        assert.ok(Math.abs(prompts[0].top - prompts[1].top) < 1, 'desktop prompts share a row');
        assert.ok(prompts[1].left > prompts[0].left, 'desktop prompts use two columns');
      } else {
        assert.ok(Math.abs(prompts[0].left - prompts[1].left) < 1, 'mobile prompts align in one column');
        assert.ok(prompts[1].top > prompts[0].bottom, 'mobile video prompt follows image prompt');
      }
      assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true);
      await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/creative-review/expanded-plan-fullwidth-open-" + width + ".png", import.meta.url)));
    }
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.method!=='GET').length"), 0);
    await browser.evaluate("document.querySelector('.creative-plan-overview-heading button').click()");
    await browser.ready("!document.querySelector('.creative-plan-details').hidden");
    await browser.evaluate("var publish=document.querySelector('.creative-plan-footer button');publish.click();publish.click();");
    await browser.ready("document.querySelector('.creative-plan-footer button').disabled");
    assert.equal(await browser.evaluate("window.calls.filter(c=>c.path.endsWith('/publish')).length"), 1);
    assert.equal(await browser.evaluate("document.querySelector('.creative-history select').disabled"), true);
    await browser.evaluate("window.finishPublish()");
    await browser.ready("window.published==='project-from-plan'");
    await browser.evaluate("document.querySelector('.creative-batch-toolbar button').click()");
    await browser.ready("document.querySelectorAll('.creative-idea').length===3");
    await browser.evaluate("var historySelect=document.querySelector('.creative-history select');historySelect.value='expanded';historySelect.dispatchEvent(new Event('change',{bubbles:true}));");
    await browser.ready("document.querySelectorAll('.creative-plan-shot').length===5");
    assert.equal(await browser.evaluate("document.querySelectorAll('.creative-plan-review details[open]').length"), 0);
    assert.equal(await browser.evaluate("document.querySelector('.creative-plan-details').hidden"), true);
    for (const state of ['published', 'language-error', 'long-content&no-parent']) {
      await browser.navigate("http://127.0.0.1:" + server.address().port + "/?expanded-plan&" + state);
      await browser.ready("document.querySelector('.creative-history select')");
      if (state === 'language-error') {
        assert.equal(await browser.evaluate("document.querySelector('.creative-plan-review')"), null);
        assert.equal(await browser.evaluate("document.querySelectorAll('.creative-preview-action button').length"), 1);
        await browser.evaluate("document.querySelector('.creative-preview-action button').click()");
        assert.equal(await browser.evaluate("window.previewed"), "expanded");
      } else {
        await browser.ready("document.querySelector('.creative-plan-footer button')");
        if (state === 'published') assert.match(await browser.evaluate("document.querySelector('.creative-plan-footer button').innerText"), /进入已创建方案/);
        else {
          assert.equal(await browser.evaluate("document.querySelector('.creative-plan-assets')"), null);
          assert.equal(await browser.evaluate("document.querySelector('.creative-batch-toolbar button').disabled"), true);
          assert.match(await browser.evaluate("document.querySelector('.creative-run-summary').innerText"), /不代表免费/);
        }
        for (const width of [1440, 1024, 768, 390, 320]) {
          await browser.viewport(width, 960);
          assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true, state+' at '+width);
        }
        if (state.startsWith('long-content')) {
          const description = () => browser.evaluate("(()=>{const element=document.querySelector('.creative-plan-shot-excerpt');const style=getComputedStyle(element);return {text:element.textContent,height:element.clientHeight,fullHeight:element.scrollHeight,lineHeight:parseFloat(style.lineHeight),clamp:style.webkitLineClamp};})()");
          const closed = await description();
          assert.equal(closed.clamp, '3');
          assert.ok(closed.height <= closed.lineHeight * 3 + 1);
          assert.ok(closed.fullHeight > closed.height + 1, 'long copy is actually clamped');
          await browser.evaluate("document.querySelector('.creative-plan-shot summary').click()");
          await browser.ready("document.querySelector('.creative-plan-shot').open");
          const opened = await description();
          assert.equal(opened.text, closed.text, 'expansion never changes the description');
          assert.equal(opened.clamp, 'none');
          assert.ok(opened.fullHeight <= opened.height + 1, 'all long copy is readable after expansion');
          assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true);
          await browser.evaluate("document.querySelector('.creative-plan-shot summary').click()");
          await browser.ready("!document.querySelector('.creative-plan-shot').open");
          assert.equal((await description()).clamp, '3');
        }
      }
      assert.equal(await browser.evaluate("window.calls.filter(c=>c.method!=='GET').length"), 0);
    }
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
});
