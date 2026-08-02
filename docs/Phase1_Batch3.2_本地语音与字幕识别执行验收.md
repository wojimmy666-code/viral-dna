# ViralDNA Phase 1 Batch 3.2：本地语音与字幕识别执行验收

> 日期：2026-08-02
> 状态：已完成
> 范围：单视频真实对白、画面烧录字幕、独立字幕轨采集与逐镜头对齐

## 1. 本批交付

本批把 Batch 3.1 的 Provider 骨架升级为可执行的本地识别链路：

```text
audio.wav
  → faster-whisper CPU int8
  → 句级转写 + 词级时间戳

shot keyframes
  → RapidOCR + ONNX Runtime
  → 文字 + 置信度 + 归一化文本框

source video subtitle stream
  → ffprobe 探测
  → FFmpeg 转换为 SRT
  → 字幕 Cue

ASR + Subtitle Cue + OCR + Shot boundaries
  → phase1-evidence-timeline-v2
  → AnalysisReport 逐镜头 dialogue / subtitle_text / ocr_text
```

实现采用 [faster-whisper 官方项目](https://github.com/SYSTRAN/faster-whisper)建议的 CPU `int8` 与词级时间戳能力；OCR 使用 [RapidOCR 官方安装与使用文档](https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/install/)提供的统一 `rapidocr` 包和 ONNX Runtime；字幕轨由 [FFmpeg 官方文档](https://www.ffmpeg.org/ffmpeg.html)所述的 stream mapping 与字幕转码完成。

## 2. Provider 与降级边界

### 2.1 ASR

- Provider：`faster-whisper`
- 默认建议模型：`base`
- 执行设备：`cpu`
- 计算类型：`int8`
- 输出：语言、句级开始/结束时间、文本、句级置信度、词级时间戳与词置信度
- 缺少依赖时：Provider 状态为 `unavailable`，媒体任务仍完成
- 没有音轨或关闭音频时：状态为 `skipped`

### 2.2 画面 OCR

- Provider：`rapidocr`
- 默认模型标识：`pp-ocrv6-small`
- 执行后端：ONNX Runtime CPU
- 输入：逐镜头代表关键帧
- 输出：文字、置信度、归一化文本框、镜头 ID、帧 URL
- 默认最低置信度：`0.60`
- 连续同文案按时间窗口去重

### 2.3 独立字幕轨

- `ffprobe` 保存字幕流索引、编码、语言和标题
- `mov_text`、`subrip`、`ass`、`ssa`、`webvtt` 等文本轨转换为 SRT
- SRT 被解析为带开始/结束时间的 `SubtitleCue`
- 图像型字幕轨暂不做像素级字幕解码，状态明确标为不可用
- 没有独立字幕轨不代表没有字幕；社交平台常见烧录字幕由 OCR 识别

## 3. 本地配置

安装可选依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".\services\api[local-ai]"
```

在被 Git 忽略的 `.env.local` 中启用：

```dotenv
VIRAL_DNA_ASR_PROVIDER=faster-whisper
VIRAL_DNA_ASR_MODEL=base
VIRAL_DNA_ASR_DEVICE=cpu
VIRAL_DNA_ASR_COMPUTE_TYPE=int8
VIRAL_DNA_ASR_LANGUAGE=zh
VIRAL_DNA_ASR_MODEL_DIR=storage\models\faster-whisper
VIRAL_DNA_OCR_PROVIDER=rapidocr
VIRAL_DNA_OCR_MODEL=pp-ocrv6-small
VIRAL_DNA_OCR_MIN_CONFIDENCE=0.60
```

`scripts/start.bat` 会读取这些配置；若配置了本地 Provider 但依赖缺失，会安装 `local-ai` 可选依赖。Whisper 权重在第一次分析时下载，之后复用本地缓存。

## 4. 真实抖音样本验收

测试视频：

- 视频 ID：`e97f0c70-d5bd-46bc-bbee-29a8bf798648`
- 正式 API 分析 ID：`cb7020e9-4a25-4d10-bd05-8779fafa2362`
- 时长：55.8 秒
- 镜头：9 个
- 分析版本：`phase1-link-evidence-timeline-v2`

结果：

| 项目 | 结果 |
|---|---:|
| ASR 句级片段 | 41 |
| ASR 词级时间戳 | 311 |
| OCR 观察 | 164 |
| 有对白的镜头 | 9 / 9 |
| 有画面文字的镜头 | 9 / 9 |
| 独立字幕轨 | 0（该视频为画面烧录字幕） |
| 缓存后 ASR 耗时 | 约 12.7 秒 |
| OCR 耗时 | 约 29.9 秒 |

识别链路已验证为真实执行结果，不是模拟文案。`base` 模型对部分口音、繁简体和产品专有名词仍会误识别，可通过切换 `small` 或更大模型提高准确率。

## 5. 自动化验收

- [x] faster-whisper 返回值转换和词级时间戳测试
- [x] RapidOCR 置信度过滤与文本框归一化测试
- [x] Provider 环境变量工厂测试
- [x] SRT 解析、跨镜头字幕 Cue 对齐测试
- [x] 合成 `mov_text` 视频的 ffprobe 探测和 FFmpeg 抽取测试
- [x] API 媒体流程测试
- [x] Ruff 检查
- [x] Web 生产构建

## 6. 已知限制与下一批

1. 当前 OCR 每个镜头只使用一张代表关键帧，极短暂字幕可能漏检。后续应增加字幕区域的自适应多帧采样和跨帧聚合。
2. Whisper `base` 兼顾下载大小和 CPU 速度，但中文口音与专有名词精度有限；评测集需要比较 `base`、`small` 和云端 ASR。
3. OCR 会同时识别界面中的大量正文，不应把所有文字都当作对白；VLM 需要区分字幕、UI、品牌、贴纸和背景文字。
4. Batch 3.3 接入逐镜头 VLM，先提取可观察主体、服装、动作、场景、道具和镜头语言，再进入爆点推理。
