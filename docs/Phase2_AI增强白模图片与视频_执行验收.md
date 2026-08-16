# Phase 2 · AI 增强白模图片与视频

更新时间：2026-08-16

状态：代码、隐私门禁、质量复检、失败回退和工作台配置已完成；等待真实百炼图片与 Seedance 视频的最低成本人工验收

## 1. 目标

在保留 DWPose WholeBody 姿态准确性和隐私边界的前提下，使用国内生成模型提升图片白模与视频白模的形体完整度、轮廓自然度和时序平滑度。

AI 增强不是直接把原始人物素材发给生成模型。生产链路固定为：

```text
原始人物图片／当前分镜视频（仅本机）
  → DWPose WholeBody 提取匿名姿态
  → ViralDNA 本机渲染匿名结构白模
  → 国内生成模型只接收匿名结构白模
  → 对生成结果再次执行 DWPose + 身份扫描
  → 通过：保存 AI 增强白模
  → 不通过：按用户选择回退本机结构白模，或失败关闭
```

任何阶段都不允许为了“提高效果”而把原始人物图片或视频自动回退给远程模型。

## 2. 两档生成质量

### 2.1 AI 增强

- 图片：使用当前已配置且通过校验的百炼图片模型，对本机 DWPose 匿名结构图进行结构引导生图。
- 视频：使用 Seedance 2.0 Fast，把本机 DWPose 匿名动作视频作为唯一远程视频参考，生成更连续的无身份白模视频。
- 输出必须重新通过姿态、主体构图和身份去除门禁。
- 记录 Provider、模型、任务 ID、预计／实际成本、基础引擎和质量证据。

### 2.2 本机结构

- 继续使用 DWPose WholeBody 与 ViralDNA 确定性渲染器。
- 免费、稳定、仅本机处理。
- 既可由用户直接选择，也可作为 AI 增强失败后的安全回退结果。

## 3. 隐私和安全门禁

AI 增强请求固定使用 `anonymous_structure_only`：

- 原始人物图片和视频只允许由本机 DWPose 引擎读取。
- 远程图片模型只接收 DWPose 匿名结构 PNG。
- 远程视频模型只接收 DWPose 匿名动作 MP4。
- 生成记录必须写入 `raw_source_uploaded=false`。
- AI 输出必须再次运行 DWPose，比较姿态误差、人物框重叠和有效帧覆盖率。
- OpenCV 人脸门禁不可用、发现人脸样式区域，或姿态偏移超阈值时均不得自动启用 AI 输出。

白模仍是动作与构图代理，不是审核绕过工具。最终 Provider 是否接受某种代理媒体，仍由模型能力、供应商规则和 ViralDNA 请求前策略门共同决定。

## 4. 失败与回退

默认开启“AI 增强失败时自动保留本机结构白模”：

- `requested_render_profile=ai_enhanced`
- `effective_render_profile=structural`
- `fallback_applied=true`
- 保存明确的 `fallback_reason`

这样不会把远程失败伪装成 AI 成功，也不会丢失已经生成的安全本机白模。关闭回退时，任何远程调用、下载、转码或质量门禁失败都会使本次操作失败，且清理未完成目录。

## 5. 成本规则

- 图片增强复用图片模型目录的单张成本、项目预算和账户成本账本。
- Seedance 白模视频当前按 Provider 实际用量记账；在提交前无法可靠预估时，用户必须显式勾选“同意按实际用量结算”。
- 资产同时记录 `estimated_cost_micros`、`actual_cost_micros` 及对应是否已知。
- AI 增强失败后回退本机结构白模，不得把本机结果标为远程生成；已经发生的上游费用仍保留在任务审计数据中。

## 6. API

能力发现：

```http
GET /api/v1/video-references/proxy-engines
```

除 DWPose 本机引擎外，响应可包含：

- `qwen_mannequin_image`
- `seedance_mannequin_video`
- `engine_class=generative_remote`
- `render_profiles=["ai_enhanced"]`
- `privacy_modes=["anonymous_structure_only"]`
- Provider、模型、可用状态和成本是否已知

生成 AI 增强图片白模示例：

```json
{
  "expected_revision_id": "...",
  "source_kind": "image_candidate",
  "source_candidate_id": "...",
  "visual_beat_id": "...",
  "kind": "pose_proxy_image",
  "render_profile": "ai_enhanced",
  "privacy_mode": "anonymous_structure_only",
  "enhancer_engine": "qwen_mannequin_image",
  "fallback_to_structural": true,
  "allow_unknown_cost": false
}
```

