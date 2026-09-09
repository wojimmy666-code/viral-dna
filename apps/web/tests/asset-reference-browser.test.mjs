import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

// Real Chromium DOM/layout tests. Only a local, in-memory React fixture is served:
// no app API, account session, generated media, or persisted project is accessed.
const webRoot = fileURLToPath(new URL('..', import.meta.url));
const browserPath = [
  process.env.CHROME_BIN,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].find(path => path && existsSync(path));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

function connect(url) {
  return new Promise((resolveConnection, rejectConnection) => {
    const socket = new WebSocket(url);
    let sequence = 0;
    const pending = new Map();
    socket.addEventListener('error', rejectConnection, { once: true });
    socket.addEventListener('message', event => {
      const result = JSON.parse(event.data), task = pending.get(result.id);
      if (!task) return;
      pending.delete(result.id); clearTimeout(task.timeout);
      result.error ? task.reject(new Error(JSON.stringify(result.error))) : task.resolve(result.result);
    });
    socket.addEventListener('close', () => {
      for (const task of pending.values()) { clearTimeout(task.timeout); task.reject(new Error('Browser closed')); }
      pending.clear();
    });
    socket.addEventListener('open', () => resolveConnection({
      close: () => socket.close(),
      send(method, params = {}) {
        const id = ++sequence;
        return new Promise((resolve, reject) => {
          const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 10000);
          pending.set(id, { resolve, reject, timeout });
          socket.send(JSON.stringify({ id, method, params }));
        });
      },
    }), { once: true });
  });
}

