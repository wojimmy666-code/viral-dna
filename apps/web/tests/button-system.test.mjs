import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { parse } from "@babel/parser";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Button, IconButton } from "./helpers/render-button.mjs";

const root = new URL("../src/", import.meta.url);
const render = (Component, props = {}, children = "保存") => renderToStaticMarkup(createElement(Component, props, children));

test("shared buttons are native, safe by default and preserve explicit form submission", () => {
  assert.match(render(Button), /<button[^>]*type="button"/);
  assert.match(render(Button), /class="ui-button secondary-button"/);
  const html = render(Button, { type: "submit", form: "editor", name: "action", value: "save" });
  for (const attribute of ['form="editor"', 'name="action"', 'value="save"', 'type="submit"']) assert.ok(html.includes(attribute));
});

test("all roles, legacy layout classes and compact sizing use one component", () => {
  for (const variant of ["primary", "secondary", "text", "warning", "danger"]) {
    assert.match(render(Button, { variant, size: "compact" }), new RegExp(`ui-button ${variant}-button compact`));
  }
  assert.match(render(Button, { className: "primary-button compact workbench-action" }), /ui-button primary-button primary-button compact workbench-action/);
  assert.match(render(Button, { variant: "quiet", fullWidth: true }), /text-button quiet-button full/);
});

test("loading disables interaction, communicates busy state and reserves both labels", () => {
  const html = render(Button, { loading: true, loadingLabel: "正在停止…" }, "停止任务");
  assert.match(html, /disabled="" aria-busy="true"/);
  assert.match(html, /ui-button-idle" aria-hidden="true"/);
  assert.match(html, /ui-button-pending">.*正在停止…/);
  assert.match(render(Button, { loadingLabel: "正在停止…" }), /ui-button-pending" aria-hidden="true"/);
  let calls = 0;
  for (const props of [{ disabled: true }, { loading: true }]) {
    Button.render({ ...props, onClick() { calls++; } }, null).props.onClick({ preventDefault() {} });
  }
  assert.equal(calls, 0);
  Button.render({ onClick() { calls++; } }, null).props.onClick({});
  assert.equal(calls, 1);
});

test("icon actions have accessible names and forward refs", () => {
  assert.match(render(IconButton, { label: "关闭" }, "×"), /aria-label="关闭"/);
  assert.match(render(IconButton, { title: "复制" }, "□"), /aria-label="复制"/);
  const ref = { current: null };
  assert.equal(Button.render({}, ref).props.ref, ref);
});

function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory()
    ? files(path.join(dir, entry.name)) : entry.name.endsWith(".jsx") ? [path.join(dir, entry.name)] : []);
}
test("ordinary actions cannot regress to native unstyled buttons", () => {
  const failures = [];
  for (const file of files(fileURLToPath(root))) {
    if (/[\\/]landing[\\/]|[\\/]ui[\\/]system[\\/]Button.jsx$/.test(file)) continue;
    const source = readFileSync(file, "utf8");
    function visit(node, form = false) {
      if (!node || typeof node !== "object") return;
      if (node.type === "JSXElement") {
        const opening = node.openingElement, tag = opening.name.name;
        const attr = name => opening.attributes.find(item => item.name?.name === name);
        const where = `${file}:${opening.loc.start.line}`;
        if (tag === "button") {
          const classes = attr("className");
          if (!classes && !attr("data-ui")) failures.push(`${where}: use Button or document a specialized control with data-ui`);
          if (classes && /(?:primary|secondary|text|danger|icon)-button/.test(source.slice(classes.start, classes.end))) failures.push(`${where}: use the shared action component`);
        }
        if (tag === "IconButton" && !attr("label") && !attr("aria-label") && !attr("title")) failures.push(`${where}: icon action has no name`);
        if (tag === "Button" && form && !attr("type") && !attr("onClick")) failures.push(`${where}: form action needs explicit submit type`);
        form ||= tag === "form";
      }
      for (const [key, value] of Object.entries(node)) if (key !== "loc") {
        if (Array.isArray(value)) value.forEach(child => visit(child, form));
        else if (value && typeof value === "object") visit(value, form);
      }
    }
    visit(parse(source, { sourceType: "module", plugins: ["jsx"] }));
  }
  assert.deepEqual(failures, []);
});

test("geometry, reduced motion and touch targets are centralized", () => {
  const css = readFileSync(new URL("ui/system/buttons.css", root), "utf8");
  assert.match(css, /border-radius: var\(--radius-control\)/);
  assert.match(css, /min-height: var\(--control-height-compact\)/);
  assert.match(css, /@media \(pointer: coarse\), \(max-width: 600px\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.doesNotMatch(css, /translateY|transition: all/);
  assert.doesNotMatch(readFileSync(new URL("styles.css", root), "utf8"), /^\.primary-button\s*\{/m);
  assert.doesNotMatch(readFileSync(new URL("production-workflow.css", root), "utf8"), /^\.danger-button\s*\{/m);
});
