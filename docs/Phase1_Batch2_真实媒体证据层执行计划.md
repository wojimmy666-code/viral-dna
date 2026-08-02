# ViralDNA Phase 1 Batch 2：真实媒体证据层执行计划

> 开始日期：2026-08-02
> 完成日期：2026-08-02
> 状态：核心实现与自动化验收完成
> 目标：让本地上传视频从固定模拟报告切换为真实 FFmpeg 媒体证据报告
>
> 后续状态：平台链接真实采集已在 [Batch 2.5](./Phase1_Batch2.5_链接采集层执行与验收.md) 完成；本文保留 Batch 2 当时的交付边界和验收记录。

## 1. 本批交付边界

本批只处理可以客观测量的媒体事实：

- 文件哈希、容器、编码、时长、分辨率、帧率、码率和音轨。
- H.264/AAC 分析代理视频。
- 16 kHz 单声道 WAV 音频。
- 基于画面变化的真实镜头边界。
- 每个镜头的代表关键帧与 Contact Sheet。
- 可持久化的视频、任务和报告记录。
- 前端可播放代理视频、查看真实分镜时间线和关键帧。

本批不输出人物、服装、场景语义，不执行 ASR、OCR、VLM、爆点推理或最终复刻 Prompt。相关字段必须明确标记为“待模型分析”，不能复用模拟早餐数据。

## 2. 处理流水线

```text
上传文件
  → SHA-256
  → ffprobe 媒体探测
  → FFmpeg H.264/AAC 代理
  → 可选 WAV 音频抽取
  → scene score 镜头边界检测
  → 镜头中点关键帧
  → Contact Sheet
  → media.json / shots.json
  → media_evidence 报告
```

## 3. 产物目录

```text
storage/
  viral_dna.db
  uploads/{video_id}/source.ext
  analyses/{analysis_id}/
    proxy.mp4
    audio.wav
    contact-sheet.jpg
    manifest.json
    shots/
      shot_001.jpg
      shot_002.jpg
```

所有对外访问通过受限的 artifact API，数据库和绝对磁盘路径不返回给浏览器。

## 4. 数据契约

### MediaMetadata

- `duration_seconds`
- `width` / `height` / `rotation`
- `fps`
- `format_name`
- `video_codec` / `audio_codec`
- `has_audio`
- `size_bytes` / `bit_rate`
- `sha256`
- `aspect_ratio`

### ShotEvidence

- `shot_id` / `index`
- `start_seconds` / `end_seconds`
- `duration_seconds`
- `representative_timestamp`
- `keyframe_url`
- `detection_method`

### 分析模式

- `simulated`：链接示例和旧演示报告。
- `media_evidence`：真实媒体事实，语义模型尚未执行。
- `model`：后续 ASR/OCR/VLM/LLM 完整分析。

## 5. 安全与失败处理

- 继续限制 MP4、MOV、WebM 和 500 MB。
- ffprobe 必须确认存在视频流、有效时长和合法尺寸。
- 首版真实处理限制为最长 5 分钟。
- 所有 FFmpeg 调用使用参数数组，不经过 shell 拼接。
- 每个子进程有超时并截断错误输出。
- artifact 路径解析后必须仍位于所属分析目录。
- 失败任务写入错误代码、可读错误和是否可重试。

## 6. 验收标准

1. 上传一条真实视频后，报告时长、尺寸、帧率与 ffprobe 一致。
2. 报告分镜数量和时间来自 FFmpeg scene detection，而不是固定五镜头模板。
3. 每个镜头至少存在一张可访问的关键帧。
4. 前端可以播放代理视频并点击分镜跳转。
5. 无音轨视频不会生成伪音频，也不会失败。
6. 服务重启后视频、任务和报告仍可读取。
7. 链接示例仍明确显示“模拟分析”。
8. `media_evidence` 报告不展示虚构爆点评分、人物实体和最终 Prompt。

## 7. 后续 Batch 3 接口

Batch 3 直接消费本批产物：

- ASR 输入 `audio.wav`。
- OCR 输入关键帧和自适应补充帧。
- VLM 输入镜头 Contact Sheet、ASR、OCR 和相邻镜头摘要。

## 8. 执行结果

已完成：

- 上传文件通过混合分析流水线进入真实媒体处理；链接输入保留为明确标识的模拟模式。
- 新增 ffprobe、代理转码、音频提取、scene score、关键帧、Contact Sheet 和 manifest。
- 新增 SQLite JSON 持久化，保留上传文件绝对路径但不向 API 响应暴露。
- 新增受限 artifact API，路径解析后必须位于所属分析目录。
- 前端可播放真实代理视频、展示媒体元数据、哈希、分镜时间线和关键帧。
- `media_evidence` 模式隐藏爆点、元素替换和最终 Prompt，避免展示未执行的模型结果。
- Windows 启动脚本已统一使用 Web 4174 和 API 8000。

自动化验收：

- Ruff 格式检查和静态检查通过。
- API 全量测试 7 项通过。
- 合成双场景视频端到端测试通过，覆盖上传、任务轮询、媒体元数据、至少两个镜头、代理视频、关键帧和 manifest。
- SQLite 重启持久化测试通过。
- Vite 生产构建通过。
- Sites Worker 测试 4 项通过。
- `scripts/start.bat --no-browser` 启动验收通过：API 8000、Web 4174 和 `/health` 均正常。
- 浏览器首屏、文件模式切换及运行日志检查通过，未发现 ViralDNA 自身控制台错误。

人工验收限制：

- Chrome 扩展未开启“Allow access to file URLs”，因此浏览器自动化无法把本地合成视频写入文件选择器。
- 该限制属于浏览器扩展权限；同一上传与真实分析流程已由 FastAPI 端到端测试实际执行并通过。

## 9. 已知边界

- 任务仍由 API 进程内的异步任务执行，服务重启时正在运行的任务不会自动恢复。
- 本批交付时抖音和小红书链接只建立记录并生成模拟报告；该限制已由后续 Batch 2.5 解除。
- ASR、OCR、VLM、爆点推理、Seedance Prompt 和真实元素替换尚未执行。
- 爆点 LLM 只消费带时间戳的事实证据。
