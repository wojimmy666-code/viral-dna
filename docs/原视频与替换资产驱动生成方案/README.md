# 原视频与替换资产驱动的新视频生成方案

> 文档状态：**讨论稿，尚未定稿**
>
> 实施状态：**暂不实现**
>
> 建立日期：2026-08-16
>
> 说明：本文记录当前一轮架构与产品方案，用于继续对齐构思。它不是已批准的产品需求，也不能作为开发、数据迁移或 Provider 接入的实施依据。只有在后续明确确认修订版后，才可进入编码阶段。

> 进展：本文中的“模型参考路由”子方案已于 2026-08-16 单独确认并进入实现，详见[模型参考路由实施说明](./模型参考路由实施说明.md)。其余端到端自动复刻构思仍保持讨论稿状态。

## 1. 当前目标

用户最终希望通过以下输入直接获得新视频：

~~~text
原始视频 + 新人物资产 + 可选服装／场景／产品／道具资产
                            ↓
                         新视频
~~~

白模、姿态提取、关键帧生成、人物遮罩、Provider 托管演员映射等都属于系统内部可能采用的中间过程：

- 默认不直接展示给普通用户。
- 仅在生成失败、质量不足、需要人工复核或用户主动打开高级详情时展示。
- 中间过程必须可以查看、重新生成、切换版本和进行有限调整。
- 中间过程不是用户完成生成任务前必须理解或操作的步骤。

## 2. 本稿与最终构思的关系

本稿提出“创作意图驱动 + 模型能力路由 + 隐藏式中间过程”的方向，但用户已明确指出它与最终构思仍有差异。

因此，本稿只承担以下作用：

1. 固化本轮讨论内容，避免丢失。
2. 标识可复用的技术抽象。
3. 记录仍需继续澄清的产品边界。
4. 作为下一轮方案修订的对照材料。

本稿不得直接触发以下动作：

- 不新增或修改数据库模型。
- 不修改现有分镜图片、分段视频或白模工作流。
- 不重构 ProductionWorkflow.jsx 或 ShotVideoWorkspace.jsx。
- 不新增 Provider 请求参数。
- 不改变现有模型能力声明。
- 不执行数据迁移。

## 3. 用户侧目标流程

### 3.1 输入区

主流程只向用户展示：

- **原始视频**：提供原始镜头、动作、运镜、构图、节奏和时间结构。
- **新人物资产**：指定新视频中的主要人物身份。
- **服装资产**：可选；未指定时采用后续确定的默认策略。
- **场景资产**：可选；未指定时采用后续确定的默认策略。
- **产品／道具资产**：可选。

若原始视频存在多个人物，系统应先识别主要人物；只有无法可靠判断时，才要求用户选择需要替换的人物。

### 3.2 生成设置

用户可以配置：

- 自动选择模型或手动指定模型。
- 输出比例与分辨率。
- 分段时长。
- 候选数量。
- 成本上限。
- 是否保留原视频音轨。

点击“生成新视频”时，系统应自动保存当前配置，再进入准备和生成流程。

### 3.3 用户可见的进度

默认使用业务语言描述进度：

1. 分析原视频动作与镜头。
2. 适配人物和其他替换资产。
3. 准备视频生成素材。
4. 生成分段视频。
5. 检查人物与画面一致性。
6. 合成新视频。

普通进度中不直接显示 DWPose、白模文件、Provider Asset ID 或请求映射细节。

## 4. 系统内部的候选执行策略

白模不应成为所有模型的固定必经步骤。系统应根据模型能力、人物素材政策和当前资产完整度选择执行策略。

