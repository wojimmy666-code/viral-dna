# Phase 2 Batch 4.2：图片生成双模式执行与验收

更新时间：2026-08-06

阶段状态：Batch 4.2.1～4.2.4 工程实现与自动化验证已完成。真实百炼／ImageGen 出图会产生平台费用或消耗订阅配额，仍保留为用户明确触发的人工验收，不在自动测试中执行。

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
                    ▲
                    │
       持久化队列 + 后台 Worker
     queued/running/cancel/retry/recovery
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
- `POST /api/v1/generation-runs/{run_id}/cancel`
- `POST /api/v1/generation-runs/{run_id}/retry`

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
- `local_concurrency` 同时使用进程内信号量和工作区文件槽位锁，多个 API worker 共享并发上限，避免同时启动过多本机生成进程。
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

可选 VLM 语义质检已接入，但默认关闭：

- 设置页可启用“生成后使用 VLM 做语义质检”；
- 每张候选连同原关键帧、已绑定参考资产和结构化检查项发送到模型网关；
- 输出人物身份、产品形态、服装、场景、异常文字、证据、置信度和总体状态；
- 调用前执行剩余预算门禁，调用后把 Token、请求 ID、预计费用和实际费用并入本次 GenerationRun；
- `warning`、`uncertain` 和 `passed` 只作为人工审核证据，任何置信度都不会自动采用、淘汰或审批候选；
- 质检费用独立于图片生成费用归集，预算不足时明确记录 `skipped_budget`，不会把未执行误报为通过。

## 8. 成本与失败语义

- Remote API：生成前显示目录估算，完成后记录 Provider 报告或配置单价。
- Local Tool：按工具返回或用户配置记录；unknown 只显示“成本未知”；`subscription_quota` 显示“使用订阅配额”，金额不写成 ¥0。
- 失败或阻止的 run 不产生已完成候选，工作台保留错误码和简体中文错误说明。
- 新一轮生成会归档旧轮次的 ready/selected 候选，避免把旧图片误认为本轮结果。
- 缓存命中费用为 0，但保留原始付费 run 和来源关系，审计信息不会丢失。

Batch 4.2.4 进一步统一任务状态：

- 创建图片任务先持久化 `queued` 并返回 HTTP 202，前端按 run ID 轮询，不再长时间占用创建请求；
- Worker 通过 SQLite 原子 claim 把 `queued` 改为 `running`，同一任务不会被多个进程重复执行；
- 运行期间保存开始时间、更新时间、心跳、请求快照和不可变 `queue.json`；
- 用户可以显式取消 queued／running 任务；本机工具回收进程树，Provider 不支持远端取消时也不会自动重发；
- 失败或取消任务可人工重试，新 run 保存 `retry_of_run_id` 和递增 `retry_count`，原运行记录不覆盖；
- API 启动时重新排队尚未执行的 queued 任务，把未知外部状态的 running 标记为 `generation_interrupted`，禁止盲目重复计费；
- 重启前处于 `cancellation_requested` 的任务终结为 `cancelled`；
- 浏览器关闭、切换页面或重新打开方案不会丢失任务，工作台会恢复轮询和最终候选。

## 9. 自动化与浏览器验收

2026-08-06 最终验证结果：

- 后端全量测试：110 项通过；
- Ruff：`services/api` 全量通过；
- 异步任务、跨进程 claim／并发槽位、取消、重试、重启恢复和 VLM 成本专项测试通过；
- 前端测试：23 项通过；
- 前端生产构建：通过，Vite 完成 4578 个模块转换并生成 Sites 产物；
- Chrome 本地冒烟：Schema 4 工作区、资产库和模型设置正常加载，VLM 语义质检开关与费用说明可读取；
- 页面日志未发现 ViralDNA 应用错误；
- 自动化验证没有调用真实付费图片模型、真实 ImageGen 出图或真实云端存储。

## 10. Batch 4.2.4 完成范围

本切片完成：

1. 持久化 queued/running 后台任务与 HTTP 202；
2. 前端轮询、取消、失败重试和重新打开恢复；
3. SQLite 原子 claim、同工作区多进程本机并发槽位和重复执行保护；
4. queued／running／cancellation_requested 的启动恢复策略；
5. 本机工具取消与进程树回收；
6. 可选 VLM 语义质检、预算门禁、结构化证据和费用归集；
7. 任务 lineage、不可变请求快照、候选缓存和人工审批门禁；
8. 全量自动化、静态检查、生产构建和无费用浏览器冒烟。

## 11. 必须由人工明确触发的验收

以下不是工程缺口，而是为了控制费用和外部副作用而保留的人工步骤：

1. 使用真实 Codex + ImageGen 生成一个单镜头候选，确认当前订阅、模型可用性、参考图传递和输出目录；
2. 使用真实百炼模型生成一个单镜头候选，确认当前账号区域、模型权限、实际费用和下载域名；
3. 启用 VLM 质检生成一个候选，核对额外 Token 和费用是否符合百炼账单；
4. 单镜头通过后再执行目标四分镜双模式验收，避免一次性扩大成本；
5. 真实测试前设置项目预算上限，测试后检查项目实际费用、run 明细和平台账单。

完整操作步骤见 `docs/Phase2_Batch4.4.4_4.4.5与4.2.4_人工验收.md`。

## 12. 仍不属于 Batch 4.2 的能力

- Provider 原生服务端任务取消：仅当具体 Provider 提供稳定取消 API 时再由 Adapter 实现；当前取消保证 ViralDNA 不继续采用结果或自动重发；
- 独立 Redis／消息队列和跨多台服务器的分布式调度；当前保证同一个本地工作区的 SQLite 原子 claim 和本机进程并发安全；
- 自动批准或自动淘汰图片候选；VLM 始终是人工审核证据；
- 真实云端文件同步、团队协作和账号权限；
- 分段视频生成、剪辑与成片导出，属于 Batch 4.5 及后续。

Batch 4.2 至此完成工程收尾。真实模型冒烟的通过与否应记录为环境／账号验收结果，不改变本批代码完成状态。
