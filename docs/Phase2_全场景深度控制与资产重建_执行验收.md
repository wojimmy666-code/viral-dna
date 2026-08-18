# Phase 2 · 全场景深度控制与资产重建

更新时间：2026-08-18
状态：统一任务接口、CPU/GPU 双引擎与账户级自动路由已实现，等待 Provider 人工验收

## 1. 产品定义

ViralDNA 的视频复刻输入统一为：

```text
原始分镜视频
  → 本机生成逐帧全场景深度视频
  → 人物资产提供身份
  → 场景／服装／产品资产提供外观
  → 深度视频只提供动作、空间、遮挡和运镜
  → 按模型能力编译请求并生成新视频
```

深度约定固定为“近处白、远处黑”。深度视频不得作为人物身份、年龄、五官、服装、颜色、纹理、原场景光照、文字或水印来源。

本版本是破坏性替换：不读取、不迁移、不展示旧图片白模、视频白模、DWPose 或 OpenCV 代理数据，也不保留旧 API、字段、依赖与 UI。

## 2. 三类独立来源

| 来源 | 决定内容 | 禁止越权 |
|---|---|---|
| 人物身份 | 脸部、年龄感、稳定人物特征 | 不决定原视频人物身份 |
| 外观资产 | 场景、服装、产品、道具、颜色与材质 | 不改变深度时序和动作轨迹 |
| 全场景深度 | 人物和物体的位置、尺度、前后关系、遮挡、动作、镜头空间变化 | 不携带身份、纹理和原场景外观 |

服务端生成清单是最终安全边界。前端标签或提示词不能替代服务端路由检查。

## 3. 模型路由

| 路由 | 身份来源 | 外观来源 | 空间控制 | 缺少深度时 |
|---|---|---|---|---|
| Seedance 托管演员深度引导 | Provider 托管演员 | 项目资产 | 公网 HTTPS 深度视频 | 阻止生成 |
| MiniMax 身份图深度引导 | 已确认人物图 | 项目资产 | 公网 HTTPS 深度视频 | 阻止生成 |
| Wan VACE Depth | 已确认人物图 | 项目资产 | `video_repainting` + depth | 阻止生成 |
| 普通多图参考模型 | 已确认有序画面 | 项目资产 | 不提交深度 | 正常按多图路由生成 |
| 单图／文字模型 | 关键帧与提示词 | 项目资产 | 不提交深度 | 正常按本模型能力生成 |

模型切换后必须重新计算路由；历史深度文件仍属于当前分镜，但不支持深度的模型不会收到它。

## 4. 代码结构

```text
services/api/src/viral_dna_api/
├── control_assets/
│   ├── domain.py                 # 深度控制领域模型
│   ├── models.py                 # API 请求、响应与安装任务
│   ├── routes.py                 # 深度生成、启停、删除、媒体和安装接口
│   ├── service.py                # 工作区存储、安装任务、通知与事务删除
│   ├── jobs/
│   │   ├── domain.py             # 持久化任务、阶段、预设与终态
│   │   ├── service.py            # 单机工作队列、恢复、取消、重试与通知
│   │   ├── progress.py           # 阶段权重、帧进度与剩余时间
│   │   └── contracts.py          # 仓库与生产方案提交边界
│   └── engines/
│       ├── contracts.py          # 深度引擎能力与输出契约
│       ├── registry.py           # 引擎注册表
│       ├── selector.py           # Auto/CPU/GPU 能力选择
│       ├── process_runner.py      # 可取消、可超时的异步子进程
│       ├── cpu_onnx/              # CPU 逐帧 ONNX 流式引擎
│       ├── async_video_depth_anything.py
│       └── video_depth_anything.py
│   └── settings.py               # 基于账户的深度执行偏好
├── reference_routes/             # 跨模型能力与路由解析
├── video_references/             # 分镜输入计划
└── video_generation/providers/   # Provider 请求物理隔离

apps/web/src/
├── depth-settings/               # Auto/CPU/GPU 设置与探测 UI
├── video-controls/
│   ├── DepthControlPanel.jsx
│   ├── depth-control.css
│   └── depth/
│       ├── useDepthControlJob.js
│       ├── DepthGenerationStatus.jsx
│       └── depth-generation.css
├── ShotVideoWorkspace.jsx
└── ProductionWorkflow.jsx
```

## 5. 深度引擎与执行模式

对外始终使用同一套深度任务 API，内部提供两种物理隔离的执行引擎：