| 策略 | 适用条件 | 内部行为 | 用户默认可见性 |
|---|---|---|---|
| 原视频直接参考 | 模型允许原视频和新人物资产共同输入 | 原视频提供动作、运镜和节奏，新资产提供身份及其他替换元素 | 隐藏技术细节 |
| 托管人物 + 动作代理 | 模型不允许提交原始真人身份素材 | 人物身份来自 Provider 托管资产，原视频在本机转换为无身份动作参考 | 白模默认隐藏 |
| 视频重绘／姿态控制 | 模型支持从视频提取动作、构图或轮廓 | 原视频作为控制视频，新人物或场景资产作为替换目标 | 控制方式默认隐藏 |
| 关键帧转视频 | 模型仅支持图片、首帧或首尾帧 | 后台先生成替换后的关键帧，再生成分段视频 | 关键帧默认隐藏 |
| 不支持 | 无法同时满足人物替换和原视频信息保留 | 阻止付费生成并提示切换模型 | 显示明确阻塞原因 |

禁止为了让任务继续而静默执行以下降级：

- 白模失败后上传原始真人素材。
- 无法保留动作时静默改成普通文生视频。
- 引用数量超限时静默丢弃人物、服装或场景资产。
- Provider 身份资产无效时继续创建付费任务。

## 5. 模型能力抽象

当前人物参考能力需要进一步扩展为统一的参考输入能力。以下字段仅为讨论稿：

~~~text
ReferenceInputCapability
├── accepts_source_video
├── source_video_semantics
│   ├── motion
│   ├── camera
│   ├── timing
│   ├── composition
│   ├── audio
│   └── repaint
├── supports_actor_identity_override
├── requires_provider_managed_identity
├── supports_motion_proxy_video
├── supports_pose_proxy_image
├── supports_scene_reference
├── supports_wardrobe_reference
├── supports_product_reference
├── maximum_reference_images
├── maximum_reference_videos
├── maximum_total_references
└── supported_transports
    ├── provider_asset_uri
    ├── public_url
    ├── signed_url
    └── provider_file_id
~~~

模型可用性不应继续只依赖“是否支持有序多图”。系统应判断该模型是否具备至少一条能够完成当前创作意图的完整执行路径。

每项能力还应记录：

- 信息来源。
- Provider 和 API 版本。
- 模型版本。
- 最近验证时间。
- 是否经过真实任务验收。
- 当前账号或区域是否可用。

## 6. 创作意图数据

建议在现有制作项目之上增加模型无关的创作意图层，暂定名称为 RemakeIntent：

~~~text
RemakeIntent
├── source_video_id
├── target_person_tracks
├── replacement_bindings
├── preserve_policy
├── model_selection
└── generation_settings
~~~

### 6.1 替换绑定

replacement_bindings 需要支持：

- 人物。
- 服装。
- 场景。
- 产品。
- 道具。
- 全局绑定。
- 单分镜覆盖。
- 保留原内容。

第一版产品可以只开放一个主要人物，但底层结构应保留多人和多目标扩展能力。

### 6.2 保留策略

preserve_policy 用于表达用户希望从原视频保留什么，例如：

- 动作。
- 运镜。
- 镜头时长。
- 节奏。
- 构图。
- 转场。
- 原始声音。

这些属于用户创作意图，不等于 Provider 的具体请求字段。

## 7. Provider 资产关联

同一个 ViralDNA 人物资产可能在不同 Provider 中使用不同的传输方式，因此需要独立关联层：

~~~text
ProviderAssetLink
├── local_asset_id
├── provider
├── provider_asset_id
├── asset_kind
├── status
├── verified_at
└── metadata
~~~

目标交互：

- 用户始终选择 ViralDNA 中统一的人物资产。
- 系统根据模型决定使用本地图片、Provider 托管演员或其他身份表达方式。
- 已绑定的 Provider 人物资产自动复用。
- 未绑定且当前模型必须使用托管人物时，只出现一次“关联演员”操作。
- 用户不需要手动输入 Provider Asset ID。
- 未经用户授权，不自动把本地人物资产上传为 Provider 托管人物。

## 8. 执行计划

每次生成前，由系统先建立不收费的执行计划：

~~~text
RemakeExecutionPlan
├── strategy
├── model_snapshot
├── source_contributions
├── resolved_assets
├── required_intermediates
├── submitted_references
├── excluded_references
├── blockers
├── warnings
├── estimated_cost
└── fingerprint
~~~

