import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import test from "node:test";

const read = name => readFileSync(new URL(name, import.meta.url), "utf8");
const home = read("../src/landing/HomePage.jsx"), styles = read("../src/landing/home.css");

test("public homepage is isolated from the private app and account requests", () => {
  const entry = read("../src/main.jsx"), privateEntry = read("../src/accounts/PrivateApplication.jsx");
  assert.match(entry, /location\.pathname === "\/"/);
  assert.match(entry, /lazy\(\(\) => import\("\.\/accounts\/PrivateApplication\.jsx"\)/);
  assert.doesNotMatch(entry, /import \{ (?:App|AccountRoot) \}/);
  assert.match(privateEntry, /<AccountRoot>/);
  assert.match(privateEntry, /lazy\(\(\) => import\("\.\.\/App\.jsx"\)/);
  assert.doesNotMatch(home, /accountRequest|fetch\(|\/api\/|currentAccountSession|edit-lease/);
});

test("public presentation is explicit, illustrative, accessible and not a private catalog", () => {
  for (const label of ["视觉示意 · 非真实案例", "静态分镜演示", "创作方向示意", "协作示意", "账户开通请联系管理员"]) assert.ok(home.includes(label), label);
  for (const id of ["showcase", "workflow", "skills", "team"]) assert.ok(home.includes(`id="${id}"`));
  assert.match(home, /role="tablist"/);
  assert.match(home, /aria-selected=/);
  assert.match(home, /aria-pressed=/);
  assert.match(home, /aria-modal|showModal\(\)/);
  assert.match(home, /previousFocus\?\.focus\(\)/);
  assert.match(home, /prefers-reduced-motion/);
  assert.match(home, /visibilitychange/);
  assert.match(home, /IntersectionObserver/);
  assert.match(home, /画面暂时不可用/);
});

test("marketing styles are scoped and do not redefine workbench tokens", () => {
  assert.doesNotMatch(styles, /:root\s*\{|--type-|--font-family-ui|--text-primary/);
  assert.match(styles, /\.vd-home\s*\{/);
  assert.match(styles, /@media \(max-width: 820px\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /font-display: swap/);
});

test("homepage uses local optimized original assets and a licensed font subset", () => {
  const names = ["hero-scene", "thumb-close", "thumb-scene", "thumb-motion"];
  let bytes = 0;
  for (const name of names) {
    assert.ok(home.includes(`/home/${name}.webp`));
    assert.ok(home.includes(`/home/${name}.png`));
    const webp = new URL(`../public/home/${name}.webp`, import.meta.url);
    bytes += statSync(webp).size;
    assert.equal(readFileSync(webp).subarray(8, 12).toString(), "WEBP");
  }
  assert.ok(bytes < 600 * 1024, `display images total ${bytes} bytes`);
  assert.match(read("../public/home/fonts/OFL.txt"), /SIL OPEN FONT LICENSE Version 1\.1/);
  assert.match(read("../index.html"), /lang="zh-CN"/);
});
