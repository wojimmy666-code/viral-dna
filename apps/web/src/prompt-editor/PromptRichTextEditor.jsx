import { useLayoutEffect, useRef } from "react";
import {
  deleteAtomicPromptDecoration,
  findPromptDecorationRanges,
  normalizePromptEditorText,
} from "./prompt-document.js";

function editorText(element) {
  if (!element) return "";
  return normalizePromptEditorText(element.innerText ?? element.textContent ?? "");
}

function renderEditorText(element, value) {
  if (!element) return;
  const text = normalizePromptEditorText(value);
  const ranges = findPromptDecorationRanges(text);
  if (ranges.length === 0) {
    element.textContent = text;
    return;
  }

  const fragment = document.createDocumentFragment();
  let cursor = 0;
  for (const range of ranges) {
    if (range.start > cursor) {
      fragment.append(document.createTextNode(text.slice(cursor, range.start)));
    }
    const decoration = document.createElement("span");
    decoration.className = `prompt-rich-token prompt-rich-token-${range.type}`;
    decoration.contentEditable = "false";
    decoration.dataset.promptToken = range.type;
    decoration.textContent = range.text;
    fragment.append(decoration);
    cursor = range.end;
  }
  if (cursor < text.length) fragment.append(document.createTextNode(text.slice(cursor)));
  element.replaceChildren(fragment);
}

function selectionOffsets(root) {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  if (!root.contains(selection.anchorNode) || !root.contains(selection.focusNode)) return null;

  function offsetAt(node, offset) {
    const range = document.createRange();
    range.selectNodeContents(root);
    range.setEnd(node, offset);
    return range.toString().length;
  }

  const anchor = offsetAt(selection.anchorNode, selection.anchorOffset);
  const focus = offsetAt(selection.focusNode, selection.focusOffset);
  return { start: Math.min(anchor, focus), end: Math.max(anchor, focus) };
}

function placeCaret(root, targetOffset) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let remaining = Math.max(0, targetOffset);
  let node = walker.nextNode();
  while (node) {
    const length = node.textContent?.length || 0;
    if (remaining <= length) {
      const range = document.createRange();
      range.setStart(node, remaining);
      range.collapse(true);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      return;
    }
    remaining -= length;
    node = walker.nextNode();
  }
  const range = document.createRange();
  range.selectNodeContents(root);
  range.collapse(false);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

function insertPlainText(root, text) {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || !root.contains(selection.anchorNode)) {
    root.append(document.createTextNode(text));
    return;
  }
  const range = selection.getRangeAt(0);
  range.deleteContents();
  const node = document.createTextNode(text);
  range.insertNode(node);
  range.setStartAfter(node);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

export function PromptRichTextEditor({
  ariaLabel,
  disabled = false,
  onChange,
  value = "",
}) {
  const editorRef = useRef(null);

  useLayoutEffect(() => {
    const editor = editorRef.current;
    if (!editor || document.activeElement === editor) return;
    if (editorText(editor) !== normalizePromptEditorText(value)) {
      renderEditorText(editor, value);
    }
  }, [value]);

  function commit() {
    const nextValue = editorText(editorRef.current);
    if (nextValue !== normalizePromptEditorText(value)) onChange(nextValue);
  }

  function handleBlur() {
    const editor = editorRef.current;
    const nextValue = editorText(editor);
    if (nextValue !== normalizePromptEditorText(value)) onChange(nextValue);
    renderEditorText(editor, nextValue);
  }

  function handleKeyDown(event) {
    if (disabled || !["Backspace", "Delete"].includes(event.key)) return;
    const editor = editorRef.current;
    const selection = selectionOffsets(editor);
    if (!selection) return;
    const result = deleteAtomicPromptDecoration(editorText(editor), {
      key: event.key,
      selectionStart: selection.start,
      selectionEnd: selection.end,
    });
    if (!result) return;
    event.preventDefault();
    renderEditorText(editor, result.value);
    onChange(result.value);
    placeCaret(editor, result.caret);
  }

  function handlePaste(event) {
    if (disabled) return;
    event.preventDefault();
    insertPlainText(
      editorRef.current,
      normalizePromptEditorText(event.clipboardData.getData("text/plain")),
    );
    commit();
  }

  return (
    <div
      ref={editorRef}
      aria-label={ariaLabel}
      aria-multiline="true"
      aria-readonly={disabled ? "true" : undefined}
      className="prompt-rich-editor"
      contentEditable={!disabled}
      onBeforeInput={(event) => {
        if (String(event.nativeEvent.inputType || "").startsWith("format")) {
          event.preventDefault();
        }
      }}
      onBlur={handleBlur}
      onInput={commit}
      onKeyDown={handleKeyDown}
      onPaste={handlePaste}
      role="textbox"
      spellCheck="true"
      suppressContentEditableWarning
    />
  );
}
