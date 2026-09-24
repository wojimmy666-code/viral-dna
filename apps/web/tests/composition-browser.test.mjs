import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import test from 'node:test';
import {localBrowser} from './helpers/local-browser.mjs';

test('composition guidance — isolated real component and mock API, no model calls',{timeout:120000},async t=>{
  const root=fileURLToPath(new URL('..',import.meta.url));
  const cover=await readFile(new URL('../../../services/api/src/viral_dna_api/style_previews/travel_vlog.png',import.meta.url));
  const bundle=await build({absWorkingDir:root,bundle:true,write:false,outfile:'fixture.js',format:'esm',platform:'browser',jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'},stdin:{resolveDir:root,loader:'jsx',contents:`
    import React,{useState} from 'react';import {createRoot} from 'react-dom/client';
    import './src/styles.css';import {CompositionControl} from './src/composition/CompositionControl.jsx';
    window.calls=[];window.fail=false;window.slow=false;let version=1;let entries={};
    const targets=[{id:'beat-1',shot_id:'shot-1',label:'分镜 1 · 画面 1'},{id:'beat-2',shot_id:'shot-2',label:'分镜 2 · 画面 1'}];
    const snapshot=()=>({context_id:'c'+version,revision_id:'r1',width:1920,height:1080,entries:structuredClone(entries),targets});
    async function request(path,options={}) {
      const body=options.body?JSON.parse(options.body):null;window.calls.push({path,method:options.method||'GET',body});
      if(window.slow)await new Promise(resolve=>window.release=resolve);
      if(options.method==='PUT'){
        if(window.fail)throw new Error('版本冲突，当前构图未保存');
        if(body.expected_context_id!=='c'+version)throw new Error('版本冲突');
        if(body.operation==='default')entries['default:p']=body.guide;
        else if(body.operation==='clear_default')delete entries['default:p'];
        else for(const id of body.visual_beat_ids){if(body.operation==='inherit')delete entries[id];else entries[id]=body.operation==='disable'?null:body.guide;}
        version++;
      }return snapshot();
    }
    function App(){const [disabled,setDisabled]=useState(false),[beat,setBeat]=useState('beat-1');window.setReadonly=setDisabled;window.setBeat=setBeat;
      return <main style={{padding:24,maxWidth:1240,margin:'auto'}}><h1>旅行分镜 · 构图定位测试</h1><p>隔离测试数据，不连接真实项目。</p><CompositionControl projectId="p" beatId={beat} request={request} disabled={disabled} previewUrl="/cover.png" assets={[{id:'person-1',type:'person',name:'测试人物',rights_confirmed:true}]} beforeOpen={async()=>true} onSaved={async()=>{window.refreshed=true;}}/></main>;
    }createRoot(document.getElementById('root')).render(<App/>);
  `}});
  const js=bundle.outputFiles.find(file=>file.path.endsWith('.js')).text,css=bundle.outputFiles.find(file=>file.path.endsWith('.css')).text;
  const server=createServer((req,res)=>{
    if(req.url==='/fixture.js'){res.setHeader('Content-Type','text/javascript');res.end(js);}
    else if(req.url==='/fixture.css'){res.setHeader('Content-Type','text/css');res.end(css);}
    else if(req.url==='/cover.png'){res.setHeader('Content-Type','image/png');res.end(cover);}
    else{res.setHeader('Content-Type','text/html; charset=utf-8');res.end('<!doctype html><html lang="zh-CN"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/fixture.css"><div id="root"></div><script type="module" src="/fixture.js"></script></html>');}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await localBrowser();
  const url=`http://127.0.0.1:${server.address().port}`;
  const click=label=>browser.evaluate(`([...document.querySelectorAll('button')].find(button=>(button.querySelector('.ui-button-idle')?.textContent||button.textContent).trim()===${JSON.stringify(label)})||document.querySelector('[aria-label="${label}"]')).click()`);
  const setValue=(selector,value)=>browser.evaluate(`(()=>{const input=document.querySelector(${JSON.stringify(selector)});Object.getOwnPropertyDescriptor(input.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value').set.call(input,${JSON.stringify(value)});input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  const open=async()=>{await browser.evaluate(`document.querySelector('.composition-control button').click()`);await browser.ready(`document.querySelector('dialog[open]')`);};
  const reset=async()=>{await browser.navigate(url);await browser.ready(`document.querySelector('.composition-control button')`);};
  try{
    await browser.viewport(1440,960);await reset();
    await t.test('cancel preserves saved data and keyboard changes geometry',async()=>{
      await open();await browser.evaluate(`document.querySelector('[aria-label="移动目标人物框"]').focus()`);
      await browser.send('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowLeft',code:'ArrowLeft',windowsVirtualKeyCode:37});
      await browser.send('Input.dispatchKeyEvent',{type:'keyUp',key:'ArrowLeft',code:'ArrowLeft',windowsVirtualKeyCode:37});
      assert.equal(await browser.evaluate(`document.querySelector('[aria-label="左边距百分比"]').value`),'39.8');
      await click('取消');assert.equal(await browser.evaluate(`window.calls.filter(call=>call.method==='PUT').length`),0);
    });
    await t.test('drag and resize use real canvas coordinates, presets stay in bounds',async()=>{
      await open();const rect=await browser.evaluate(`(()=>{const r=document.querySelector('.composition-drag').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
      await browser.send('Input.dispatchMouseEvent',{type:'mousePressed',x:rect.x,y:rect.y,button:'left',clickCount:1});
      await browser.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:rect.x+80,y:rect.y,button:'left',buttons:1});
      await browser.send('Input.dispatchMouseEvent',{type:'mouseReleased',x:rect.x+80,y:rect.y,button:'left',clickCount:1});
      assert.ok(Number(await browser.evaluate(`document.querySelector('[aria-label="左边距百分比"]').value`))>45);
      await click('左三分之一');assert.ok(Math.abs(Number(await browser.evaluate(`document.querySelector('[aria-label="左边距百分比"]').value`))-23.3)<.2);
      await browser.evaluate(`document.querySelector('[aria-label="调整目标人物大小"]').focus()`);
      await browser.send('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowDown',code:'ArrowDown',windowsVirtualKeyCode:40});
      await browser.send('Input.dispatchKeyEvent',{type:'keyUp',key:'ArrowDown',code:'ArrowDown',windowsVirtualKeyCode:40});
      assert.equal(await browser.evaluate(`document.querySelector('[aria-label="人物高度百分比"]').value`),'65.2');
      await click('取消');
    });
    await t.test('multi-frame apply commits once and refreshing keeps normalized box',async()=>{
      await open();await click('右三分之一');await setValue('[aria-label="构图应用范围"]','all');await click('应用构图');await browser.ready(`!document.querySelector('dialog[open]')`);
      const writes=await browser.evaluate(`window.calls.filter(call=>call.method==='PUT')`);assert.equal(writes.length,1);assert.deepEqual(writes[0].body.visual_beat_ids,['beat-1','beat-2']);
      await open();assert.equal(await browser.evaluate(`document.querySelector('[aria-label="左边距百分比"]').value`),'56.7');await click('取消');
    });
    await t.test('CAS failure retains the draft without retry; manual comparison is explicitly labeled',async()=>{
      await open();await click('居中');await browser.evaluate(`window.fail=true`);await click('应用构图');await browser.ready(`document.querySelector('.composition-error')`);
      assert.equal(await browser.evaluate(`document.querySelector('[aria-label="左边距百分比"]').value`),'40');
      assert.match(await browser.evaluate(`document.querySelector('.composition-error').textContent`),/未保存/);
      await browser.evaluate(`document.querySelector('.composition-review input').click()`);
      assert.match(await browser.evaluate(`document.querySelector('.composition-review').textContent`),/不是自动识别/);
      await click('取消');await browser.evaluate(`window.fail=false`);
    });
    await t.test('lost edit permission disables apply and changing frames dismisses stale modal',async()=>{
      await open();await browser.evaluate(`window.setReadonly(true)`);await browser.ready(`document.querySelector('.composition-dialog .primary-button').disabled`);
      await browser.evaluate(`window.setBeat('beat-2')`);await browser.ready(`!document.querySelector('dialog[open]')`);await browser.evaluate(`window.setReadonly(false)`);
    });
    await t.test('adopting manual geometry preserves later subject and facing edits',async()=>{
      await open();await browser.evaluate(`document.querySelector('.composition-review input').click()`);
      await setValue('.composition-controls fieldset:first-child select:first-of-type','person-1');
      await setValue('.composition-controls fieldset:first-child label:last-child select','left');
      await click('用人工标记作为新构图');
      assert.equal(await browser.evaluate(`document.querySelector('.composition-controls fieldset:first-child select:first-of-type').value`),'person-1');
      assert.equal(await browser.evaluate(`document.querySelector('.composition-controls fieldset:first-child label:last-child select').value`),'left');
      await click('取消');
    });
    await t.test('default scope cannot reset current frame override',async()=>{
      await open();await setValue('[aria-label="构图应用范围"]','default');
      assert.equal(await browser.evaluate(`[...document.querySelectorAll('.composition-secondary button')].some(button=>button.textContent.includes('恢复默认'))`),false);
      assert.match(await browser.evaluate(`document.querySelector('.composition-secondary').textContent`),/清除方案默认/);
      await setValue('[aria-label="构图应用范围"]','current');
      assert.equal(await browser.evaluate(`[...document.querySelectorAll('.composition-secondary button')].some(button=>button.textContent.includes('恢复默认'))`),true);
      await click('取消');
    });
    await t.test('desktop/mobile sizing and actual screenshots',async()=>{
      await open();await browser.ready(`document.querySelector('.composition-canvas img').complete`);
      for(const [name,width,height] of [['desktop',1440,960],['mobile',390,844]]){
        await browser.viewport(width,height);
        const geometry=await browser.evaluate(`(()=>{const d=document.querySelector('dialog'),r=d.getBoundingClientRect(),c=document.querySelector('.composition-canvas').getBoundingClientRect();return {left:r.left,right:r.right,canvas:c.width,overflow:d.scrollWidth>d.clientWidth+1};})()`);
        assert.ok(geometry.left>=-1&&geometry.right<=width+1);assert.ok(geometry.canvas>250);assert.equal(geometry.overflow,false);
        if(process.env.COMPOSITION_SCREENSHOTS==='1')await browser.screenshot(fileURLToPath(new URL('../../../.impeccable/review/composition/'+name+'.png',import.meta.url)));
      }
      await click('取消');
    });
  }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
});
