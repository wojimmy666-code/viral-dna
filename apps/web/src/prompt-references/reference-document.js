// Text + stable reference objects are the source of truth. DOM/HTML is never saved.
export function referenceKey(reference) {
  return String(reference.key || reference.reference_asset_id
    || `${reference.reference_kind}:${reference.reference_id}`);
}

export function referenceToken(reference) {
  return `@${String(reference.label || "").replace(/^@+/, "")}`;
}

export function activeReferences(value, references = []) {
  const used = new Set(referenceSegments(value, references).filter((segment) => segment.reference).map((segment) => referenceKey(segment.reference)));
  const seen = new Set();
  return references.filter((reference) => {
    const key = referenceKey(reference);
    if (seen.has(key) || !used.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function referenceSegments(value, references = []) {
  const text = String(value || "");
  const candidates = references.map((reference) => ({ reference, token: referenceToken(reference) }))
    .filter((item) => item.token.length > 1).sort((a, b) => b.token.length - a.token.length);
  const segments = [];
  let cursor = 0;
  while (cursor < text.length) {
    let match = null;
    for (const item of candidates) {
      const index = text.indexOf(item.token, cursor);
      if (index >= 0 && (!match || index < match.start)) match = { ...item, start: index };
    }
    if (!match) { segments.push({ text: text.slice(cursor), start: cursor }); break; }
    if (match.start > cursor) segments.push({ text: text.slice(cursor, match.start), start: cursor });
    segments.push({ text: match.token, reference: match.reference, start: match.start });
    cursor = match.start + match.token.length;
  }
  return segments;
}

export function atomicDeletion(value, references, start, end, backwards) {
  for (const segment of referenceSegments(value, references)) {
    if (!segment.reference) continue;
    const right = segment.start + segment.text.length;
    if (start === end && (backwards ? start > segment.start && start <= right : start >= segment.start && start < right)) {
      return { start: segment.start, end: right };
    }
    if (start < right && end > segment.start) {
      start = Math.min(start, segment.start); end = Math.max(end, right);
    }
  }
  return { start, end };
}

export function replaceReference(value, references, oldReference, replacement) {
  const next = referenceSegments(value, references).map((segment) => segment.reference && referenceKey(segment.reference) === referenceKey(oldReference)
    ? (replacement ? referenceToken(replacement) : "") : segment.text).join("");
  return { value: next, references: activeReferences(next, [
    ...references.filter((item) => referenceKey(item) !== referenceKey(oldReference)),
    ...(replacement ? [replacement] : []),
  ]) };
}

// Insertion at a collapsed caret must not behave like Backspace.
export function replacementRange(value, references, start, end) {
  return start === end ? { start, end } : atomicDeletion(value, references, Math.min(start, end), Math.max(start, end), false);
}

export function readReferenceDOM(root) {
  if (!root) return "";
  function read(node) {
    if (node.nodeType === 3) return node.textContent;
    if (node.nodeType !== 1 && node.nodeType !== 11) return "";
    if (node.dataset?.referenceToken) return node.dataset.referenceToken;
    if (node.nodeName === "BR") return "\n";
    let text = "";
    for (const child of node.childNodes) {
      const block = ["DIV", "P"].includes(child.nodeName);
      if (block && text && !text.endsWith("\n")) text += "\n";
      text += read(child);
    }
    return text;
  }
  return read(root).replace(/\u00a0/g, " ").replace(/\r\n?/g, "\n");
}
