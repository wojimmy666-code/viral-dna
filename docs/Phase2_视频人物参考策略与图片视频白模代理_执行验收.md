# Phase 2 · 视频人物参考策略与图片／视频白模代理

更新时间：2026-08-15

状态：模型能力抽象、服务端策略门、DWPose WholeBody 图片／视频白模、Seedance／MiniMax／百炼差异化路由与工作台交互已完成；等待首次模型安装、人工验收和真实 Provider 最低成本验证

> 2026-08-15：旧 OpenCV 粗剪影已永久降级为只读历史资产。当前生产实现、质量门禁、迁移和验收流程见 [DWPose WholeBody 白模永久修复](./Phase2_DWPose白模永久修复_执行验收.md)。

## 1. 目标与原则

不同视频模型对人物参考素材的安全要求不同：

- Seedance 当前链路不应直接提交可能包含真人身份的本地图片或原视频帧；人物身份必须来自火山方舟托管演员资产。
- MiniMax H3、百炼 Wan 2.7 等允许原始人物参考的模型继续使用原始关键帧，不强制转白模，不损失人物、服装与场景信息。
- 白模只负责传递动作、姿态、人物位置、构图或运动节奏，不负责身份；它不能代替供应商托管演员。
- 图片白模和视频白模是两种独立的派生资产，可以任选、同时使用、停用或重新生成。
- 所有模型差异必须由模型能力和服务端策略门决定，不能在页面里硬编码模型名，也不能依赖提示词绕过 Provider 审核。

本功能是合规的参考素材路由，不是审核规避器。任何未经 Provider 认可的真人素材都不会因为改写提示词而被强行提交。

## 2. 模型无关的领域抽象

### 2.1 人物参考策略

`PersonReferenceCapability` 为每个模型声明以下能力：

- `policy`
  - `managed_required`：人物身份必须来自 Provider 托管资产；Seedance 2.0／Fast／Mini 使用该策略。
  - `raw_supported`：可直接使用本地原始人物素材；百炼 Wan 2.7 与 MiniMax H3 使用该策略。
  - `managed_optional`：既支持原始素材，也可选托管身份，为后续模型预留。
  - `no_person`：不允许任何人物参考。
  - `unknown`：旧模型兼容状态，只允许显式告警，不作为新模型默认值。
- `allow_raw_photoreal_person`：是否允许提交写实人物原图。
- `allow_provider_managed_identity`：是否支持供应商托管身份。
- `allow_asset_only_generation`：只绑定托管演员、没有本地人物图时能否生成。
- `supports_pose_proxy_image`：是否支持图片动作代理。
- `supports_motion_proxy_video`：是否支持视频动作代理。
- `supported_roles`：身份、动作、构图、场景、产品、服装、首尾帧、转场等参考角色。

模型目录只声明能力；业务代码、UI 和 Provider Adapter 都消费同一份能力对象。后续增加新模型时，只需补充目录能力和 Provider 请求映射。

### 2.2 参考绑定

`VideoReferenceBinding` 把“创作意图”与“供应商请求格式”分开保存：

- `role`：`actor_identity`、`motion`、`composition` 等。
- `source_kind`：本地原图、项目资产、Provider 托管资产、生成代理或无人物净板。
- `media_type`：图片、视频或音频。
- `person_class`：无人、真人、写实虚拟人、非写实代理、Provider 托管人物或未知。
- `enabled`：是否参与当前生成；停用不会删除历史资产。

每个绑定只允许指向一个稳定素材 ID。所有变更写入分镜 Revision，旧候选保留并按既有规则标记过期。

### 2.3 白模派生资产

`ReferenceProxyAsset` 是一等派生资产，而不是临时文件，包含：