test('reference preview browser regression', { timeout: 90000 }, async t => {
  assert.ok(browserPath, 'Install Chrome/Chromium or set CHROME_BIN to run this explicit browser suite');
  assert.equal(typeof WebSocket, 'function', 'Use npm run test:prompt-browser (Node 20 needs --experimental-websocket)');
  const bundle = await build({
    absWorkingDir: webRoot, bundle: true, write: false, outfile: 'harness.js',
    format: 'esm', platform: 'browser', jsx: 'automatic',
    define: { 'process.env.NODE_ENV': '"production"' },
    stdin: { resolveDir: webRoot, loader: 'jsx', contents: `
      import React, { useEffect, useState } from 'react';
      import { createRoot } from 'react-dom/client';
      import { AssetReferenceEditor } from './src/prompt-references/AssetReferenceEditor.jsx';
      import { VideoPromptReferenceEditor } from './src/video-inputs/VideoPromptReferenceEditor.jsx';
      import { approvedVisualBeatFramesFromDetail, reconcileVideoDraftReferences } from './src/video-inputs/video-prompt-references.js';
      import { ShotVideoList, ShotVideoWorkspace } from './src/ShotVideoWorkspace.jsx';
      import { videoStageShots } from './src/creation-workspace/video-stage-selection.js';
      import { EMPTY_VIDEO_DRAFT, useShotVideoGenerationDraft } from './src/video-generation-controls/useShotVideoGenerationDraft.js';
      import './src/production-workflow.css';
      import { ImageBatchToolbar } from './src/image-generation-controls/ImageBatchToolbar.jsx';
      import { ImageGenerationCommandBar } from './src/image-generation-controls/ImageGenerationCommandBar.jsx';
      import { useGenerationPreferences } from './src/image-generation-controls/generation-preferences.js';
      import { GlobalPromptEditor, PromptPreview } from './src/prompt-context/GlobalPromptEditor.jsx';
      import { PromptSectionHeader } from './src/prompt-context/PromptSectionHeader.jsx';
      import { SkillShotNavigation } from './src/image-generation-controls/SkillShotNavigation.jsx';
      import { AddToAssetsButton } from './src/generated-assets/AddToAssetsButton.jsx';
      const settings = { api_key_configured:true, local_executable_path:'fixture', remote_model_alias:'local_tool', image_width:720, image_height:1280, models:[{
        alias:'qwen',label:'Qwen Image 2.0 Pro 非常长的模型名称',provider:'dashscope',unit_cost_micros:500000,
        capabilities:{text_to_image:true,image_to_image:true,max_input_images:5,max_candidates:4,maximum_width:4096,maximum_height:4096,maximum_pixels:16777216}
      }] };
      window.batchCalls=[]; window.lastBatch=null; window.flushes=0;
      const request = async(path,options={}) => {
        if(path==='/context') return {id:'globals',common_image_prompt:'全局约束',common_video_prompt:'全局视频约束'};
        if(options.method!=='POST') return path.endsWith('/latest') ? window.lastBatch : {project:{current_revision_id:'revision'}};
        const body=JSON.parse(options.body||'{}'); window.batchCalls.push({path,body});
        if(path.endsWith('/preview')) return {model_label:'fixture',width:body.width,height:body.height,estimated_cost_micros:null,items:[{visual_beat_id:'beat',shot_plan_id:'shot',shot_index:1,status:window.preflightFail?'failed':'pending',error_message:window.preflightFail?'参考数量超过模型限制':null}]};
        window.lastBatch={id:body.request_id,status:'completed',items:[{visual_beat_id:'beat',shot_plan_id:'shot',status:'completed',candidate_ids:['candidate']}],created_at:new Date().toISOString(),updated_at:new Date().toISOString()};
        if(window.loseReply){window.loseReply=false;throw new Error('网络暂时断开');} return window.lastBatch;
      };
      const image = (w,h) => 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="'+w+'" height="'+h+'"><rect width="100%" height="100%" fill="#f4d644"/></svg>');
      window.promotedImages = { a: { id:'asset-a', folder_id:null } };
      window.promotionCalls = []; window.statusCalls = []; window.statusReplies = {};
      window.promotionFolders = [{id:'folder-1',name:'品牌产品'}, {id:'folder-2',name:'工厂环境'}];
      const promotionRequest = async(path,options={}) => {
        const body=options.body?JSON.parse(options.body):null;
        if(path==='/context') return {account:{id:'test-account'},active_workspace:{id:window.promotionWorkspace||'test-workspace'}};
        if(path.endsWith('/asset-folders')) {
          if(window.failFolders) throw new Error('目录暂时不可用');
          if(options.method==='POST') {
            const folder={id:'new-folder-'+window.promotionFolders.length,name:body.name};
            window.promotionFolders.push(folder); return folder;
          }
          return [...window.promotionFolders];
        }
        if(path==='/assets/generated-artifact-status') {
          window.statusCalls.push(body.source_entity_id);
          if(window.failStatus===body.source_entity_id) throw new Error('状态暂时不可用');
          const result={promoted:!!window.promotedImages[body.source_entity_id]};
          if(window.holdStatus) return new Promise(resolve=>{window.statusReplies[body.source_entity_id]=()=>resolve(result);});
          return result;
        }
        if(path==='/assets/from-generated-artifact') {
          window.promotionCalls.push(body);
          if(window.failPromotion) throw new Error('入库失败，请重试');
          if(window.holdPromotion) await new Promise(resolve=>{window.releasePromotion=resolve;});
          const existing=window.promotedImages[body.source_entity_id];
          const asset=existing||{id:'asset-'+body.source_entity_id,...body};
          window.promotedImages[body.source_entity_id]=asset;
          if(window.losePromotionReply){window.losePromotionReply=false;throw new Error('响应中断，请重试核对');}
          return {asset,already_existed:!!existing};
        }
        throw new Error('Unexpected fixture request: '+path);
      };
      function PromotionFixture() {
        const [candidate,setCandidate] = useState('a');
        const [project,setProject] = useState('project-promotion');
        window.setPromotionCandidate=setCandidate; window.setPromotionProject=setProject;
        return <section id="promotion-fixture">
          <div>{['a','b','c'].map(id=><button key={id} id={'promotion-'+id} type="button" onClick={()=>setCandidate(id)}>图片 {id}</button>)}</div>
          <AddToAssetsButton artifactKind="image_candidate" sourceEntityId={candidate} shotPlanId="shot"
            projectId={project} request={promotionRequest} name={'分镜图片 '+candidate} assetType="other"
            previewUrl={image(720,1280)} onNotice={message=>{window.promotionNotice=message;}} />
        </section>;
      }
      const options = [
        { reference_asset_id:'square', label:'产品/方形图', thumbnail_url:image(1024,1024) },
        { reference_asset_id:'portrait', label:'产品/竖图', thumbnail_url:image(720,2560) },
        { reference_asset_id:'wide', label:'产品/横图', thumbnail_url:image(3840,720) },
        { reference_asset_id:'missing', label:'产品/失效图片', thumbnail_url:'data:image/png;base64,broken' },
      ];
      const params = new URLSearchParams(location.search);
      const imageCountPrefix = 'fixture:image-count:' + (params.get('origin') || 'skill') + ':';
      if (params.has('seed-image-count')) for (const [id,count] of [['a',2],['b',4]]) {
        localStorage.setItem(imageCountPrefix+id,JSON.stringify({count,model:'qwen',resolution:'1280x720',inputMode:'text_to_image'}));
      }
      function ImageCountFixture() {
        const [shot,setShot]=useState('a'); window.selectImageCountShot=setShot;
        const [choice,setChoice]=useGenerationPreferences(imageCountPrefix+shot,
          {count:1,model:'qwen',resolution:'1280x720',inputMode:'text_to_image'}, {defaultVersions:{count:1}});
        window.imageCountChoice=choice;
        return <><ImageGenerationCommandBar aspectRatio="16:9" settings={{...settings,execution_mode:'remote_api'}}
          candidateCount={choice.count} modelAlias={choice.model} resolution={choice.resolution} inputMode={choice.inputMode}
          inputCount={0} generationAvailable onGenerate={()=>{window.submittedImageCount=choice.count;}}
          onCandidateCountChange={count=>setChoice({count})} onResolutionChange={resolution=>setChoice({resolution})}
          onInputModeChange={inputMode=>setChoice({inputMode})} onModelChange={model=>setChoice({model})} />
          <AssetReferenceEditor value="@产品/方形图" references={[options[0]]} options={options} onChange={()=>{}} /></>;
      }
      if(params.has('partial')) window.lastBatch={id:'partial-fixture',status:'partial',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),items:Array.from({length:15},(_,index)=>({visual_beat_id:'beat-'+index,shot_plan_id:'shot-'+index,shot_index:index+1,status:index<13?'completed':'failed',error_message:index<13?null:'生成失败，请重试'}))};
      const reference = options.find(item => item.reference_asset_id === params.get('asset')) || options[0];
      if(params.has('long')) reference.label = '产品/' + '超长中文素材名称'.repeat(20);
      window.promptChanges = []; window.saveRetries = 0;
      const videoAssets = Array.from({length:18},(_,i)=>({id:'asset-'+i,name:i===0?'产品正面':'产品参考'+i,type:'product',thumbnail_url:image(720,1280)}));
      const videoReference={reference_kind:'project_asset',reference_id:'asset-0',label:'资产/产品正面',role:'product',order:1};
      const hydrationSettings = {default_model_alias:'fixture',models:[]};
      const hydrationRecord = id => ({schema_version:'viral-dna-shot-video-draft/v2',shot_plan_id:id,draft_version:1,
        model_alias:'fixture',video_prompt:'保持手写运镜。',video_prompt_mentions:[],input_plan:{sources:[],references:[]}});
      window.hydrationRecords = {first:hydrationRecord('first'),second:hydrationRecord('second')};
      window.hydrationSaves = [];
      const hydrationRequest = async(path,options={}) => {
        const id=path.split('/')[2];
        if(!options.body) return window.hydrationRecords[id];
        const body=JSON.parse(options.body);window.hydrationSaves.push({id,...body});
        if(window.holdHydrationSave) {
          window.holdHydrationSave=false;
          await new Promise(resolve=>{window.releaseHydrationSave=resolve;});
        }
        return window.hydrationRecords[id]={...window.hydrationRecords[id],...body,draft_version:body.expected_draft_version+1};
      };
      function VideoHydrationFixture() {
        const [shot,setShot]=useState('first'),[refresh,setRefresh]=useState(0);
        const [details,setDetails]=useState(()=>Object.fromEntries(['first','second'].map(id=>[id,{
          plan:{id,video_prompt:'保持手写运镜。',duration_seconds:3,visual_beats:(id==='first'?[1,2,3]:[1]).map(index=>({
            id:id+'-'+index,index,required:index===1,title:'画面'+index,start_ratio:0,end_ratio:1,
            approved_image_candidate_id:index===3?null:id+'-image-'+index,
          }))},generation_runs:(id==='first'?[1,2,3]:[1]).map(index=>({kind:'image',
            ...(id==='first'?{visual_beat_id:id+'-'+index}:{}),
            candidates:[{id:id+'-image-'+index,thumbnail_url:image(720,1280)},{id:id+'-new-'+index,thumbnail_url:image(1280,720)}],
          })),
        }])));
        const {videoDraft,setVideoDraft,hydrateVideoDraft,flushVideoDraft}=useShotVideoGenerationDraft({request:hydrationRequest});
        const detail=details[shot],frames=approvedVisualBeatFramesFromDetail(detail);
        useEffect(()=>{hydrateVideoDraft({shotPlanId:shot,detail,settings:hydrationSettings,persistedDraft:window.hydrationRecords[shot]});},[shot,detail,refresh,hydrateVideoDraft]);
        window.hydratedDraft=videoDraft;
        window.refreshHydration=()=>setRefresh(value=>value+1);
        window.switchHydration=async(id)=>{await flushVideoDraft();setShot(id);};
        window.changeHydrationImage=()=>setDetails(current=>({...current,first:{...current.first,
          plan:{...current.first.plan,visual_beats:current.first.plan.visual_beats.map(beat=>beat.index===2?{...beat,approved_image_candidate_id:'first-new-2'}:beat)},
        }}));
        return <VideoPromptReferenceEditor assets={[]} referenceFrames={frames} value={videoDraft.videoPrompt}
          videoPromptMentions={videoDraft.videoPromptMentions} selectedReferences={videoDraft.selectedReferences}
          onChange={change=>setVideoDraft(current=>reconcileVideoDraftReferences(current,change,frames))} onBlur={()=>void flushVideoDraft()} resolveUrl={url=>url} />;
      }
      function VideoPromptFixture() {
        const [draft,setDraft]=useState({videoPrompt:'参考 @资产/产品正面。\\n'+'保持画面要求与产品材质。\\n'.repeat(45),videoPromptMentions:[videoReference],selectedReferences:[videoReference],inputSources:['project_assets']});
        window.videoDraft=draft;
        window.echoVideoDraft=()=>setDraft(current=>({...current}));
        return <div className="production-field"><div style={{height:180}}>长提示词测试</div>
          <VideoPromptReferenceEditor assets={videoAssets} value={draft.videoPrompt} selectedReferences={draft.selectedReferences}
            videoPromptMentions={draft.videoPromptMentions} onBlur={()=>{window.videoBlurred=true;}}
            onChange={change=>setDraft(current=>reconcileVideoDraftReferences(current,change,[]))} />
          <div style={{height:700}}>页面可滚动</div></div>;
      }
      function VideoListFixture() {
        const [shots,setShots]=useState(Array.from({length:params.has('scope')?15:3},(_,i)=>i+1).map(index=>({plan:{id:'s'+index,index,start_seconds:index-1,end_seconds:index,duration_seconds:1,video_prompt:'不得作为标题的很长提示词',video_status:index===3?'draft':'approved',include_in_editing:true}})));
        const [project,setProject]=useState(params.has('scope')?{video_stage_shot_ids:['s2','s4','s8','s10','s15']}:{});
        window.setVideoScope=ids=>setProject({video_stage_shot_ids:ids}); window.allVideoShotCount=shots.length;
        const [busy,setBusy]=useState(false); window.setVideoBusy=setBusy;
        const eligible=['s1','s2'],selected=shots.filter(item=>eligible.includes(item.plan.id)&&item.plan.include_in_editing).map(item=>item.plan.id);
        return <section style={{width:'min(300px,100%)'}}><ShotVideoList shots={videoStageShots(shots,project)} busy={busy} selectedShotId="s1"
          gate={{eligible_video_shot_ids:eligible,selected_video_shot_ids:selected}} onSelectShot={id=>{window.selectedShot=id;}}
          onReorderShots={ids=>{window.videoOrder=ids;setShots(current=>{let position=0;return current.map((item,index)=>{const id=ids.includes(item.plan.id)?ids[position++]:item.plan.id;const next=current.find(shot=>shot.plan.id===id);return {...next,plan:{...next.plan,index:index+1}};});});}}
          onEditingSelectionChange={(id,included)=>{window.videoSelected={id,included};setShots(current=>current.map(item=>item.plan.id===id?{...item,plan:{...item.plan,include_in_editing:included}}:item));}} />
          <AssetReferenceEditor value="@产品/方形图" references={[options[0]]} options={options} onChange={()=>{}} /></section>;
      }
      const videoWorkspaceRequest=async()=>({id:'context',common_image_prompt:'',common_video_prompt:''});
      function VideoWorkspaceFixture() {
        const [draft,setDraft]=useState({...EMPTY_VIDEO_DRAFT,videoPrompt:'参考 @资产/产品正面。保持局部视频要求。',videoPromptMentions:[videoReference],selectedReferences:[videoReference],inputSources:['project_assets'],intent:{status:'stale'},durationSeconds:'5'});
        const plan={id:'s1',index:1,start_seconds:0,end_seconds:1,duration_seconds:1,video_status:'draft',visual_beats:[]};
        const project={id:'video-fixture',origin_type:params.has('analysis')?'analysis':'skill_run',output_aspect_ratio:'16:9',output_width:1280,output_height:720};
        return <ShotVideoWorkspace project={project} shotDetail={{plan,generation_runs:[]}} shots={[{plan}]} selectedShotId="s1"
          request={videoWorkspaceRequest} assets={videoAssets} resolveUrl={url=>url} videoDraft={draft} setVideoDraft={setDraft}
          videoGenerationSettings={{models:[],enabled:false}} gate={{current_step:'shot_videos',allowed:false,eligible_video_shot_ids:[],selected_video_shot_ids:[],selected_video_count:0}}
          onSelectShot={()=>{}} onNotice={()=>{}} onAddAssets={()=>{}} />;
      }
      function Fixture() {
        const [draft,setDraft] = useState({value:'普通提示词文字 @'+reference.label+'，继续编辑。\\n末行文字。', references:[reference]});
        const [saveState,setSaveState] = useState('saved');
        const [retryState,setRetryState] = useState(null);
        window.setSaveState = setSaveState;
        window.setRetryState = setRetryState;
        const retryPlan={id:'shot-2',image_status:retryState==='approved'?'approved':'ready'};
        const retryDetail=params.has('recovered')?{plan:retryPlan,generation_runs:retryState&&retryState!=='approved'?[{id:'retry',kind:'image',execution_mode:'local_tool',visual_beat_id:'beat-2',created_at:'2026-09-07T07:00:00Z',status:retryState}]:[]}:undefined;
        const oldFailure={shot_plan_id:'shot-2',visual_beat_id:'beat-2',status:'failed',batch_completed_at:'2026-09-06T13:00:00Z'};
        return <div className="production-field">
          {params.has('promotion') && <PromotionFixture />}
          {params.has('navigation') && <SkillShotNavigation selectedId="shot-2" discarded={[]} items={params.has('recovered')?[oldFailure]:[]} shotDetail={retryDetail} handlers={{current:{}}} resolveUrl={url=>url} shots={[
            {plan:{id:'shot-1',index:1,image_status:'approved'},image_preview:{kind:'approved_image',thumbnail_url:image(1024,1024)}},
            {plan:{id:'shot-2',index:2,image_status:'review_required'},visual_beat_count:1,image_preview:{kind:'candidate_image',candidate_id:'new-image',updated_at:'2026-09-07T06:18:00Z',thumbnail_url:image(1024,1024)}},
            {plan:{id:'shot-3',index:3,image_status:'ready'}}
          ]} />}
          {params.has('workspace') && <><ImageBatchToolbar projectId="fixture" settings={settings} aspectRatio="9:16" pictureCount={15} request={request} onFlush={async()=>{window.flushes++;}} onState={items=>{window.navigationBatchItems=items;}} />
            <ImageGenerationCommandBar settings={settings} modelAlias="local_tool" aspectRatio="9:16" inputMode="text_to_image" inputCount={0} candidateCount={1} resolution="720x1280" generationAvailable onModelChange={()=>{}} onCandidateCountChange={()=>{}} />
          </>}
          <PromptSectionHeader titleId="prompt-label" title="局部图片提示词" state={saveState} onRetry={()=>{window.saveRetries++;setSaveState('saving');}} />
          <AssetReferenceEditor label="局部图片提示词" labelledBy="prompt-label" rows={16}
            disabled={params.has('disabled')} options={options} value={draft.value} references={draft.references}
            onChange={(value,references) => { window.promptChanges.push({value,references});setDraft({value,references}); }} />
          {params.has('workspace') && <><PromptPreview common="全局约束" local={draft.value} /><GlobalPromptEditor path="/context" part="image" request={request} /></>}
        </div>;
      }
      createRoot(document.getElementById('root')).render(params.has('image-count') ? <ImageCountFixture /> : params.has('video-hydration') ? <VideoHydrationFixture /> : params.has('video-workspace') ? <VideoWorkspaceFixture /> : params.has('video-prompt') ? <VideoPromptFixture /> : params.has('video-list') ? <VideoListFixture /> : <Fixture />);
    ` },
  });
  const js = bundle.outputFiles.find(file => file.path.endsWith('.js')).contents;
  const css = bundle.outputFiles.find(file => file.path.endsWith('.css')).contents;
  const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <style>*{box-sizing:border-box} :root{--space-1:4px;--space-2:8px;--space-3:12px;--space-4:16px;--type-body-size:14px;--type-caption-size:12px;--type-heading-size:16px;--type-leading-editor:1.55;--type-weight-regular:400;--type-weight-semibold:600;--border-default:#ddd;--surface-panel:#fff;--surface-subtle:#f2f2f7;--text-primary:#222;--text-secondary:#555;--accent:#6150ff;--radius-control:8px;--radius-overlay:12px;--z-tooltip:60;--control-height:40px} body{font-family:Arial,sans-serif;margin:16px} .production-field{max-width:560px;display:grid;gap:8px} .secondary-button{padding:8px 12px;background:#fff;border:1px solid #ddd;border-radius:8px;font:inherit}</style>
    <style>:root{--space-6:24px;--space-8:32px;--font-family-ui:Arial,sans-serif;--status-danger-text:#c0263d}.primary-button{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;background:#6150ff;color:white;border:1px solid #6150ff;border-radius:8px;font:inherit}.text-button{display:inline-flex;align-items:center;gap:8px;background:transparent;border:0;color:#6150ff;font:inherit;cursor:pointer}.generated-asset-dialog button:disabled{opacity:.6}</style>
    <link rel="stylesheet" href="/harness.css"><button id="before">编辑器之前</button><div id="root"></div><button id="after">编辑器之后</button><script type="module" src="/harness.js"></script></html>`;
  const server = createServer((request, response) => {
    const path = new URL(request.url, 'http://fixture').pathname;
    response.setHeader('Content-Type', path.endsWith('.js') ? 'text/javascript' : path.endsWith('.css') ? 'text/css' : 'text/html; charset=utf-8');
    response.end(path === '/harness.js' ? js : path === '/harness.css' ? css : html);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const profile = await mkdtemp(join(tmpdir(), 'viral-prompt-browser-'));
  const chrome = spawn(browserPath, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
  ], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
  const exited = new Promise(resolve => chrome.once('exit', resolve));
  let client;
  try {
    const debuggerUrl = await new Promise((resolve, reject) => {
      let output = '';
      const timeout = setTimeout(() => reject(new Error('Chrome startup timed out')), 10000);
      chrome.once('error', error => { clearTimeout(timeout); reject(error); });
      chrome.stderr.on('data', data => {
        output += data;
        const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
        if (match) { clearTimeout(timeout); resolve(match[1]); }
      });
    });
    const address = new URL(debuggerUrl);
    const target = await fetch(`http://${address.host}/json/new?about:blank`, {method:'PUT'}).then(response=>response.json());
    client = await connect(target.webSocketDebuggerUrl);
    const send = (method, params) => client.send(method, params);
    async function evaluate(expression) {
      const result = await send('Runtime.evaluate', {expression,returnByValue:true,awaitPromise:true});
      if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
      return result.result.value;
    }
    async function ready(expression) {
      for (let attempt=0;attempt<100;attempt++) { if(await evaluate(`Boolean(${expression})`)) return; await pause(25); }
      assert.fail(`Timed out: ${expression}`);
    }
    async function click(selector, corner = false) {
      const point = await evaluate(`(() => {const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:${corner?'r.right-8':'r.x+r.width/2'},y:${corner?'r.bottom-8':'r.y+r.height/2'}}})()`);
      for(const type of ['mouseMoved','mousePressed','mouseReleased']) await send('Input.dispatchMouseEvent',{type,...point,...(type==='mouseMoved'?{}:{button:'left',clickCount:1})});
    }
    async function key(key, code=key, modifiers=0) {
      const windowsVirtualKeyCode = { Escape:27, Enter:13, Tab:9, ArrowDown:40 }[key] || 0;
      await send('Input.dispatchKeyEvent',{type:'keyDown',key,code,modifiers,windowsVirtualKeyCode});
      await send('Input.dispatchKeyEvent',{type:'keyUp',key,code,modifiers,windowsVirtualKeyCode});
    }
    let navigation = 0;
    async function load(query='', width=1200, height=820) {
      await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
      const url = new URL(query || '/', base);
      url.searchParams.set('testcase', String(++navigation));
      await send('Page.navigate',{url:url.href});
      await ready(`location.href === ${JSON.stringify(url.href)} && document.querySelector('.asset-reference-token')`);
    }
    const visible = "Boolean(document.querySelector('.asset-reference-popover'))";
    await send('Page.enable'); await send('Runtime.enable');

    for (const origin of ['skill','analysis']) await t.test(origin+' image count defaults to one and manual multi-image choices remain per shot',async()=>{
      await load('?image-count=1&seed-image-count=1&origin='+origin);
      assert.match(await evaluate("document.querySelector('.shot-image-settings-trigger').textContent"),/1张/);
      await click('.shot-image-generate-button');
      assert.equal(await evaluate('window.submittedImageCount'),1);
      await click('.shot-image-settings-trigger');
      await ready("document.querySelector('.image-setting-segments.candidates button:nth-child(3)')");
      await click('.image-setting-segments.candidates button:nth-child(3)');
      await ready('window.imageCountChoice.count===3'); await key('Escape');
      await click('.shot-image-generate-button');
      assert.equal(await evaluate('window.submittedImageCount'),3);
      await evaluate("window.selectImageCountShot('b')"); await ready('window.imageCountChoice.count===1');
      assert.equal(await evaluate('window.imageCountChoice.resolution'),'1280x720');
      await evaluate("window.selectImageCountShot('c')"); await ready('window.imageCountChoice.count===1');
      await evaluate("window.selectImageCountShot('a')"); await ready('window.imageCountChoice.count===3');
      await load('?image-count=1&origin='+origin);
      assert.equal(await evaluate('window.imageCountChoice.count'),3);
      assert.match(await evaluate("document.querySelector('.shot-image-settings-trigger').textContent"),/3张/);
    });

    await t.test('video hydration displays every adopted frame and preserves typing, switching and explicit removal',async()=>{
      await load('?video-hydration=1');
      assert.equal(await evaluate("document.querySelectorAll('.asset-reference-rail button').length"),2);
      assert.deepEqual(await evaluate("window.hydratedDraft.selectedReferences.map(item=>item.reference_id)"),['first-image-1','first-image-2']);
      await evaluate('window.holdHydrationSave=true');
      await evaluate("(()=>{const input=document.querySelector('.asset-reference-input');input.focus();const range=document.createRange();range.selectNodeContents(input);range.collapse(false);getSelection().removeAllRanges();getSelection().addRange(range);})()");
      await send('Input.insertText',{text:' 用户中文调整 '});
      await ready('window.releaseHydrationSave');
      await evaluate('window.changeHydrationImage()');
      await ready("window.hydratedDraft.selectedReferences[1]?.reference_id==='first-new-2'");
      assert.ok(await evaluate("window.hydratedDraft.videoPrompt.endsWith(' 用户中文调整 ')") );
      assert.equal(await evaluate("document.querySelectorAll('.asset-reference-token').length"),2);
      await evaluate('window.releaseHydrationSave()');
      await ready("window.hydrationSaves.at(-1)?.input_plan.references[1]?.reference_id==='first-new-2'");
      await evaluate("window.beforeRefreshNode=document.querySelector('.asset-reference-input').firstChild;window.refreshHydration()");
      await pause(80);
      assert.equal(await evaluate("window.beforeRefreshNode===document.querySelector('.asset-reference-input').firstChild"),true);
      await evaluate("window.switchHydration('second')");
      await ready("window.hydratedDraft.selectedReferences[0]?.reference_id==='second-image-1'");
      assert.equal(await evaluate("document.querySelectorAll('.asset-reference-token').length"),1);
      await evaluate("window.switchHydration('first')");
      await ready("window.hydratedDraft.selectedReferences[0]?.reference_id==='first-image-1'");
      assert.ok(await evaluate("window.hydratedDraft.videoPrompt.endsWith(' 用户中文调整 ')") );
      await click('.asset-reference-rail button:nth-child(2)');
      await click('.asset-reference-actions button:nth-child(3)');
      await ready('window.hydratedDraft.autoReferenceExclusions.length===1');
      await evaluate('window.changeHydrationImage()'); await pause(80);
      assert.deepEqual(await evaluate("window.hydratedDraft.selectedReferences.map(item=>item.reference_id)"),['first-image-1']);
      assert.equal(await evaluate("document.querySelectorAll('.asset-reference-rail button').length"),1);
      await evaluate("window.switchHydration('second')");
      await ready("window.hydratedDraft.selectedReferences[0]?.reference_id==='second-image-1'");
      await evaluate("window.switchHydration('first')");
      await ready("window.hydratedDraft.selectedReferences[0]?.reference_id==='first-image-1'");
      assert.equal(await evaluate("document.querySelectorAll('.asset-reference-token').length"),1);
    });

    await t.test('full workspace uses existing Skill prompts and retains analysis intent',async()=>{
      for(const analysis of [false,true]) {
        await load('?video-workspace=1'+(analysis?'&analysis=1':''));
        assert.equal(await evaluate("Boolean(document.querySelector('.creative-intent-panel'))"),analysis);
        assert.equal(await evaluate("document.body.textContent.includes('资产引用与控制')"),false);
        assert.equal(await evaluate("document.querySelectorAll('.generation-reference-composer').length"),0);
        assert.equal(await evaluate("document.querySelector('.shot-video-gate button').disabled"),true);
        assert.equal(await evaluate("document.querySelector('.shot-video-gate-blockers, .shot-video-selection-hint')"),null);
        assert.equal(await evaluate("document.body.innerText.includes('请至少选择一个有效的已采用视频参与剪辑')"),false);
        assert.ok(await evaluate("document.querySelector('.shot-video-advance').title.includes('请至少选择一个')"));
        assert.ok(await evaluate("document.querySelector('.shot-video-gate').textContent.includes('已选 0 个视频')"));
        assert.equal(await evaluate("document.querySelectorAll('.asset-reference-add').length"),1);
      }
    });

    await t.test('video @ menu survives long editor scroll, autosave echo and keyboard search',async()=>{
      await load('?video-prompt=1',1100,740);
      await evaluate("(()=>{const root=document.querySelector('.asset-reference-input');root.focus({preventScroll:true});const range=document.createRange();range.selectNodeContents(root);range.collapse(false);const s=getSelection();s.removeAllRanges();s.addRange(range);root.scrollTop=root.scrollHeight;})()");
      await send('Input.insertText',{text:'@'});
      await ready("document.querySelector('.asset-reference-popover [role=option]')");
      await pause(150);
      assert.equal(await evaluate(visible),true);
      const pageScroll=await evaluate('window.scrollY');
      for(let i=0;i<12;i++) await key('ArrowDown');
      assert.equal(await evaluate(visible),true);
      assert.equal(await evaluate('window.scrollY'),pageScroll);
      assert.ok(await evaluate("document.querySelector('[role=listbox]').scrollTop>0"));
      await evaluate('window.echoVideoDraft(); window.scrollBy(0,80)'); await pause(100);
      assert.equal(await evaluate(visible),true);
      assert.equal(await evaluate('document.activeElement.className'),'asset-reference-input');
      await send('Input.insertText',{text:'产品参考17'});
      await ready("document.querySelectorAll('[role=option]').length===1");
      await key('Enter'); await ready('!'+visible);
      assert.equal(await evaluate("window.videoDraft.videoPromptMentions.at(-1).reference_id"),'asset-17');
      assert.ok(await evaluate("window.videoDraft.selectedReferences.some(item=>item.reference_id==='asset-17')"));
      await send('Input.insertText',{text:'@'}); await ready(visible); await key('Escape');
      assert.equal(await evaluate(visible),false);
      assert.equal(await evaluate('document.activeElement.className'),'asset-reference-input');
    });

    await t.test('video shot titles, independent checkboxes and drag/keyboard ordering',async()=>{
      await load('?video-list=1');
      assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('.shot-video-list-copy strong'),item=>item.textContent.trim())"),['分镜1','分镜2','分镜3']);
      assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('.shot-video-include input'),item=>[item.checked,item.disabled])"),[[true,false],[true,false],[false,true]]);
      await click('.shot-video-row:nth-child(1) .shot-video-include');
      assert.deepEqual(await evaluate('window.videoSelected'),{id:'s1',included:false});
      assert.equal(await evaluate('window.selectedShot'),undefined);
      await evaluate("document.querySelector('.shot-video-drag').focus()"); await key('ArrowDown');
      await ready("window.videoOrder?.[0]==='s2'");
      assert.equal(await evaluate("document.querySelectorAll('.shot-video-include input')[1].checked"),false);
      await evaluate("(()=>{const transfer=new DataTransfer();document.querySelector('.shot-video-row:nth-child(1) .shot-video-drag').dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:transfer}));const target=document.querySelector('.shot-video-row:nth-child(3)');target.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:transfer}));target.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));})()");
      await ready("window.videoOrder?.[2]==='s2'");
      assert.deepEqual(await evaluate('window.videoOrder'),['s1','s3','s2']);
      await evaluate('window.setVideoBusy(true)');
      await ready("document.querySelector('.shot-video-drag').disabled");
      assert.ok(await evaluate("Array.from(document.querySelectorAll('.shot-video-include input'),item=>item.disabled).every(Boolean)"));
      await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
      assert.ok(await evaluate('document.documentElement.scrollWidth<=390'));
      if(process.env.VIDEO_UI_SCREENSHOT_PATH) {
        await evaluate('window.setVideoBusy(false)'); await pause(80);
        const shot=await send('Page.captureScreenshot',{format:'png'});
        await writeFile(process.env.VIDEO_UI_SCREENSHOT_PATH,Buffer.from(shot.data,'base64'));
      }
    });

    await t.test('fifteen image shots show exactly five video participants with scoped ordering',async()=>{
      await load('?video-list=1&scope=1');
      const titles="Array.from(document.querySelectorAll('.shot-video-list-copy strong'),item=>item.textContent.trim())";
      assert.deepEqual(await evaluate(titles),['分镜2','分镜4','分镜8','分镜10','分镜15']);
      assert.equal(await evaluate("document.querySelector('.shot-video-list header span').textContent"),'5 个');
      await click('.shot-video-select');
      assert.equal(await evaluate('window.selectedShot'),'s2');
      await evaluate("document.querySelector('.shot-video-drag').focus()"); await key('ArrowDown');
      await ready("window.videoOrder?.[0]==='s4'");
      assert.deepEqual(await evaluate('window.videoOrder'),['s4','s2','s8','s10','s15']);
      assert.equal(await evaluate('window.allVideoShotCount'),15);
      await evaluate("window.setVideoScope(['s4','s2','s8','s10','s15','s12'])");
      await ready("document.querySelectorAll('.shot-video-row').length===6");
      assert.equal(await evaluate("document.querySelector('.shot-video-list header span').textContent"),'6 个');
      await evaluate("window.setVideoScope(['s8'])");
      await ready("document.querySelectorAll('.shot-video-row').length===1");
      assert.deepEqual(await evaluate(titles),['分镜8']);
      await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
      assert.ok(await evaluate('document.documentElement.scrollWidth<=390'));
    });

    await t.test('plain text and blank clicks place a caret, never activate the first thumbnail',async()=>{
      await load();
      await click('.asset-reference-input',true);
      assert.equal(await evaluate(visible),false);
      assert.equal(await evaluate("document.activeElement.className"),'asset-reference-input');
      await evaluate("window.clickTargets=[];document.addEventListener('click',e=>window.clickTargets.push(e.target.className),true)");
      const point = await evaluate("(() => {const r=document.createRange();r.setStart(document.querySelector('.asset-reference-input').firstChild,1);r.setEnd(document.querySelector('.asset-reference-input').firstChild,2);const b=r.getBoundingClientRect();return{x:b.x+b.width/2,y:b.y+b.height/2}})()");
      await send('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});
      await send('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:1});
      assert.equal(await evaluate(visible),false);
      assert.deepEqual(await evaluate('window.clickTargets'),['asset-reference-input']);
      assert.equal(await evaluate('window.promptChanges.length'),0);
      await send('Input.insertText',{text:'验证'});
      await ready('window.promptChanges.length>0');
      assert.equal(await evaluate("window.promptChanges.at(-1).references[0].reference_asset_id"),'square');
    });

    await t.test('pinned previews close on normal editing; inline and keyboard references still open',async()=>{
      await load(); await click('.asset-reference-rail button'); await ready(visible);
      await click('.asset-reference-input',true); assert.equal(await evaluate(visible),false);
      await pause(220); assert.equal(await evaluate(visible),false);
      await click('.asset-reference-token'); await ready(visible);
      await click('.asset-reference-close'); assert.equal(await evaluate(visible),false);
      assert.equal(await evaluate('document.activeElement.className'),'asset-reference-input');
      await evaluate("document.getElementById('before').focus()"); await key('Tab'); await ready(visible);
      await key('Escape'); assert.equal(await evaluate(visible),false);
      assert.equal(await evaluate('document.activeElement.className'),'asset-reference-input');
      await click('.asset-reference-rail button'); await ready(visible); await click('#before');
      assert.equal(await evaluate(visible),false);
      assert.equal(await evaluate('window.promptChanges.length'),0);
    });

    await t.test('hover dismisses and locate, replace, remove, undo retain their behavior',async()=>{
      await load();
      const point=await evaluate("(()=>{const r=document.querySelector('.asset-reference-rail button').getBoundingClientRect();return{x:r.x+12,y:r.y+12}})()");
      await send('Input.dispatchMouseEvent',{type:'mouseMoved',...point}); await ready(visible);
      await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:1000,y:700}); await ready('!'+visible);
      await click('.asset-reference-rail button'); await click('.asset-reference-actions button:nth-child(1)');
      assert.equal(await evaluate(visible),false);
      assert.ok(await evaluate("document.getSelection().toString().includes('图片1')"));
      await click('.asset-reference-rail button'); await click('.asset-reference-actions button:nth-child(2)');
      await ready("document.querySelector('.asset-reference-popover [role=option]')");
      await click('.asset-reference-popover [role=option]:nth-child(2)');
      assert.equal(await evaluate('window.promptChanges.at(-1).references[0].reference_asset_id'),'portrait');
      await key('z','KeyZ',2);
      assert.equal(await evaluate('window.promptChanges.at(-1).references[0].reference_asset_id'),'square');
      await click('.asset-reference-rail button'); await click('.asset-reference-actions button:nth-child(3)');
      assert.equal(await evaluate('window.promptChanges.at(-1).references.length'),0);
      await evaluate("document.querySelector('.asset-reference-input').focus()"); await key('z','KeyZ',2);
      assert.equal(await evaluate('window.promptChanges.at(-1).references[0].reference_asset_id'),'square');
    });

    await t.test('portrait, square and wide images stay inside preview at narrow, desktop and zoom-sized viewports',async()=>{
      for(const [width,height] of [[1440,900],[1024,768],[390,844],[320,568],[800,450]]) {
        for(const asset of ['square','portrait','wide']) {
          await load('?asset='+asset,width,height); await click('.asset-reference-rail button'); await ready(visible);
          await ready("document.querySelector('.asset-reference-preview img')?.naturalWidth>0");
          const geometry=await evaluate(`(()=>{const preview=document.querySelector('.asset-reference-preview'),img=preview.querySelector('img'),panel=document.querySelector('.asset-reference-popover');const box=e=>{const r=e.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom}};return{preview:box(preview),image:box(img),title:box(panel.querySelector('strong')),panel:box(panel),fit:getComputedStyle(img).objectFit,overflow:panel.scrollWidth>panel.clientWidth,documentOverflow:document.documentElement.scrollWidth>innerWidth}})()`);
          const context=`${asset} ${width}x${height}`;
          assert.ok(geometry.image.bottom<=geometry.preview.bottom+1,context+' image bottom');
          assert.ok(geometry.image.top>=geometry.preview.top-1,context+' image top');
          assert.ok(geometry.image.right<=geometry.preview.right+1,context+' image right');
          assert.ok(geometry.image.left>=geometry.preview.left-1,context+' image left');
          assert.ok(geometry.title.top>=geometry.preview.bottom,context+' title below image');
          assert.ok(geometry.panel.left>=0 && geometry.panel.right<=width && geometry.panel.top>=0 && geometry.panel.bottom<=height,context+' viewport');
          assert.equal(geometry.fit,'contain'); assert.equal(geometry.overflow,false,context+' popover overflow');
          assert.equal(geometry.documentOverflow,false,context+' document overflow');
          if(width===1024 && asset==='square' && process.env.PROMPT_SCREENSHOT_PATH) {
            const screenshot=await send('Page.captureScreenshot',{format:'png'});
            await writeFile(process.env.PROMPT_SCREENSHOT_PATH,Buffer.from(screenshot.data,'base64'));
          }
        }
      }
    });

    await t.test('long names, broken thumbnails, and read-only state keep usable close controls',async()=>{
      await load('?long=1',390,600); await click('.asset-reference-rail button'); await ready(visible);
      assert.equal(await evaluate("document.querySelector('.asset-reference-popover').scrollWidth>document.querySelector('.asset-reference-popover').clientWidth"),false);
      await key('Escape'); assert.equal(await evaluate(visible),false);
      await load('?asset=missing'); await click('.asset-reference-rail button');
      await ready("document.querySelector('.asset-reference-preview svg')");
      await click('.asset-reference-close'); assert.equal(await evaluate(visible),false);
      await load('?disabled=1'); await click('.asset-reference-rail button'); await ready(visible);
      assert.equal(await evaluate("document.querySelector('.asset-reference-actions button:nth-child(2)').disabled"),true);
      await key('Escape'); assert.equal(await evaluate(visible),false);
    });

    await t.test('batch choices are modal-only; cancel is inert and each confirmed batch freezes one image per shot',async()=>{
      await load('?workspace=1',390,844);
      assert.equal(await evaluate("document.querySelector('.image-batch-dialog').open"),false);
      assert.equal(await evaluate("document.querySelector('.image-batch-choice')"),null);
      await click('.image-batch-actions > button');
      await ready("document.querySelector('.image-batch-dialog').open");
      assert.equal(await evaluate('window.batchCalls.length'),0);
      assert.equal(await evaluate("document.querySelector('.image-batch-dialog footer .primary-button').disabled"),true);
      assert.equal(await evaluate("document.querySelector('.image-batch-dialog').scrollWidth>document.querySelector('.image-batch-dialog').clientWidth"),false);
      await click('.image-batch-dialog footer .secondary-button');
      assert.equal(await evaluate('window.batchCalls.length'),0);
      assert.equal(await evaluate('window.flushes'),0);
      await click('.image-batch-actions > button'); await click('.image-batch-cost-consent input');
      await click('.image-batch-dialog footer .primary-button');
      await ready("!document.querySelector('.image-batch-dialog').open && window.batchCalls.length===2");
      const first=await evaluate('window.batchCalls.at(-1).body');
      assert.equal(first.candidate_count,1); assert.equal(first.mode,'all'); assert.equal(first.model_alias,'local_tool');
      assert.equal(first.allow_unknown_cost,true); assert.equal(await evaluate('window.flushes'),1);
      assert.equal(await evaluate("document.querySelector('.image-batch-choice')"),null);
      await click('.image-batch-actions > button');
      await evaluate("(()=>{const field=document.querySelector('[aria-label=本次图片模型]');field.value='qwen';field.dispatchEvent(new Event('change',{bubbles:true}));})()");
      await ready("!document.querySelector('.image-batch-cost-consent')");
      await click('.image-batch-dialog footer .primary-button');
      await ready("window.batchCalls.length===4 && !document.querySelector('.image-batch-dialog').open");
      const second=await evaluate('window.batchCalls.at(-1).body');
      assert.notEqual(first.request_id,second.request_id);assert.equal(second.model_alias,'qwen');assert.equal(second.candidate_count,1);
      await click('.image-batch-actions > button'); await ready("document.querySelector('.image-batch-dialog').open"); await key('Escape');
      await ready("!document.querySelector('.image-batch-dialog').open");
      assert.equal(await evaluate("document.querySelector('.image-batch-dialog').open"),false);
      assert.equal(await evaluate("document.activeElement.textContent"),'一键生成全部分镜图');
    });

    await t.test('preflight errors stay in dialog; ambiguous submission retries the same frozen batch',async()=>{
      await load('?workspace=1');
      await click('.image-batch-actions > button');
      // Previous confirmed model is remembered, but opening never submits.
      await evaluate('window.preflightFail=true');
      await click('.image-batch-dialog footer .primary-button'); await ready('window.batchCalls.length===1');
      assert.equal(await evaluate("document.querySelector('.image-batch-dialog').open"),true);
      assert.ok(await evaluate("document.querySelector('.image-batch-dialog').textContent.includes('参考数量超过模型限制')"));
      await evaluate('window.preflightFail=false;window.loseReply=true');
      await click('.image-batch-dialog footer .primary-button'); await ready("document.querySelector('.image-batch-dialog [role=alert]')");
      const frozen=await evaluate('window.batchCalls.at(-1).body');
      assert.equal(await evaluate("document.querySelector('[aria-label=本次图片模型]').disabled"),true);
      await click('.image-batch-dialog footer .primary-button'); await ready("!document.querySelector('.image-batch-dialog').open");
      assert.deepEqual(await evaluate('window.batchCalls.at(-1).body'),frozen);
      assert.equal(await evaluate("window.batchCalls.filter(call=>call.path.endsWith('/preview')).length"),2);
    });

    await t.test('compact labels, shared prompt headings and neutral reference chips retain readable typography',async()=>{
      await load('?workspace=1',390,844);
      assert.equal(await evaluate("document.querySelector('.shot-image-model-copy').textContent"),'image-2');
      assert.ok(await evaluate("document.querySelector('.shot-image-model-trigger').title.includes('本机 ImageGen')"));
      assert.equal(await evaluate("document.querySelector('.asset-reference-token').textContent"),'图片1');
      const type=await evaluate("(()=>{const input=getComputedStyle(document.querySelector('.asset-reference-input')),chip=getComputedStyle(document.querySelector('.asset-reference-token'));return{input:[input.fontSize,input.fontWeight],chip:[chip.fontSize,chip.fontWeight]}})()");
      assert.deepEqual(type.input,type.chip);
      assert.equal(await evaluate("document.querySelector('.global-prompt-editor details').open"),false);
      await evaluate("document.querySelector('.global-prompt-editor summary').click()");
      assert.equal(await evaluate("document.querySelector('.global-prompt-fields label > span')"),null);
      const heading=await evaluate("Array.from(document.querySelectorAll('.prompt-section-heading strong'),e=>[getComputedStyle(e).fontSize,getComputedStyle(e).fontWeight])");
      assert.deepEqual(heading,[['16px','600'],['12px','400']]);
      assert.equal(await evaluate("document.querySelector('.global-prompt-editor summary').title"),'适用于全部分镜');
      assert.equal(await evaluate("document.querySelector('.global-prompt-editor small')"),null);
      const utilities=await evaluate("Array.from(document.querySelectorAll('.prompt-preview > button,.prompt-preview summary'),e=>{const s=getComputedStyle(e);return [s.fontSize,s.fontWeight,s.color]})");
      assert.deepEqual(utilities,[['12px','400','rgb(85, 85, 85)'],['12px','400','rgb(85, 85, 85)']]);
      if(process.env.PROMPT_UI_SCREENSHOT_PATH) {
        await evaluate("document.querySelector('.global-prompt-editor details').open=false");
        const clip=await evaluate("(()=>{const rect=document.querySelector('.production-field').getBoundingClientRect();return{x:rect.x,y:rect.y+scrollY,width:rect.width,height:rect.height,scale:1}})()");
        const screenshot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip});
        await writeFile(process.env.PROMPT_UI_SCREENSHOT_PATH,Buffer.from(screenshot.data,'base64'));
      }
    });

    await t.test('partial batch summary contains only completed/total and keeps failure details accessible',async()=>{
      await load('?workspace=1&partial=1');
      await ready("Boolean(document.querySelector('.image-batch-actions > span'))");
      assert.equal(await evaluate("document.querySelector('.image-batch-actions > span').textContent"),'完成 13/15 个画面');
      assert.equal(await evaluate("document.querySelector('.image-batch-problems').open"),false);
      await click('.image-batch-problems summary');
      assert.ok(await evaluate("document.querySelector('.image-batch-problems').textContent.includes('生成失败，请重试')"));
      assert.equal(await evaluate('window.batchCalls.length'),0);
    });

    await t.test('recovered shot status follows the current attempt instead of its historical failed batch',async()=>{
      await load('?navigation=1&recovered=1');
      const label="document.querySelector('.skill-shot-row.active .skill-shot-copy small').textContent";
      assert.equal(await evaluate(label),'待采用');
      const thumbnail=await evaluate("document.querySelector('.skill-shot-row.active img').src");
      for(const [state,expected] of [['queued','排队中'],['running','生成中'],['completed','待采用'],['failed','失败'],['completed','待采用'],['approved','已采用']]) {
        await evaluate(`window.setRetryState('${state}')`);
        await ready(`${label}==='${expected}'`);
        assert.equal(await evaluate("document.querySelector('.skill-shot-row.active img').src"),thumbnail);
      }
      await load('?workspace=1&partial=1');
      await ready('window.navigationBatchItems?.length===15');
      assert.ok(await evaluate('window.navigationBatchItems.every(item=>item.batch_created_at && item.batch_updated_at)'));
      assert.equal(await evaluate("'batch_created_at' in window.lastBatch.items[0]"),false,'batch history remains untouched');
      assert.equal(await evaluate('window.batchCalls.length'),0);
    });

    await t.test('Skill thumbnails only mark adopted images, without repeated shot numbers or unadopted circles',async()=>{
      await load('?navigation=1');
      const items=await evaluate("Array.from(document.querySelectorAll('.skill-shot-select'),e=>({label:e.querySelector('strong').textContent,image:!!e.querySelector('img'),number:!!e.querySelector('.shot-navigation-index-badge'),badge:e.querySelector('.shot-navigation-image-badge')?.getAttribute('aria-label')||null}))");
      assert.deepEqual(items,[
        {label:'分镜 01',image:true,number:false,badge:'已采用图片'},
        {label:'分镜 02',image:true,number:false,badge:null},
        {label:'分镜 03',image:false,number:false,badge:null},
      ]);
    });

    await t.test('prompt headers stay quiet when saved but retain pending, saving and actionable error feedback',async()=>{
      await load('?workspace=1');
      assert.equal(await evaluate("document.querySelector('.prompt-section-header .ui-autosave-status')"),null);
      for(const [state,label] of [['dirty','待保存'],['saving','保存中…'],['error','保存失败']]) {
        await evaluate(`window.setSaveState('${state}')`);
        await ready(`document.querySelector('.prompt-section-header .ui-autosave-status')?.textContent==='${label}'`);
      }
      await click('.prompt-section-header .ui-autosave-status.is-error');
      await ready("document.querySelector('.prompt-section-header .ui-autosave-status')?.textContent==='保存中…'");
      assert.equal(await evaluate('window.saveRetries'),1);
      await evaluate("window.setSaveState('saved')");
      await ready("!document.querySelector('.prompt-section-header .ui-autosave-status')");
    });
    await t.test('promotion status stays silent and follows each candidate despite late replies',async()=>{
      await load('?promotion=1');
      await ready('window.statusCalls.length>0');
      const hidden = "!document.querySelector('#promotion-fixture .generated-asset-button')";
      assert.ok(await evaluate(hidden));
      await evaluate('window.holdStatus=true');
      await click('#promotion-b'); await ready('window.statusReplies.b');
      assert.ok(await evaluate(hidden));
      await click('#promotion-a'); await ready('window.statusReplies.a');
      await evaluate('window.statusReplies.a();window.statusReplies.b()'); await pause(80);
      assert.ok(await evaluate(hidden),'late absent reply cannot reveal an already-promoted image action');
      await evaluate('window.holdStatus=false');
      for (const id of ['b','c']) {
        await click('#promotion-'+id); await ready('!('+hidden+')');
      }
      await evaluate("window.failStatus='c';window.dispatchEvent(new Event('focus'))");
      await ready(hidden);
      assert.equal(await evaluate("/查询中|已在资产库/.test(document.querySelector('#promotion-fixture').textContent)"),false);
      await evaluate("window.failStatus=null;window.dispatchEvent(new Event('focus'))");
      await ready('!('+hidden+')');
      await click('#promotion-a'); await ready(hidden);
    });

    async function fillPromotion(selector,value) {
      await evaluate(`(() => {const el=document.querySelector(${JSON.stringify(selector)});const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`);
    }
    const promotionDialog = '.generated-asset-dialog';
    async function openPromotion(id='b') {
      await click('#promotion-'+id); await ready("document.querySelector('#promotion-fixture .generated-asset-button')");
      await click('#promotion-fixture .generated-asset-button');
      await ready("document.querySelector('.generated-asset-dialog[open] select:not(:disabled)')");
    }

    await t.test('promotion stages metadata, cancellation is inert and in-flight preview changes cannot retarget it',async()=>{
      await load('?promotion=1'); await openPromotion();
      assert.equal(await evaluate('window.promotionCalls.length'),0);
      assert.equal(await evaluate("document.activeElement.getAttribute('required')"),'');
      await key('Escape'); await ready("!document.querySelector('.generated-asset-dialog')");
      assert.equal(await evaluate('window.promotionCalls.length'),0);
      assert.equal(await evaluate("document.activeElement.textContent"),'加入资产库');
      await openPromotion();
      await fillPromotion(promotionDialog+' input[required]','空气滤芯正面');
      await fillPromotion(promotionDialog+' select','folder-2');
      await fillPromotion(promotionDialog+' .generated-asset-dialog-fields label:nth-child(2) select','product');
      await click(promotionDialog+' summary');
      await fillPromotion(promotionDialog+' textarea','真实产品结构');
      await fillPromotion(promotionDialog+' input[placeholder]','滤芯，产品,滤芯');
      await evaluate("window.setPromotionCandidate('c');window.holdPromotion=true");
      await click(promotionDialog+' footer .primary-button'); await ready('window.releasePromotion');
      await evaluate("document.querySelector('.generated-asset-dialog form').requestSubmit()");
      assert.equal(await evaluate('window.promotionCalls.length'),1);
      await evaluate('window.releasePromotion()'); await ready("!document.querySelector('.generated-asset-dialog')");
      const payload=await evaluate('window.promotionCalls[0]');
      assert.deepEqual(payload,{kind:'image_candidate',source_entity_id:'b',shot_plan_id:'shot',folder_id:'folder-2',asset_type:'product',name:'空气滤芯正面',description:'真实产品结构',tags:['滤芯','产品']});
      await ready("document.querySelector('#promotion-fixture .generated-asset-button')");
      await click('#promotion-b'); await ready("!document.querySelector('#promotion-fixture .generated-asset-button')");
      await openPromotion('c');
      assert.equal(await evaluate("document.querySelector('.generated-asset-dialog select').value"),'folder-2');
      await key('Escape');
      await evaluate("window.setPromotionProject('another-project')");
      await openPromotion('c');
      assert.equal(await evaluate("document.querySelector('.generated-asset-dialog select').value"),'');
      await key('Escape');
    });

    await t.test('promotion errors preserve form edits and a lost reply remains idempotent',async()=>{
      await load('?promotion=1'); await openPromotion();
      await fillPromotion(promotionDialog+' input[required]','保留这个名称');
      await evaluate('window.failPromotion=true');
      await click(promotionDialog+' footer .primary-button');
      await ready("document.querySelector('.generated-asset-dialog-error')");
      assert.equal(await evaluate("document.querySelector('.generated-asset-dialog input[required]').value"),'保留这个名称');
      await evaluate('window.failPromotion=false;window.losePromotionReply=true');
      await click(promotionDialog+' footer .primary-button');
      await ready("document.querySelector('.generated-asset-dialog-error')?.textContent.includes('响应中断')");
      await ready("!document.querySelector('#promotion-fixture .generated-asset-button')");
      await click(promotionDialog+' footer .primary-button'); await ready("!document.querySelector('.generated-asset-dialog')");
      assert.equal(await evaluate('Object.keys(window.promotedImages).length'),2);
      assert.equal(await evaluate('window.promotedImages.b.name'),'保留这个名称');
      assert.ok(await evaluate('window.promotionCalls.every(call=>call.source_entity_id==="b")'));
    });

    await t.test('directory creation is explicit, workspace changes block submission, and layouts fit narrow screens',async()=>{
      await load('?promotion=1'); await openPromotion();
      await click('.generated-asset-new-folder');
      await fillPromotion('.generated-asset-create-folder input','新建产品目录');
      await click('.generated-asset-create-folder > div button:last-child');
      await ready("document.querySelector('.generated-asset-dialog select').value.startsWith('new-folder-')");
      assert.equal(await evaluate('window.promotionCalls.length'),0);
      await evaluate("window.promotionWorkspace='another-workspace'");
      await click(promotionDialog+' footer .primary-button');
      await ready("document.querySelector('.generated-asset-dialog-error')?.textContent.includes('工作区已切换')");
      assert.equal(await evaluate('window.promotionCalls.length'),0);
      await key('Escape');
      for (const width of [1280,390]) {
        await load('?promotion=1',width,760); await openPromotion();
        const geometry=await evaluate("(() => {const dialog=document.querySelector('.generated-asset-dialog'),r=dialog.getBoundingClientRect(),image=dialog.querySelector('img');return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:dialog.scrollWidth>dialog.clientWidth,fit:getComputedStyle(image).objectFit};})()");
        assert.ok(geometry.left>=0 && geometry.right<=width && geometry.top>=0 && geometry.bottom<=760,JSON.stringify(geometry));
        assert.equal(geometry.overflow,false); assert.equal(geometry.fit,'contain');
        if(process.env.PROMOTION_SCREENSHOT_PATH) {
          const shot=await send('Page.captureScreenshot',{format:'png'});
          await writeFile(process.env.PROMOTION_SCREENSHOT_PATH.replace('.png','-'+width+'.png'),Buffer.from(shot.data,'base64'));
        }
        await key('Escape');
      }
    });
  } finally {
    await client?.send('Browser.close').catch(()=>{}); client?.close();
    if(chrome.exitCode===null) await Promise.race([exited,pause(3000)]);
    if(chrome.exitCode===null) { chrome.kill(); await Promise.race([exited,pause(3000)]); }
    await new Promise(resolve=>server.close(resolve));
    // Delete only the disposable profile created by this test, never a user profile.
    if(dirname(resolve(profile))===resolve(tmpdir()) && basename(profile).startsWith('viral-prompt-browser-')) {
      await rm(profile,{recursive:true,force:true,maxRetries:4,retryDelay:250});
    }
  }
});
