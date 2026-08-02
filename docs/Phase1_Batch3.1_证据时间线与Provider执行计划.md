# ViralDNA Phase 1 Batch 3.1：证据时间线与 Provider 执行计划

> 开始日期：2026-08-02
> 状态：证据时间线与 Provider 骨架完成；真实 Provider 已在 Batch 3.2 接入
> 目标：在真实媒体分镜和后续 VLM/爆点推理之间建立可验证、可替换 Provider 的 ASR/OCR 证据时间线

## 1. 为什么先做证据时间线

现有流水线已经能稳定获得源视频、代理视频、16 kHz 音频、镜头边界和关键帧，但报告里的对白、OCR、主体、爆点和真实复刻提示词仍为空。不能直接让大模型一次性观看整段视频并自由输出报告，否则难以定位证据、校验时间戳、控制成本和替换模型。

本批先把语音、画面文字和镜头边界对齐成统一事实层。下一批 VLM、实体归并、爆点 LLM 和 Prompt 编译只消费这层结构化证据。

## 2. 处理链路

```text
source video
  → FFmpeg proxy / audio.wav / shot keyframes
  → ASR Provider → transcript segments + word timestamps
  → OCR Provider → timestamped text observations
  → timeline alignment
  → timeline.json
  → AnalysisReport.evidence_timeline
  → per-shot dialogue / ocr_text
  → VLM facts（下一批）
```

## 3. 数据契约

### 3.1 Provider 运行记录

每个 Provider 必须记录：

- 类型：`asr` 或 `ocr`
- Provider 和模型标识
- 状态：`completed`、`skipped`、`unavailable` 或 `failed`
- 输出条数与耗时
- 不包含密钥和敏感请求内容的状态说明

Provider 未配置时必须返回 `skipped`，不能用占位文本伪装识别结果。配置了未安装的 Provider 时返回 `unavailable`，媒体证据报告仍可完成。

### 3.2 转写片段

```json
{
  "id": "asr_001",
  "start_seconds": 1.2,
  "end_seconds": 4.8,
  "text": "今天测试一个新的 AI 工作台",
  "language": "zh",
  "confidence": 0.94,
  "words": []
}
```

### 3.3 OCR 观察

```json
{
  "id": "ocr_001",
  "timestamp_seconds": 2.7,
  "text": "一段提示词去掉 AI 味",
  "confidence": 0.91,
  "shot_id": "shot_001",
  "frame_url": "/api/v1/analyses/.../artifacts/shots/shot_001.jpg"
}
```

### 3.4 镜头对齐

每个镜头保存命中的转写和 OCR ID，同时生成去空白、去重复后的 `transcript_text` 与 `ocr_text`。跨越镜头边界的转写片段可以同时关联两个镜头，不裁剪或篡改原始证据。

## 4. Provider 边界

首个切片先完成稳定接口和降级行为，不把重型模型库设为 API 的强制依赖。本机当前没有 `faster-whisper`、PaddleOCR、Torch 或 Tesseract，因此默认 Provider 为 `disabled`。

后续 Provider 可以独立接入：

- 本地 ASR：`faster-whisper`
- 本地中文 OCR：PaddleOCR
- 云端多模态 Provider
- 测试与评测 Fake Provider

环境变量预留：

```dotenv
VIRAL_DNA_ASR_PROVIDER=disabled
VIRAL_DNA_ASR_MODEL=
VIRAL_DNA_OCR_PROVIDER=disabled
VIRAL_DNA_OCR_MODEL=
```

API Key 只能放入被 Git 忽略的 `.env.local` 或进程环境，不能写入日志、报告、产物或数据库。

## 5. 失败与降级

- 没有音轨或用户关闭音频：ASR 为 `skipped`。
- 用户关闭 OCR：OCR 为 `skipped`。
- Provider 未配置：生成空证据时间线并明确标注 `skipped`。
- Provider 已配置但依赖不可用：标注 `unavailable`，保留媒体报告。
- Provider 调用异常：标注 `failed`，错误信息脱敏后进入运行记录。
- 时间戳越界：丢弃该条结果并计入校验错误，不污染镜头报告。

## 6. 本批验收

- [x] 报告 Schema 向后兼容，模拟报告和旧 SQLite JSON 仍可读取。
- [x] 每次真实媒体分析都生成 `timeline.json`。
- [x] 时间线包含与媒体分镜一一对应的镜头记录。
- [x] Fake ASR/OCR Provider 能把结果正确对齐到多个镜头。
- [x] Provider 未配置时任务正常完成且状态可解释。
- [x] 报告逐镜头 `dialogue` 和 `ocr_text` 来自真实 Provider 输出，不使用模拟文案。
- [x] API 测试和 Ruff 通过；前端保持向后兼容。

## 7. 下一批

Batch 3.2 已接入 faster-whisper、RapidOCR 和 FFmpeg 文本字幕轨。逐镜头 VLM 顺延到 Batch 3.3，提取人物、服装、动作、场景、产品、道具、镜头语言、灯光、色彩和转场，并保留关键帧与时间戳证据。