- 源图片候选或源视频／原分镜视频。
- `silhouette_image` 或 `silhouette_video` 等代理类型。
- 输出媒体、缩略图、SHA-256、引擎和版本。
- `identity_removed`、文件校验、姿态语义校验、质量分数和校验说明。
- 姿态清单、质量报告和固定模型组合摘要。
- `ready`、`failed`、`stale` 等生命周期状态。

只有 `identity_removed=true` 且校验通过的代理才允许进入 Provider 请求。原始素材路径只用于本机派生处理，不能由前端直接变成安全代理。

## 3. 两种白模

### 3.1 图片人物白模

输入：当前分镜已确认的 AI 图片候选或关键帧。

输出：保持人物大致位置、占画比例和粗粒度姿态的无纹理剪影图片，不复制原图人物像素。

用途：

- 单个关键姿态。
- 人物在画面中的位置和尺度。
- 构图、视线方向和动作起点的辅助参考。

当前实现使用 DWPose WholeBody 推理身体、足部和双手姿态，再由确定性无纹理渲染器生成白模。它不绘制或持久化可识别面部几何，也不复制源人物像素。输出仍是二维姿态代理，不是精确三维人体。

### 3.2 视频人物白模

输入：原视频中当前分镜的时间范围。

输出：逐帧重绘的无纹理人物剪影视频，不复制源视频人物像素。

用途：

- 连续动作轨迹和人物位移。
- 动作节奏、入画／出画和镜头内时序。
- 需要多帧运动参考而单张图片无法表达的镜头。

当前实现逐帧进行 WholeBody 推理、主主体跟踪、短缺失插值和时序平滑，并输出浏览器可播放的 H.264 视频。检测覆盖或连续性不合格时保留结果供复核，但禁止提交；绝不退回原视频。

### 3.3 两者关系

- 图片白模与视频白模可以同时存在，各自保存历史版本。
- 当前 Revision 通过 `VideoReferenceBinding.enabled` 指定实际启用的代理。
- 停用代理只解除当前使用关系，不删除本地派生文件，便于回退和审计。
- 白模没有身份。Seedance 中的人物脸部、年龄与稳定外观必须来自已绑定的 Provider 托管演员。

## 4. 模型策略矩阵

| 模型策略 | 身份来源 | 原始人物图／视频 | 图片白模 | 视频白模 | 最终行为 |
|---|---|---|---|---|---|
| Seedance `managed_required` | Provider 托管演员 | 不提交 | 可选 | 可选 | 托管演员是唯一身份；白模只传动作／构图 |
| MiniMax H3 `raw_supported` | 原始参考素材 | 直接提交 | 不强制 | 不强制 | 保留原始人物、服装、场景信息 |
| 百炼 Wan 2.7 `raw_supported` | 原始参考素材 | 直接提交 | 不强制 | 不强制 | 沿用现有多图参考链路 |
| 未来 `managed_optional` | 用户选择 | 按能力提交 | 可选 | 可选 | 策略编译器决定具体组合 |
| 未来 `no_person` | 无 | 禁止 | 仅明确无人代理 | 仅明确无人代理 | 发现人物绑定即阻止生成 |

前端只展示能力允许的选项；服务端 `resolve_video_reference_plan` 在生成前重新编译并校验最终素材集合，因此绕过 UI 也不能提交不符合模型策略的真人素材。

## 5. Seedance 请求链路

Seedance 生成前按以下顺序处理：

1. 校验已绑定且仍有效的火山方舟托管演员。
2. 将托管演员 `asset://...` 放在请求参考素材的最前面。
3. 排除所有被分类为 `real_person`、`synthetic_photoreal_person` 或 `unknown` 的本地人物关键帧。
4. 只追加明确标记为 `non_photoreal_proxy` 且身份去除校验通过的图片／视频白模，以及明确无人物的场景、产品参考。
5. 在 Provider Prompt 中声明托管演员是唯一身份来源；白模只允许影响位置、姿态、节奏和镜头运动。
6. 把最终策略、选中项、排除项、警告和指纹写入 `reference_manifest`，随任务和候选留档。