| 模式 | 引擎 | 设备 | 用途 |
|---|---|---|---|
| CPU | Depth Anything V2 Small ONNX | ONNX Runtime CPUExecutionProvider | 默认回退、无独显电脑、逐帧流式生成 |
| GPU | Video Depth Anything Small | NVIDIA CUDA | 时序一致性更强的 GPU 推理 |

账户设置提供“自动识别、CPU、GPU”三种选择，默认“自动识别”。自动模式仅在 PyTorch 实际报告 `torch.cuda.is_available()` 时选择 GPU，否则选择 CPU；强制 GPU 不会静默回退。每个任务在创建时固化请求偏好、实际引擎、设备、运行时版本和选择原因，之后修改设置不会改变正在运行或历史任务。

CPU ONNX 引擎：

- 使用 Depth Anything V2 Small ONNX，模型输入 518 × 518。
- FFmpeg 解码与编码均采用管道流式处理，不落盘全部帧。
- 每处理一帧上报真实帧进度和 ETA；默认最长任务时间 7200 秒。
- 输出使用百分位归一化、时间平滑和场景切换保护，编码为 H.264。
- 模型固定 SHA-256：`d2b11a11c1d4a12b47608fa65a17ee9a4c605b55ee1730c8e3b526304f2562be`。

GPU 时序引擎：

- 源码通过 SSH 克隆到 `tools/video-depth-anything`。
- 引擎使用自己的 `.venv`，不污染 ViralDNA API 的 Python 环境。
- 安装器使用固定的 `viral-dna-inference-core/v1` 推理依赖集；不安装灰度推理路径不需要、且在 Windows 上容易失败的可选 `xformers` 与 `OpenEXR`。官方代码在缺少 `xformers` 时使用 PyTorch 注意力回退，`OpenEXR` 只在显式导出 EXR 时使用。
- 使用 Apache-2.0 的 Small 模型，不自动安装非商业许可证的 Base／Large 权重。
- 权重固定 SHA-256：`13379300b739e659f076a59d52e9801bd8d38c541a7e71f73bbca4dcfb013609`。
- 安装任务提供百分比、当前阶段、失败详情和账户通知。
- 生成后检查媒体尺寸、时长、帧率、灰度动态范围和 SHA-256。
- 生成由持久化后台任务执行，HTTP 创建请求立即返回，不再占用 30 分钟长连接。
- 安装器单独安装 CUDA 12.1 的 PyTorch/torchvision，并在完成前强制验证 CUDA 可用；不会把 CPU 版 PyTorch 错报为 GPU 引擎。
- 推理子进程实时解析处理帧数，记录阶段百分比、心跳、预计剩余时间和 PID；支持取消整棵 Windows 子进程树。
- API 重启后，排队任务自动恢复；已运行但失去子进程的任务标记为“已中断”，允许一键重试，不会永久卡在生成中。
- 超时、内存不足或子进程异常时保留任务诊断和 stderr 尾部，自动清理大体积临时帧。

可选环境变量：

- `VIRAL_DNA_VIDEO_DEPTH_ANYTHING_HOME`：手工安装目录。
- `VIRAL_DNA_VIDEO_DEPTH_PYTHON`：手工安装所用 Python。
- `VIRAL_DNA_FFMPEG_PATH` / `VIRAL_DNA_FFPROBE_PATH`：媒体工具路径。

## 6. 数据与文件

分镜字段只有 `depth_control_assets`，资产类型只有 `full_scene_depth_video`。

```text
<workspace>/records/<record>/productions/<project>/shots/<shot>/
└── depth-controls/<asset-id>/
    ├── depth.mp4
    ├── thumbnail.jpg
    └── manifest.json

<workspace>/records/<record>/productions/<project>/shots/<shot>/
└── depth-control-jobs/<job-id>/
    ├── job.json
    └── stderr-tail.log            # 仅失败时存在
```

Manifest 使用 `viral-dna-depth-control/v1`，记录源视频区间、引擎版本、模型变体、深度约定、媒体元数据、校验指标和文件哈希。删除采用“先暂存、更新方案、再永久删除”的事务流程。

