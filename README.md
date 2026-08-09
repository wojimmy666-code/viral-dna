# ViralDNA

ViralDNA 是一个面向短视频创作者和内容团队的 AI 单视频逆向拆解工作台。

第一阶段聚焦一个完整闭环：导入视频文件或公开链接，生成逐镜头拆解、爆点分析、元素清单、复刻提示词，以及人物/服装/场景替换后的新提示词。

## 仓库结构

```text
apps/web                 React + Vite 桌面端工作台
services/api             FastAPI 分析任务与报告 API
docs                     产品、架构、执行计划与 UI 参考
```

## 当前状态

当前已完成 Phase 1 单视频分析闭环，以及 Phase 2 Batch 4.6 的生成、剪辑、预览与最终导出链路：

- 视频文件流式上传，以及抖音/小红书公开视频真实下载。
- `yt-dlp` 平台解析、白名单校验、下载限制、错误码和可选显式 Cookie 文件。
- 上传或采集视频的 ffprobe 探测、SHA-256、H.264/AAC 代理和 WAV 音频。
- FFmpeg scene score 真实分镜、逐镜头关键帧、Contact Sheet 和 manifest。
- SQLite 持久化、分析状态机和受限的媒体产物 API。
- 链接任务使用真实 `media_evidence` 报告，不再默认回退模拟数据。
- faster-whisper 本地 ASR，输出句级和词级时间戳。
- RapidOCR 本地画面文字识别，以及 FFmpeg 独立文本字幕轨抽取。
- ASR、独立字幕、画面 OCR 和镜头边界统一写入 `timeline.json`。
- 每个镜头提取开始、中间、结束三张 VLM 证据帧。
- Provider 无关的模型目录、质量档位、冻结模型计划和百炼 `qwen3.7-plus` 适配器。
- 逐镜头主体、动作、场景、摄影、构图、灯光、色彩和复刻提示词。
- 模型调用 Token、价格快照、缓存、重试、预算上限和微元成本账本。
- 报告按 `analysis_id` 版本化，并提供成本和逐调用查询 API。
- 单视频报告工作台，以及真实媒体证据和模拟报告的明确区分。
- GUI 可指定和切换本地工作区，配置会在本机持久化。
- 视频源文件、分析产物、报告与导出文件按分析记录统一归档。
- 分析记录可搜索、按状态筛选、按一级目录归类、重命名并重复打开。
- 历史记录重复打开不触发模型；只有手动“重新分析”才创建新分析版本。
- 报告 JSON/Markdown、提示词包、替换版提示词包、转写和字幕由服务端归档后下载。
- 面向用户的报告与导出结果统一转换为简体中文，原始证据仍保留以便审计。
- Windows `scripts/start.bat` 一键启动 API 8000 和 Web 4174。
- 创作方案、参考资产、分镜图片和分段视频均可版本化保存并人工确认。
- 国内视频模型配置、逐分镜生成成本、候选审核和剪辑准备已接入。
- 已确认片段可进入受控时间线，调整顺序、启用状态、裁剪、时长、音量、字幕和基础转场。
- 时间线每次保存创建不可变快照，可查看历史并从旧版本恢复为新版本。
- FFmpeg 可生成带原音轨映射、字幕和基础转场的低清预览；任务进度与结果进入账户消息中心。
- 最终导出可冻结时间线版本，生成 720P、1080P 或方案尺寸的 H.264/AAC 成片，并选择烧录、内嵌或无字幕模式。
- 高清成片完成后会校验时长、尺寸、编码、音轨、字幕、文件大小和 SHA-256，并归档视频、字幕、封面与交付清单。

当前剪辑能力见 [Batch 4.6.1～4.6.5 执行验收](./docs/Phase2_Batch4.6.1-4.6.5_剪辑时间线与低清预览执行验收.md)，最终交付能力见 [Batch 4.6.6 执行验收](./docs/Phase2_Batch4.6.6_最终高清渲染与导出执行验收.md)。

## 本地开发

环境要求：Node.js 20.19+、Python 3.11+。

### Windows 一键启动

双击 `scripts/start.bat` 即可启动 API（8000）和 Web（4174），服务就绪后会自动打开浏览器。首次运行缺少依赖时，脚本会自动安装。

