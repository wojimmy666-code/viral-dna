# Phase 2 Batch 4.2：图片生成双模式执行与验收

更新时间：2026-08-04

阶段状态：Batch 4.2.1～4.2.3 已实现；Batch 4.2.4 已完成统一候选 UI、缓存和基础质量检查，持久化后台任务、显式取消与 VLM 语义质检仍待完成，因此本文件暂不把 Batch 4.2 标记为全部完成。

## 1. 本批目标

在不改变 ShotPlan、参考资产、候选选择、人工审批和工作流门禁的前提下，让分镜图片生成支持两种可切换执行模式：

1. `remote_api`：首批调用阿里云百炼 DashScope 的 Qwen Image。
2. `local_tool`：调用本机已安装并完成授权的任意 CLI／包装器，不把业务层绑定到 Codex 或某个厂商内部接口。

两种模式必须共用输入快照、请求指纹、候选文件、成本台账、人工审批和版本历史。API Key 不得进入 GenerationRun、日志、Revision 或导出文件。

## 2. 已实现架构

~~~text
ShotPlan + 原关键帧 + ReferenceBinding
                    │
                    ▼
          ImageGenerationGateway
             │             │
             │             └── local_tool
             │                 版本化 request.json / result.json
             └── remote_api
                 DashScope Qwen Image Adapter
                    │
                    ▼
      GenerationRun + GenerationCandidate
                    │
                    ▼
           选择 → 人工确认 → 门禁
~~~

业务层只识别统一能力模型和执行模式，不判断模型 ID、可执行文件路径或厂商私有字段。Adapter 冻结 provider、model snapshot、adapter/protocol version、能力快照、成本来源和执行摘要，保证后续可以增加其他国内平台。

## 3. Batch 4.2.1：Gateway、配置与 GUI

已完成：

- 新增统一 ImageGenerationGateway、AdapterRequest、AdapterResult、GeneratedImage 和能力快照。
- 新增图片模型目录及版本化价格快照，首批模型为 `qwen-image-2.0` 和 `qwen-image-2.0-pro`。
- “模型与设置”支持“国内大模型 API／本机工具”切换。
- 国内模式可设置区域 Endpoint、模型、API Key 和默认候选数；保存时执行认证校验，密钥只写本机 `.env.local`，响应只返回掩码提示。
- 本机模式可设置 Adapter、可执行文件、固定参数、超时、并发上限、协议版本和成本来源，并支持“检测工具”。
- GUI 显示模型能力、预计单次成本、已配置状态和未知成本警告。
- 分镜工作台根据当前设置动态显示执行模式、模型／工具、候选数量、预计或未知成本和最近一次运行状态。

相关 API：

- `GET /api/v1/settings/image-generation`
- `PUT /api/v1/settings/image-generation`
- `POST /api/v1/settings/image-generation/detect-local`
- `POST /api/v1/settings/image-generation/discover-local-codex`
- `POST /api/v1/settings/image-generation/auto-configure-codex`
- `POST /api/v1/production-shots/{shot_plan_id}/image-runs`
- `GET /api/v1/generation-runs/{run_id}`

## 4. Batch 4.2.2：国内 Remote Adapter

已完成：

- 使用 DashScope 官方 HTTPS Endpoint 和 Bearer API Key。
- 将原关键帧作为基础编辑图，并按 identity、product、scene、wardrobe、style、layout 编译多参考输入。
- 自动把项目目标尺寸约束到模型能力范围；提示词、负面提示词和输入哈希写入不可变快照。
- 对认证失败、限流、服务繁忙、超时、内容安全和下载失败进行错误标准化；仅对可重试错误执行有限重试。
- 下载生成结果时限制目标域名、媒体类型、响应体积和重定向，重新解码图片并计算本地 SHA-256。
- 调用前按模型价格快照做预算门禁，调用后优先使用 Provider 返回费用，否则使用冻结单价。

尚未执行真实付费图片冒烟测试。当前自动化测试使用 MockTransport 验证请求、返回解析、图片下载和费用记录，不会产生平台费用。

## 5. Batch 4.2.3：本机工具 Adapter

