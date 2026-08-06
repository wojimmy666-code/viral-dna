# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## Branding

- 浏览器标签页图标始终复用侧边栏的项目标识：紫色圆角方块与白色播放三角。

## Record detail layout

- 分析报告与创作方案共用专注的记录详情布局：顶部不显示全局搜索和“新建分析”，正文不显示产品介绍区与“导入短视频”模块；记录卡上方保留紧凑面包屑，支持返回工作台、分析记录和方案列表；这些入口只保留在分析记录页和新建分析流程中。
