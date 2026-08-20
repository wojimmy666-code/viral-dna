export function PromptFieldList({ fields = [] }) {
  if (!fields.length) return null;
  return (
    <dl className="prompt-field-list">
      {fields.map((field, index) => (
        <div key={`${field.label}-${index}`}>
          <dt>{field.label}</dt>
          <dd>{field.value}</dd>
        </div>
      ))}
    </dl>
  );
}
