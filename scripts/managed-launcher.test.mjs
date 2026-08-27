import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServicePlan, createSpawnOptions } from "./managed-launcher.mjs";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));

test("managed services bypass cmd and inherit the launch-run logs", () => {
  const projectRoot = path.resolve("D:/example/ViralDna");
  const plan = createServicePlan(projectRoot);

  assert.deepEqual(plan.map((service) => service.id), ["api", "web"]);
  assert.match(plan[0].command, /python\.exe$/i);
  assert.equal(plan[0].args.includes("--reload"), false);
  assert.equal(plan[1].command, process.execPath);
  assert.match(plan[1].args[0], /vite[\\/]bin[\\/]vite\.js$/i);

  for (const service of plan) {
    const options = createSpawnOptions(service, { TEST_ENV: "1" });
    assert.equal(options.shell, false);
    assert.equal(options.detached, false);
    assert.equal(options.windowsHide, true);
    assert.equal(options.stdio, "inherit");
  }
});

test("batch entry routes managed launches around manual console and PowerShell polling", () => {
  const batch = readFileSync(path.join(scriptDirectory, "start.bat"), "utf8");
  const managedRoute = "if defined PROJECT_LAUNCHER_MANAGED goto :managed_start";
  const managedStart = batch.indexOf("\r\n:managed_start\r\n");
  const managedEnd = batch.indexOf("\r\n:prepare_api\r\n", managedStart);
  const managedBlock = batch.slice(managedStart, managedEnd);

  assert.ok(batch.indexOf(managedRoute) >= 0);
  assert.ok(batch.indexOf(managedRoute) < batch.indexOf("call :is_web_ready"));
  assert.ok(managedStart >= 0);
  assert.ok(managedEnd > managedStart);
  assert.match(managedBlock, /managed-launcher\.mjs/i);
  assert.doesNotMatch(managedBlock, /^\s*start\s|cmd(?:\.exe)?\s+\/k|powershell(?:\.exe)?/im);
  assert.doesNotMatch(batch, /(?<!\r)\n/);
});
