import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parse } from "@babel/parser";
import { apiErrorMessage } from "../src/api-errors.js";

test("preserves explicit business errors and existing response formats", () => {
  assert.equal(apiErrorMessage({ detail: "项目不存在" }, 404), "项目不存在");
  assert.equal(apiErrorMessage({ detail: { code: "project_not_trashed", message: "项目必须先移入回收站" } }, 409), "项目必须先移入回收站");
  assert.equal(apiErrorMessage({ message: "服务暂时不可用" }, 503), "服务暂时不可用");
});

test("explains path and selected-project UUID validation without echoing the input", () => {
  for (const loc of [["path", "project_id"], ["body", "project_ids", 0]]) {
    const message = apiErrorMessage({ detail: [{ loc, type: "uuid_parsing", msg: "Invalid UUID", input: "batch", ctx: { error: "raw input" } }] }, 422);
    assert.equal(message, "请求参数有误：项目 ID 格式不正确");
    assert.doesNotMatch(message, /batch|raw input/);
  }
});

test("empty selection and invalid lifecycle actions have useful Chinese errors", () => {
  assert.equal(apiErrorMessage({ detail: [{ loc: ["body", "project_ids"], type: "too_short" }] }, 422), "请求参数有误：请至少选择一个项目");
  assert.equal(apiErrorMessage({ detail: [{ loc: ["body", "action"], type: "enum" }] }, 422), "请求参数有误：操作类型选项无效");
  assert.equal(apiErrorMessage({ detail: [{ loc: ["body", "project_ids"], type: "missing" }] }, 422), "请求参数有误：请选择要操作的项目");
});

test("deduplicates validation messages and limits long error arrays", () => {
  const issues = ["第一处错误", "第一处错误", "第二处错误", "第三处错误", "第四处错误"].map((msg) => ({ msg, type: "value_error", loc: ["body", "name"] }));
  assert.equal(apiErrorMessage({ detail: issues }, 422), "请求参数有误：名称：第一处错误；名称：第二处错误；名称：第三处错误");
});

test("malformed/empty bodies retain a safe fallback and never stringify input data", () => {
  assert.equal(apiErrorMessage(null, 500), "请求失败，请稍后重试");
  assert.equal(apiErrorMessage({ detail: [null, {}, "invalid"] }, 422), "请求参数不正确，请检查后重试");
  const message = apiErrorMessage({ detail: [{ loc: ["body", "api_key"], msg: "Invalid value", input: "secret-token", ctx: { token: "another-secret" } }] }, 422);
  assert.equal(message, "请求参数有误：Invalid value");
  assert.doesNotMatch(message, /secret-token|another-secret|api_key/);
});

test("the real API request handler uses validation messages while preserving error metadata", async () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const ast = parse(source, { sourceType: "module", plugins: ["jsx"] });
  const fn = ast.program.body.find((node) => node.type === "FunctionDeclaration" && node.id.name === "apiRequest");
  const calls = [];
  const fetch = async (path, options) => {
    calls.push({ path, options });
    return { ok: false, status: 422, json: async () => ({ detail: [{ loc: ["path", "project_id"], type: "uuid_parsing" }] }) };
  };
  const request = new Function("fetch", "API_BASE", "apiErrorMessage", "projectFacingMessage", `return (${source.slice(fn.start, fn.end)});`)(fetch, "/api/v1", apiErrorMessage, (value) => value);
  await assert.rejects(request("/projects/batch/lifecycle", { method: "POST" }), (error) => {
    assert.equal(error.status, 422);
    assert.equal(error.message, "请求参数有误：项目 ID 格式不正确");
    assert.equal(error.code, null);
    return true;
  });
  assert.equal(calls[0].path, "/api/v1/projects/batch/lifecycle");
  assert.equal(calls[0].options.method, "POST");
});
