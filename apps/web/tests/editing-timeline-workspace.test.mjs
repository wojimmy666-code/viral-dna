import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workspaceSource = readFileSync(
  new URL("../src/video-editor/VideoEditorWorkspace.jsx", import.meta.url),
  "utf8",
);
const workflowSource = readFileSync(
  new URL("../src/ProductionWorkflow.jsx", import.meta.url),
  "utf8",
);
const productionUiSource = readFileSync(
  new URL("../src/production-ui.js", import.meta.url),
  "utf8",
);
const editorStyles = readFileSync(
  new URL("../src/video-editor/video-editor.css", import.meta.url),
  "utf8",
);
const editorStateSource = readFileSync(
  new URL("../src/video-editor/editor-state.js", import.meta.url),
  "utf8",
);

test("opens the editing step only after workflow advancement", () => {
  assert.match(productionUiSource, /id: "editing", label: "视频剪辑"/);
  assert.doesNotMatch(
    productionUiSource,
    /id: "editing"[^\n]+locked: true/,
  );
  assert.match(workflowSource, /<VideoEditorWorkspace/);
  assert.match(workflowSource, /setActiveSection\("editing"\)/);
  assert.match(workflowSource, /step\.id === "export" && project\.active_step === "editing"/);
});

test("persists controlled edits with optimistic timeline revisions", () => {
  assert.match(workspaceSource, /expected_revision_id: timeline\.revision_id/);
  assert.match(workspaceSource, /clip_order: timeline\.clips\.map/);
  assert.match(workspaceSource, /clip_updates: timeline\.clips\.map/);
  assert.match(workspaceSource, /audio_track: timeline\.audio_track/);
  assert.match(workspaceSource, /subtitle_cues: timeline\.subtitle_cues/);
  assert.match(workspaceSource, /timeline\/revisions\/\$\{revision\.id\}\/restore/);
  assert.match(editorStateSource, /handoff_synced: "同步最新分段视频"/);
});

test("offers source audio subtitles transitions and low-resolution preview jobs", () => {
  assert.match(workspaceSource, /option value="crossfade">叠化/);
  assert.match(workspaceSource, /option value="source">映射原视频音轨/);
  assert.match(workspaceSource, /timeline\/preview-renders/);
  assert.match(workspaceSource, /render-jobs\/\$\{renderJob\.id\}\/cancel/);
  assert.match(workspaceSource, /<TimelinePreviewPlayer/);
  assert.match(workspaceSource, /aria-label="播放进度"/);
  assert.match(workspaceSource, /aria-label="播放音量"/);
  assert.match(workspaceSource, /playsInline/);
  assert.match(workspaceSource, /<track default kind="subtitles"/);
  assert.match(workspaceSource, /onNotificationsChanged/);
  assert.match(workspaceSource, /cover_timestamp_seconds/);
  assert.match(workspaceSource, /timeline\/clips\/\$\{selectedClip\.id\}\/inspect/);
  assert.match(workspaceSource, /重新质检/);
  assert.doesNotMatch(workspaceSource, /timeline-cover-field|封面帧必须位于入点和出点之间/);
});

test("keeps preview media complete and places the timeline directly below it", () => {
  assert.match(
    editorStyles,
    /\.timeline-preview-player\s*\{[^}]+width:\s*min\(100%, var\(--timeline-preview-max-width\)\)/s,
  );
  assert.match(
    editorStyles,
    /\.timeline-preview-stage\s*\{[^}]+aspect-ratio:\s*var\(--timeline-preview-aspect\)/s,
  );
  assert.doesNotMatch(
    editorStyles,
    /\.timeline-preview-stage\s*\{[^}]+max-height:/s,
  );
  assert.match(
    editorStyles,
    /\.timeline-preview-stage video\s*\{[^}]+object-fit:\s*contain/s,
  );
  assert.match(
    editorStyles,
    /\.timeline-preview-controls\s*\{[^}]+display:\s*flex/s,
  );
  assert.match(
    editorStyles,
    /@media \(max-width: 1080px\)[\s\S]+\.timeline-editor-grid\s*\{[^}]+grid-template-columns:\s*minmax\(0, 1fr\)/,
  );
  assert.match(
    editorStyles,
    /\.timeline-inspector\s*\{[^}]+position:\s*sticky/s,
  );
  assert.match(
    editorStyles,
    /\.timeline-inspector\s*\{[^}]+max-height:\s*calc\(100dvh - 24px\)[^}]+grid-template-rows:\s*auto minmax\(0, 1fr\)/s,
  );
  assert.match(
    editorStyles,
    /\.timeline-canvas-column\s*\{[^}]+display:\s*grid[^}]+gap:\s*var\(--editor-space-related\)/s,
  );
  assert.doesNotMatch(
    editorStyles,
    /\.timeline-track-zone\s*\{[^}]+grid-column:/s,
  );
  assert.ok(
    workspaceSource.indexOf('className="timeline-track-zone"')
      < workspaceSource.indexOf('<aside className="timeline-inspector">'),
    "timeline should follow the preview before the inspector in DOM order",
  );
});
