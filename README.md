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

当前已完成 Phase 1 Batch 2 的真实媒体证据层：

- 视频文件流式上传，以及抖音/小红书链接记录。
- 上传视频的 ffprobe 探测、SHA-256、H.264/AAC 代理和 WAV 音频。
- FFmpeg scene score 真实分镜、逐镜头关键帧、Contact Sheet 和 manifest。
- SQLite 持久化、分析状态机和受限的媒体产物 API。
- 单视频报告工作台，以及真实媒体证据和模拟报告的明确区分。
- Windows `scripts/start.bat` 一键启动 API 8000 和 Web 4174。

抖音/小红书链接的真实下载解析，以及 ASR、OCR、VLM、爆点 LLM、Seedance Prompt 和真实元素替换仍待后续批次接入。详细边界见 [Batch 2 执行与验收记录](./docs/Phase1_Batch2_真实媒体证据层执行计划.md)。

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
.venv/Scripts/python -m pip install -e "services/api[dev]"
.venv/Scripts/python -m uvicorn viral_dna_api.main:app --app-dir services/api/src --reload --port 8000
```

Web 开发服务器默认将 `/api` 代理到 `http://127.0.0.1:8000`。

## 文档

- [项目定位与长期技术方案](./docs/ViralDNA_项目定位与技术方案.md)
- [Phase 1 执行计划](./docs/Phase1_执行计划.md)
- [Phase 1 架构与接口设计](./docs/Phase1_架构与接口设计.md)
- [UI 风格参考](./docs/UI模板.png)
