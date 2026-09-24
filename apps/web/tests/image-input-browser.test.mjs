import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import test from "node:test";
import { localBrowser } from "./helpers/local-browser.mjs";

// Real workspace, isolated data and a fake submission; no live API or model calls.
test("reference creation and explicit generated-image editing work without source footage", { timeout: 90000 }, async () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const bundle = await build({ absWorkingDir: root, bundle: true, write: false, outfile: "fixture.js", format: "esm", platform: "browser", jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' }, stdin: { resolveDir: root, loader: "jsx", contents: `
    import React,{useState} from 'react'; import {createRoot} from 'react-dom/client';
    import {ShotImageWorkspace} from './src/ShotImageWorkspace.jsx';
    import './src/styles.css'; import './src/production-workflow.css';
    const preview='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#dad4f5"/></svg>');
    const person={id:'person',type:'person',name:'人物参考',thumbnail_url:preview,content_url:preview};
    const wardrobe={id:'wardrobe',type:'wardrobe',name:'服装参考',thumbnail_url:preview,content_url:preview};
    const initialDraft={imagePrompt:'@人物参考 身穿 @服装参考，位于巴黎铁塔前，人物居中。',imagePromptMentions:[{reference_asset_id:'person',label:'人物参考'},{reference_asset_id:'wardrobe',label:'服装参考'}],referenceBindings:[{reference_asset_id:'person',role:'identity',weight:1},{reference_asset_id:'wardrobe',role:'wardrobe',weight:1}],locks:[],negativeConstraints:'',required:true};
    const noop=()=>{}; window.calls=[];
    const settings={enabled:true,supports_candidate_base_image:true,api_key_configured:true,allow_local_tool:false,execution_mode:'remote_api',remote_model_alias:'fixture',models:[{alias:'fixture',label:'验收模型',capabilities:{text_to_image:true,image_to_image:true,multi_reference:true,max_input_images:5,max_reference_images:4,max_candidates:4,maximum_width:2048,maximum_height:2048,maximum_pixels:4194304}}]};
    function Fixture(){
      const [draft,setDraft]=useState(initialDraft),[inputMode,setMode]=useState('keyframe_edit'),[base,setBase]=useState(''),[source,setSource]=useState(false),[available,setAvailable]=useState(true);
      window.changeRefs=count=>setDraft({...initialDraft,imagePrompt:count?initialDraft.imagePrompt:'巴黎街头的完整画面',referenceBindings:initialDraft.referenceBindings.slice(0,count),imagePromptMentions:initialDraft.imagePromptMentions.slice(0,count)});
      window.changeSource=setSource;window.changeAvailable=setAvailable;
      const beat={id:'beat',index:1,duration_seconds:1.5,image_prompt:draft.imagePrompt,image_prompt_mentions:draft.imagePromptMentions,image_status:'ready',source_frame_url:source?preview:null};
      const plan={id:'shot',index:1,source_kind:'blank',image_status:'ready',output_mode:'image_to_video',start_seconds:0,end_seconds:1.5,duration_seconds:1.5,visual_beats:[beat],lifecycle_status:'active',image_prompt:draft.imagePrompt};
      const runs=[{id:'run',kind:'image',visual_beat_id:'beat',execution_mode:'remote_api',status:'completed',model:'fixture',candidates:available?[{id:'candidate',ordinal:1,status:'ready',content_url:preview,thumbnail_url:preview}]:[]}];
      return <ShotImageWorkspace shots={[{plan}]} shotDetail={{plan,generation_runs:runs}} selectedShotId="shot" selectedVisualBeatId="beat" draft={draft} setDraft={setDraft} assets={[person,wardrobe]} generationCandidateCount={1} generationEngine="remote_api" generationInputMode={inputMode} generationBaseImageId={base} setGenerationBaseImageId={setBase} generationModelAlias="fixture" generationSettings={settings} project={{id:'project',origin_type:'analysis',output_aspect_ratio:'16:9',output_width:1280,output_height:720}} busy={false} error="" resolveUrl={v=>v} setGenerationCandidateCount={noop} setGenerationEngine={noop} setGenerationInputMode={setMode} setGenerationModelAlias={noop} onSelectShot={noop} onGenerate={()=>window.calls.push({mode:inputMode,base,refs:draft.referenceBindings.length})} onCancelRun={noop} onSelectCandidate={noop} onApprove={noop} onCreateVisualBeat={noop} onFlushDraft={async()=>{}} onAddAssets={noop} onNotice={noop} request={async()=>({current_global_prompts:{},items:[]})}/>;
    }
    createRoot(document.getElementById('root')).render(<Fixture/>);
  ` } });
  const script = bundle.outputFiles.find(file => file.path.endsWith(".js")).text;
  const css = bundle.outputFiles.find(file => file.path.endsWith(".css"))?.text || "";
  const server = createServer((req, res) => {
    res.setHeader("Content-Type", req.url === "/fixture.js" ? "text/javascript" : "text/html; charset=utf-8");
    res.end(req.url === "/fixture.js" ? script : `<!doctype html><meta charset="UTF-8"><style>${css}</style><div id="root"></div><script type="module" src="/fixture.js"></script>`);
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  let browser;
  const errors = [];
  try {
    browser = await localBrowser();
    browser.on("Runtime.exceptionThrown", event => errors.push(event.exceptionDetails.text));
    await browser.navigate(`http://127.0.0.1:${server.address().port}`);
    await browser.ready("document.querySelector('.shot-image-settings-trigger')");
    for (const width of [1440, 390]) {
      await browser.viewport(width, 960);
      await browser.evaluate("document.querySelector('.shot-image-generation-command').scrollIntoView({block:'center',behavior:'instant'})");
      assert.match(await browser.evaluate("document.querySelector('.shot-image-settings-trigger').textContent"), /参考图创作/);
      assert.equal(await browser.evaluate("document.querySelector('.shot-image-generate-button').disabled"), false);
      assert.equal(await browser.evaluate("document.querySelector('.shot-image-command-error')"), null);
      assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true);
      await browser.screenshot(fileURLToPath(new URL(`../../../.impeccable/review/image-input/reference-${width}.png`, import.meta.url)));
    }
    await browser.evaluate("document.querySelector('.shot-image-settings-trigger').click()");
    await browser.ready("document.querySelector('.image-settings-popover')");
    await browser.evaluate("[...document.querySelectorAll('.image-setting-segments button')].find(b=>b.textContent==='底图编辑').click()");
    await browser.ready("document.querySelector('select[aria-label=编辑底图]')");
    assert.equal(await browser.evaluate("document.querySelector('.shot-image-generate-button').disabled"), true);
    await browser.evaluate("var base=document.querySelector('select[aria-label=编辑底图]');base.value='candidate';base.dispatchEvent(new Event('change',{bubbles:true}));");
    await browser.ready("!document.querySelector('.shot-image-generate-button').disabled");
    assert.match(await browser.evaluate("document.querySelector('.shot-image-settings-trigger').textContent"), /底图编辑/);
    assert.equal(await browser.evaluate("window.calls.length"), 0, "mode and base selection never generate");
    for (const width of [1440, 390]) {
      await browser.viewport(width, 960);
      assert.equal(await browser.evaluate("document.documentElement.scrollWidth<=innerWidth"), true);
      assert.ok(await browser.evaluate("document.querySelector('select[aria-label=编辑底图]').getBoundingClientRect().height >= 44"));
      await browser.screenshot(fileURLToPath(new URL(`../../../.impeccable/review/image-input/base-edit-${width}.png`, import.meta.url)));
    }
    await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
    await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
    await browser.evaluate("document.querySelector('.shot-image-generate-button').click()");
    assert.deepEqual(await browser.evaluate("window.calls"), [{ mode: "keyframe_edit", base: "candidate", refs: 2 }]);
    await browser.evaluate("window.changeAvailable(false)");
    await browser.ready("document.querySelector('.shot-image-generate-button').disabled");
    assert.match(await browser.evaluate("document.querySelector('.shot-image-command-error').textContent"), /底图/);
    await browser.evaluate("document.querySelector('.shot-image-settings-trigger').click()");
    await browser.ready("document.querySelector('.image-settings-popover')");
    await browser.evaluate("[...document.querySelectorAll('.image-setting-segments button')].find(b=>b.textContent==='参考图创作').click()");
    await browser.ready("!document.querySelector('.shot-image-generate-button').disabled");
    await browser.evaluate("window.changeRefs(0)");
    await browser.ready("document.querySelector('.shot-image-settings-trigger').textContent.includes('纯文生图')");
    await browser.evaluate("window.changeRefs(1);window.changeSource(true)");
    await browser.ready("document.querySelector('.shot-image-settings-trigger').textContent.includes('参考图创作')");
    assert.equal(await browser.evaluate("document.querySelector('.shot-image-generate-button').disabled"), false);
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
});
