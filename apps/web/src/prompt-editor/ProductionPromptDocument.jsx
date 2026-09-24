import { Button } from "../ui/system/Button.jsx";
import { useCallback, useEffect, useRef, useState } from "react";
import { Copy, DownloadSimple } from "@phosphor-icons/react";
import { registerAccountFlusher } from "../accounts/account-client.js";
import { AssetReferenceEditor } from "../prompt-references/AssetReferenceEditor.jsx";
import { usePromptAssetLibrary } from '../prompt-references/usePromptAssetLibrary.jsx';
import { promptAssetReference, promptMentionData } from '../prompt-references/prompt-assets.js';
import { PromptPreview } from "../prompt-context/GlobalPromptEditor.jsx";
import { promptDocumentBody, productionPromptsToText, downloadProductionPrompts } from "./prompt-sources.js";

function BodyEditor({ label, value, mentions = [], readOnly, onChange, assets = [], onAddAssets, part = 'image' }) {
  const options = assets.map(asset => promptAssetReference(asset, part));
  const references = mentions.map(mention => ({ ...options.find(item => (item.reference_id || item.reference_asset_id) === (mention.reference_id || mention.reference_asset_id)), ...mention }));
  return <div className="scheme-prompt-field"><span>{label}</span><AssetReferenceEditor label={label} value={value} references={references} options={[...options, ...references]} disabled={readOnly}
    onAddAssets={!readOnly && onAddAssets ? (insert, pickerOptions) => onAddAssets(selected => insert(selected.map(asset => promptAssetReference(asset, part))), pickerOptions) : undefined}
    onChange={(text, refs) => onChange?.(text, promptMentionData(refs, part))} placeholder="描述画面；输入 @ 引用资产" /></div>;
}