视频白模使用 `source_kind=source_shot_video`、`kind=motion_proxy_video` 和 `enhancer_engine=seedance_mannequin_video`。费用不可预估时必须显式传入 `allow_unknown_cost=true`。

## 7. 物理代码边界

- `video_references/domain.py`：质量档位、隐私模式、引擎类型和持久化溯源字段。
- `video_references/models.py`：API 输入验证，阻止不合法的档位／隐私组合。
- `video_references/proxies/contracts.py`：本机结构引擎与远程增强器的独立协议。
- `video_references/proxies/service.py`：两阶段编排、回退、目录清理和资产落盘。
- `video_references/proxies/ai/image.py`：百炼图片白模增强器。
- `video_references/proxies/ai/video.py`：Seedance 视频白模增强器。
- `video_references/proxies/ai/quality.py`：姿态、构图、覆盖率和人脸样式门禁。
- `image_generation/gateway.py`：不写入普通分镜候选的辅助图片生成入口。
- `apps/web/src/video-references/`：默认收起的“白模生成质量”、状态、隐私、成本和历史信息。

本机基础引擎与远程增强器物理隔离。未来增加其他国内图片／视频模型时，只需实现 `ReferenceProxyEnhancer`，不需要修改 DWPose 推理和生成资产领域模型。

## 8. UI 行为

“人物参考策略”中新增默认收起的“白模生成质量”：

- 第一次加载能力后，有可用 AI 增强器则默认选择“AI 增强”，否则默认“本机结构”。
- 展开后分别显示图片／视频增强器、Provider、模型和未就绪原因。
- 固定显示“远程只接收 DWPose 匿名结构稿，原始人物素材不会上传”。
- 可以关闭自动回退，进入失败关闭模式。
- 视频增强费用未知时必须确认费用，否则生成视频白模按钮不可用。
- 历史卡片显示实际生效档位；发生回退时明确显示“已回退本机结构”，并显示成本（如有）。

## 9. 人工验收

### 9.1 能力与默认状态

1. 启动 API 与 Web，进入一个已绑定人物身份且允许动作白模的分镜。
2. 展开“白模生成质量”。
3. 已配置百炼图片 Key 时，确认图片增强器显示就绪；未配置时显示明确原因。
4. 已配置火山方舟 Key 时，确认 Seedance 视频增强器显示就绪；未配置时显示明确原因。
5. 确认 DWPose 未安装时 AI 增强不会伪装为可用，并保留安装入口。

### 9.2 AI 图片白模

1. 选择“AI 增强”，保留自动回退，生成图片白模。
2. 确认远程任务输入是 `reference-proxies/.../base/proxy.png`，不是原始人物候选路径。
3. 成功时放大预览，确认人物位置、手臂方向和构图接近原图，同时没有可识别五官、服装纹理或背景身份信息。
4. 确认历史卡片显示 AI Provider／模型、质量分和成本。
5. 暂时填错图片模型设置，确认结果明确回退到“本机结构”，而不是显示 AI 成功。

### 9.3 AI 视频白模

1. 勾选未知费用确认，仅生成最短时长、单任务视频白模。
2. 确认 Seedance 请求中唯一视频参考是 DWPose 匿名动作视频。
3. 播放结果，确认人物动作节奏、位移和镜头内轨迹接近原分镜，轮廓比本机结构稿更自然。
4. 确认输出再次执行 DWPose；姿态漂移或人脸门禁失败时不自动启用。
5. 关闭自动回退并模拟 Provider 失败，确认操作失败且不产生伪成功资产。

### 9.4 隐私审计

1. 检查资产 JSON 和质量报告，确认 `raw_source_uploaded=false`。
2. 检查 Provider 请求审计文件，确认只包含匿名结构文件摘要。
3. 确认任何失败路径都不会自动改用原始人物图片或原视频。
4. 切换到允许原始参考的 MiniMax／百炼视频模型，确认原有模型路由不受本白模质量选项强制改变。

## 10. 当前边界

- 真实模型效果和质量阈值必须通过多类姿态素材人工校准；第一版阈值采取失败关闭原则，可能出现宁可回退也不放行的情况。
- AI 视频白模会额外产生一次视频模型费用和一次本机 DWPose 复检时间。
- Seedance 的增强结果是否可再次作为后续视频生成参考，仍须遵守供应商当时的素材和审核规则。
- 第一版没有实现 Wan VACE 视频重绘增强器；领域接口和能力发现已为后续实现预留。
