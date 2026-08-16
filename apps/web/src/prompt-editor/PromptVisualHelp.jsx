import { Question, X } from "@phosphor-icons/react";
import { useId } from "react";

const VISUAL_HELP_ITEMS = [
  ["主体与服装", "人物、产品、道具和服装，只描述需要出现在画面中的内容。"],
  ["场景", "地点、背景和环境信息。"],
  ["构图", "景别、主体位置和前中后景关系。"],
  ["光线", "光向、软硬、色温和对比度。"],
  ["色彩", "主色、辅色和整体色调。"],
];

export function PromptVisualHelp() {
  const generatedId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const popoverId = `prompt-visual-help-${generatedId}`;
  const titleId = `${popoverId}-title`;

  return (
    <>
      <button
        className="prompt-visual-help-trigger"
        type="button"
        aria-haspopup="dialog"
        popoverTarget={popoverId}
        popoverTargetAction="toggle"
      >
        <Question size={16} />
        填写说明
      </button>

      <aside
        className="prompt-visual-help-popover"
        id={popoverId}
        popover="auto"
        role="dialog"
        aria-labelledby={titleId}
      >
        <header>
          <div>
            <strong id={titleId}>基础画面填写说明</strong>
            <span>这里只记录静态视觉事实；动作和运镜放在时间轴中。</span>
          </div>
          <button
            className="prompt-visual-help-close"
            type="button"
            aria-label="关闭填写说明"
            popoverTarget={popoverId}
            popoverTargetAction="hide"
          >
            <X size={16} />
          </button>
        </header>

        <dl>
          {VISUAL_HELP_ITEMS.map(([label, description]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{description}</dd>
            </div>
          ))}
        </dl>
      </aside>
    </>
  );
}