命令行验收时可禁止自动打开浏览器：

```bat
scripts\start.bat --no-browser
```

### Web

```bash
npm install
npm run dev:web
```

### API

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e "services/api[dev,local-ai]"
.venv/Scripts/python -m uvicorn viral_dna_api.main:app --app-dir services/api/src --reload --port 8000
```

Web 开发服务器默认将 `/api` 代理到 `http://127.0.0.1:8000`。

### 工作区与分析记录

默认工作区是仓库下的 `storage/`。启动后可进入左侧“模型与设置”，在“工作区”区域填写绝对路径，先校验再切换。切换成功后路径写入本机 `.env.local`，下次启动自动恢复；API Key 不会写入工作区。

工作区使用以下核心结构：

```text
<workspace>/
├─ .viraldna/
│  ├─ workspace.json
│  └─ workspace.db
├─ records/<record_id>/
│  ├─ source/
│  ├─ analyses/<analysis_id>/
│  └─ exports/<analysis_id>/
└─ temp/
```

左侧“分析记录”支持：

- 搜索记录并按目录、状态和更新时间筛选。
- 创建或重命名一级目录，重命名记录并移动目录。
- 重复打开历史报告、视频与分析版本，不重复调用模型。
- 手动重新分析，并将新任务保存为同一记录下的新版本。
- 将报告、提示词包、替换版提示词包、转写与字幕保存到 `exports/` 后下载。

旧版 `storage/viral_dna.db` 和分析产物会采用复制、校验、登记的方式兼容迁移；迁移过程不会删除旧文件。

### 通过 GUI 配置阿里云百炼 VLM

VLM 默认关闭，因此既有媒体证据流程不会产生模型费用。启用真实逐镜头视觉分析不再需要手工编辑 `.env.local`：

1. 启动项目后点击左侧“模型与设置”。
2. 选择阿里云百炼、分析主模型和质量档位。
3. 填写 API Key，点击“验证并保存”。

浏览器不会持久化 API Key，后端也不会在接口响应或日志中返回密钥。保存时，本地 API 只向 DashScope 官方 HTTPS 地址发送一次 `max_tokens=1` 的最小验证请求，可能产生极小费用；验证失败不会改写现有配置。验证成功后配置写入已被 Git 忽略的本机 `.env.local`，新分析立即生效，无需重启 API。

手动选择模型会将其设为各分析任务的首选路由；选择“自动”则跟随 `quality`、`balanced` 或 `economy` 档位。每个分析任务仍会冻结模型与价格快照，并按 Provider 返回的 Token 用量以微元精度记账。

模型与价格目录分别位于：

- `services/api/src/viral_dna_api/ai/model_catalog.toml`
- `services/api/src/viral_dna_api/ai/model_pricing.toml`

相关查询接口：

- `GET /api/v1/settings/model`
- `PUT /api/v1/settings/model`
- `GET /api/v1/analyses/{analysis_id}/report`
- `GET /api/v1/analyses/{analysis_id}/model-runs`
- `GET /api/v1/analyses/{analysis_id}/cost`

## 文档

- [项目定位与长期技术方案](./docs/ViralDNA_项目定位与技术方案.md)
- [Phase 1 执行计划](./docs/Phase1_执行计划.md)
- [Phase 1 架构与接口设计](./docs/Phase1_架构与接口设计.md)
- [Batch 2 真实媒体证据层执行与验收](./docs/Phase1_Batch2_真实媒体证据层执行计划.md)
- [Batch 2.5 链接采集层执行与验收](./docs/Phase1_Batch2.5_链接采集层执行与验收.md)
- [Batch 3.1 证据时间线与 Provider 执行计划](./docs/Phase1_Batch3.1_证据时间线与Provider执行计划.md)
- [Batch 3.2 本地语音与字幕识别执行验收](./docs/Phase1_Batch3.2_本地语音与字幕识别执行验收.md)
- [Batch 3.3 VLM 网关与模型计费执行计划](./docs/Phase1_Batch3.3_VLM网关与模型计费执行计划.md)
- [Batch 3.4 工作区与分析记录执行计划](./docs/Phase1_Batch3.4_工作区与分析记录执行计划.md)
- [UI 风格参考](./docs/UI模板.png)
