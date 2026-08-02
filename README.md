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

当前正在执行 Phase 1 的第一个纵向切片：

- 视频文件/链接导入
- 分析任务状态机
- 模拟分析流水线
- 单视频报告工作台
- 元素替换和 Prompt Pack 导出

真实 FFmpeg、ASR、OCR、VLM 和 LLM Provider 将按 [Phase 1 执行计划](./docs/Phase1_执行计划.md) 分批接入。

## 本地开发

环境要求：Node.js 20.19+、Python 3.11+。

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