禁止行为：

- 不把“这是一名虚拟人物”之类文案当成安全凭证。
- 不把真人图改名、压缩、打码后继续作为身份参考提交。
- 白模生成失败时不自动回退原素材。
- 不把本地资产 ID 或 Provider Asset ID 写进自然语言提示词。

## 6. 非受限模型请求链路

MiniMax H3 与百炼 Wan 2.7 使用 `raw_supported`：

1. 沿用已确认的有序原始关键帧。
2. 不要求绑定火山方舟演员。
3. 不要求生成图片或视频白模。
4. 白模历史资产不会被误发给这些模型，除非以后提供明确的人工选择入口并由能力声明允许。

这样既满足 Seedance 的真人素材限制，也避免所有模型都被迫使用低信息量剪影。

## 7. API 与代码边界

### 7.1 API

- `GET /api/v1/video-references/proxy-engines`：查询本机代理引擎、版本、支持类型与可用状态。
- `GET /api/v1/video-references/shots/{shot_plan_id}/strategy?model_alias=...`：返回当前模型的引用策略、阻塞原因和已选代理数量。
- `POST /api/v1/video-references/shots/{shot_plan_id}/proxies`：从图片候选、视频候选或原分镜视频生成代理并持久化。
- 现有分镜 PATCH 接口负责启用／停用 `video_reference_bindings`。

### 7.2 物理隔离

- `video_references/domain.py`：模型无关领域模型。
- `video_references/planner.py`：最终策略编译和安全门。
- `video_references/proxies/contracts.py`：代理引擎协议。
- `video_references/proxies/dwpose/`：模型校验、WholeBody 推理、跟踪、渲染与质量门禁。
- `video_references/proxies/opencv_silhouette.py`：旧粗剪影兼容，只允许历史预览。
- `video_references/proxies/service.py`：源文件、输出、摘要与校验生命周期。
- `video_references/routes.py`：HTTP 接口。
- `video_generation/providers/seedance/request_mapper.py`：仅 Seedance 的托管身份和动作代理映射。
- `video_generation/gateway.py`：业务请求到 Provider 请求前的统一策略门。
- `apps/web/src/video-references/`：人物参考策略 UI，避免继续膨胀分段视频主组件。

外部姿态服务、3D 白模引擎或其他供应商以后只需实现 `ReferenceProxyEngine`，不改生产项目数据结构。

## 8. 本机依赖与数据安全

- 代理引擎依赖位于 API 的 `reference-proxy` extra：NumPy、OpenCV 与 ONNX Runtime。
- `scripts/start.bat` 启动前会检测 `cv2`、`numpy` 和 `onnxruntime`，缺失时安装该 extra。
- 首次在 GUI 安装约 351 MB、固定 SHA-256 的官方 DWPose 模型；模型不进入项目工作区或 Git。
- 派生文件保存在当前工作区分镜目录的 `reference-proxies/{proxy_id}/` 下。
- 图片代理为 PNG；视频代理为 MP4；同时保存缩略图与 SHA-256。
- 白模生成仅在本机读取源素材；对 Seedance 的实际请求只传托管演员和校验通过的代理输出。
- 代理文件仍属于项目素材，遵循工作区、归档、删除和后续云端存储接口边界。

## 9. GUI 交互

在“分段视频”选择不同模型时，人物参考策略条自动切换：

- Seedance：显示“托管演员 + 无身份动作”，要求先绑定演员；可按能力生成图片白模或原分镜视频白模。
- MiniMax／百炼：显示“原始素材可用”，不展示强制白模操作。
- 已启用白模显示为独立状态标签；点击关闭只停用当前绑定，不删除历史文件。
- 代理引擎未安装时显示“白模引擎未就绪”，不出现不可执行的生成按钮。
- Seedance 未绑定托管演员时阻止付费生成，并给出绑定入口。
- 只绑定托管演员、不生成白模时仍可生成；此时动作完全由文字 Prompt 描述。