export function ProductionPromptDocument({ document, request, onCopy, onEditProduction, children }) {
  const [working, setWorking] = useState(document);
  const [status, setStatus] = useState("saved");
  const [error, setError] = useState("");
  const state = useRef({ document, version: 0, saved: 0, chain: Promise.resolve(), timer: null });
  const alive = useRef(true);
  const readOnly = Boolean(document.read_only);
  const [assets, setAssets] = useState([]);
  useEffect(() => {
    if (readOnly) return undefined;
    let active = true;
    request(`/productions/${document.project_id}/references`).then(items => { if (active) setAssets(items || []); }).catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [document.project_id, request, readOnly]);
  const flush = useCallback(async () => {
    const current = state.current;
    clearTimeout(current.timer);
    const save = async () => {
      if (readOnly || current.version === current.saved) return true;
      const version = current.version;
      if (alive.current) { setStatus("saving"); setError(""); }
      try {
        const saved = await request(`/productions/${document.project_id}/prompt-document`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(promptDocumentBody(current.document)), signal: AbortSignal.timeout(30000),
        });
        // An acknowledgement advances the token, never discards text typed in flight.
        current.document = current.version === version ? saved : { ...current.document, token: saved.token };
        current.saved = version;
        if (alive.current) { setWorking(current.document); setStatus(current.version === version ? "saved" : "dirty"); }
        return true;
      } catch (failure) {
        if (alive.current) { setError(`${failure.message || "保存失败"}。当前文字仍保留，可复制备份后核对。`); setStatus("error"); }
        return false;
      }
    };
    const drain = async () => {
      while (current.version !== current.saved) { if (!await save()) return false; }
      return true;
    };
    current.chain = current.chain.then(drain, drain);
    return current.chain;
  }, [document.project_id, readOnly, request]);
  const library = usePromptAssetLibrary({ request, productionId: document.project_id, beforeLink: flush,
    onLinked: async (_assets, _facts, check) => {
      const [latest, references] = await Promise.all([request(`/productions/${document.project_id}/prompt-document`), request(`/productions/${document.project_id}/references`)]);
      check();
      if (!alive.current) throw new Error('提示词文档已关闭，请重新打开。');
      const body = value => { const { expected_token, ...content } = promptDocumentBody(value); return JSON.stringify(content); };
      if (body(latest) !== body(state.current.document)) throw new Error('提示词已在其他页面更新，当前草稿已保留。请先核对最新内容，再引用资产。');
      // Linking advances the production revision but does not edit any body.
      state.current.document = { ...state.current.document, token: latest.token, revision_id: latest.revision_id };
      setWorking(state.current.document); setAssets(references);
    },
  });

  useEffect(() => {
    alive.current = true;
    const unregister = registerAccountFlusher(flush);
    const warn = event => {
      if (state.current.version !== state.current.saved) { event.preventDefault(); event.returnValue = ""; }
    };
    window.addEventListener("beforeunload", warn);
    return () => { alive.current = false; clearTimeout(state.current.timer); unregister(); window.removeEventListener("beforeunload", warn); };
  }, [flush]);

  function change(update) {
    if (readOnly) return;
    const current = state.current;
    current.document = update(current.document);
    current.version += 1;
    setWorking(current.document); setStatus("dirty");
    clearTimeout(current.timer); current.timer = setTimeout(flush, 900);
  }
  function changeShot(id, update) {
    change(value => ({ ...value, shots: value.shots.map(shot => shot.id === id ? update(shot) : shot) }));
  }
  function changeImage(shotId, imageId, update) {
    changeShot(shotId, shot => ({ ...shot, images: shot.images.map(image => image.id === imageId ? update(image) : image) }));
  }
  async function download() { if (await flush()) downloadProductionPrompts(state.current.document); }
  const constraints = (label, values, onChange) => <details className="scheme-constraints"><summary>{label}{values.length ? ` · ${values.length} 条` : ""}</summary><textarea aria-label={label} value={values.join("\n")} readOnly={readOnly} rows={3} onChange={event => onChange(event.target.value.split("\n"))} /></details>;

  return <section className="prompt-editor scheme-prompt-document" aria-label="方案提示词文档">
    <header className="prompt-document-toolbar">
      <div className="prompt-document-title"><span><h2>{working.name}</h2><small>{working.shots.length} 个分镜 · {readOnly ? "只读预览" : "与制作阶段共用提示词"}</small></span></div>
      <div className="prompt-document-toolbar-actions">
        {!readOnly && <span className={`prompt-save-state ${status}`} role="status">{{ saved: "已保存", dirty: "待保存", saving: "保存中…", error: "未保存" }[status]}</span>}
        {status === "error" && <Button type="button" className="secondary-button compact" onClick={flush}>重试保存</Button>}
        <Button type="button" className="secondary-button compact" onClick={async () => { if (await flush()) onCopy(productionPromptsToText(state.current.document), "方案提示词已复制"); }}><Copy size={16} />复制全文</Button>
        <Button type="button" className="primary-button compact" onClick={download}><DownloadSimple size={16} />下载 TXT</Button>
      </div>
    </header>
    {error && <p className="scheme-prompt-error" role="alert">{error}</p>}
    {children}
    {library.dialog}
    <div className="scheme-prompt-content">
      <details className="scheme-global"><summary>全局提示词</summary><div className="scheme-prompt-columns">
        <BodyEditor label="全局图片提示词" value={working.common_image_prompt} mentions={working.common_image_mentions} assets={assets} onAddAssets={library.open} readOnly={readOnly} onChange={(value, mentions) => change(doc => ({ ...doc, common_image_prompt: value, common_image_mentions: mentions }))} />
        <BodyEditor label="全局视频提示词" part="video" value={working.common_video_prompt} mentions={working.common_video_mentions} assets={assets} onAddAssets={library.open} readOnly={readOnly} onChange={(value, mentions) => change(doc => ({ ...doc, common_video_prompt: value, common_video_mentions: mentions }))} />
      </div></details>
      {working.shots.map((shot, index) => <details className="scheme-shot" key={shot.id} open={index === 0 ? true : undefined}>
        <summary><strong>分镜 {shot.index}</strong><span>{Number(shot.duration_seconds.toFixed(2))} 秒</span><span className="scheme-shot-excerpt">{shot.images[0]?.prompt}</span></summary>
        <div className="scheme-prompt-columns">
          <div>{shot.images.map((image, index) => <div key={image.id}>
            <BodyEditor label={`局部图片提示词${shot.images.length > 1 ? ` ${index + 1}` : ""}`} value={image.prompt} mentions={image.mentions} assets={assets} onAddAssets={library.open} readOnly={readOnly} onChange={(value, mentions) => changeImage(shot.id, image.id, row => ({ ...row, prompt: value, mentions }))} />
            <PromptPreview label="图片提示词" common={working.common_image_prompt} local={image.prompt} style={(shot.visual_style_snapshot ?? working.visual_style_snapshot)?.image_prompt || ""} />
            {constraints("图片负面约束", image.negative_constraints, values => changeImage(shot.id, image.id, row => ({ ...row, negative_constraints: values })))}
          </div>)}{!readOnly && onEditProduction && <Button type="button" className="text-button" onClick={async () => { if (await flush()) onEditProduction(document.project_id, shot.id, "shot_images"); }}>到分镜图片编辑资产引用</Button>}</div>
          <div><BodyEditor label={shot.video_group_id ? "分镜动作说明（由生成组合并）" : "局部视频提示词"} part="video" value={shot.video_prompt} mentions={shot.video_mentions} assets={assets} onAddAssets={library.open} readOnly={readOnly} onChange={(value, mentions) => changeShot(shot.id, row => ({ ...row, video_prompt: value, video_mentions: mentions }))} />
            {!shot.video_group_id && <PromptPreview label="视频提示词" common={working.common_video_prompt} local={shot.video_prompt} style={(shot.visual_style_snapshot ?? working.visual_style_snapshot)?.video_prompt || ""} />}
            {constraints("视频负面约束", shot.video_negative_constraints, values => changeShot(shot.id, row => ({ ...row, video_negative_constraints: values })))}
            {!readOnly && onEditProduction && <Button type="button" className="text-button" onClick={async () => { if (await flush()) onEditProduction(document.project_id, shot.id, "shot_videos"); }}>到分镜视频编辑资产引用</Button>}
          </div>
        </div>
      </details>)}
      {working.video_groups?.map((group, index) => <details className="scheme-shot" key={group.id}>
        <summary><strong>视频生成组 {index + 1}</strong><span>{group.shot_plan_ids.length} 个分镜 → 1 段视频</span></summary>
        <BodyEditor label="合并后的分段提示词（自动汇总）" value={group.compiled_prompt} readOnly />
        {status !== "saved" && <p role="status">分镜修改保存后，合并提示词会重新汇总。</p>}
        {group.error && <p role="alert">{group.error}</p>}
        {!readOnly && onEditProduction && <Button type="button" className="text-button" onClick={async () => { if (await flush()) onEditProduction(document.project_id, group.shot_plan_ids[0], "shot_videos"); }}>调整分组与生成参数</Button>}
      </details>)}
    </div>
  </section>;
}
