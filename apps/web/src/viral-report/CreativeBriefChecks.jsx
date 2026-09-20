export function CreativeBriefChecks({ checks }) {
  if (!checks?.length) return null;
  return <dl className="creative-brief-checks" aria-label="补充想法落实说明">
    {checks.map((item) => <div key={item.requirement_index}>
      <dt>{item.requirement}</dt>
      <dd>{item.explanation}</dd>
    </div>)}
  </dl>;
}