## 10. 错误与审计

关键错误码：

- `video_managed_identity_required`：当前模型必须绑定托管人物。
- `video_motion_proxy_unsupported`：模型不接受视频动作代理。
- `video_person_reference_not_allowed`：模型不允许人物参考。
- `reference_proxy_engine_unavailable`：本机代理引擎未安装或不可用。
- `reference_proxy_source_missing`：源图片／视频不存在。
- `reference_proxy_generation_failed`：检测或输出失败。
- `reference_proxy_identity_validation_failed`：输出未通过身份去除校验。

每次生成的 `reference_manifest` 记录模型策略、最终选中素材、被排除素材、代理摘要和策略版本，便于解释“实际提交了什么”。

## 11. 人工验收

### 11.1 Seedance：托管演员，不使用白模

1. 打开一个包含真人关键帧的分镜，选择 Seedance 2.0／Fast／Mini。
2. 未绑定演员时，确认生成按钮被阻止，并显示“绑定演员”。
3. 绑定一个 Active 的火山方舟虚拟人物。
4. 不生成白模，直接发起最低成本任务。
5. 确认请求使用托管 `asset://` 身份，原始真人关键帧没有进入 Provider 请求。

### 11.2 Seedance：图片白模

1. 在相同分镜点击“生成图片白模”。
2. 确认生成独立 PNG 和缩略图，界面显示“图片白模已启用”。
3. 生成视频，确认托管人物决定身份，白模仅辅助位置和姿态。
4. 停用图片白模，确认标签消失但工作区派生文件和历史记录仍存在。

### 11.3 Seedance：视频白模

1. 点击“生成原视频白模”。
2. 确认系统只读取当前分镜时间范围，并生成 MP4 动作代理。
3. 生成视频，确认请求包含托管演员和无身份视频代理，不包含原分镜视频。
4. 停用视频白模后重新生成，确认新任务不再携带该代理。

### 11.4 MiniMax／百炼

1. 将同一分镜切换到 MiniMax H3 或百炼 Wan 2.7。
2. 确认显示“原始素材可用”，不强制绑定火山演员或生成白模。
3. 生成最低成本候选，确认原始已确认关键帧按既有顺序提交。

### 11.5 失败边界

1. 使用无人或检测困难的图片生成白模，确认明确报错，不自动提交原图。
2. 暂时移除 ONNX Runtime 依赖或模型文件，确认 UI 显示未就绪并提供安装入口。
3. 绕过 UI 对 Seedance 提交未绑定演员的请求，确认服务端仍返回 `video_managed_identity_required`。
4. 检查 GenerationRun／ProviderTask 的 `reference_manifest`，确认可以追踪选中、排除和代理摘要。

## 12. 当前边界与后续增强

- 本期 DWPose 实现是二维 WholeBody 姿态白模，不是精确 3D 白模或完整动作捕捉。
- 下一步可实现 SMPL 3D 人体驱动、GPU 推理或远程姿态渲染服务；通过相同协议注册。
- 在真实 Seedance 任务验证 Provider 对内嵌代理视频的传输约束后，可在 Seedance Adapter 内增加对象存储上传，不影响业务层。
- 可增加代理预览、历史版本切换、逐画面指定代理，以及自动人物／无人物分类；在分类可靠前继续采用保守策略。

## 13. 官方依据

- [火山方舟资产管理](https://www.volcengine.com/docs/82379/2333565?lang=zh)
- [Seedance 参考素材请求](https://www.volcengine.com/docs/82379/2315856?lang=zh)
- [Seedance 2.0 安全与可信人物说明](https://www.volcengine.com/activity/Seedance2-0-security?infrom=100001.100.140)
- [Seedance 2.0 全能参考能力说明](https://developer.volcengine.com/articles/7628567056649125942)
