# ViralDNA Phase 1 Batch 3.3：VLM 网关、模型计费与逐镜头视觉理解

> 开始日期：2026-08-02
> 状态：基础实现完成，真实百炼样本待验收
> 主模型：阿里云百炼 `qwen3.7-plus-2026-05-26`
> 范围：模型可切换底座、调用成本账本、逐镜头视觉事实；全局实体归并与爆点推理在底座验收后继续

## 1. 本批目标

在已有链接采集、FFmpeg 分镜、faster-whisper ASR、RapidOCR 和字幕时间线之上，接入第一条真实 VLM 链路，同时保证：

1. 分析流水线不直接依赖任何厂商 SDK 或模型 ID。
2. 新分析任务冻结模型、Prompt、Schema 和价格版本，运行中配置变化不会污染结果。
3. 每一次模型请求都保存 Token、耗时、重试、价格快照和成本。
4. 没有 API Key、供应商不可用或模型失败时，媒体证据报告仍然可以完成，并明确标注降级原因。
5. 同一视频可以保存多个分析版本，不再只按 `video_id` 覆盖最后一份报告。

## 2. 非目标

- 本批不调用 Seedance 或其他视频生成模型。
- 不分析账号或作者历史内容。
- 不根据临时促销和免费额度改变历史成本。
- 不允许客户端传入任意厂商模型 ID。
- 不在第一条真实调用里让 VLM 同时自由生成完整报告；先只提取可验证的逐镜头视觉事实。

## 3. 分层架构

```text
HybridAnalysisPipeline
  -> ShotFactsService
      -> ModelRouter
          -> ModelCatalog + frozen ModelPlanSnapshot
          -> StructuredModelProvider
              -> DashScopeProvider
              -> VolcengineProvider (future)
          -> ModelRunLedger
              -> PriceSnapshot
              -> AnalysisCostSummary
```

业务层使用任务类型，而不是模型名：

- `shot_facts`
- `entity_resolution`
- `viral_reasoning`
- `prompt_generation`

`Video.target_model=seedance` 只表示输出 Prompt 的目标视频模型；分析侧模型由 `AnalysisJob.model_plan` 独立控制。

## 4. 模型计划与切换规则

客户端通过“模型与设置”选择有限、受服务端目录约束的配置：

- Provider：当前为 `dashscope`
- 主模型：`auto`、`qwen37` 或 `qwen36flash`
- 分析档位：`quality`、`balanced` 或 `economy`

`auto` 按档位使用模型目录的默认顺序；手动模型会成为每个任务的首选目标，并保留目录内的合法回退目标。客户端不能提交任意厂商模型 ID。

服务端模型目录将档位和任务映射为有序目标列表。创建分析任务时解析并保存不可变的 `ModelPlanSnapshot`，包括：

- Provider
- 请求模型 ID
- 固定模型快照
- 地域和 API Base URL 标识
- 思考模式
- Prompt 版本
- 输出 Schema 版本
- 路由版本
- 价格目录版本

模型回退只发生在明确可重试的网络错误、限流、供应商故障或 Schema 校验失败后。每一次尝试单独记账，不能用最终成功结果覆盖失败调用。

## 5. Provider 契约

```python
class StructuredModelProvider(Protocol):
    async def generate(
        self,
        request: ModelRequest,
        response_schema: type[T],
    ) -> ModelResult[T]: ...
```

Provider 适配器负责：

- 把文本和本地关键帧转换为厂商请求格式。
- 关闭思考模式并请求 JSON 输出。
- 解析并归一化返回的 Token、请求 ID、模型快照和错误。
- 使用 Pydantic 校验业务 Schema。
- 对日志、异常和原始响应引用进行脱敏。

Provider 适配器不负责实体归并、爆点判断或 Seedance Prompt 业务规则。

## 6. 逐镜头视觉事实 Schema

首个 VLM 任务只输出客观可观察事实：

```json
{
  "title": "镜头简短标题",
  "subjects": ["人物或主体描述"],
  "action": "主体动作与时序",
  "scene": "地点、背景和环境",
  "camera": "景别、机位、运动和焦段观感",
  "composition": "主体位置、前中后景和视觉重心",
  "lighting": "光向、软硬、色温和对比度",
  "color": "主色、辅色、饱和度和整体色调",
  "transition": "入镜、出镜或与上一镜头的转场",
  "narrative_role": "该镜头承担的信息功能",
  "replication_prompt": "不包含品牌猜测的复刻画面提示词",
  "confidence": 0.9
}
```

输入证据包含镜头开始/中间/结束帧、时间范围、ASR 对白、独立字幕和 OCR 文本。模型必须区分“画面可见事实”和“基于对白的推断”。

## 7. 成本账本

每一次请求保存一条 `ModelRun`：

- `analysis_id`、`video_id`、`task_type`、`shot_id`
- `provider`、`requested_model`、`resolved_model`
- `prompt_version`、`schema_version`、`request_fingerprint`
- `attempt`、`retry_of_run_id`、状态和错误码
- 输入、缓存输入、输出、推理和总 Token
- 图片数量、耗时和 Provider request ID
- `price_snapshot_id`
- 调用前估算成本、调用后实测成本

