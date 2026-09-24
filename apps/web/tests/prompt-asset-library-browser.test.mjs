import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import test from 'node:test';
import { localBrowser, pause } from './helpers/local-browser.mjs';

// Actual shared editors and modal, an in-memory account, isolated browser only.
// Never touches a signed-in browser, production API or paid generation service.
test('unified prompt asset library across image, video, global, Skill and documents', { timeout: 180000 }, async t => {
  const root = fileURLToPath(new URL('..', import.meta.url));
  const cover = await readFile(new URL('../../../services/api/src/viral_dna_api/style_previews/travel_vlog.png', import.meta.url));
  const bundle = await build({
    absWorkingDir: root, bundle: true, write: false, outfile: 'fixture.js', format: 'esm', platform: 'browser', jsx: 'automatic',
    define: { 'process.env.NODE_ENV': '"production"' },
    stdin: { resolveDir: root, loader: 'jsx', contents: `
      import React, {useRef, useState} from 'react';
      import {createRoot} from 'react-dom/client';
      import './src/styles.css';
      import './src/prompt-editor/prompt-editor.css';
      import {ImageAssetPromptEditor} from './src/prompt-references/ImageAssetPromptEditor.jsx';
      import {VideoPromptReferenceEditor} from './src/video-inputs/VideoPromptReferenceEditor.jsx';
      import {usePromptAssetLibrary} from './src/prompt-references/usePromptAssetLibrary.jsx';
      import {GlobalPromptEditor} from './src/prompt-context/GlobalPromptEditor.jsx';
      import {StoryboardPromptEditor} from './src/skill-workflow/StoryboardPromptEditor.jsx';
      import {ProductionPromptDocument} from './src/prompt-editor/ProductionPromptDocument.jsx';
      import {PromptShotEditor} from './src/prompt-editor/PromptShotEditor.jsx';
      import {CreativeIntentMentionEditor} from './src/video-intents/CreativeIntentMentionEditor.jsx';
      const assets = [
        {id:'person', name:'旅行人物', type:'person', folder_id:'people', folder_name:'人物'},
        {id:'scene', name:'巴黎街景', type:'scene', folder_id:'places', folder_name:'场景'},
        {id:'coat', name:'格纹外套', type:'clothing', folder_id:null, folder_name:null},
        {id:'blocked', name:'未授权素材', type:'person', folder_id:null, rights_confirmed:false},
      ].map(item => ({media_kind:'image', thumbnail_url:'/cover.png', rights_confirmed:true, ...item}));
      const initialContext = {id:'context-1', common_image_prompt:'保持自然光线', common_video_prompt:'自然运动', common_image_mentions:[], common_video_mentions:[]};
      const initialManifest = {id:'manifest-1', revision_number:1, shots:[{stable_shot_key:'shot_12345678', duration_frames:72, image_prompt_body:'图片画面', video_prompt_body:'向左行走', image_prompt_mentions:[], video_prompt_mentions:[]}]};
      const initialDoc = {project_id:'production', name:'旅行方案', token:'doc-1', shots:[{id:'shot',index:1,duration_seconds:3,images:[{id:'image',prompt:'巴黎旅行画面',negative_constraints:[],mentions:[]}],video_prompt:'自然行走',video_mentions:[],video_negative_constraints:[]}] , common_image_prompt:'保持自然光线',common_video_prompt:'自然运动',common_image_mentions:[],common_video_mentions:[]};
      let linked = [], facts = [], revision = 1, context = initialContext, doc = initialDoc, manifest = initialManifest;
      window.calls = []; window.failAsset = ''; window.remoteDocChange = false;
      async function request(path, options={}) {
        const method=options.method || 'GET', body=options.body ? JSON.parse(options.body) : null;
        window.calls.push({path,method,body});
        if (path==='/context') return {active_workspace:{id:'account'}};
        if (path.endsWith('/asset-folders')) return [{id:'people',name:'人物'},{id:'places',name:'场景'}];
        if (path.startsWith('/workspaces/account/assets?')) {
          const params=new URL('http://fixture'+path).searchParams;
          const folder=params.get('folder_id'), q=params.get('query') || '', type=params.get('type');
          let items=assets.filter(item=>(!folder || (folder==='unfiled' ? !item.folder_id : item.folder_id===folder)) && (!q || item.name.includes(q)) && (!type || item.type===type));
          return {items,total:items.length,total_pages:1,page:1};
        }
        if (path==='/productions/production') return {project:{id:'production',current_revision_id:'revision-'+revision}};
        if (path.endsWith('/references')) return linked;
        if (path.endsWith('/link')) {
          const id=path.split('/').at(-2);
          if(window.failAsset===id) throw new Error('模拟保存失败，选择仍保留');
          if(!linked.some(item=>item.id===id)) linked.push(assets.find(item=>item.id===id));
          revision++; return {current_revision_id:'revision-'+revision};
        }
        if (path==='/projects/skill/prompt-assets') return facts;
        if (path.startsWith('/projects/skill/prompt-assets/')) {
          const asset=assets.find(item=>item.id===path.split('/').at(-1));
          if(!facts.some(item=>item.asset_id===asset.id)) facts.push({...asset,id:'usage-'+asset.id,asset_id:asset.id,image_eligible:true});
          return facts;
        }
        if (path.endsWith('/prompt-context')) {
          if(method==='PUT') context={...context,...body,id:'context-'+window.calls.length};
          return context;
        }
        if (path.endsWith('/storyboard-draft')) {
          manifest={...manifest,...body,id:'manifest-'+window.calls.length,revision_number:manifest.revision_number+1};
          window.savedManifest=manifest; return manifest;
        }
        if (path.endsWith('/prompt-document')) {
          if(method==='PUT') {doc={...doc,...body,shots:body.shots.map(row=>({...doc.shots.find(shot=>shot.id===row.id),...row})),token:'doc-'+window.calls.length};window.savedDocument=doc;}
          const current={...doc,token:'doc-'+revision};
          if(window.remoteDocChange) current.common_image_prompt='其他页面的修改';
          return current;
        }
        throw new Error('Unexpected fixture request '+method+' '+path);
      }
      const initialDraft={imagePrompt:'开头 结尾',imagePromptMentions:[],referenceBindings:[],videoPrompt:'开头 结尾',videoPromptMentions:[],selectedReferences:[]};
      function Fixture(){
        const [mode,setMode]=useState('image'),[draft,setDraft]=useState(initialDraft),[available,setAvailable]=useState([]),[locked,setLocked]=useState(false),[scope,setScope]=useState('production'),[version,setVersion]=useState(0);
        const [source,setSource]=useState({visual:{subjects:'旅行人物',scene:'巴黎',composition:'全身',lighting:'自然光',color:'自然'},phases:[],transition:{kind:'cut',instruction:''},continuity_refs:[],negative_constraints:[],custom_notes:''});
        const globalRef=useRef(null);
        const library=usePromptAssetLibrary({request,productionId:mode==='source'?undefined:scope,beforeLink:()=>globalRef.current?.flush(),onLinked:()=>setAvailable([...linked])});
        window.draft=draft; window.source=source; window.flushGlobal=()=>globalRef.current?.flush();
        window.reset=(nextMode='image',readOnly=false)=>{
          linked=[];facts=[];revision=1;context={...initialContext};doc=structuredClone(initialDoc);manifest=structuredClone(initialManifest);
          window.calls=[];window.failAsset='';window.remoteDocChange=false;window.savedManifest=null;window.savedDocument=null;localStorage.clear();
          setAvailable([]);setDraft({...initialDraft});setLocked(readOnly);setScope('production');setMode(nextMode);setVersion(value=>value+1);
        };
        window.switchScope=()=>setScope('different');
        window.setDraft=setDraft;
        return <main style={{padding:24,maxWidth:1280,margin:'auto'}} key={version}>
          <h2>旅行创作 · 提示词编辑</h2>
          {mode==='image' && <ImageAssetPromptEditor draft={draft} assets={available} setDraft={setDraft} disabled={locked} onAddAssets={library.open} referenceLimit={2}/>}
          {mode==='video' && <VideoPromptReferenceEditor assets={available} value={draft.videoPrompt} videoPromptMentions={draft.videoPromptMentions} selectedReferences={draft.selectedReferences} disabled={locked} onAddAssets={library.open} referenceLimit={2} onChange={next=>setDraft(current=>({...current,...next}))}/>}
          {mode==='intent' && <CreativeIntentMentionEditor assets={available} value={draft.intentText || '创作要求 '} mentions={draft.intentMentions || []} disabled={locked} onAddAssets={library.open} onRequestManagedAssetMention={options=>{window.managedPicker=options;}} onChange={next=>setDraft(current=>({...current,...next}))}/>}
          {mode==='global' && <GlobalPromptEditor ref={globalRef} path="/productions/production/prompt-context" request={request} assets={available} onAddAssets={library.open} disabled={locked}/>}
          {mode==='skill' && <StoryboardPromptEditor manifest={manifest} projectId="skill" request={request} busy={locked} onComplete={()=>{}}/>}
          {mode==='document' && <ProductionPromptDocument document={{...doc,read_only:locked}} request={request} onCopy={()=>{}}/>}
          {mode==='source' && <PromptShotEditor index={0} shot={{shot_id:'source',duration_seconds:3,draft:source}} disabled={locked} onChange={setSource} onAddAssets={library.open} onCopy={()=>{}}/>}
          {library.dialog}
        </main>;
      }
      createRoot(document.getElementById('root')).render(<Fixture/>);
    ` },
  });
  const script = bundle.outputFiles.find(file => file.path.endsWith('.js')).text;
  const css = bundle.outputFiles.find(file => file.path.endsWith('.css')).text;
  const server = createServer((req, res) => {
    if (req.url === '/cover.png') { res.setHeader('Content-Type', 'image/png'); res.end(cover); return; }
    if (req.url === '/fixture.js') { res.setHeader('Content-Type', 'text/javascript'); res.end(script); return; }
    res.setHeader('Content-Type','text/html; charset=utf-8');
    res.end(`<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}</style><body><div id="root"></div><script type="module" src="/fixture.js"></script></body></html>`);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  const errors = [];
  try {
    browser = await localBrowser();
    const {evaluate,ready,send} = browser;
    browser.on('Runtime.exceptionThrown',event=>errors.push(event.exceptionDetails.exception?.description || event.exceptionDetails.text));
    await browser.viewport(1440,960);
    await browser.navigate(`http://127.0.0.1:${server.address().port}`);
    await ready('window.reset');
    const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
    const textButton = text => evaluate(`[...document.querySelectorAll('button')].find(b=>(b.querySelector('.ui-button-idle') || b).textContent.trim()===${JSON.stringify(text)}).click()`);
    const tile = name => evaluate(`[...document.querySelectorAll('.prompt-asset-tile')].find(b=>b.querySelector('strong')?.textContent===${JSON.stringify(name)}).click()`);
    const key = async (key,code,extra={}) => { const windowsVirtualKeyCode={Escape:27,Enter:13,Tab:9,ArrowDown:40}[key] || 0;await send('Input.dispatchKeyEvent',{type:'keyDown',key,code,windowsVirtualKeyCode,...extra});await send('Input.dispatchKeyEvent',{type:'keyUp',key,code,windowsVirtualKeyCode,...extra}); };
    const reset = async (mode='image',locked=false) => { await evaluate(`window.reset(${JSON.stringify(mode)},${locked})`);await pause(50); };
    const openLibrary = async () => { await textButton('添加参考'); await ready("document.querySelector('.prompt-asset-tile') && !document.querySelector('[aria-busy=true]')"); };
    const selectInFolder = async (folder,name) => { await tile(folder); await ready(`[...document.querySelectorAll('.prompt-asset-tile strong')].some(e=>e.textContent===${JSON.stringify(name)})`); await tile(name); };
    const confirm = async () => {await textButton('确认引用');await ready("!document.querySelector('dialog[open]')");};
    const typeAt = async (selector,offset,text) => {
      await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.focus();window.getSelection().setBaseAndExtent(e.firstChild,${offset},e.firstChild,${offset});})()`);
      await send('Input.insertText',{text});
    };
    const home = () => click('.prompt-asset-picker-sidebar button');
    const screenshot = async name => {
      if (process.env.PROMPT_ASSET_SCREENSHOTS !== '1') return;
      await send('Page.bringToFront');
      await browser.screenshot(fileURLToPath(new URL('../../../.impeccable/review/prompt-asset-library/'+name+'.png',import.meta.url)));
    };
    await t.test('caret menu, category navigation and cancel preserve text and perform no writes',async()=>{
      await typeAt('.asset-reference-input',3,'@');
      await ready("document.querySelector('[role=listbox]')");
      assert.deepEqual(await evaluate("[...document.querySelectorAll('[role=option]')].map(e=>e.textContent)"),['图片','资产']);
      const pos=await evaluate("(()=>{const p=document.querySelector('.asset-reference-popover').getBoundingClientRect();return {right:p.right,bottom:p.bottom,left:p.left}})()");
      assert.ok(pos.left>=0 && pos.right<=1440 && pos.bottom<=960);
      await screenshot('menu');
      await textButton('资产');await ready("document.querySelector('dialog[open] .prompt-asset-check') && !document.querySelector('[aria-busy=true]')");
      await tile('格纹外套');
      await textButton('取消');await ready("!document.querySelector('dialog')");
      assert.equal(await evaluate('window.draft.imagePrompt'),'开头 @结尾');
      assert.equal(await evaluate("window.calls.filter(c=>c.method!=='GET').length"),0);
      assert.equal(await evaluate("document.activeElement.className"),'asset-reference-input');
      await send('Input.insertText',{text:'继续'});
      assert.equal(await evaluate('window.draft.imagePrompt'),'开头 @继续结尾');
    });
    await t.test('folder multi-selection, limit, single commit and batch undo preserve surrounding text',async()=>{
      await reset(); await typeAt('.asset-reference-input',3,'@');await textButton('资产');await ready("document.querySelector('dialog[open] .prompt-asset-check') && !document.querySelector('[aria-busy=true]')");
      await selectInFolder('人物','旅行人物');await home();await ready("[...document.querySelectorAll('.prompt-asset-tile strong')].some(e=>e.textContent==='格纹外套')");
      await tile('格纹外套');
      await selectInFolder('场景','巴黎街景');
      assert.equal(await evaluate("document.querySelector('.prompt-asset-tile[aria-pressed]').disabled"),true);
      await confirm();
      const draft=await evaluate('window.draft');
      assert.equal(draft.imagePrompt,'开头 @人物/旅行人物 @未分类/格纹外套 结尾');
      assert.deepEqual(draft.imagePromptMentions.map(item=>item.reference_asset_id),['person','coat']);
      assert.equal(draft.referenceBindings.length,2);
      assert.equal(draft.referenceBindings[1].role,'wardrobe');
      assert.equal(await evaluate("document.querySelectorAll('.asset-reference-thumbnail').length"),2);
      await key('z','KeyZ',{modifiers:2});
      assert.equal(await evaluate('window.draft.imagePrompt'),'开头 @结尾');
      assert.deepEqual(await evaluate('window.draft.imagePromptMentions'),[]);
      await key('y','KeyY',{modifiers:2});
      assert.equal(await evaluate('window.draft.imagePromptMentions.length'),2);
    });
    await t.test('already linked references can be inserted again without duplicate bindings or links',async()=>{
      await openLibrary();await selectInFolder('人物','旅行人物');await confirm();
      assert.equal(await evaluate('window.draft.imagePromptMentions.length'),2);
      assert.equal(await evaluate('window.draft.referenceBindings.length'),2);
      assert.equal(await evaluate("window.calls.filter(c=>c.path.endsWith('/person/link')).length"),1);
    });
    await t.test('failed partial linking keeps selection and skips completed links on retry',async()=>{
      await reset();await openLibrary();await tile('格纹外套');await selectInFolder('人物','旅行人物');
      await evaluate("window.failAsset='person'");await textButton('确认引用');await ready("document.querySelector('dialog [role=alert]')");
      assert.equal(await evaluate('window.draft.imagePrompt'),'开头 结尾');
      assert.match(await evaluate("document.querySelector('dialog footer').textContent"),/已选择 2 项/);
      await evaluate("window.failAsset=''");await confirm();
      assert.equal(await evaluate("window.calls.filter(c=>c.path.endsWith('/coat/link')).length"),1);
      assert.equal(await evaluate('window.draft.imagePromptMentions.length'),2);
    });
    await t.test('video uses the same library and persists actual video input references',async()=>{
      await reset('video');await openLibrary();await tile('格纹外套');await confirm();
      const draft=await evaluate('window.draft');
      assert.equal(draft.videoPromptMentions[0].reference_kind,'project_asset');
      assert.equal(draft.videoPromptMentions[0].reference_id,'coat');
      assert.equal(draft.selectedReferences[0].reference_id,'coat');
    });
    await t.test('global image and video editors save stable mention metadata',async()=>{
      await reset('global');await ready("document.querySelector('[aria-label=全局图片提示词][contenteditable=true]')");
      await click('.global-prompt-editor summary');await openLibrary();await tile('格纹外套');await confirm();
      await evaluate('window.flushGlobal()');
      assert.equal(await evaluate("window.calls.filter(c=>c.method==='PUT').at(-1).body.common_image_mentions[0].reference_asset_id"),'coat');
      await evaluate("document.querySelectorAll('.global-prompt-fields .prompt-style-tools button')[1].click()");await ready("document.querySelector('dialog .prompt-asset-check') && !document.querySelector('[aria-busy=true]')");
      await tile('格纹外套');await confirm();await evaluate('window.flushGlobal()');
      assert.equal(await evaluate("window.calls.filter(c=>c.method==='PUT').at(-1).body.common_video_mentions[0].reference_id"),'coat');
    });
    await t.test('creative intent shares the library, search and managed-character entry',async()=>{
      await reset('intent');await openLibrary();
      await evaluate("(()=>{const e=document.querySelector('[aria-label=搜索资产库]');e.focus();})()");
      await send('Input.insertText',{text:'格纹'});
      await ready("document.querySelectorAll('.prompt-asset-tile').length===1 && !document.querySelector('[aria-busy=true]')");
      await tile('格纹外套');await confirm();
      assert.equal(await evaluate('window.draft.intentMentions[0].reference_id'),'coat');
      await send('Input.insertText',{text:'@'});await ready("document.querySelector('[role=listbox]')");
      await textButton('从托管资产目录选择');await ready('window.managedPicker');
      await evaluate("window.managedPicker.insert({reference_kind:'provider_managed_asset',reference_id:'actor',label:'托管角色/小喵',role:'actor_identity'})");
      await ready('window.draft.intentMentions.length===2');
      assert.equal(await evaluate('window.draft.intentMentions[1].reference_id'),'actor');
    });
    await t.test('Skill-created projects reuse the picker for both prompt fields and save asset IDs, not usage IDs',async()=>{
      await reset('skill');await ready("document.querySelectorAll('.asset-reference-input').length>=4");
      await evaluate("[...document.querySelectorAll('.asset-reference-editor')].find(e=>e.querySelector('[role=textbox]')?.getAttribute('aria-label')?.includes('分镜 1 局部图片')).querySelector('.prompt-style-tools button').click()");
      await ready("document.querySelector('dialog .prompt-asset-check') && !document.querySelector('[aria-busy=true]')");await tile('格纹外套');await confirm();
      await ready("window.savedManifest?.shots[0].image_prompt_mentions.length===1");
      assert.equal(await evaluate('window.savedManifest.shots[0].image_prompt_mentions[0].reference_asset_id'),'coat');
      await evaluate("[...document.querySelectorAll('.asset-reference-editor')].find(e=>e.querySelector('[role=textbox]')?.getAttribute('aria-label')?.includes('分镜 1 局部视频')).querySelector('.prompt-style-tools button').click()");
      await ready("document.querySelector('dialog .prompt-asset-check') && !document.querySelector('[aria-busy=true]')");await tile('格纹外套');await confirm();
      await ready("window.savedManifest?.shots[0].video_prompt_mentions.length===1");
      assert.equal(await evaluate('window.savedManifest.shots[0].video_prompt_mentions[0].reference_id'),'coat');
    });
    await t.test('production prompt document saves image/video mentions and preserves CAS conflicts',async()=>{
      await reset('document');await ready("document.querySelector('[aria-label=局部图片提示词]')");
      await evaluate("document.querySelector('[aria-label=局部图片提示词]').closest('.asset-reference-editor').querySelector('button').click()");
      await ready("document.querySelector('dialog .prompt-asset-check') && !document.querySelector('[aria-busy=true]')");await tile('格纹外套');await confirm();
      await ready("window.savedDocument?.shots[0].images[0].mentions.length===1");
      assert.equal(await evaluate('window.savedDocument.shots[0].images[0].mentions[0].reference_asset_id'),'coat');
      await evaluate("document.querySelector('[aria-label=局部视频提示词]').closest('.asset-reference-editor').querySelector('button').click()");
      await ready("document.querySelector('dialog .prompt-asset-check') && !document.querySelector('[aria-busy=true]')");await tile('格纹外套');await confirm();
      await ready("window.savedDocument?.shots[0].video_mentions.length===1");
      await evaluate("document.querySelector('[aria-label=局部图片提示词]').closest('.asset-reference-editor').querySelector('button').click()");
      await ready("document.querySelector('dialog .prompt-asset-check') && !document.querySelector('[aria-busy=true]')");await tile('格纹外套');await evaluate('window.remoteDocChange=true');await textButton('确认引用');
      await ready("document.querySelector('dialog [role=alert]')");
      assert.match(await evaluate("document.querySelector('dialog [role=alert]').textContent"),/其他页面更新/);
      await textButton('取消');
    });
    await t.test('original analysis document supports the same @ library while preserving structured draft',async()=>{
      await reset('source');await click('.prompt-document-shot-toggle');await openLibrary();await tile('格纹外套');await confirm();
      assert.equal(await evaluate('window.source.asset_mentions[0].reference_asset_id'),'coat');
      assert.equal(await evaluate('window.source.visual.scene'),'巴黎');
      assert.equal(await evaluate("window.calls.filter(c=>c.method!=='GET').length"),0);
    });
    await t.test('read-only prevents editing and scope change dismisses stale library',async()=>{
      await reset('image',true);
      assert.equal(await evaluate("document.querySelector('.asset-reference-input').contentEditable"),'false');
      assert.equal(await evaluate("document.querySelector('.prompt-style-tools button').disabled"),true);
      await reset();await openLibrary();await evaluate('window.switchScope()');await ready("!document.querySelector('dialog')");
      assert.equal(await evaluate("window.calls.filter(c=>c.method!=='GET').length"),0);
    });
    await t.test('IME defers menu until composition ends; Escape dismisses without deleting input',async()=>{
      await reset();
      await evaluate("(()=>{const e=document.querySelector('.asset-reference-input');e.focus();e.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));e.textContent='中文@';const n=e.firstChild;window.getSelection().setBaseAndExtent(n,n.length,n,n.length);e.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));})()");
      assert.equal(await evaluate("!!document.querySelector('[role=listbox]')"),false);
      await evaluate("document.querySelector('.asset-reference-input').dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}))");
      await ready("document.querySelector('[role=listbox]')");await key('Escape','Escape');
      assert.equal(await evaluate('window.draft.imagePrompt'),'中文@');
      assert.equal(await evaluate("!!document.querySelector('[role=listbox]')"),false);
    });
    await t.test('desktop/mobile dialog stays within viewport with visible confirmation and unavailable asset feedback',async()=>{
      await reset();await openLibrary();
      assert.equal(await evaluate("[...document.querySelectorAll('.prompt-asset-tile')].find(e=>e.textContent.includes('未授权素材')).disabled"),true);
      await screenshot('desktop');
      await browser.viewport(390,844);await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
      const box=await evaluate("(()=>{const d=document.querySelector('dialog').getBoundingClientRect(),f=document.querySelector('dialog footer').getBoundingClientRect();return {left:d.left,right:d.right,bottom:d.bottom,footer:f.bottom,width:document.documentElement.scrollWidth}})()");
      assert.ok(box.left>=0 && box.right<=391 && box.bottom<=845 && box.footer<=845 && box.width<=390,JSON.stringify(box));
      await screenshot('mobile');
      await key('Escape','Escape');await ready("!document.querySelector('dialog')");
    });
    assert.deepEqual(errors,[]);
  } finally { await browser?.close(); await new Promise(resolve=>server.close(resolve)); }
});
