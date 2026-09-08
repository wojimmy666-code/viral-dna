import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { activeReferences, referenceSegments, atomicDeletion, replacementRange, replaceReference } from '../src/prompt-references/reference-document.js';
import { reconcileVideoDraftReferences, synchronizeAutomaticVideoPrompt } from '../src/video-inputs/video-prompt-references.js';

const face = { reference_asset_id: 'face', label: '产品/正面' };
const detail = { reference_asset_id: 'detail', label: '产品/正面细节' };
test('longest full token wins, not a name-prefix asset', () => {
  const refs = [face, detail];
  assert.deepEqual(activeReferences('参考 @产品/正面细节。', refs), [detail]);
  assert.equal(referenceSegments('参考 @产品/正面细节。', refs)[1].reference, detail);
  assert.equal(replaceReference('参考 @产品/正面细节。', refs, face, null).value, '参考 @产品/正面细节。');
});
test('collapsed Enter/paste insertion after a chip preserves the reference', () => {
  const text = '前 @产品/正面';
  for (const inserted of ['\n', '粘贴的文字']) {
    const range = replacementRange(text, [face], text.length, text.length);
    assert.equal(text.slice(0, range.start) + inserted + text.slice(range.end), text + inserted);
  }
});
test('Backspace/Delete and reverse replacement treat the reference atomically', () => {
  const text = '前 @产品/正面 后';
  assert.deepEqual(atomicDeletion(text, [face], 8, 8, true), { start: 2, end: 8 });
  assert.deepEqual(atomicDeletion(text, [face], 2, 2, false), { start: 2, end: 8 });
  assert.deepEqual(replacementRange(text, [face], 5, 3), { start: 2, end: 8 });
});
test('repeated references use one binding; removing last token drops it', () => {
  assert.deepEqual(activeReferences('@产品/正面 @产品/正面', [face, face]), [face]);
  assert.deepEqual(activeReferences('其他文字', [face]), []);
  const next = replaceReference('@产品/正面 与 @产品/正面', [face], face, detail);
  assert.equal(next.value, '@产品/正面细节 与 @产品/正面细节');
  assert.deepEqual(next.references, [detail]);
});
test('plain asset names never create a binding implicitly', () => {
  assert.deepEqual(activeReferences('产品/正面，不是引用', [face]), []);
  assert.deepEqual(activeReferences('@产品/正面', []), []);
});
test('video editing keeps typed whitespace and does not duplicate inline references', () => {
  const reference = { reference_kind:'project_asset', reference_id:'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', label:'资产/产品/正面', role:'product', order:1 };
  const text = '参考 @资产/产品/正面，固定机位。';
  const draft = {videoPrompt:text,videoPromptMentions:[reference],selectedReferences:[reference],inputSources:['project_assets']};
  const synchronized = synchronizeAutomaticVideoPrompt({ prompt:text,mentions:[reference],selectedReferences:[reference] });
  assert.equal(synchronized.videoPrompt, text);
  const edited = reconcileVideoDraftReferences(draft, {videoPrompt:text+'  \n',videoPromptMentions:[reference],selectedReferences:[reference]}, []);
  assert.equal(edited.videoPrompt, text+'  \n');
});
test('one atomic editor owns IME, undo, clipboard and accessible thumbnail UI', () => {
  const source = readFileSync(new URL('../src/prompt-references/AssetReferenceEditor.jsx', import.meta.url), 'utf8');
  const image = readFileSync(new URL('../src/prompt-references/ImageAssetPromptEditor.jsx', import.meta.url), 'utf8');
  assert.match(source, /token.contentEditable = "false"/);
  assert.match(source, /onCompositionStart/);
  assert.match(source, /onCompositionEnd/);
  assert.match(source, /if \(composing.current\) return/);
  assert.match(source, /onCut=/);
  assert.match(source, /clipboardData.setData\('text\/plain'/);
  assert.match(source, /selection.setBaseAndExtent/);
  assert.match(source, /aria-activedescendant/);
  assert.match(source, /else menuKeyDown\(event\)/);
  assert.match(source, /list\.scrollTop \+= item/);
  assert.doesNotMatch(source, /\.scrollIntoView\(/);
  assert.match(source, /popup.kind === 'menu'\) positionPopup\(\)/);
  assert.match(source, /history.current\[index\]/);
  assert.match(image, /item.binding \? \{ \.\.\.item.binding \}/);
});

test('rich prompt editors are never wrapped in a native label that activates the first thumbnail', () => {
  for (const path of ['ShotImageWorkspace.jsx', 'skill-workflow/StoryboardPromptEditor.jsx', 'ShotVideoWorkspace.jsx']) {
    const source = readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
    for (const label of source.matchAll(/<label\b[\s\S]*?<\/label>/g)) {
      assert.doesNotMatch(label[0], /<(?:ImageAssetPromptEditor|AssetReferenceEditor|VideoPromptReferenceEditor)\b/, path);
    }
  }
  const editor = readFileSync(new URL('../src/prompt-references/AssetReferenceEditor.jsx', import.meta.url), 'utf8');
  assert.match(editor, /aria-labelledby=\{labelledBy\}/);
  assert.match(editor, /onPointerDown=\{\(event\) => \{ if \(!inputReference\(event.target\)\) dismissReference\(\)/);
});

test('preview grid and image both constrain intrinsic image dimensions', () => {
  const css = readFileSync(new URL('../src/prompt-references/asset-reference-editor.css', import.meta.url), 'utf8');
  const preview = css.match(/\.asset-reference-preview\s*\{([^}]+)\}/)[1];
  const image = css.match(/\.asset-reference-preview img\s*\{([^}]+)\}/)[1];
  assert.match(preview, /grid-template:\s*minmax\(0, 1fr\)\s*\/\s*minmax\(0, 1fr\)/);
  assert.match(image, /min-height:\s*0/);
  assert.match(image, /min-width:\s*0/);
  assert.match(image, /object-fit:\s*contain/);
});

test('inline chips show only an image number and inherit prose typography', () => {
  const source = readFileSync(new URL('../src/prompt-references/AssetReferenceEditor.jsx', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../src/prompt-references/asset-reference-editor.css', import.meta.url), 'utf8');
  assert.match(source, /text.textContent = `图片\$\{reference.number\}`/);
  assert.match(source, /token.title = reference.label/);
  assert.match(css, /\.asset-reference-token \{[^}]*border: 1px solid var\(--border-default\)[^}]*font: inherit/);
});
