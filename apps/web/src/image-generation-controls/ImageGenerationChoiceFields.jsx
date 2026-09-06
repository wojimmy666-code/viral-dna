import { imageModelOptions } from "./image-generation-ui.js";
import { imageResolutionOptions, resolutionForDimensions } from "../media-resolution.js";

export function imageChoiceState(settings, aspectRatio, value) {
  const models = imageModelOptions(settings);
  const model = models.find(item => item.alias === value.model);
  const resolutions = imageResolutionOptions(aspectRatio, model);
  const [width, height] = String(value.resolution || "").split("x").map(Number);
  const cap = model?.capabilities;
  const validResolution = Boolean(cap && width && height && width <= cap.maximum_width && height <= cap.maximum_height && width * height <= cap.maximum_pixels);
  const unknown = model?.provider === "local_tool" && model.unit_cost_micros == null;
  const ready = Boolean(model?.configured && model.available !== false && validResolution && (!unknown || value.allowUnknownCost));
  return { models, model, resolutions, validResolution, unknown, ready, width, height };
}

export function imageChoicePayload(settings, aspectRatio, value) {
  const state = imageChoiceState(settings, aspectRatio, value);
  return { model_alias: value.model, execution_mode: state.model?.executionMode, width: state.width, height: state.height, allow_unknown_cost: Boolean(value.allowUnknownCost) };
}

export function ImageGenerationChoiceFields({ settings, aspectRatio, value, onChange, disabled, prefix = "本次" }) {
  const { models, resolutions, unknown, validResolution } = imageChoiceState(settings, aspectRatio, value);
  return <>
    <label className="image-batch-choice"><span>{prefix}图片模型</span><select aria-label={`${prefix}图片模型`} disabled={disabled} value={value.model} onChange={event => {
      const model = models.find(item => item.alias === event.target.value);
      const supported = imageResolutionOptions(aspectRatio, model).some(item => item.value === value.resolution);
      onChange({ model: event.target.value, resolution: supported ? value.resolution : "" });
    }}><option value="">请选择模型</option>{models.map(item => <option key={item.alias} value={item.alias} disabled={!item.configured || item.available === false}>{item.label}{!item.configured ? " · 尚未配置" : ""}</option>)}</select></label>
    <label className="image-batch-choice"><span>{prefix}图片分辨率</span><select aria-label={`${prefix}图片分辨率`} disabled={disabled} value={value.resolution} onChange={event => onChange({ resolution: event.target.value })}>
      <option value="">请选择分辨率</option>
      {validResolution && value.resolution && !resolutions.some(item => item.value === value.resolution) && <option value={value.resolution}>{resolutionForDimensions(value.resolution)}</option>}
      {resolutions.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
    </select></label>
    {unknown && <label className="image-batch-cost-consent"><input type="checkbox" disabled={disabled} checked={Boolean(value.allowUnknownCost)} onChange={event => onChange({ allowUnknownCost: event.target.checked })} /><span>本机图片费用未知，我同意本次使用</span></label>}
  </>;
}
