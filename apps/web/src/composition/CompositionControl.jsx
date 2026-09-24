import {useEffect, useId, useRef, useState} from 'react';
import {CornersOut, X} from '@phosphor-icons/react';
import {Button, IconButton} from '../ui/system/Button.jsx';
import {clampBox, compositionDifference, defaultComposition, effectiveComposition, moveBox} from './composition.js';
import './composition.css';

function Box({box, onChange, actual=false, interactive=true, silhouette=false}) {
  const drag = useRef(null);
  function start(event, resize) {
    if (!interactive || event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    const bounds = event.currentTarget.closest('.composition-canvas').getBoundingClientRect();
    drag.current = {box, x:event.clientX, y:event.clientY, bounds, resize};
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event) {
    const current = drag.current;
    if (current) onChange(moveBox(current.box,(event.clientX-current.x)/current.bounds.width,(event.clientY-current.y)/current.bounds.height,current.resize));
  }
  function keyboard(event, resize) {
    const directions = {ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
    if (!directions[event.key]) return;
    event.preventDefault(); event.stopPropagation();
    const [x,y] = directions[event.key], step=event.shiftKey?0.01:0.002;
    onChange(moveBox(box,x*step,y*step,resize));
  }
  const events = {onPointerMove:move,onPointerUp:()=>{drag.current=null;},onPointerCancel:()=>{drag.current=null;}};
  return <div className={`composition-box ${actual?'is-actual':''} ${interactive?'is-interactive':''}`} style={{left:box.x*100+'%',top:box.y*100+'%',width:box.width*100+'%',height:box.height*100+'%'}}>
    {silhouette && <svg className="composition-figure" viewBox="0 0 100 200" preserveAspectRatio="none" aria-hidden="true"><circle cx="50" cy="17" r="13"/><path d="M50 34 V112 M17 99 L50 48 L83 99 M28 193 L50 112 L72 193" fill="none" stroke="currentColor" strokeWidth="9" strokeLinecap="round"/></svg>}
    <span className="composition-box-label">{actual?'实际位置（人工标记）':'目标位置'}</span>
    {interactive && <><button type="button" data-ui="composition-position" className="composition-drag" aria-label={actual?'移动实际人物框':'移动目标人物框'} onPointerDown={event=>start(event,false)} onKeyDown={event=>keyboard(event,false)} {...events}/>
      <button type="button" data-ui="composition-resize" className="composition-resize" aria-label={actual?'调整实际人物大小':'调整目标人物大小'} onPointerDown={event=>start(event,true)} onKeyDown={event=>keyboard(event,true)} {...events}><CornersOut size={18}/></button></>}
  </div>;
}

export function CompositionDialog({state, projectId, beatId, previewUrl, assets=[], disabled, onClose, onSave, onReload}) {
  const dialog = useRef(null), titleId=useId();
  const initial=effectiveComposition(state,projectId,beatId);
  const [draft,setDraft]=useState(()=>initial || defaultComposition(state.width/state.height));
  const [selected,setSelected]=useState([beatId]);
  const [scope,setScope]=useState('current'), [busy,setBusy]=useState(false), [error,setError]=useState('');
  const [review,setReview]=useState(false), [actual,setActual]=useState(null), [failedPreview,setFailedPreview]=useState(false);
  const disabledRef=useRef(disabled); disabledRef.current=disabled;
  const ratio=state.width/state.height;
  const aspectChanged=Math.abs(draft.aspect_ratio/ratio-1)>0.02;
  useEffect(()=>{const previous=document.activeElement; dialog.current.showModal(); return ()=>previous?.isConnected && previous.focus();},[]);
  const delta=actual?compositionDifference(draft,actual):null;
  const targets=state.targets || [];
  const targetIds=scope==='all'?targets.map(item=>item.id):scope==='selected'?selected:[beatId];
  async function save(operation='apply') {
    if(disabledRef.current || busy) return;
    setBusy(true); setError('');
    try { await onSave({operation:scope==='default'&&operation==='apply'?'default':operation,visual_beat_ids:targetIds,guide:draft}); }
    catch(failure){setError(failure.message || '保存失败，当前构图已保留');}
    finally{setBusy(false);}
  }
  function field(key,value){setDraft(current=>clampBox({...current,[key]:value}));}
  function close(){if(!busy)onClose();}
  return <dialog ref={dialog} className="composition-dialog" aria-labelledby={titleId} onCancel={event=>{event.preventDefault();close();}}>
    <header><div><h2 id={titleId}>构图引导</h2><p>拖动人物框确定位置与大小；生成结果仍需人工核对。</p></div><IconButton label="关闭构图" disabled={busy} onClick={close}><X size={20}/></IconButton></header>
    <div className="composition-body"><div className="composition-stage">
      <div className="composition-canvas" style={{aspectRatio:ratio, maxWidth:`min(100%, ${52*ratio}vh)`}}>
        {previewUrl&&!failedPreview && <img src={previewUrl} alt="当前分镜画面，仅供构图定位和人工核对" onError={()=>setFailedPreview(true)}/>}
        <div className="composition-guide-lines" aria-hidden="true"/>
        <Box box={draft} onChange={setDraft} interactive={!review&&!busy&&!disabled} silhouette={!previewUrl||failedPreview}/>
        {review && actual && <Box box={actual} onChange={setActual} actual interactive={!busy&&!disabled}/>}
      </div>
      <p className="composition-help">方向键微调，Shift＋方向键加快；右下角调整大小。辅助线和人物示意不会写入成片。</p>
      {previewUrl&&!failedPreview && <div className="composition-review">
        <label><input type="checkbox" checked={review} disabled={busy} onChange={event=>{setReview(event.target.checked);if(!actual)setActual({...draft});}}/>叠加核对实际位置</label>
        {review&&delta&&<><p>请把虚线框拖到图片中人物的真实位置。这是人工测量，不是自动识别。</p><output>水平中心差 {delta.horizontal.toFixed(1)}% · 脚底差 {delta.feet.toFixed(1)}% · 高度差 {delta.height.toFixed(1)}%（相对画幅）</output><Button variant="quiet" size="compact" disabled={busy||disabled} onClick={()=>{const {x,y,width,height}=actual;setDraft({...draft,x,y,width,height,aspect_ratio:ratio});setReview(false);}}>用人工标记作为新构图</Button></>}
      </div>}
      {failedPreview && <p role="status">预览图片读取失败，仍可在空白画布设置构图。</p>}
    </div><div className="composition-controls">
      <fieldset disabled={busy||disabled}><legend>人物定位</legend>
        <div className="composition-presets">{[['左三分之一',1/3],['居中',0.5],['右三分之一',2/3]].map(([name,center])=><Button key={name} size="compact" onClick={()=>field('x',center-draft.width/2)}>{name}</Button>)}</div>
        <div className="composition-numbers">{[['x','左边距'],['y','头顶位置'],['width','人物宽度'],['height','人物高度']].map(([key,label])=><label key={key}>{label} %<input aria-label={label+'百分比'} type="number" min={key==='width'?3:key==='height'?5:0} max="100" step="0.1" value={+(draft[key]*100).toFixed(1)} onChange={event=>field(key,Number(event.target.value)/100)}/></label>)}</div>
        <label>对应人物<select value={draft.subject_reference_id||''} onChange={event=>{const asset=assets.find(item=>item.id===event.target.value);setDraft({...draft,subject_reference_id:asset?.id||null,subject_label:asset?.name?.slice(0,80)||'主要人物'});}}><option value="">提示词中的主要人物</option>{assets.filter(item=>item.type==='person'&&!item.archived_at&&item.rights_confirmed).map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        {draft.subject_reference_id&&<p>每个应用画面需在提示词中引用该人物资产。</p>}
        <label>朝向<select value={draft.facing} onChange={event=>setDraft({...draft,facing:event.target.value})}><option value="auto">按提示词要求</option><option value="left">向左</option><option value="right">向右</option><option value="front">面向镜头</option></select></label>
      </fieldset>
      <fieldset disabled={busy||disabled}><legend>应用范围</legend><select aria-label="构图应用范围" value={scope} onChange={event=>setScope(event.target.value)}><option value="current">仅当前画面</option><option value="selected">勾选多个画面</option><option value="all">全部 {targets.length} 个画面</option><option value="default">设为方案默认构图</option></select>
        {scope==='selected'&&<div className="composition-targets">{targets.map(item=><label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} onChange={event=>setSelected(current=>event.target.checked?[...current,item.id]:current.filter(id=>id!==item.id))}/>{item.label}</label>)}</div>}
        <p>{scope==='default'?'默认构图适用于未单独设置的画面及后续新增画面。':`将更新 ${targetIds.length} 个画面；不会重新生成、覆盖图片或改变采用状态。`}</p>
      </fieldset>
      <p className="composition-limit">生成时额外使用 1 张构图参考图，计入模型输入上限。当前为位置引导，不保证像素级对齐。</p>
      {aspectChanged&&<div role="alert"><p>方案画幅已改变，请核对定位框后确认新画幅。</p><Button size="compact" disabled={busy||disabled} onClick={()=>setDraft({...draft,aspect_ratio:ratio})}>确认当前画幅</Button></div>}
      {error&&<div className="composition-error" role="alert">{error}<Button variant="text" size="compact" disabled={busy} onClick={async()=>{try{await onReload();setError('已读取最新版本，当前构图仍保留，请核对后再次应用。');}catch(failure){setError(failure.message);}}}>重新读取版本</Button></div>}
      {disabled&&<p role="alert">当前只读，构图草稿暂时保留，不能应用。</p>}
    </div></div>
    <footer><div className="composition-secondary">{scope!=='default'&&<Button variant="quiet" size="compact" disabled={busy||disabled||!targetIds.length} onClick={()=>save('inherit')}>所选画面恢复默认</Button>}<Button variant="quiet" size="compact" disabled={busy||disabled||!targetIds.length} onClick={()=>save(scope==='default'?'clear_default':'disable')}>{scope==='default'?'清除方案默认':'所选画面不使用构图'}</Button></div><div><Button disabled={busy} onClick={close}>取消</Button><Button variant="primary" loading={busy} loadingLabel="正在应用…" disabled={disabled||aspectChanged||(scope!=='default'&&!targetIds.length)} onClick={()=>save()}>应用构图</Button></div></footer>
  </dialog>;
}

export function CompositionControl({projectId,beatId,request,disabled,assets,previewUrl,beforeOpen,onSaved,onEffectiveChange}) {
  const [state,setState]=useState(null),[open,setOpen]=useState(false),[pending,setPending]=useState(false),[error,setError]=useState('');
  const live=useRef({projectId,beatId,disabled});live.current={projectId,beatId,disabled};
  useEffect(()=>{live.current={projectId,beatId,disabled};return()=>{live.current.projectId=null;};},[projectId,beatId]);
  const callbacks=useRef({beforeOpen,onSaved,onEffectiveChange});callbacks.current={beforeOpen,onSaved,onEffectiveChange};
  const path=`/productions/${projectId}/composition`;
  useEffect(()=>{let active=true;setState(null);setOpen(false);setError(''); if(!request)return;
    request(path).then(value=>{if(active)setState(value);}).catch(failure=>{if(active)setError(failure.message);});return()=>{active=false;};},[path,request]);
  useEffect(()=>{setOpen(false);},[beatId]);
  const effective=effectiveComposition(state,projectId,beatId);
  useEffect(()=>{callbacks.current.onEffectiveChange?.(effective);},[effective]);
  async function load(){const result=await request(path);if(live.current.projectId!==projectId||live.current.beatId!==beatId)throw new Error('画面已切换，请重新打开构图');setState(result);return result;}
  async function show(){if(disabled||pending)return;setPending(true);setError('');try{if(await callbacks.current.beforeOpen?.()===false)throw new Error('请先处理未保存的提示词');await load();if(!live.current.disabled)setOpen(true);}catch(failure){setError(failure.message);}finally{setPending(false);}}
  async function save(payload){if(live.current.disabled||live.current.projectId!==projectId||live.current.beatId!==beatId)throw new Error('编辑权限或当前画面已改变');
    const saved=await request(path,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,expected_context_id:state.context_id,expected_revision_id:state.revision_id})});
    if(live.current.projectId!==projectId||live.current.beatId!==beatId)return;
    setState(saved);
    try { if(await callbacks.current.onSaved?.()===false)throw new Error('提示词版本尚未同步'); }
    catch { throw new Error('构图已保存，但提示词版本同步失败。请重新读取版本或刷新页面后继续。'); }
    if(live.current.projectId===projectId&&live.current.beatId===beatId)setOpen(false);
  }
  return <div className="composition-control"><Button variant="quiet" size="compact" icon={<CornersOut size={18}/>} disabled={disabled||!request} loading={pending} loadingLabel="读取构图…" onClick={show}>{effective?'构图引导 · 已设置':'构图'}</Button>{error&&<span role="alert">{error}</span>}{open&&state&&<CompositionDialog state={state} projectId={projectId} beatId={beatId} assets={assets} previewUrl={previewUrl} disabled={disabled} onClose={()=>setOpen(false)} onSave={save} onReload={load}/>}</div>;
}
