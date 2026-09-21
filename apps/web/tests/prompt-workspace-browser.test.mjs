import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import test from "node:test";
import { localBrowser, pause } from "./helpers/local-browser.mjs";

// In-memory fixture only: no account database, real API or model request.
test("prompt source, saved draft, localization confirmation and responsive layout", { timeout: 90000 }, async () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const bundle = await build({ absWorkingDir: root, bundle: true, write: false, outfile: "fixture.js", format: "esm", platform: "browser", jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' }, stdin: { resolveDir: root, loader: "jsx", contents: `
    import React, { useState } from 'react';
    import { createRoot } from 'react-dom/client';
    import { PromptWorkspace } from './src/prompt-editor/PromptWorkspace.jsx';
    import './src/styles.css';
    const project = '11111111-1111-4111-8111-111111111111', batch = '22222222-2222-4222-8222-222222222222', job = '33333333-3333-4333-8333-333333333333';
    const source = { id:'source',version:1,revision_id:batch,revision_number:0,target_model:'seedance',global_prompt:'',shots:Array.from({length:9},(_,i)=>({shot_id:'original'+i,duration_seconds:1,prompt:'原片教堂与雪景',negative_constraints:[]})) };
    let doc={project_id:project,name:'世界地标里的格纹呼吸',token:'old',common_image_prompt:'冷调，暖色主体',common_video_prompt:'硬切，节奏均匀',language_issues:['分镜 1 图片'],shots:Array.from({length:5},(_,i)=>({id:'shot'+i,index:i+1,duration_seconds:1.5,images:[{id:'image'+i,prompt:i?'中文地标场景':'Wide shot of a young woman on the black sand beach.',negative_constraints:[],mentions:[]}],video_prompt:'最新视频草稿 '+i,video_negative_constraints:[],video_mentions:[]}))};
    let translated=null, original=null, hasJob=false;
    window.calls=[];window.copied='';window.failSave=false;
    const request=async(path,options={})=>{
      window.calls.push({path,method:options.method||'GET',body:options.body&&JSON.parse(options.body)});
      if(path.endsWith('/prompt-sources'))return [{key:'production:'+project,kind:'production',id:project,batch_id:batch,name:doc.name},...(hasJob?[{key:'concept:'+job,kind:'concept',id:job,batch_id:job,name:doc.name,operation:'localize'}]:[])];
      if(path.endsWith('/prompt-draft'))return structuredClone(source);
      if(path.includes('/localization-estimate'))return {model:'模拟文案模型',estimated_cost_micros:12300,estimate_token:'estimate'};
      if(path.endsWith('/localize')){hasJob=true;original=structuredClone(doc);translated={...structuredClone(doc),read_only:true,operation:'localize',language_issues:[]};translated.shots[0].images[0].prompt='远景，一位年轻女性站在冰岛黑沙滩上。';return {id:job,status:'running'};}
      if(path.endsWith('/apply-language')){doc={...translated,read_only:false,token:'applied'};return structuredClone(doc);}
      if(path==='/viral-concept-sets/'+job)return {id:job,status:'completed',operation:'localize',phase:'expanded',resolved_model:'模拟文案模型',cost_status:'measured',model_cost_micros:12000,concepts:[{id:batch}]};
      if(path==='/viral-concept-sets/'+job+'/prompt-document')return {...structuredClone(translated),source_document:original};
      if(path.endsWith('/prompt-document')){
        if(options.method==='PUT'){
          if(window.failSave)throw Object.assign(new Error('版本冲突'),{status:409});
          const body=JSON.parse(options.body);doc={...doc,...body,shots:body.shots.map((shot,i)=>({...doc.shots[i],...shot,images:shot.images.map((image,j)=>({...doc.shots[i].images[j],...image}))})),token:'saved'+window.calls.length};
        }
        return structuredClone(doc);
      }
      throw new Error('Unexpected fixture path '+path);
    };
    function Fixture(){const [selection,setSelection]=useState('source');window.selectSource=setSelection;return <main style={{padding:'24px',maxWidth:'1400px',margin:'auto'}}><PromptWorkspace analysisId={batch} recordId={project} selectedSource={selection} onSourceChange={setSelection} request={request} promptPackage={source} onCopy={text=>window.copied=text} onNotice={()=>{}} onPromptPackageChange={()=>{}} onDownload={()=>{}} /></main>;}
    createRoot(document.getElementById('root')).render(<Fixture/>);
  ` } });
  const js = bundle.outputFiles.find(file => file.path.endsWith(".js")).text;
  const css = bundle.outputFiles.find(file => file.path.endsWith(".css")).text;
  const server = createServer((req, res) => {
    res.setHeader("Content-Type", req.url === "/fixture.js" ? "text/javascript" : req.url === "/fixture.css" ? "text/css" : "text/html; charset=utf-8");
    res.end(req.url === "/fixture.js" ? js : req.url === "/fixture.css" ? css : '<meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/fixture.css"><div id="root"></div><script type="module" src="/fixture.js"></script>');
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await localBrowser();
    const errors = [];
    browser.on("Runtime.exceptionThrown", event => errors.push(event.exceptionDetails.text));
    await browser.viewport(1440);
    await browser.navigate(`http://127.0.0.1:${server.address().port}`);
    await browser.ready("document.querySelectorAll('.prompt-document-shot').length===9");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='方案提示词').click()");
    await browser.ready("document.querySelectorAll('.scheme-shot').length===5");
    assert.equal(await browser.evaluate("document.querySelector('textarea[aria-label=局部视频提示词]').value"), "最新视频草稿 0");
    assert.equal(await browser.evaluate("window.calls.filter(x=>x.method==='POST').length"), 0);
    await browser.screenshot(fileURLToPath(new URL("../../../.tmp/prompt-workspace/desktop.png", import.meta.url)));
    await browser.viewport(390, 844);
    assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true);
    const columns = await browser.evaluate("getComputedStyle(document.querySelector('.scheme-shot .scheme-prompt-columns')).gridTemplateColumns.split(' ').length");
    assert.equal(columns, 1);
    await browser.screenshot(fileURLToPath(new URL("../../../.tmp/prompt-workspace/mobile.png", import.meta.url)));
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='复制全文').click()");
    assert.match(await browser.evaluate("window.copied"), /5 个分镜[\s\S]*最新视频草稿 0/);
    await browser.evaluate("window.failSave=true;const a=document.querySelector('textarea[aria-label=局部视频提示词]');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(a,'未提交文字保留');a.dispatchEvent(new Event('input',{bubbles:true}))");
    await browser.ready("document.body.textContent.includes('版本冲突')");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='原片提示词').click()");
    await pause(100);
    assert.equal(await browser.evaluate("document.querySelector('textarea[aria-label=局部视频提示词]').value"), "未提交文字保留");
    await browser.evaluate("window.failSave=false;[...document.querySelectorAll('button')].find(b=>b.textContent==='重试保存').click()");
    await browser.ready("document.querySelector('.prompt-save-state')?.textContent==='已保存'");
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='转为中文').click()");
    await browser.ready("document.body.textContent.includes('确认生成中文预览')");
    assert.equal(await browser.evaluate("window.calls.filter(x=>x.method==='POST').length"), 0);
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='确认生成中文预览').click()");
    await browser.ready("document.body.textContent.includes('确认应用到原方案')");
    assert.equal(await browser.evaluate("window.calls.filter(x=>x.path.endsWith('/localize')).length"), 1);
    assert.equal(await browser.evaluate("window.calls.filter(x=>x.path.endsWith('/apply-language')).length"), 0);
    await browser.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='确认应用到原方案').click()");
    await browser.ready("document.querySelector('textarea[aria-label=局部图片提示词]')?.readOnly===false");
    assert.match(await browser.evaluate("document.querySelector('textarea[aria-label=局部图片提示词]').value"), /冰岛黑沙滩/);
    assert.equal(await browser.evaluate("window.calls.filter(x=>x.path.endsWith('/localize')).length"), 1);
    assert.deepEqual(errors, []);
  } finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
});