执行计划需要能够回答：

- 为什么选择当前模型和策略。
- 原视频实际贡献了哪些信息。
- 哪个人物资产是身份来源。
- 服装、场景和产品分别来自哪里。
- 是否需要生成动作代理或关键帧。
- 哪些素材不会提交给 Provider。
- 当前是否存在阻塞项。
- 预计费用是多少。

## 9. 中间资产

现有 ReferenceProxyAsset 可以继续作为动作代理的专业数据结构，不需要因为 UI 隐藏而删除。可以在外层增加统一的中间资产描述：

~~~text
RemakeIntermediateArtifact
├── kind
│   ├── motion_proxy_video
│   ├── pose_proxy_image
│   ├── generated_keyframe
│   ├── subject_mask
│   └── clean_plate
├── visibility
│   ├── internal
│   └── review_required
├── source_fingerprint
├── auto_generated
├── active_version
├── quality_status
└── stale_reason
~~~

### 9.1 自动复用与失效

- 只更换新人物：动作代理通常可以复用。
- 只更换服装或场景：动作代理通常可以复用。
- 修改原视频时间范围：相关动作代理失效。
- 更换原视频中被跟踪的人物：相关动作代理失效。
- 姿态引擎或模型版本变化：旧代理标记为过期。
- 切换到不需要动作代理的模型：历史代理保留但不提交。
- 修改动作代理：生成新的 Revision，不覆盖历史生成结果。

## 10. 自动编排流程

当前建议的内部流程如下，但仍需根据最终构思调整：

1. 保存当前创作意图。
2. 识别原视频人物轨迹及分镜范围。
3. 读取当前模型能力。
4. 解析人物、服装、场景和产品资产。
5. 构建执行计划并检查阻塞项。
6. 仅在需要时生成或复用中间资产。
7. 编译 Provider 专用提示词和素材顺序。
8. 在服务端再次执行安全与能力校验。
9. 创建分段视频任务。
10. 对生成结果执行身份、服装、场景和动作一致性检查。
11. 保留所有候选和执行清单。
12. 进入视频剪辑与合成。

## 11. 提示词职责分离

用户编辑的是创意描述，系统编译的是 Provider 执行指令。用户不需要手动输入白模名称、图片序号或 Asset ID。

内部提示词应明确区分各素材职责：

~~~text
目标人物资产：
是新视频中唯一的人物身份来源。

原视频或动作代理：
只提供动作顺序、身体姿态、人物位置、镜头运动、节奏和时间结构。

服装资产：
只定义服装款式、材质、颜色和穿着细节。

场景资产：
只定义环境、空间、光线和背景元素。

限制：
不得继承原视频人物的身份、年龄、五官和其他未被要求保留的外观特征。
~~~

Provider Asset ID 和本地文件路径只能存在于结构化请求或执行清单中，不写入自然语言提示词。

## 12. 默认 UI

主界面建议只保留：

1. 原始视频。
2. 替换人物。
3. 可选服装、场景、产品和道具。
4. 保留内容摘要。
5. 模型及输出参数。
6. 预计成本。
7. “生成新视频”按钮。

现有“人物参考策略”“生成图片白模”“生成原视频白模”“白模预览”等内容应从默认工作流移出。

## 13. 高级详情

页面提供弱化的“查看生成详情”入口，默认收起。展开后可以查看：

- 当前执行策略。
- 原视频贡献项。
- 人物与其他资产映射。
- 自动生成关键帧。
- 动作代理预览。
- 实际提交素材。
- 排除素材及原因。
- Provider 技术提示词。
- 质量报告。
- 历史 Revision。

允许的动作代理操作：

- 播放或放大。
- 重新选择原视频时间范围。
- 更换被跟踪人物。
- 重新生成。
- 切换历史版本。
- 调整动作保留强度。
- 恢复系统自动版本。
- 删除未被使用的历史版本。