已完成版本化协议：

~~~text
<executable> <fixed-args> capabilities
<executable> <fixed-args> generate --request <request.json> --output <output-dir>
~~~

安全边界：

- 不通过 shell 拼接命令，参数始终以数组传入。
- 可执行文件必须是绝对路径；固定参数拒绝换行、控制字符和危险占位符。
- 原图和参考图复制到本次 run 的隔离输入目录，CLI 只接收本次任务目录。
- 候选只能来自指定输出目录，拒绝绝对路径、目录穿越、符号链接越界、超大文件、错误文件头、尺寸或哈希不一致。
- 支持执行超时、Windows 进程树回收、退出码和截断后的标准错误。
- `local_concurrency` 已在单 API 进程内使用信号量落实，避免同时启动过多本机生成进程。
- 成本来源支持 `provider_reported`、`configured_rate`、`unmetered`、`subscription_quota` 和 `unknown`；unknown 必须逐次人工确认，不能伪装为零费用；订阅配额不记作 ¥0，也不重复弹未知金额确认。

自动化测试使用假 CLI 完成能力检测、双候选生成、协议校验、文件落盘和未知成本门禁。

### 5.1 Codex + ImageGen 自动发现与包装器

已新增首套内置本机包装器 `scripts/codex_imagegen_adapter.py`，但业务 Gateway 仍只依赖通用 JSON 协议：

- 设置弹窗打开后自动执行无费用环境发现，并支持手动重新检测。
- 检查 Codex CLI 的绝对可执行路径、版本、登录状态、ChatGPT／Codex 桌面端和本机 `imagegen` 技能；发现过程不会提交提示词，也不会调用模型。
- 支持 `latest_flagship`、`balanced`、`pinned` 三种模型策略。版本化模型目录 `openai-model-guidance-2026-08-04` 当前把最新旗舰解析为 `gpt-5.6-sol`，均衡模型解析为 `gpt-5.6-terra`。
- 默认推理强度为 `xhigh`；GUI 可显式降为 high、medium 或 low。
- “应用推荐配置”会立即保存包装器、Codex CLI 路径、模型策略、协议、20 分钟超时、单并发和 `subscription_quota` 成本口径。
- 包装器把原关键帧、修改后的分镜提示词和多张人物／产品／服装／场景参考图交给 Codex CLI 的 `$imagegen` 工作流，候选仍回写统一 `result.json`，后续人工选择和审批流程不变。
- 能力检测只执行 `codex --version`，不会进行真实生成。设置中明确保留“已安装，待首次出图验证”状态，避免把安装检测误报为模型可用。

自动化测试已使用假 Codex 完整验证包装器命令、输入图片、候选落盘、哈希和订阅配额用量结构。真实 ImageGen 冒烟仍须由用户明确触发。

## 6. 缓存与重复计费保护

本轮新增可验证缓存复用：

- 请求指纹只包含会影响输出的稳定字段：执行模式、Provider／模型／Adapter／协议和能力快照、输出尺寸、候选数、编译提示词、原图哈希、参考图角色与哈希、权重和锁定项。
- project_id、shot_plan_id、revision_id、工作区相对路径和当前价格不进入稳定指纹，避免仅保存新 Revision 就导致相同请求重复付费。
- 缓存只在同一项目同一分镜中复用 completed/cached 运行。
- 命中前重新检查候选正文、元数据、缩略图和 SHA-256；任一文件缺失或变化即视为未命中并正常重新生成。
- 命中后创建新的 GenerationRun 和候选记录供当前 Revision 审核，但复用不可变媒体文件；状态为 `cached`，预计和实际费用均为 0，并记录来源 run ID。
- 缓存判断早于预算门禁和 unknown 成本确认，因此真正的缓存命中不会被错误阻止，也不会要求再次接受未知费用。

## 7. 候选质量检查

已完成自动检查：

- 文件可解码、图片像素上限、标准化 JPEG 输出、WebP 缩略图和 SHA-256。
- 实际宽高、目标宽高、画幅误差和像素比例检查；画幅偏差超过 3% 或像素数低于目标 25% 时写入 warning。
- 每个候选保存版本化 `quality_report`，工作台显示“基础质检通过／尺寸有提示／未自动质检”，同时始终保留人工确认。

