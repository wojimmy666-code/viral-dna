import { PromptFieldList } from "./PromptFieldList.jsx";

export function PromptTimeline({ segments = [] }) {
  if (!segments.length) return null;
  return (
    <ol className="prompt-timeline">
      {segments.map((segment, index) => (
        <li key={`${segment.time}-${index}`}>
          <time>{segment.time}</time>
          <div>
            {segment.lead?.map((paragraph, paragraphIndex) => (
              <p key={paragraphIndex}>{paragraph}</p>
            ))}
            <PromptFieldList fields={segment.fields} />
          </div>
        </li>
      ))}
    </ol>
  );
}
