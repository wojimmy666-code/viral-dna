# ViralDNA

面向短视频创作者与内容团队的分析和视频创作工作台：既可从原视频分析创建方案，也可从平台 Skill、品牌／产品方向及所选资产开始创作。

## 当前能力

- 原视频导入、链接采集、媒体证据、逐分镜分析和复刻方案。
- Skill 简报、风格、大纲分镜，以及两种入口共用的图片、视频、剪辑和导出流程。
- 图片／视频全局与局部提示词、项目已选资产引用、版本化候选与人工采用。
- 独立个人／企业账户与单 admin 后台；企业成员共享数据，项目同一时刻仅一个编辑会话。
- 账户级资产与生成历史存储、增量同步、回收站及手动容量管理：个人默认 2 GB，企业共享 10 GB。

代码与本地隔离测试通过，不表示已经部署到真实服务器。实际资产上传需要兼容的 HTTPS 目标、明确的目标账户确认和服务器验收；真实模型调用另需配置与授权。

## 仓库结构

```text
apps/web       React + Vite 工作台
services/api   FastAPI、账户、任务、媒体和存储
scripts        本地启动、运行工具与检查
docs           按用途分类的功能、架构、部署和验收文档
```

## 本地运行

Windows 环境要求 Node.js 20.19+、Python 3.11+；媒体处理需要 FFmpeg／ffprobe。运行前先确认没有应继续保留的真实任务：启动器发现旧 API 时可能受控重启。

```powershell
.\scripts\start.bat --no-browser
```

默认前端为 `http://127.0.0.1:4174`，API 健康检查为 `http://127.0.0.1:8000/health`。完整安装、停止和手工启动步骤见 [本地环境与启动](docs/deployment/本地环境与启动.md)，不要将开发服务器直接作为公网生产服务。

首次在部署本机打开 `/login`，设置 admin 并明确旧数据归属，不需要初始化码。前端为中国大陆 11 位手机号登录，密码至少 8 位，不要求复杂度组合；后台入口为 `/admin/login`。详见 [账户初始化](docs/deployment/账户初始化.md)。

平台 Provider 凭据和模型目录由独立 admin 后台维护，用户设置只管理生成偏好，不在用户页面填写 API Key。已有工作区与账户数据路径不得通过重新初始化或切换免登录模式绕过。

## 文档入口

- [全部文档与维护规则](docs/README.md)
- [当前创作流程](docs/features/创作流程与生成规则.md)
- [账户与企业协作](docs/features/accounts/account-system-implementation.md)
- [部署流程](docs/deployment/README.md)
- [服务器同步与容量配置](docs/deployment/资产同步与容量配置.md)
- [架构与技术协议](docs/architecture/README.md)
- [设计规范](docs/design/README.md)、[验收记录](docs/qa/README.md)
- [规划与待核对事项](docs/roadmap/README.md)、[历史归档](docs/archive/README.md)

历史 Phase／Batch 文档记录当时边界，不能作为当前功能、价格或部署状态的依据。部署与备份操作只在 `docs/deployment/` 维护。

## 开发检查

```powershell
node scripts/check-docs.mjs
npm run check:design
npm run test:web
npm run build:web
```

后端依赖和测试配置见 [services/api/pyproject.toml](services/api/pyproject.toml)；账户／存储检查入口见对应功能文档。测试使用隔离数据，不自动提交付费任务或上传真实资产。

## GitHub 约定

遵守 [AGENTS.md](AGENTS.md)：默认在 `main` 开发；GitHub 交互使用 SSH，`origin` 保持 `git@github.com:wojimmy666-code/viral-dna.git`。提交在本地完成，只有收到明确推送指令才允许 push。