当前不会虚假声称已经自动判断语义一致性。人物身份、产品形态、服装、场景和异常文字根据参考角色列为人工核对项；接入 VLM 自动复核后，仍由人工做最终确认。

## 8. 成本与失败语义

- Remote API：生成前显示目录估算，完成后记录 Provider 报告或配置单价。
- Local Tool：按工具返回或用户配置记录；unknown 只显示“成本未知”；`subscription_quota` 显示“使用订阅配额”，金额不写成 ¥0。
- 失败或阻止的 run 不产生已完成候选，工作台保留错误码和简体中文错误说明。
- 新一轮生成会归档旧轮次的 ready/selected 候选，避免把旧图片误认为本轮结果。
- 缓存命中费用为 0，但保留原始付费 run 和来源关系，审计信息不会丢失。

## 9. 自动化与浏览器验收

2026-08-04 验证结果：

- 后端全量测试：80 项通过。
- Ruff：`services/api/src` 与 `services/api/tests` 全量通过。
- 图片生成与生产 API 针对性测试：11 项通过。
- 前端测试：15 项通过。
- 前端生产构建：通过，Vite 完成 4575 个模块转换并生成 Sites 产物。
- Chrome 桌面验收：模型设置双模式字段、能力与费用提示、分镜工作台运行状态和候选区域均可读取。
- Codex 自动配置 GUI 验收：实际显示 `codex-cli 0.146.0`、已登录、桌面端已安装、ImageGen“待首次出图验证”、`gpt-5.6-sol` 和 `xhigh`；未点击应用配置，页面无控制台错误。
- 560×820 视口验收：设置弹窗无横向溢出，模式卡片自动切换为单列，内容区可纵向滚动。
- 页面日志未发现 ViralDNA 应用错误；仅有浏览器扩展自身警告。

## 10. 尚未完成

以下内容仍属于 Batch 4.2，不应误报为已完成：

1. 持久化后台任务：当前 POST 仍等待 Adapter 返回，远端超时上限较长，生成期间 HTTP 请求会保持连接。
2. 显式取消：尚无 `POST /generation-runs/{id}/cancel`；远端 Provider 取消和本机进程即时取消均未形成统一协议。
3. 崩溃恢复：API 重启后 completed/failed/cached 可恢复，但 queued/running 任务还不能自动续跑或安全终止。
4. VLM 语义质检：人物一致性、产品形态和异常文字目前是明确的人工核对项，尚未调用 VLM 自动评分。
5. 双模式真实四分镜验收：Remote 尚未做付费四分镜测试；本机包装器已通过假 Codex 协议测试和真实安装发现，但尚未用真实 imagegen 完成样本出图。
6. 多进程全局并发：本机并发限制当前只覆盖单 API 进程；多 worker 部署需要数据库租约或外部队列。

## 11. 下一执行切片

建议按以下顺序完成 Batch 4.2.4：

1. 把 GenerationRun 改为先持久化 queued，再由后台执行器更新 running/completed/failed/cached；POST 返回 202 和 run ID，前端轮询。
2. 增加 cancellation_requested、cancelled 状态和取消 API；本机 Adapter 暴露进程句柄并回收进程树，远端仅在 Provider 支持时调用取消。
3. API 启动时扫描 queued/running：未发起远端请求的任务可重排队，未知外部状态的任务标记为可重试失败，禁止盲目重复计费。
4. 增加可选 VLM 候选质检任务，把人物、产品、服装、场景和文字异常输出为结构化证据、置信度和额外费用；低置信度不自动拒绝。
5. 先由用户在 GUI 明确触发一次 Codex + ImageGen 单镜头冒烟，确认订阅权限、实际输出目录和参考图一致性；Remote 也仅在明确授权后做单镜头付费冒烟，再扩展到目标四分镜。
6. 完成失败重试、取消、重启恢复、缓存缺失回退、预算并发竞争和四分镜双模式端到端测试后，再把 Batch 4.2 标记为完成。
