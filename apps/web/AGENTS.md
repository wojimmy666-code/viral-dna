# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## Branding

- 浏览器标签页图标始终复用侧边栏的项目标识：紫色圆角方块与白色播放三角。

## Record detail layout

- 分析报告与创作方案共用专注的记录详情布局：顶部不显示全局搜索和“新建分析”，正文不显示产品介绍区与“导入短视频”模块；记录卡上方保留紧凑面包屑，支持返回工作台、分析记录和方案列表；这些入口只保留在分析记录页和新建分析流程中。

## Production aspect ratios

- 新建创作方案时，默认输出画幅必须根据源视频尺寸或宽高比选择最接近的受支持画幅；当前支持 `9:16`、`16:9`、`1:1` 和 `4:5`，用户仍可在创建前手动调整。
- 分镜图片工作台中的“当前关键帧”和“AI 生成图”必须共用方案输出画幅作为预览画布；图片始终使用 `object-fit: contain` 完整显示，禁止用固定竖向高度或 `cover` 裁剪横版、竖版素材。

## Production video controls

- 分段视频的“原分镜时长”和“AI 生成时长”是两个独立概念：原时长保留精确小数用于时间线和剪辑，生成时长必须根据当前视频模型能力归一化后单独提交。
- 视频生成时长使用模型能力驱动的滑块；固定时长模型只显示合法停靠点，范围模型读取最小值、最大值和步长。切换模型时必须映射到最接近的合法时长，并同步更新成本预估。
- 视频候选预览必须把图片和视频完整约束在预览容器内，保持 `object-fit: contain`，不得因媒体固有宽高比裁掉画面或位于视频底部的播放控件。

## Production parameter controls

- 视频生成参数字段统一采用“标题行、主控件行、辅助说明行”的结构；标题行固定 22px，主控件固定 44px，辅助说明不得撑高或下移同排的其他控件。

## Production workspace layout

- “创作方案”列表和项目详情使用全宽专注布局，不显示分析报告右侧的 VLM 状态面板；VLM 状态只保留在“分析报告”工作区。
- 报告标题栏不放“创建方案”快捷按钮，创建入口统一保留在“创作方案”列表及空状态中；分析记录页顶部栏不显示“新建分析”，页面正文入口继续保留。

## Production shot navigation

- “分镜列表”和“有效分镜”统一显示紧凑缩略图导航项：编号叠加在缩略图上，图片使用 `object-fit: contain` 完整显示；图片阶段优先显示当前图片候选，视频阶段优先显示当前视频候选并回退到已采用图片和原关键帧。缩略图失败时必须继续回退或显示稳定占位，不显示浏览器破图。

## Account notifications

- 异步操作的完成、失败、余额不足等结果统一进入顶部账户消息中心，并用短暂 Toast 提醒；主工作区不重复放置大块状态卡。消息按账户隔离，前端只传业务跳转参数，不传账户 ID。
- 视频候选下载使用媒体右上角悬浮图标；模型、候选数量和预计／实际费用放在生成操作行或候选审核行内，避免单独占据整行。
- 通知深链必须在 React StrictMode 的 effect 重放下保持幂等；不要用会跨越 StrictMode 二次执行的一次性 ref 提前阻断项目或候选定位。
