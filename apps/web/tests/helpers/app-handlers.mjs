import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parse } from "@babel/parser";

const source = readFileSync(new URL("../../src/App.jsx", import.meta.url), "utf8");
const ast = parse(source, { sourceType: "module", plugins: ["jsx"] });
const app = ast.program.body.map(node => node.declaration || node).find(node => node.id?.name === "App");

export function appHandlerSource(name) {
  const fn = app.body.body.find(node => node.type === "FunctionDeclaration" && node.id.name === name);
  assert.ok(fn, `App.${name} must remain covered`);
  return source.slice(fn.start, fn.end);
}

export function appHandler(name, scope) {
  return new Function("scope", `with (scope) { return (${appHandlerSource(name)}); }`)(scope);
}
