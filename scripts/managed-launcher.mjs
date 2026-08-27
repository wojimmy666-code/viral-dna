import { spawn as spawnChild } from "node:child_process";
import { appendFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const defaultProjectRoot = path.resolve(scriptDirectory, "..");

export function createServicePlan(projectRoot = defaultProjectRoot) {
  return [
    {
      id: "api",
      label: "API",
      command: path.join(projectRoot, ".venv", "Scripts", "python.exe"),
      args: [
        "-m", "uvicorn", "viral_dna_api.main:app",
        "--app-dir", "services/api/src",
        "--host", "127.0.0.1",
        "--port", "8000"
      ],
      cwd: projectRoot
    },
    {
      id: "web",
      label: "Web",
      command: process.execPath,
      args: [
        path.join(projectRoot, "node_modules", "vite", "bin", "vite.js"),
        "--host", "127.0.0.1",
        "--port", "4174",
        "--strictPort"
      ],
      cwd: path.join(projectRoot, "apps", "web")
    }
  ];
}

export function createSpawnOptions(service, environment = process.env) {
  return {
    cwd: service.cwd,
    env: environment,
    shell: false,
    detached: false,
    windowsHide: true,
    stdio: "inherit"
  };
}

export function appendStage(stage, label, message, environment = process.env) {
  const eventFile = String(environment.PROJECT_LAUNCHER_EVENT_FILE || "").trim();
  if (!eventFile) return;
  try {
    appendFileSync(eventFile, `${JSON.stringify({ type: "stage", stage, label, message })}\n`, "utf8");
  } catch (error) {
    console.warn(`[ViralDNA] Unable to report startup stage: ${error.message}`);
  }
}

function validateServicePlan(plan) {
  for (const service of plan) {
    if (!existsSync(service.command)) {
      throw new Error(`${service.label} executable was not found: ${service.command}`);
    }
    if (service.id === "web" && !existsSync(service.args[0])) {
      throw new Error(`Vite entry was not found: ${service.args[0]}`);
    }
  }
}

export async function runManagedLauncher({
  projectRoot = defaultProjectRoot,
  environment = process.env,
  spawnImpl = spawnChild
} = {}) {
  const plan = createServicePlan(projectRoot);
  validateServicePlan(plan);

  const children = [];
  let stopping = false;
  let finish;
  const completion = new Promise((resolve) => {
    finish = resolve;
  });

  const stopAll = (exitCode) => {
    if (stopping) return;
    stopping = true;
    for (const child of children) {
      if (child.exitCode === null && child.signalCode === null) child.kill();
    }
    finish(exitCode);
  };

  for (const service of plan) {
    appendStage(
      `starting_${service.id}`,
      `启动 ${service.label}`,
      service.id === "api" ? "正在启动 8000 端口服务" : "正在启动 4174 端口服务",
      environment
    );
    console.log(`[ViralDNA] Starting ${service.label}...`);
    const child = spawnImpl(service.command, service.args, createSpawnOptions(service, environment));
    children.push(child);
    child.once("error", (error) => {
      console.error(`[ViralDNA] ${service.label} failed to start: ${error.message}`);
      stopAll(1);
    });
    child.once("exit", (code, signal) => {
      if (stopping) return;
      const result = signal || (code ?? "unknown");
      console.error(`[ViralDNA] ${service.label} exited unexpectedly (${result}).`);
      stopAll(Number.isInteger(code) && code !== 0 ? code : 1);
    });
  }

  appendStage("services_spawned", "服务进程已创建", "等待管理台验证 API 与 Web 端口", environment);
  console.log("[ViralDNA] API and Web processes started; waiting for project-launcher health checks.");
  process.once("SIGINT", () => stopAll(0));
  process.once("SIGTERM", () => stopAll(0));
  return completion;
}

const isMain = process.argv[1]
  && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;

if (isMain) {
  runManagedLauncher()
    .then((exitCode) => {
      process.exitCode = exitCode;
    })
    .catch((error) => {
      console.error(`[ViralDNA] Managed launcher failed: ${error.stack || error.message}`);
      process.exitCode = 1;
    });
}
