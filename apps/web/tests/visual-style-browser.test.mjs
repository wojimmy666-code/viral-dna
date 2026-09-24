import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import test from "node:test";
import { localBrowser } from "./helpers/local-browser.mjs";

// The real control and shared styles, with in-memory selections and save failures.
// This fixture never reads an account or calls a production API or generation model.
test("single visual style: thumbnail layout, replacement, removal and keyboard recovery", { timeout: 90000 }, async t => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const cover = await readFile(new URL("../../../services/api/src/viral_dna_api/style_previews/travel_vlog.png", import.meta.url));
  const bundle = await build({
    absWorkingDir: root, bundle: true, write: false, outfile: "fixture.js", format: "esm", platform: "browser", jsx: "automatic",
    define: { "process.env.NODE_ENV": '"production"' },
    stdin: { resolveDir: root, loader: "jsx", contents: `
      import React, {useState} from 'react';
      import {createRoot} from 'react-dom/client';
      import './src/styles.css';
      import {ShotStyleControl} from './src/visual-styles/ProductionStyleControl.jsx';
      import {AssetReferenceEditor} from './src/prompt-references/AssetReferenceEditor.jsx';
      const original = {preset:'original'};
      const items = [['travel','旅行 Vlog'],['cinema','电影质感'],['long','这是一个名称很长的旅行纪实画面风格']].map(([id,name]) => ({
        id, name, version:1, category:'摄影', tags:[], applies_to:['image','video'],
        selection:{catalog_id:id,catalog_version:1}, cover_url:id==='long'?null:'/cover.png',
        description:'隔离验收示意', image_prompt:'保持日常随拍质感', video_prompt:'自然随拍动态',
      }));
      const snapshot = item => item ? {selection:item.selection,label:item.name,cover_url:item.cover_url} : {};
      const references = ['人物','服装','地标','场景'].map((label,index)=>({reference_asset_id:'asset-'+index,label,thumbnail_url:'/cover.png',preview_url:'/cover.png'}));
      const initialPrompt = '画面中心是一位年轻亚洲女性 @人物，身穿深蓝色格纹制服 @服装，自然向左行走。背景为巴黎埃菲尔铁塔 @地标，保持旅行随拍的现场光线 @场景。';
      window.calls = []; window.saves = []; window.failSave = false; window.holdSave = false;
      async function request(path, options) {
        window.calls.push({path,method:options?.method || 'GET'});
        if (path.endsWith('/preview')) return snapshot(items.find(item=>item.id===JSON.parse(options.body).catalog_id));
        if (path.endsWith('/used')) return {};
        if (path==='/me/settings/visual-styles') return {version:'visual-style-library-v1',items};
        throw new Error('Unexpected fixture request: '+path);
      }
      function Fixture() {
        const [value,setValue]=useState(original), [compiled,setCompiled]=useState({}), [disabled,setDisabled]=useState(false);
        const [part,setPart]=useState('image'), [prompt,setPrompt]=useState(initialPrompt), [refs,setRefs]=useState(references);
        window.setPart=setPart; window.currentPrompt=prompt; window.currentReferences=refs;
        window.resetStyle=(id, locked=false)=>{
          const item=items.find(item=>item.id===id);
          setValue(id==='inherit'?null:item?.selection || original); setCompiled(snapshot(item)); setDisabled(locked);
        };
        return <main style={{padding:'24px',background:'var(--surface-panel)'}}>
          <h2>局部{part==='image'?'图片':'视频'}提示词</h2>
          <AssetReferenceEditor value={prompt} references={refs} options={references} disabled={disabled} rows={4}
            label={part==='image'?'图片提示词':'视频提示词'} onAddAssets={()=>{}} onChange={(text,next)=>{setPrompt(text);setRefs(next);}}
            styleControl={<ShotStyleControl shotKey="shot" part={part} disabled={disabled} request={request}
            context={{visual_style:original,visual_style_snapshot:snapshot(items[0]),shot_styles:{shot:value},shot_style_snapshots:{shot:compiled}}}
            editorRef={{current:{applyStyle:async (next,result)=>{
              window.saves.push(next);
              if(window.holdSave) await new Promise(resolve=>{window.releaseSave=resolve;});
              if(window.failSave) throw new Error('保存失败，请重试');
              setValue(next); setCompiled(result);
            }}}}/>} />
        </main>;
      }
      createRoot(document.getElementById('root')).render(<Fixture/>);
    ` },
  });
  const script = bundle.outputFiles.find(file => file.path.endsWith(".js")).text;
  const css = bundle.outputFiles.find(file => file.path.endsWith(".css")).text;
  const server = createServer((req, res) => {
    if (req.url === "/cover.png") { res.setHeader("Content-Type", "image/png"); res.end(cover); return; }
    if (req.url === "/fixture.js") { res.setHeader("Content-Type", "text/javascript"); res.end(script); return; }
    if (req.url !== "/") { res.writeHead(404); res.end(); return; }
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.end(`<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}</style></head><body><div id="root"></div><script type="module" src="/fixture.js"></script></body></html>`);
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  let browser;
  const errors = [];
  try {
    browser = await localBrowser();
    const { evaluate, ready, send } = browser;
    const base = `http://127.0.0.1:${server.address().port}`;
    browser.on("Runtime.exceptionThrown", event => errors.push(event.exceptionDetails.text));
    const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
    const key = async (name, code) => {
      await send("Input.dispatchKeyEvent", { type: "keyDown", key: name, code: name, windowsVirtualKeyCode: code, ...(name === "Enter" ? { text: "\r", unmodifiedText: "\r" } : {}) });
      await send("Input.dispatchKeyEvent", { type: "keyUp", key: name, code: name, windowsVirtualKeyCode: code });
    };
    const openPicker = async () => {
      await click('.visual-style-control [aria-haspopup="dialog"]');
      await ready("document.querySelector('.style-picker-dialog[open] .style-card-choice')");
    };
    const choose = name => click(`.style-card-choice[aria-label="选择${name}"]`);
    const apply = async () => {
      await click(".style-picker-actions .primary-button");
      await ready("!document.querySelector('.style-picker-dialog')");
    };
    await browser.viewport(1440, 960);
    await browser.navigate(base + "/");
    await ready("document.querySelector('.visual-style-control')");

    await t.test("selecting one style hides the original entry and keeps the actual name on the image", async () => {
      assert.equal(await evaluate("document.querySelectorAll('.visual-style-control [aria-haspopup=dialog]').length"), 1);
      assert.equal(await evaluate("document.querySelector('.visual-style-control [aria-haspopup=dialog]').textContent"), "风格");
      await openPicker();
      for (const name of ["旅行 Vlog", "电影质感", "旅行 Vlog"]) {
        await choose(name);
        await ready(`document.querySelector('.style-card-choice[aria-pressed=true]').getAttribute('aria-label') === ${JSON.stringify(`选择${name}`)}`);
        assert.equal(await evaluate("document.querySelectorAll('.style-card-choice[aria-pressed=true]').length"), 1);
      }
      assert.deepEqual(await evaluate("window.saves"), []);
      await apply();
      await ready("document.activeElement === document.querySelector('.style-selected-choice')");
      assert.equal(await evaluate("document.querySelectorAll('.style-selected').length"), 1);
      assert.equal(await evaluate("document.querySelector('.prompt-style-tools > .ui-button[aria-haspopup=dialog]')"), null);
      assert.equal(await evaluate("document.querySelector('.style-selected-name').textContent"), "旅行 Vlog");
      assert.equal(await evaluate("document.querySelector('.style-selected-kind')"), null);
      assert.equal(await evaluate("document.querySelector('.style-selected-choice .style-selected-remove')"), null);
      assert.deepEqual(await evaluate("window.saves"), [{ catalog_id: "travel", catalog_version: 1 }]);
    });

    await t.test("desktop and mobile share aligned square thumbnails with style first, wrapping and a small close icon", async () => {
      await ready("document.querySelector('.style-selected img').complete && document.querySelector('.style-selected img').naturalWidth");
      for (const width of [1440, 390]) {
        await browser.viewport(width, 640);
        await evaluate("document.activeElement?.blur()");
        await send("Input.dispatchMouseEvent", {type:"mouseMoved",x:0,y:0});
        const layout = await evaluate(`(() => {
          const choice=document.querySelector('.style-selected-choice'), cover=choice.querySelector('.style-cover').getBoundingClientRect();
          const name=choice.querySelector('.style-selected-name').getBoundingClientRect(), button=document.querySelector('.style-selected-remove').getBoundingClientRect();
          const mark=document.querySelector('.style-selected-remove-mark'), assets=[...document.querySelectorAll('.asset-reference-thumbnail')];
          return {nameTop:name.top,coverBottom:cover.bottom,removeTop:button.top,removeRight:button.right,removeBottom:button.bottom,
            coverTop:cover.top,coverRight:cover.right,removeWidth:button.width,removeHeight:button.height,overflow:document.documentElement.scrollWidth>innerWidth,
            closeSize:mark.getBoundingClientRect().width,closeRadius:getComputedStyle(mark).borderRadius,closeOpacity:getComputedStyle(mark.parentElement).opacity,
            first:document.querySelector('.asset-reference-rail').firstElementChild.className,
            dimensions:[choice,...assets].map(el=>{const r=el.getBoundingClientRect();return [r.width,r.height,r.top];}),
            numbers:assets.map(el=>el.querySelector('span').textContent)};
        })()`);
        assert.ok(layout.nameTop > layout.coverTop && layout.nameTop < layout.coverBottom, "name overlays the cover instead of using a white strip");
        assert.ok(Math.abs(layout.removeRight - layout.coverRight) <= 10);
        assert.ok(Math.abs(layout.removeTop - layout.coverTop) <= 10);
        assert.ok(layout.removeBottom < layout.nameTop, "remove action does not obscure the style name");
        assert.ok(layout.removeWidth >= 44 && layout.removeHeight >= 44);
        assert.equal(layout.closeSize, 24); assert.equal(layout.closeRadius, "50%");
        assert.equal(layout.closeOpacity, width === 390 ? "1" : "0");
        assert.equal(layout.first, "style-selected");
        assert.deepEqual(layout.numbers, ["1","2","3","4"]);
        assert.ok(layout.dimensions.every(([w,h])=>w===64 && h===64));
        assert.equal(layout.dimensions[0][2], layout.dimensions[1][2]);
        if (width === 390) assert.ok(layout.dimensions.at(-1)[2] > layout.dimensions[0][2], "small screens wrap assets below without scrolling sideways");
        assert.equal(layout.overflow, false);
        await browser.screenshot(fileURLToPath(new URL(`../../../.impeccable/review/style-reference-rail/selected-${width}.png`, import.meta.url)));
      }
    });

    await t.test("pointer and keyboard replacement overlays are reachable; style changes never remount the editor or number a cover", async () => {
      await browser.viewport(1440,640);
      const point=await evaluate("(()=>{const r=document.querySelector('.style-selected-choice').getBoundingClientRect();return{x:r.x+16,y:r.y+32}})()");
      await send("Input.dispatchMouseEvent",{type:"mouseMoved",...point});
      assert.equal(await evaluate("getComputedStyle(document.querySelector('.style-selected-replace')).opacity"),"1");
      assert.equal(await evaluate("getComputedStyle(document.querySelector('.style-selected-remove')).opacity"),"1");
      await browser.screenshot(fileURLToPath(new URL("../../../.impeccable/review/style-reference-rail/hover-1440.png", import.meta.url)));
      await evaluate("window.editorNode=document.querySelector('.asset-reference-input');window.promptBefore=window.currentPrompt;window.refsBefore=JSON.stringify(window.currentReferences);window.setPart('video')");
      await ready("document.querySelector('.asset-reference-input').getAttribute('aria-label')==='视频提示词'");
      assert.equal(await evaluate("document.querySelector('.asset-reference-input')===window.editorNode"),true);
      assert.equal(await evaluate("document.querySelector('.asset-reference-rail').firstElementChild.className"),"style-selected");
      await evaluate("window.setPart('image')");
      await ready("document.querySelector('.asset-reference-input').getAttribute('aria-label')==='图片提示词'");
    });

    await t.test("keyboard reopen, cancel and replacement keep a single selection and restore focus", async () => {
      await evaluate("document.querySelector('.style-selected-choice').focus()");
      assert.equal(await evaluate("document.activeElement === document.querySelector('.style-selected-choice')"), true);
      await key("Enter", 13);
      await ready("document.querySelector('.style-picker-dialog[open] .style-card-choice')");
      await choose("电影质感");
      await key("Escape", 27);
      await ready("!document.querySelector('.style-picker-dialog') && document.activeElement === document.querySelector('.style-selected-choice')");
      assert.equal(await evaluate("document.querySelector('.style-selected-name').textContent"), "旅行 Vlog");
      assert.equal(await evaluate("window.saves.length"), 1);
      await openPicker(); await choose("电影质感"); await apply();
      assert.equal(await evaluate("document.querySelectorAll('.style-selected').length"), 1);
      assert.equal(await evaluate("document.querySelector('.style-selected-name').textContent"), "电影质感");
    });

    await t.test("remove failures keep the thumbnail, saving locks both actions, and success restores the entry", async () => {
      await browser.viewport(390,640);
      await evaluate("window.failSave=true");
      // Real pointer coordinates hit the sibling close button, not the thumbnail underneath.
      const point = await evaluate("(()=>{const r=document.querySelector('.style-selected-remove').getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2};})()");
      await send("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, ...point });
      await send("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, ...point });
      await ready("document.querySelector('.visual-style-error')");
      assert.match(await evaluate("document.querySelector('.visual-style-error').textContent"), /保存失败/);
      assert.equal(await evaluate("document.querySelector('.style-selected-name').textContent"), "电影质感");
      assert.equal(await evaluate("document.querySelector('.style-picker-dialog')"), null);
      await evaluate("window.failSave=false;window.holdSave=true");
      await click(".style-selected-remove");
      await ready("document.querySelector('.style-selected-remove').disabled");
      assert.equal(await evaluate("document.querySelector('.style-selected-choice').disabled"), true);
      await click(".style-selected-remove");
      assert.equal(await evaluate("window.saves.length"), 4);
      await evaluate("window.holdSave=false;window.releaseSave()");
      await ready("!document.querySelector('.style-selected') && document.activeElement === document.querySelector('.visual-style-control [aria-haspopup=dialog]')");
      assert.equal(await evaluate("document.querySelector('.visual-style-control [aria-haspopup=dialog]').textContent"), "风格");
      assert.deepEqual(await evaluate("window.saves.at(-1)"), { preset: "original" });
      assert.equal(await evaluate("document.querySelector('.visual-style-error')"), null);
      assert.equal(await evaluate("document.querySelector('.asset-reference-input')===window.editorNode"),true);
      assert.equal(await evaluate("window.currentPrompt===window.promptBefore && JSON.stringify(window.currentReferences)===window.refsBefore"),true);
      assert.deepEqual(await evaluate("[...document.querySelectorAll('.asset-reference-thumbnail > span')].map(el=>el.textContent)"),["1","2","3","4"]);
    });

    await t.test("inherited, disabled, long-name and missing-cover states preserve their meaning", async () => {
      await evaluate("window.resetStyle('inherit')");
      await ready("document.querySelector('.style-selected small')");
      assert.equal(await evaluate("document.querySelector('.style-selected-name').textContent"), "旅行 Vlog");
      assert.equal(await evaluate("document.querySelector('.style-selected small').textContent"), "继承整片");
      await click(".style-selected-remove");
      await ready("!document.querySelector('.style-selected')");
      assert.deepEqual(await evaluate("window.saves.at(-1)"), { preset: "original" });
      await evaluate("window.resetStyle('travel',true)");
      await ready("document.querySelector('.style-selected-choice')?.disabled");
      assert.equal(await evaluate("document.querySelector('.style-selected-remove').disabled"), true);
      const saves = await evaluate("window.saves.length");
      await click(".style-selected-choice"); await click(".style-selected-remove");
      assert.equal(await evaluate("window.saves.length"), saves);
      assert.equal(await evaluate("document.querySelector('.style-picker-dialog')"), null);
      await evaluate("window.resetStyle('long')");
      await ready("document.querySelector('.style-selected-choice .style-cover-missing')");
      const fullName = "这是一个名称很长的旅行纪实画面风格";
      assert.equal(await evaluate("document.querySelector('.style-selected-choice').title"), fullName);
      assert.match(await evaluate("document.querySelector('.style-selected-choice').getAttribute('aria-label')"), new RegExp(fullName));
      assert.equal(await evaluate("getComputedStyle(document.querySelector('.style-selected-name')).textOverflow"), "ellipsis");
      assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
      await evaluate("document.querySelector('.style-selected-choice').focus()"); await key("Tab", 9);
      assert.equal(await evaluate("document.activeElement === document.querySelector('.style-selected-remove')"), true);
      assert.equal(await evaluate("getComputedStyle(document.activeElement).outlineStyle"), "solid");
      assert.ok((await evaluate("window.calls")).every(call => call.path.startsWith("/me/settings/visual-styles")));
      assert.deepEqual(errors, []);
    });
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
});
