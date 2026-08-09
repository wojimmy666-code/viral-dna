import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workspaceSource = readFileSync(
  new URL("../src/EditingTimelineWorkspace.jsx", import.meta.url),
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
const workflowStyles = readFileSync(
  new URL("../src/production-workflow.css", import.meta.url),
  "utf8",
);

test("opens the editing step only after workflow advancement", () => {
  assert.match(productionUiSource, /id: "editing", label: "剪辑合成"/);
  assert.doesNotMatch(
    productionUiSource,
    /id: "editing"[^\n]+locked: true/,
  );
  assert.match(workflowSource, /<EditingTimelineWorkspace/);
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
});

test("keeps preview media complete and collapses the inspector structurally", () => {
  assert.match(
    workflowStyles,
    /\.timeline-preview-player\s*\{[^}]+width:\s*min\(100%, var\(--timeline-preview-max-width\)\)/s,
  );
  assert.match(
    workflowStyles,
    /\.timeline-preview-stage\s*\{[^}]+aspect-ratio:\s*var\(--timeline-preview-aspect\)/s,
  );
  assert.doesNotMatch(
    workflowStyles,
    /\.timeline-preview-stage\s*\{[^}]+max-height:/s,
  );
  assert.match(
    workflowStyles,
    /\.timeline-preview-stage video\s*\{[^}]+object-fit:\s*contain/s,
  );
  assert.match(
    workflowStyles,
    /\.timeline-preview-controls\s*\{[^}]+display:\s*flex/s,
  );
  assert.match(
    workflowStyles,
    /@media \(max-width: 1080px\)[\s\S]+\.timeline-editor-grid\s*\{[^}]+grid-template-columns:\s*minmax\(0, 1fr\)/,
  );
  assert.match(
    workflowStyles,
    /\.timeline-inspector\s*\{[^}]+position:\s*sticky/s,
  );
});
