import {useRef, useState} from 'react';
import {Button} from '../ui/system/Button.jsx';
import {resolutionForDimensions} from '../media-resolution.js';
import {clampBox, defaultComposition, reframeGeometry} from './composition.js';

const rectangle=({x,y,width,height})=>({x,y,width,height});

export function ReframePanel({source, target, onTargetChange, disabled, onBusy, onClose, onGenerate, Box}) {
  const [actual,setActual]=useState(()=>({...defaultComposition(),x:.35,y:.1,width:.3,height:.8}));
  const [step,setStep]=useState('source'),[confirmed,setConfirmed]=useState(false),[accepted,setAccepted]=useState(false);
  const [loaded,setLoaded]=useState(false),[failed,setFailed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [submitted,setSubmitted]=useState(false);
  const attempt=useRef(null), lock=useRef(false);
  const width=source.outputWidth, height=source.outputHeight;
  const geometry=reframeGeometry(actual,target,source.width,source.height,width,height);
  const locked=busy||disabled||submitted;
  const delta=geometry.actual;
  function changeActual(value){setActual(clampBox(value));setConfirmed(false);setAccepted(false);}
  function changeTarget(key,value){
    const center=target.x+target.width/2;
    // Width is derived, never a second independent scale axis.
    if(key==='center')onTargetChange(clampBox({...target,x:value-target.width/2}));
    else onTargetChange(clampBox({...target,[key]:value,x:center-target.width/2}));
    setAccepted(false);
  }
  function markTarget(box){onTargetChange({...target,...box,width:target.width});setAccepted(false);}
  async function generate(){
    if(lock.current||disabled||!confirmed||!accepted||!loaded||failed||geometry.error||source.blocker)return;
    lock.current=true;setBusy(true);onBusy(true);setError('');setSubmitted(true);
    attempt.current ||= {version:1,request_id:crypto.randomUUID(),source_sha256:source.sha256,source_box:rectangle(actual),target_box:rectangle(target)};
    try {await onGenerate({compositionReframe:attempt.current,baseCandidateId:source.id,reframeGeneration:source.generation});onClose();}
    catch(failure){setError(failure.message||'提交未完成。请重试同一请求，不会重复创建任务。');}
    finally{lock.current=false;setBusy(false);onBusy(false);}
  }
  const preview=step==='target';
  return <>
    <div className="composition-body reframe-body">
      <div className="composition-stage">
        <div className="composition-presets" aria-label="缩放扩图步骤">
          <Button size="compact" aria-pressed={!preview} disabled={busy} onClick={()=>setStep('source')}>1. 标记原图人物</Button>
          <Button size="compact" aria-pressed={preview} disabled={!confirmed||busy} onClick={()=>setStep('target')}>2. 预览目标构图</Button>
        </div>
        <div className="composition-canvas reframe-canvas" style={{aspectRatio:preview?width/height:source.width/source.height,maxWidth:`min(100%, ${48*(preview?width/height:source.width/source.height)}vh)`}}>
          <img src={source.url} alt={preview?'整图缩放预览，空白部分将由 AI 补全':'选定原图，请手工框住人物的头顶、脚底及最宽处'} onLoad={event=>{
            if(event.currentTarget.naturalWidth!==source.width||event.currentTarget.naturalHeight!==source.height){setFailed(true);setError('原图尺寸与记录不一致，请刷新后重新打开');}
            else setLoaded(true);
          }} onError={()=>{setFailed(true);setError('原图加载失败，请关闭并重新打开');}}
            style={preview?{left:geometry.left/width*100+'%',top:geometry.top/height*100+'%',right:'auto',bottom:'auto',width:geometry.scaledWidth/width*100+'%',height:geometry.scaledHeight/height*100+'%'}:undefined}/>
          {!preview&&loaded&&!failed&&<Box box={actual} onChange={changeActual} actual interactive={!locked}/>}
          {preview&&delta&&!geometry.error&&<Box box={delta} onChange={box=>markTarget({...target,x:box.x+(box.width-target.width)/2,y:box.y,height:box.height})} interactive={!locked} resizable={false}/>}
        </div>
        <p className="composition-help">{preview?'灰色区域为待扩图环境。原图整体缩小，人物与背景比例保持不变。':'拖动虚线框，包住完整人物（含头发、手和鞋）。方向键微调，右下角调整大小。'}</p>
        <p>人物尺寸依据你的标记计算，不是自动识别；朝向、姿态与服装保留原样。</p>
      </div>
      <div className="composition-controls">
        {!preview?<fieldset disabled={locked}><legend>原图人物范围</legend>
          <div className="composition-numbers">{[['x','原图左边距'],['y','原图头顶'],['width','原图人物宽度'],['height','原图人物高度']].map(([key,label])=><label key={key}>{label} %<input type="number" aria-label={label+'百分比'} min="0" max="100" step="0.1" value={+(actual[key]*100).toFixed(1)} onChange={event=>changeActual({...actual,[key]:Number(event.target.value)/100})}/></label>)}</div>
          <label className="reframe-check"><input type="checkbox" checked={confirmed} disabled={!loaded||failed||locked} onChange={event=>{setConfirmed(event.target.checked);setAccepted(false);}}/>我已准确框住原图中的完整人物</label>
          <Button disabled={!confirmed||locked} onClick={()=>setStep('target')}>下一步：预览缩放</Button>
        </fieldset>:<fieldset disabled={locked}><legend>目标人物位置</legend>
          <div className="composition-numbers">{[['center','水平中心',(target.x+target.width/2)*100],['y','头顶位置',target.y*100],['height','人物高度',target.height*100]].map(([key,label,value])=><label key={key}>{label} %<input type="number" min="0" max="100" step="0.1" aria-label={'目标'+label+'百分比'} value={+value.toFixed(1)} onChange={event=>changeTarget(key,Number(event.target.value)/100)}/></label>)}</div>
          {delta&&!geometry.error&&<output>实际高度 {(delta.height*100).toFixed(1)}% · 宽度 {(delta.width*100).toFixed(1)}%<br/>脚底位置 {((delta.y+delta.height)*100).toFixed(1)}% · 宽度等比例计算</output>}
          <Button variant="quiet" size="compact" disabled={locked} onClick={()=>{onTargetChange({...target,x:.5-target.width/2,y:.25,height:.5});setAccepted(false);}}>居中 · 高度 50%</Button>
        </fieldset>}
        {preview&&geometry.error&&<div className="composition-error" role="alert">{geometry.error}</div>}
        <section className="reframe-confirmation" aria-label="扩图生成确认">
          <strong>仅处理当前这张原图</strong>
          <p>{source.modelLabel} · {resolutionForDimensions(width,height)} · 1 张<br/>{source.costLabel}</p>
          <p>仅用选定原图补环境，不重新应用提示词、风格或资产。结果另存为新候选，不自动采用。环境与接缝仍需人工检查。</p>
          <label className="reframe-check"><input type="checkbox" checked={accepted} disabled={!preview||!confirmed||!!geometry.error||locked||!!source.blocker} onChange={event=>setAccepted(event.target.checked)}/>确认目标构图，并接受本次生成费用</label>
        </section>
        {source.blocker&&<div className="composition-error" role="alert">{source.blocker}</div>}
        {disabled&&!busy&&<p role="alert">当前不可编辑或已有任务运行，标记暂时保留。</p>}
        {error&&<div className="composition-error" role="alert">{error}{submitted&&<p>重试会查询或继续同一请求，不会重复创建任务。需修改参数时，请先关闭并核对任务状态。</p>}</div>}
      </div>
    </div>
    <footer><p>原图保护区域将无损回贴；这是二维构图调整，不是重新拍摄。</p><div><Button disabled={busy} onClick={onClose}>取消</Button><Button variant="primary" loading={busy} loadingLabel="提交扩图…" disabled={disabled||!preview||!confirmed||!accepted||!loaded||failed||!!geometry.error||!!source.blocker} onClick={generate}>{submitted?'重试同一请求':'生成缩放扩图'}</Button></div></footer>
  </>;
}
