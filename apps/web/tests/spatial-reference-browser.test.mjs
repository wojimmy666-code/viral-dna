import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import test from 'node:test';
import { localBrowser, pause } from './helpers/local-browser.mjs';

// Fresh headless profile and in-memory fixture only. No user session, account,
// generation provider or production content is touched by this acceptance test.
test('spatial purpose, shared picker, batch confirmation and responsive layout', { timeout: 180000 }, async () => {
  const root = fileURLToPath(new URL('..', import.meta.url));
  const cover = await readFile(new URL('../../../services/api/src/viral_dna_api/style_previews/travel_vlog.png', import.meta.url));
  const bundle = await build({ absWorkingDir: root, bundle: true, write: false, outfile: 'fixture.js', format: 'esm', platform: 'browser', jsx: 'automatic',
    define: { 'process.env.NODE_ENV': '"production"' }, stdin: { resolveDir: root, loader: 'jsx', contents: `
      import React, {useState} from 'react';
      import {createRoot} from 'react-dom/client';
      import './src/styles.css';
      import {ImageAssetPromptEditor} from './src/prompt-references/ImageAssetPromptEditor.jsx';
      import {ShotStyleControl} from './src/visual-styles/ProductionStyleControl.jsx';
      import {PromptAssetPicker} from './src/prompt-references/PromptAssetPicker.jsx';
      import {SpatialReferenceApply} from './src/prompt-references/SpatialReferenceApply.jsx';
      import {StyleLibraryAdmin} from './src/admin/StyleLibraryAdmin.jsx';
      const assets = [ ['person','旅行人物','person'],['space','街头行走空间样例','scene'],['second','另一张街景','scene'] ].map(([id,name,type])=>({
        id,name,type,media_kind:'image',rights_confirmed:true,thumbnail_url:'/cover.png',folder_id:null,
      }));
      const style={id:'travel',name:'旅行 Vlog',category:'写实摄影',tags:['日常随拍'],description:'自然现场光线与旅行随拍质感',version:2,revision:2,enabled:true,sort_order:0,
        applies_to:['image','video'],selection:{catalog_id:'travel',catalog_version:2},cover_id:'cover',cover_url:'/cover.png',reference_image_id:'reference',reference_image_url:'/cover.png',sample_ids:[],image_prompt:'保持现场光线与日常随拍质感',video_prompt:'自然行走'};
      const context={visual_style:style.selection,visual_style_snapshot:{label:style.name,cover_url:style.cover_url},shot_styles:{},shot_style_snapshots:{}};
      const targets=[{id:'a',shot_id:'s1',label:'分镜 1 · 巴黎街头',spatial_reference_ids:[]},{id:'b',shot_id:'s2',label:'分镜 2 · 河边行走',spatial_reference_ids:['old']},{id:'c',shot_id:'s3',label:'分镜 3 · 街角转场',spatial_reference_ids:[]}];
      window.calls=[];window.failSave=false;window.guide=false;
      async function request(path,options={}) {
        const body=options.body?JSON.parse(options.body):null;window.calls.push({path,method:options.method||'GET',body});
        if(path==='/context') return {active_workspace:{id:'account'}};
        if(path.endsWith('/asset-folders')) return [];
        if(path.includes('/assets?')) return {items:assets,total:3,page:1,total_pages:1};
        if(path==='/admin/visual-styles' || path==='/me/settings/visual-styles') return {version:'visual-style-library-v1',items:[style]};
        if(path.endsWith('/spatial-references')) {
          if(options.method==='PUT' && window.failSave) throw new Error('版本已更新');
          return {revision_id:'revision',context_id:'context',targets:targets.map(item=>({...item,has_composition:window.guide && item.id==='a'}))};
        }
        throw new Error('Unexpected isolated request '+path);
      }
      function Fixture(){
        const [draft,setDraft]=useState({imagePrompt:'保持日常随拍。@人物/旅行人物 向左行走，空间参考 @场景/街头行走空间样例。',imagePromptMentions:[{reference_asset_id:'person',label:'人物/旅行人物',role:'identity'},{reference_asset_id:'space',label:'场景/街头行走空间样例',role:'scene'}],referenceBindings:[{reference_asset_id:'person',role:'identity',weight:1},{reference_asset_id:'space',role:'scene',weight:1}]});
        const [batch,setBatch]=useState(null),[picker,setPicker]=useState(null),[locked,setLocked]=useState(false),[admin,setAdmin]=useState(false),[version,setVersion]=useState(0);
        window.draft=draft;window.setLocked=setLocked;window.setAdmin=setAdmin;window.remount=()=>setVersion(n=>n+1);
        return <main style={{padding:24,maxWidth:1120,margin:'auto'}}><h2>{admin?'风格库管理':'分镜 1 · 巴黎街头'}</h2>
          {admin?<StyleLibraryAdmin request={request}/>:<ImageAssetPromptEditor key={version} draft={draft} setDraft={setDraft} assets={assets} disabled={locked}
            onApplySpatial={setBatch} onAddAssets={(insert,options)=>setPicker({insert,options})} referenceLimit={4}
            styleControl={<ShotStyleControl shotKey="s1" part="image" context={context} request={request} editorRef={{current:{applyStyle:async()=>{}}}} disabled={locked}/>}/>}
          {picker&&<PromptAssetPicker {...picker.options} request={request} onClose={()=>setPicker(null)} onSelect={items=>{picker.insert(items);setPicker(null);}}/>}
          {batch&&<SpatialReferenceApply projectId="project" beatId="a" reference={batch} request={request} disabled={locked} beforeLoad={async()=>true} onSaved={async ids=>{window.savedShots=ids;}} onClose={()=>setBatch(null)}/>}
        </main>;
      }
      createRoot(document.getElementById('root')).render(<Fixture/>);
    ` } });
  const script=bundle.outputFiles.find(file=>file.path.endsWith('.js')).text;
  const css=bundle.outputFiles.find(file=>file.path.endsWith('.css')).text;
  const server=createServer((req,res)=>{
    if(req.url==='/cover.png'){res.setHeader('Content-Type','image/png');res.end(cover);return;}
    if(req.url==='/fixture.js'){res.setHeader('Content-Type','text/javascript');res.end(script);return;}
    res.setHeader('Content-Type','text/html; charset=utf-8');
    res.end(`<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style><body><div id="root"></div><script type="module" src="/fixture.js"></script></body></html>`);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  let browser;
  try {
    browser=await localBrowser();
    const {evaluate,ready,send}=browser, errors=[];
    browser.on('Runtime.exceptionThrown',event=>errors.push(event.exceptionDetails.exception?.description||event.exceptionDetails.text));
    await browser.viewport(1440,960);
    await browser.navigate(`http://127.0.0.1:${server.address().port}`);
    await ready('window.draft && document.querySelector(".asset-reference-thumbnail")');
    const click=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
    const button=text=>evaluate(`[...document.querySelectorAll('button')].find(b=>(b.querySelector('.ui-button-idle')||b).textContent.trim()===${JSON.stringify(text)}).click()`);
    const select=(selector,value)=>evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
    const preview=()=>click('.asset-reference-thumbnail[aria-label*="街头行走"]');
    const overflow=async()=>assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth+1'),false);
    const shot=(name,fullPage=false)=>browser.screenshot(fileURLToPath(new URL(`../../../.impeccable/review/spatial-reference/${name}.png`,import.meta.url)),fullPage);
    await preview(); await ready('document.querySelector("select[aria-label=引用用途]")');
    await select('select[aria-label="引用用途"]','spatial');
    await ready('window.draft.imagePromptMentions[1].role==="spatial"');
    assert.equal(await evaluate('window.draft.referenceBindings[1].role'),'scene','shared binding is not mutated');
    await click('[aria-label="关闭引用预览"]');
    assert.match(await evaluate('document.querySelector(".asset-reference-thumbnail").getAttribute("aria-label")'),/街头行走/);
    await evaluate('window.remount()'); await pause(60);
    await preview(); await ready('document.querySelector("select[aria-label=引用用途]")?.value==="spatial"');
    await overflow(); await shot('desktop-preview');
    await button('应用到其他画面…'); await ready('document.querySelector(".spatial-reference-dialog select")');
    await select('[aria-label="空间参考应用范围"]','selected');
    await click('.spatial-reference-targets label:nth-of-type(2) input');
    assert.equal(await evaluate('[...document.querySelectorAll(".spatial-reference-dialog footer button")].at(-1).disabled'),true);
    await click('.spatial-reference-confirm input');
    await shot('desktop-batch');
    await evaluate('window.failSave=true'); await button('应用到 2 个画面');
    await ready('document.querySelector(".spatial-reference-dialog [role=alert]")');
    assert.equal(await evaluate('document.querySelectorAll(".spatial-reference-targets input:checked").length'),2);
    await evaluate('window.failSave=false'); await button('重新读取状态');
    await ready('!document.querySelector(".spatial-reference-dialog [role=alert]")');
    assert.equal(await evaluate('document.querySelector(".spatial-reference-confirm input").checked'),false);
    await click('.spatial-reference-confirm input'); await button('应用到 2 个画面');
    await ready('!document.querySelector("dialog[open]")');
    assert.deepEqual(await evaluate('window.savedShots'),['s1','s2']);
    assert.deepEqual(await evaluate('window.calls.filter(c=>c.method==="PUT").at(-1).body.visual_beat_ids'),['a','b']);
    await button('添加参考'); await ready('document.querySelectorAll(".prompt-asset-tile").length===3');
    await evaluate('[...document.querySelectorAll(".prompt-asset-tile")].find(e=>e.textContent.includes("另一张街景")).click()');
    await select('[aria-label="另一张街景的引用用途"]','spatial');
    await shot('desktop-picker');
    await button('确认引用');
    await ready('document.querySelector(".prompt-asset-picker [role=alert]")');
    assert.equal(await evaluate('document.querySelectorAll(".reference-purpose-selection select").length'),1,'rejected duplicate retains selection');
    await select('[aria-label="另一张街景的引用用途"]','scene'); await button('确认引用');
    await ready('!document.querySelector("dialog[open]")');
    await browser.viewport(390,844); await pause(150); await preview(); await ready('document.querySelector("select[aria-label=引用用途]")');
    await overflow(); await shot('mobile-preview');
    await click('[aria-label="关闭引用预览"]');
    await click('.asset-reference-thumbnail[aria-label*="另一张街景"]');
    await ready('document.querySelector("select[aria-label=引用用途]")');
    await select('[aria-label="引用用途"]','spatial');
    await ready('document.querySelector(".asset-reference-popover [role=alert]")');
    assert.equal(await evaluate('document.querySelector("select[aria-label=引用用途]").getAttribute("aria-invalid")'),'true');
    const errorVisible=await evaluate('(()=>{const r=document.querySelector(".asset-reference-popover [role=alert]").getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;})()');
    assert.equal(errorVisible,true,'purpose conflict is visible next to the mobile control');
    await shot('mobile-purpose-conflict');
    await select('[aria-label="引用用途"]','scene');
    await click('[aria-label="关闭引用预览"]'); await preview();
    await button('应用到其他画面…'); await ready('document.querySelector(".spatial-reference-dialog select")');
    await select('[aria-label="空间参考应用范围"]','all');
    await overflow(); await shot('mobile-batch');
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
    await ready('!document.querySelector("dialog[open]")');
    await button('添加参考'); await ready('document.querySelectorAll(".prompt-asset-tile").length===3');
    await evaluate('document.querySelector(".prompt-asset-tile").click()');
    await evaluate('document.querySelector(".reference-purpose-selection").scrollIntoView({block:"end"})');
    await overflow(); await shot('mobile-picker'); await button('取消');
    await evaluate('window.setLocked(true)'); await preview(); await ready('document.querySelector("select[aria-label=引用用途]")?.disabled');
    await click('[aria-label="关闭引用预览"]');
    await evaluate('window.setAdmin(true)'); await ready('document.querySelector(".style-admin-list button")');
    await click('.style-admin-list button'); await ready('document.querySelector(".style-admin-editor")');
    await shot('mobile-admin',true);
    const adminOverflow=await evaluate('document.documentElement.scrollWidth>innerWidth+1');
    if(adminOverflow) console.log('Admin overflow:',await evaluate('[...document.querySelectorAll(".style-admin *")].filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,className:e.className,right:e.getBoundingClientRect().right})).slice(0,20)'));
    await browser.viewport(1440,1080); await shot('desktop-admin',true);
    assert.equal(await evaluate('window.calls.some(c=>c.path.includes("generate"))'),false);
    assert.deepEqual(errors,[]);
    assert.equal(adminOverflow,false,'mobile admin must not overflow');
  } finally { await browser?.close(); await new Promise(resolve=>server.close(resolve)); }
});