第一版不建议开放逐关键点骨骼编辑。

## 14. 错误展示

普通用户只看到业务错误：

- 需要关联当前模型可用的人物身份。
- 检测到多个人物，需要选择替换目标。
- 原视频动作解析置信度较低。
- 当前模型不能同时完成指定替换和原动作保留。
- 素材适配失败，尚未创建付费任务。

高级详情中再显示：

- DWPose 或其他中间引擎错误。
- Provider 错误码。
- 请求 ID。
- 被排除素材。
- 中间资产质量分。
- 请求素材清单。

任何失败都不能绕过服务端安全门。

## 15. 建议的代码边界

以下目录只作为后续讨论建议，本稿不授权创建：

~~~text
services/api/src/viral_dna_api/remake/
├── domain.py
├── models.py
├── routes.py
├── service.py
├── planner.py
├── capability_resolver.py
├── asset_resolver.py
├── intermediate_manager.py
├── prompt_compiler.py
├── validation.py
└── strategies/
    ├── base.py
    ├── direct_reference.py
    ├── managed_identity_proxy.py
    ├── video_repaint.py
    └── keyframe_i2v.py
~~~

~~~text
apps/web/src/remake-workflow/
├── RemakeWorkspace.jsx
├── SourceVideoPanel.jsx
├── ReplacementAssetSlots.jsx
├── RemakeGenerationBar.jsx
├── RemakeProgress.jsx
├── GenerationDetailsDrawer.jsx
├── ShotAssetOverrides.jsx
├── IntermediateArtifactViewer.jsx
├── RemakeBlockerCard.jsx
└── useRemakeJob.js
~~~

职责边界建议：

- remake：理解用户要保留和替换什么。
- video_references：处理人物素材政策、动作代理及安全边界。
- video_generation/providers：映射 Provider 请求格式。
- production：保存方案、分镜、候选和 Revision。
- editing：剪辑、音频、字幕及最终合成。

## 16. 候选 API

以下 API 仅作为讨论草案：

| API | 用途 |
|---|---|
| POST /api/v1/remakes/plan | 生成执行计划、阻塞项和预计成本，不创建付费任务 |
| POST /api/v1/remakes/{id}/generate | 自动保存输入并启动生成 |
| GET /api/v1/remakes/{id}/status | 返回用户可理解的生成阶段 |
| GET /api/v1/remakes/{id}/execution-details | 返回中间资产和请求清单 |
| PATCH /api/v1/remakes/{id}/shots/{shot_id}/overrides | 修改单分镜资产、人物轨迹或策略 |
| POST /api/v1/remakes/{id}/shots/{shot_id}/reprepare | 重新准备单分镜中间资产 |

## 17. 尚未对齐的关键问题

进入实现前，至少还需要明确：

1. “原始视频 + 新人物资产”是否要求尽量由一次 Provider 调用完成，还是允许系统内部多阶段生成。
2. 最终目标更强调像素级复刻、动作级复刻、镜头级复刻，还是结构级复刻。
3. 新人物资产是否始终由 ViralDNA 管理，Provider 托管演员是否只能作为透明映射。
4. 服装和场景未指定时，默认保留原视频还是由人物资产／方案决定。
5. 用户是否需要在分段视频生成前确认替换后的关键帧。
6. 自动模型选择优先考虑质量、成本、速度还是原视频动作还原度。
7. 白模之外是否允许使用深度、遮罩、骨骼、视频重绘等中间表达。
8. 当模型不能完整保留原视频动作时，系统应该阻止、询问还是允许有提示地降级。
9. 一段视频有多个人物时，第一期是否允许同时替换多人。
10. 中间过程的人工修改需要做到什么粒度。

## 18. 后续处理原则

在上述差异完成对齐前：

- 本目录只维护讨论记录。
- 不依据本文新增实现。
- 后续每次修订需要记录日期和关键决策。
- 达成一致后，应生成单独的“已确认实施方案”，不要直接把本讨论稿改名为实施文档。
