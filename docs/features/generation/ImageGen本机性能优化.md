# 本机 ImageGen 性能优化

> 现行功能说明 · 2026-09-09 整理。部署与首次使用见 [部署索引](../../deployment/README.md)；文中的历史验收记录保留原始时间和范围。

适用于 Skill 与分析报告创建视频的共用图片生成链路。

- 项目 Codex 子进程使用独立 OpenAI provider 别名，`supports_websockets=false`，直接 HTTPS；保留现有登录认证，不修改全局 Codex 配置。
- Codex 自动配置并发为 2，跨任务、跨进程共享槽位；超出部分排队。暂不自动升至 3，需真实批次验证无串图、异常率及排队情况后再调整。
- 默认调度推理强度为 `medium`，保留用户显式设置。仅精简调度说明，不裁剪全局/局部画面提示词、负向要求、参考图职责顺序、目标分辨率及候选张数，不替换图片模型。
- 包装器实时读取 Codex 事件，只从当前会话目录或当前事件明确返回的图片路径收集输出，不按全局时间戳猜图。完整解码校验后，原子发布 `progress.json`。
- 本地适配器约每 250 ms 检查进度；每张校验通过即保存稳定的候选 ID 和缩略图。页面沿用已有轮询，单分镜与批量任务均可在整个任务结束前显示图片。
- 逐张回传不更改提示词、项目修订或采用状态。终态结果复用候选 ID，保留用户期间的选择、采用或归档；失败/取消不删除已保存的图片，也不自动重复提交。
- 若开启语义质检，单张质检完成后发布；生成中断后保留的未质检图片标注人工检查。
- 一键批量仍固定每分镜 1 张，单分镜独立生成仍允许多张。

## 1.4：技能加载与出图后收尾

- 默认改用 Codex 本机 `app-server` 的 stdio 控制接口，仍使用现有账号与内置 ImageGen，不接入 Images API。stdio 是宿主与子进程的通信方式，模型请求仍使用上面的 HTTPS provider。
- 先通过 `skills/list` 定位唯一启用的系统 ImageGen 技能，再以显式 `skill` 输入随提示词提交，让 Codex 原生注入技能内容，不再要求模型用 PowerShell 读取 `SKILL.md`。未找到技能时，在生成前报错。该输入方式与取消接口参照 [Codex app-server 文档](https://learn.chatgpt.com/docs/app-server)。
- 每次使用独立临时线程，显式保持指定模型、推理强度、HTTPS provider、工作区沙箱和 `approvalPolicy=never`；不修改全局配置或认证，不自动批准交互权限请求。并发仍为 2，不在此次调整到 3。
- 只有收到当前线程图片工具的明确完成事件、全部所需图片通过路径与完整解码校验、且没有其他进行中的工具时，才请求结束后续收尾。等待 Codex 确认回合结束，再清理本次拥有的子进程，之后才释放并发槽位。
- 不凭“磁盘出现文件”结束任务。图片还未写完整、只完成部分图片、有其他工具运行或缺少完成事件时，继续等待；缺少图片工具事件则沿用正常回合结束路径。失败不自动重新提交，已经发布的图片继续保留。
- 保留手动 `--codex-runner exec` 兼容入口，失败时不会自动切换入口重试。旧入口的 `--json` 事件能力见 [Codex 非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)。

## 分段计时

每个实际生成任务在自己的运行目录保存两份记录，并在任务结果的 `execution_summary` 中回传；失败任务也保留已记录的阶段。

| 记录 | 内容 |
| --- | --- |
| `gateway-timing.json` / `execution_summary.timing` | 输入准备、适配器检测、并发排队、适配器执行、首次候选落库、候选发布、可选语义质检、总耗时 |
| `tool-output/timing.json` / `execution_summary.codex_timing` | Codex 版本检查、进程启动、服务初始化、技能定位、临时线程准备、任务提交、图片工具起止、逐张图片发布、回合结束和进程清理 |

`skill_discovery_ms` 只表示定位技能，不冒充模型加载耗时；原生技能注入随 `skill_input_submitted` 提交，不能独立观测的时间不单列。图片工具耗时按工具 ID 配对记录；没有工具事件的阶段为 `null`，不将整段请求耗时算作纯绘图耗时。网关执行时间包含其内部子阶段，不能把所有字段直接相加。

无出图预检（只初始化服务、定位技能、检查临时线程配置，不提交生成回合）：

```powershell
.\.venv\Scripts\python.exe scripts/codex_imagegen_adapter.py --codex-executable '<本机 codex.exe 路径>' preflight-runtime --cwd 'D:\Projects\ViralDna\tmp' --timeout 30
```

本机 Codex 0.153.4 的三次预检约 0.6–1.1 秒，包含实际任务的 Windows 长路径目录；这不是实际出图测速。验证使用模拟 Codex/图片工具，不消费图片额度。实际加速比例仍需下一批真实出图确认，不承诺固定倍速。

回归入口：`test_imagegen_runtime.py`、`test_image_streaming.py`、`test_image_generation.py`、`test_generation_jobs.py`、`test_image_batches.py`、`test_process_slots.py`、前端 `image-batch-ui.test.mjs` 与 `creation-workspace-runtime.test.mjs`。运行时用例覆盖完整出图、部分出图、未写完文件、跨线程文件、其他工具未结束、正常结束回退、延迟退出、技能缺失、错误模型/沙箱及拒绝临时权限请求。
