import { PromptFieldList } from "./PromptFieldList.jsx";
import { PromptTimeline } from "./PromptTimeline.jsx";
import { parsePromptSections } from "./prompt-section-parser.js";
import "./prompt-presentation.css";

function Paragraphs({ items = [] }) {
  return items.map((paragraph, index) => <p key={index}>{paragraph}</p>);
}

export function PromptSectionView({ className = "", introTitle = "复刻要求", prompt }) {
  const parsed = parsePromptSections(prompt);
  if (!parsed.intro.length && !parsed.sections.length) return null;

  return (
    <div className={`prompt-section-view${className ? ` ${className}` : ""}`}>
      {parsed.intro.length > 0 && (
        <section className="prompt-section-block prompt-section-intro">
          <h5>{introTitle}</h5>
          <Paragraphs items={parsed.intro} />
        </section>
      )}
      {parsed.sections.map((section, index) => (
        <section className={`prompt-section-block prompt-section-${section.key}`} key={`${section.key}-${index}`}>
          <h5>{section.title}</h5>
          <Paragraphs items={section.lead || section.paragraphs} />
          {section.key === "timeline" && section.segments?.length > 0
            ? <PromptTimeline segments={section.segments} />
            : <PromptFieldList fields={section.fields} />}
        </section>
      ))}
    </div>
  );
}
