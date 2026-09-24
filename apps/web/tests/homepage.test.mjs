import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import test from "node:test";
import { FILM_SCENES, HOME_FILM, filmSceneAtTime } from "../src/landing/home-media.js";

const read = name => readFileSync(new URL(name, import.meta.url), "utf8");
const home = read("../src/landing/HomePage.jsx"), styles = read("../src/landing/home.css");
const film = read("../src/landing/HomeFilm.jsx"), media = read("../src/landing/home-media.js");

test("public homepage is isolated from the private app and account requests", () => {
  const entry = read("../src/main.jsx"), privateEntry = read("../src/accounts/PrivateApplication.jsx");
  assert.match(entry, /location\.pathname === "\/"/);
  assert.match(entry, /lazy\(\(\) => import\("\.\/accounts\/PrivateApplication\.jsx"\)/);
  assert.doesNotMatch(entry, /import \{ (?:App|AccountRoot) \}/);
  assert.match(privateEntry, /<AccountRoot>/);
  assert.match(privateEntry, /lazy\(\(\) => import\("\.\.\/App\.jsx"\)/);
  assert.doesNotMatch(home, /accountRequest|fetch\(|\/api\/|currentAccountSession|edit-lease/);
  assert.doesNotMatch(film + media, /accountRequest|fetch\(|\/api\/|currentAccountSession|edit-lease/);
});

test("public presentation is explicit, illustrative, accessible and not a private catalog", () => {
  for (const label of ["视觉示意 · 非真实案例", "静音分镜短片", "创作方向示意", "协作示意", "账户开通请联系管理员"]) assert.ok(home.includes(label), label);
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

test("public footer displays the supplied ICP number as a safe official registry link", () => {
  const footer = home.match(/<footer className="vd-footer">([\s\S]*?)<\/footer>/)?.[1];
  assert.ok(footer, "public footer is present without an account request");
  assert.equal((footer.match(/沪ICP备15044279号-7/g) || []).length, 1);
  assert.match(footer, /<a href="https:\/\/beian\.miit\.gov\.cn\/" target="_blank" rel="noopener noreferrer"[^>]*>沪ICP备15044279号-7<\/a>/);
  assert.match(footer, /<div className="vd-footer-legal">[\s\S]*<\/div>\s*$/);
  assert.match(styles, /\.vd-footer-legal\s*\{[^}]*text-align: center/);
});

test("real film keeps three complete shots and uses frame-accurate chapter boundaries", () => {
  assert.equal(FILM_SCENES.length, 3);
  assert.deepEqual(FILM_SCENES.map(scene => scene.label), ["光线唤醒", "材质特写", "英雄定格"]);
  assert.deepEqual(FILM_SCENES.map(scene => scene.start), [0, 121 / 24, 242 / 24]);
  assert.equal(HOME_FILM.duration, 363 / 24);
  for (const [seconds, expected] of [[-1, 0], [NaN, 0], [0, 0], [5, 0], [121 / 24, 1], [10, 1], [242 / 24, 2], [15.12, 2]]) {
    assert.equal(filmSceneAtTime(seconds), expected, `chapter at ${seconds}`);
  }
  assert.doesNotMatch(home, /setInterval|7000|静态分镜演示/);
  assert.match(home, /seekToScene\(index\)/);
  assert.match(film, /onTimeUpdate=/);
  assert.match(film, /muted playsInline loop preload="none"/);
  assert.match(film, /src=\{activated \? HOME_FILM.src : undefined\}/);
  assert.match(home, /navigator.connection\?\.saveData/);
  assert.doesNotMatch(home, /disabled=\{reduced\}/);
  assert.doesNotMatch(styles, /vd-camera-drift|brightness\(0\.58\)/);
});

test("public video is locally packaged, fast-start MP4 with real matching posters", () => {
  const videoPath = new URL(`../public${HOME_FILM.src}`, import.meta.url);
  const bytes = readFileSync(videoPath);
  assert.ok(bytes.length > 1024 && bytes.length < 16 * 1024 * 1024);
  const atoms = [];
  for (let offset = 0; offset + 8 <= bytes.length;) {
    const size32 = bytes.readUInt32BE(offset);
    const size = size32 === 1 ? Number(bytes.readBigUInt64BE(offset + 8)) : size32 || bytes.length - offset;
    assert.ok(size >= 8 && offset + size <= bytes.length, "valid MP4 atom boundary");
    atoms.push(bytes.toString("ascii", offset + 4, offset + 8));
    offset += size;
  }
  assert.equal(atoms[0], "ftyp");
  assert.ok(atoms.indexOf("moov") > 0 && atoms.indexOf("moov") < atoms.indexOf("mdat"), "metadata precedes media for streaming");
  let posterBytes = 0;
  for (const id of ["01", "02", "03"]) {
    const image = readFileSync(new URL(`../public/home/video/amber-${id}.png`, import.meta.url));
    assert.equal(image.readUInt32BE(16), HOME_FILM.width);
    assert.equal(image.readUInt32BE(20), HOME_FILM.height);
    const webp = readFileSync(new URL(`../public/home/video/amber-${id}.webp`, import.meta.url));
    assert.equal(webp.subarray(8, 12).toString(), "WEBP");
    posterBytes += webp.length;
  }
  assert.ok(posterBytes < 400 * 1024, `poster total ${posterBytes} bytes`);
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
