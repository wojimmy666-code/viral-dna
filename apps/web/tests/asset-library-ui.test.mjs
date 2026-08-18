import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  assetLibraryView,
  assetListFolderForView,
  buildAssetListQuery,
  buildAssetPaginationItems,
  buildPostUploadView,
  formatAssetSize,
  normalizeAssetTags,
} from "../src/asset-library-ui.js";

test("uses the all-assets route as a folder home and flattens active searches", () => {
  assert.equal(assetLibraryView(), "home");
  assert.equal(assetListFolderForView({ folderId: "" }), "unfiled");
  assert.equal(assetLibraryView({ folderId: "folder-1" }), "folder");
  assert.equal(assetListFolderForView({ folderId: "folder-1" }), "folder-1");
  assert.equal(assetLibraryView({ folderId: "unfiled" }), "unfiled");
  assert.equal(assetLibraryView({ query: "主播" }), "search");
  assert.equal(assetLibraryView({ type: "person" }), "search");
  assert.equal(assetLibraryView({ includeArchived: true }), "search");
  assert.equal(assetListFolderForView({ query: "主播" }), "");
});

test("asset library home presents folder covers before unfiled assets", () => {
  const source = readFileSync(new URL("../src/AssetLibrary.jsx", import.meta.url), "utf8");
  const styles = readFileSync(new URL("../src/asset-library.css", import.meta.url), "utf8");

  assert.match(source, /className="asset-folder-card-grid"/);
  assert.match(source, /<FolderCover cover=\{folder\.cover\}/);
  assert.match(source, /cover\?\.thumbnail_url/);
  assert.match(source, /<h2 id="asset-unfiled-heading">未分类资产<\/h2>/);
  assert.match(source, /cover_asset_id: coverAssetId \|\| null/);
  assert.match(source, /设为所在目录封面/);
  assert.match(styles, /\.asset-folder-card-cover > img[\s\S]*?object-fit: contain/);
  assert.match(styles, /\.asset-cover-option-visual img[\s\S]*?object-fit: contain/);
});

test("uploaded assets return to a clean list view without opening details", () => {
  assert.deepEqual(buildPostUploadView({ id: "asset-1", folder_id: "folder-1" }), {
    folderId: "folder-1",
    query: "",
    type: "",
    storageState: "",
    includeArchived: false,
    page: 1,
  });
  assert.equal(buildPostUploadView({ id: "asset-2" }).folderId, "unfiled");
});

test("asset list query includes only active filters", () => {
  const query = new URLSearchParams(buildAssetListQuery({
    page: 3,
    pageSize: 40,
    folderId: "unfiled",
    type: "person",
    query: "  主播  ",
    storageState: "local_only",
    includeArchived: true,
  }));

  assert.deepEqual(Object.fromEntries(query), {
    page: "3",
    page_size: "40",
    folder_id: "unfiled",
    type: "person",
    query: "主播",
    storage_state: "local_only",
    include_archived: "true",
  });
});

test("asset pagination remains compact for long result sets", () => {
  assert.deepEqual(buildAssetPaginationItems(1, 3), [1, 2, 3]);
  assert.deepEqual(buildAssetPaginationItems(8, 16), [1, "ellipsis-1-7", 7, 8, 9, "ellipsis-9-16", 16]);
});

test("asset tags normalize Chinese punctuation and duplicates", () => {
  assert.deepEqual(normalizeAssetTags("人物， 主播,人物\n白裙"), ["人物", "主播", "白裙"]);
});

test("asset size is formatted for display", () => {
  assert.equal(formatAssetSize(950), "950 B");
  assert.equal(formatAssetSize(1536), "1.5 KB");
  assert.equal(formatAssetSize(2 * 1024 * 1024), "2.0 MB");
});

test("generated image video and depth artifacts expose asset-library actions", () => {
  const imageWorkspace = readFileSync(
    new URL("../src/ShotImageWorkspace.jsx", import.meta.url),
    "utf8",
  );
  const videoLibrary = readFileSync(
    new URL("../src/VideoCandidateLibrary.jsx", import.meta.url),
    "utf8",
  );
  const depthPanel = readFileSync(
    new URL("../src/video-controls/DepthControlPanel.jsx", import.meta.url),
    "utf8",
  );
  const assetLibrary = readFileSync(
    new URL("../src/AssetLibrary.jsx", import.meta.url),
    "utf8",
  );

  assert.match(imageWorkspace, /artifactKind="image_candidate"/);
  assert.match(videoLibrary, /artifactKind="video_candidate"/);
  assert.match(depthPanel, /artifactKind="depth_control"/);
  assert.match(assetLibrary, /asset\.media_kind !== "image"/);
  assert.match(assetLibrary, /\/provenance/);
});
