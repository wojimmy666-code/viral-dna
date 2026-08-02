# ViralDNA Phase 1 架构与接口设计

## 1. 架构决策

Phase 1 采用前后端分离的单仓库结构：

- Web：React、Vite、TypeScript/JavaScript 渐进迁移。
- API：Python、FastAPI、Pydantic。
- Worker：首轮为进程内模拟器，随后迁移到 Redis 队列和独立 Python Worker。
- 数据：首轮内存仓库，随后 PostgreSQL。
- 文件：首轮开发目录，随后 S3 兼容对象存储。

原长期方案推荐 Next.js。Phase 1 的核心页面是登录后的桌面 SPA，服务端渲染不是关键路径，因此首轮选择更轻的 Vite 前端。若后续增加官网、SEO、服务端鉴权或复杂 BFF，再评估迁移到 Next.js；API 和领域契约不受影响。

## 2. 逻辑架构

```text
Browser
  │
  ├─ React Workbench
  │    ├─ Import Flow
  │    ├─ Analysis Progress
  │    ├─ Report Workspace
  │    └─ Replacement Editor
  │
  └─ /api/v1
       │
       FastAPI
       ├─ Video Service
       ├─ Analysis Orchestrator
       ├─ Report Service
       ├─ Prompt Compiler
       └─ Replacement Service
              │
              Worker Pipeline
              ├─ Ingest
              ├─ Probe/Normalize
              ├─ Shots
              ├─ ASR/OCR
              ├─ VLM Facts
              ├─ Entity Resolution
              ├─ Viral Reasoning
              └─ Prompt QA
```

## 3. 分析状态机

```text
queued
  → ingesting
  → preprocessing
  → segmenting
  → transcribing
  → understanding
  → reasoning
  → compiling_prompts
  → validating
  → completed

任一阶段 → failed
failed → queued（显式重试）
```

每次状态更新包含：

- `stage`
- `progress`：0～100
- `message`
- `started_at`
- `updated_at`
- `error_code`
- `retryable`

## 4. 核心领域对象

### Video

- `id`
- `source_type`: upload/douyin/xiaohongshu
- `source_url`
- `original_filename`
- `status`
- `duration_seconds`
- `width`
- `height`
- `fps`
- `content_hash`
- `created_at`

### AnalysisJob

- `id`
- `video_id`
- `analysis_version`
- `stage`
- `progress`
- `message`
- `model_runs`
- `error`
- `created_at`
- `completed_at`

### Shot

- `id`
- `index`
- `start_seconds`
- `end_seconds`
- `keyframe_uri`
- `subjects`
- `action`
- `scene`
- `camera`
- `composition`
- `lighting`
- `color`
- `dialogue`
- `ocr_text`
- `audio`
- `transition`
- `narrative_role`
- `prompt`
- `confidence`

### Entity

- `id`: person_01、wardrobe_01、scene_01 等。
- `type`
- `name`
- `description`
- `attributes`
- `occurrence_shot_ids`
- `replaceable_fields`
- `reference_frame_ids`
- `confidence`

### ViralFinding

- `type`
- `score`
- `time_range`
- `observation`
- `mechanism`
- `expected_effect`
- `recommendation`
- `confidence`

### PromptPackage

- `id`
- `video_id`
- `version`
- `target_model`
- `format`
- `global_visual_bible`
- `entities`
- `continuity_locks`
- `shots`
- `negative_constraints`
- `created_at`

## 5. API 契约

所有业务接口使用 `/api/v1` 前缀。

### POST `/videos/link`

请求：

```json
{
  "url": "https://v.douyin.com/example",
  "title": "可选标题",
  "target_model": "seedance",
  "rights_confirmed": true
}
```

响应：`Video`。

约束：

- 只允许 HTTP/HTTPS。
- 只允许显式配置的平台域名。
- 不允许 localhost、内网地址和文件协议。
- 最多跟随有限次数重定向。
- 无法读取时返回可理解错误并提示文件上传。

### POST `/videos/upload`

`multipart/form-data`：

- `file`
- `title`
- `target_model`
- `rights_confirmed`

响应：`Video`。

### POST `/videos/{video_id}/analyses`

创建分析任务。相同视频哈希、分析版本和配置已存在完成结果时，可返回缓存任务。

### GET `/analyses/{analysis_id}`

返回任务当前阶段、进度和错误。

### GET `/analyses/{analysis_id}/events`

SSE 事件：

```text
event: progress
data: {"stage":"segmenting","progress":35,"message":"正在识别镜头边界"}
```

完成或失败后关闭连接。

### GET `/videos/{video_id}/report`

返回视频总览、分镜、实体、爆点结论和 Prompt Package。

### POST `/videos/{video_id}/replacement-versions`

请求：

```json
{
  "replacements": [
    {
      "entity_id": "person_01",
      "description": "35 岁中国男厨师，短发，沉稳气质"
    }
  ],
  "locks": ["timing", "camera", "composition", "action"]
}
```

响应包含新 Prompt Package、受影响镜头和字段差异。

## 6. Provider 接口

业务服务只能依赖内部 Provider 协议：

```python
class VideoUnderstandingProvider(Protocol):
    async def analyze_shot(self, request: ShotAnalysisRequest) -> ShotFacts: ...

class TextReasoningProvider(Protocol):
    async def analyze_viral_mechanics(self, evidence: EvidenceTimeline) -> ViralReport: ...

class PromptAdapter(Protocol):
    def compile(self, prompt_ir: PromptIR) -> CompiledPromptPackage: ...
```

Provider 返回结果必须带：

- 供应商和模型 ID。
- 模型版本或快照。
- 输入输出 Token。
- 调用耗时。
- 重试次数。
- 原始响应引用。
- Schema 版本。

## 7. 数据与版本策略

- 原始视频分析结果不可原地覆盖。
- 人工编辑和元素替换产生新版本。
- Prompt IR 和编译后的模型 Prompt 分开保存。
- `analysis_version` 由预处理版本、Schema 版本、Prompt 版本和模型配置组成。
- 模型升级必须跑黄金测试集，不能静默替换。

## 8. 安全要求

- 上传使用随机对象键，不使用原文件名作为路径。
- 使用 ffprobe 验证真实媒体类型。
- 限制文件大小、时长、分辨率和解压后资源。
- 链接解析防 SSRF、内网地址、重绑定和无限重定向。
- 模型 API Key 只存在服务端。
- 日志不记录完整签名 URL、Token 或敏感素材。
- 用户可删除视频、关键帧、字幕、报告和 Prompt 版本。
- 真人替换要求用户确认拥有授权。

## 9. 可观测性

每个分析任务记录：

- 总耗时和各阶段耗时。
- 每个 Provider 调用次数、Token 和估算费用。
- 缓存命中率。
- 失败阶段、错误码和重试次数。
- 视频时长与处理耗时比。
- Schema 校验失败率。

这些数据将用于选择模型、定价和定位质量退化。