金额统一使用整数微元：`1 CNY = 1,000,000 micros`。计算过程使用 `Decimal`，不能使用二进制浮点金额。

成本状态分为：

- `estimated`：调用前估算
- `measured`：按 API `usage` 计算
- `reconciled`：未来与云账单核对

免费额度和临时促销不修改标准成本；可另存供应商结算成本。

## 8. 预算与缓存

创建任务可提交 `max_cost_cny`。服务端在每次调用前用保守的文本、视觉和输出 Token 估算检查累计预算；如果下一次调用会超过硬上限，则写入状态为 `blocked`、错误码为 `budget_exceeded` 的 `ModelRun`，停止后续模型调用并保留已完成镜头。最终成本始终以 Provider 返回的实际 `usage` 计算。

缓存指纹由以下字段组成：

```text
video sha256
+ shot time range
+ evidence frame sha256
+ ASR/OCR/subtitle hash
+ provider/model snapshot
+ prompt version
+ schema version
+ generation parameters
```

只有指纹完全一致才能复用。缓存命中不产生新的 Provider 成本，但必须保留来源 `ModelRun`。

## 9. 数据与 API 变化

新增或调整：

- `AnalysisCreate.analysis_profile`
- `AnalysisCreate.max_cost_cny`
- `AnalysisJob.model_plan`
- `AnalysisJob.estimated_cost_micros`
- `AnalysisJob.measured_cost_micros`
- `ModelRun`
- `PriceSnapshot`
- `AnalysisCostSummary`
- 报告按 `analysis_id` 保存，同时保留“某视频最新报告”的兼容查询

新增接口：

```text
GET /api/v1/analyses/{analysis_id}/report
GET /api/v1/analyses/{analysis_id}/cost
GET /api/v1/analyses/{analysis_id}/model-runs
```

旧接口 `GET /videos/{video_id}/report` 继续返回该视频最新完成报告。

## 10. 配置与密钥

模型目录和标准价格进入版本控制；用户通过 GUI 选择 Provider 和模型并填写 API Key：

1. `GET /api/v1/settings/model` 只返回模型目录、是否已配置密钥、脱敏后缀和最近验证时间。
2. `PUT /api/v1/settings/model` 使用 Pydantic `SecretStr` 接收密钥。
3. 后端只允许 DashScope 官方 HTTPS OpenAI 兼容地址，避免密钥被发送到任意 URL。
4. 后端执行一次 `max_tokens=1` 的最小连接请求；只有成功后才原子写入 `.env.local`。
5. API Key 不进入 `localStorage`、接口响应或应用日志；留空保存可沿用已验证密钥。

GUI 成功保存后生成或更新：

```dotenv
VIRAL_DNA_VLM_PROVIDER=dashscope
VIRAL_DNA_VLM_MODEL_ALIAS=auto
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VIRAL_DNA_MODEL_LAST_VALIDATED_AT=
```

配置同时更新当前 API 进程环境，因此新任务立即生效，无需重启。未来豆包使用独立的 `VOLCENGINE_ARK_API_KEY`，不能复用通用 `VIRAL_DNA_MODEL_API_KEY`。

## 11. 验收条件

- [x] Fake Provider 可在不联网的测试中返回结构化镜头事实。
- [x] 质量、均衡、经济档位可通过配置切换，业务服务无模型 ID 判断。
- [x] GUI 可读取 Provider/模型目录并提交 API Key 校验。
- [x] 无效 Key 不落盘；有效 Key 原子保存且接口不返回明文。
- [x] 非官方服务地址在发送密钥前被拒绝。
- [x] GUI 手动选择的模型成为新任务首选路由。
- [x] 分析任务保存冻结的模型计划。
- [x] 每次调用均产生可查询 `ModelRun` 和准确的微元成本，失败但返回 `usage` 的调用也会计费。
- [x] 价格档位、缓存 Token、失败重试和预算上限有单元测试。
- [x] 百炼未配置时真实媒体分析正常降级。
- [ ] 百炼配置后镜头字段来自真实 VLM，并标记 `evidence_kind=model`。
- [x] 报告可按 `analysis_id` 查询，旧视频报告接口保持兼容。
- [x] API 测试、Ruff 和 Web 构建通过。
- [ ] 使用真实抖音样本记录模型、Token、耗时和成本。

### 当前验收记录

- 后端 Ruff：通过。
- 后端测试：49 项通过，新增覆盖 GUI 配置 API、密钥原子保存、无效 Key 拒绝、服务地址白名单和模型首选路由。
- Web 生产构建：通过。
- Sites Worker 测试：4 项通过。
- `scripts/start.bat --no-browser`：通过，确认使用 API 8000、Web 4174。
- 真实百炼调用：未执行，不会在未明确配置和授权时产生付费请求。

## 12. 后续批次

底座与逐镜头事实验收后继续：

1. 全局人物、服装、场景、产品和道具归并。
2. 基于画面、对白、字幕、节奏和转场的爆点推理。
3. Prompt IR 与 Seedance Prompt 编译。
4. 元素替换后的差异化 Prompt。
5. 豆包视觉 Provider 和黄金样本 A/B 评测。
