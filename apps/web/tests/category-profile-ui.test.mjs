import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  categoryProfileValidationMessage,
  draftToPayload,
  profileSearchText,
  splitProfileItems,
} from "../src/category-profiles/category-profile-ui.js";

const LIBRARY_URL = new URL("../src/category-profiles/CategoryProfileLibrary.jsx", import.meta.url);
const PICKER_URL = new URL("../src/category-profiles/CategoryProfilePicker.jsx", import.meta.url);
const CSS_URL = new URL("../src/category-profiles/category-profiles.css", import.meta.url);
const APP_URL = new URL("../src/App.jsx", import.meta.url);

test("normalizes category profile lists and validates required grounding", () => {
  assert.deepEqual(splitProfileItems("通勤女性、轻熟风用户，通勤女性\n职场新人"), [
    "通勤女性",
    "轻熟风用户",
    "职场新人",
  ]);
  const payload = draftToPayload({
    display_name: " 都市通勤女装 ",
    category_name: "女装",
    brand_name: "",
    brief: "轻职场穿搭",
    audiences: "通勤女性、职场新人",
    selling_points: "抗皱\n易搭配",
    scenes: "通勤、会议",
    forbidden_claims: "绝对显瘦",
    visual_style: "自然光",
  });
  assert.equal(payload.brand_name, null);
  assert.deepEqual(payload.selling_points, ["抗皱", "易搭配"]);
  assert.equal(categoryProfileValidationMessage(payload), "");
  assert.equal(categoryProfileValidationMessage({ ...payload, selling_points: [] }), "请至少填写一项核心卖点");
  assert.match(profileSearchText(payload), /抗皱/);
});

test("ships account category CRUD with soft delete and undo", async () => {
  const library = await readFile(LIBRARY_URL, "utf8");
  const app = await readFile(APP_URL, "utf8");
  assert.match(app, /label: "品类库"/);
  assert.match(app, /<CategoryProfileLibrary/);
  assert.match(library, /\/me\/category-profiles/);
  assert.match(library, /method: "DELETE"/);
  assert.match(library, /\/restore/);
  assert.match(library, /历史方案仍保留此档案快照/);
});

test("uses a searchable required picker and a single-column mobile fallback", async () => {
  const picker = await readFile(PICKER_URL, "utf8");
  const css = await readFile(CSS_URL, "utf8");
  assert.match(picker, /搜索品类、品牌或卖点/);
  assert.match(picker, /role="listbox"/);
  assert.match(picker, /目标人群/);
  assert.match(picker, /核心卖点/);
  assert.match(css, /\.category-profile-workspace\s*\{[^}]*grid-template-columns:\s*20rem minmax\(0, 1fr\)/s);
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.category-profile-workspace\s*\{[^}]*grid-template-columns:\s*1fr/s);
  assert.match(css, /\.category-picker-options input\s*\{\s*font-size:\s*var\(--type-subheading-size\)/s);
});
