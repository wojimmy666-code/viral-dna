import "./text-model-indicator.css";

export function TextModelIndicator({ label = "Qwen3.7 Plus" }) {
  return <span className="text-model-indicator">文案模型：{label}</span>;
}