## 7. API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/depth-controls/engines` | 读取引擎能力 |
| POST | `/api/v1/depth-controls/engines/{engine}/installations` | 启动安装 |
| GET | `/api/v1/depth-controls/engines/installations/{id}` | 读取安装进度 |
| POST | `/api/v1/depth-controls/shots/{shot_id}/jobs` | 创建后台深度任务，立即返回 202 |
| GET | `/api/v1/depth-controls/shots/{shot_id}/jobs` | 查询该分镜任务历史／恢复页面状态 |
| GET | `/api/v1/depth-controls/jobs/{job_id}` | 读取阶段、帧进度、ETA 和诊断 |
| POST | `/api/v1/depth-controls/jobs/{job_id}/cancel` | 取消排队或运行任务 |
| POST | `/api/v1/depth-controls/jobs/{job_id}/retry` | 依据失败类型重新排队；超时自动用 CPU 快速档 |
| PATCH | `/api/v1/depth-controls/shots/{shot_id}/{asset_id}` | 启用／停用版本 |
| DELETE | `/api/v1/depth-controls/shots/{shot_id}/{asset_id}` | 永久删除记录和文件 |
| GET | `/api/v1/depth-controls/shots/{shot_id}/{asset_id}/content` | 预览／下载媒体 |
| GET | `/api/v1/settings/depth-generation` | 读取账户级执行偏好和解析结果 |
| PUT | `/api/v1/settings/depth-generation` | 保存 Auto/CPU/GPU 偏好 |
| POST | `/api/v1/settings/depth-generation/probe` | 重新探测 CPU、CUDA 与实际路由 |

所有写操作仍使用当前方案 Revision，冲突时返回明确错误，不静默覆盖。

## 8. UI

分段视频工作台默认只显示三类来源状态：人物身份、外观资产、动作与空间。深度控制位于默认收起的“高级”区域：

- “模型与设置 → 深度视频生成”提供自动识别、CPU、GPU 三个选项，并显示当前实际解析到的设备与引擎。
- GPU 不可用时选项禁用并展示原因；CPU 模型缺失时可直接安装并查看进度。

- 左侧预览原始分镜，右侧预览近白远黑的深度视频。
- 引擎未安装时显示安装按钮、进度条和当前阶段。
- 生成时显示真实阶段、百分比、已处理帧、设备和预计剩余时间；刷新页面后继续显示同一任务。
- 用户可取消任务；失败后显示可读原因和“快速重试”，原始技术信息默认收起。
- 完成／失败／取消同时写入基于账户的右上角通知，不在主工作区堆叠重复结果卡片。
- 可重新生成、启用历史版本、停用或永久删除。
- 深度不支持的模型只显示简短路由摘要，不显示无效控件。
- 路由未就绪时明确阻止生成，不自动回退旧代理或原始真人素材。

## 9. 人工验收

1. 进入一个有人物移动、前景遮挡和明显景深的分镜。
2. 选择支持深度路由的模型，展开“深度控制（高级）”。
3. 打开“模型与设置 → 深度视频生成”，确认默认是自动识别；无 NVIDIA CUDA 的电脑应显示解析为 CPU ONNX。
4. 分别切换 CPU 和 GPU：CPU 可保存；GPU 不可用时必须明确阻止且不得静默回退。
5. CPU 模型未安装时点击安装，确认进度持续更新，成功／失败同时进入右上角通知。
6. 点击生成后确认请求立即返回，出现逐帧任务进度；刷新页面后仍能恢复同一任务和当前进度。
7. 在推理期间点击取消，确认进程停止、状态变为已取消，且 API 仍可响应其他请求。
8. 再次生成，确认画面为完整场景灰度深度，而不是单个人形轮廓；近处更白、远处更黑。
9. 对照原片播放，确认人物、物体和镜头运动逐帧同步，时长误差没有阻止使用。
10. 绑定人物身份、场景和服装资产，打开生成输入计划，确认三类来源相互独立。
11. 用 Seedance 生成时确认原始真人图／视频不在请求媒体清单，身份只来自托管演员。
12. 用 MiniMax／Wan VACE 路由时确认人物图、项目外观资产和深度视频分别映射到对应字段。
13. 切换到不支持深度的普通模型，确认深度控件隐藏且深度 URL 不进入请求。
14. 生成第二个深度版本并切换，确认历史版本可选；删除后本地目录同步消失。
15. 测试中重启 API，确认原运行任务显示“因服务重启而中断”，可用快速重试恢复，而不是无限生成中。

## 10. 官方依据

- [Video Depth Anything 官方仓库](https://github.com/DepthAnything/Video-Depth-Anything)
- [Video Depth Anything Small 官方模型页](https://huggingface.co/depth-anything/Video-Depth-Anything-Small)
