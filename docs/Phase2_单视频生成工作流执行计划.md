# Phase 2：单视频生成工作流执行计划

更新时间：2026-08-08

文档状态：Batch 4.1、Batch 4.2.1～4.2.4、Batch 4.3、Batch 4.4.1～4.4.5、Batch 4.5.1～4.5.3、Batch 4.6.1～4.6.6 以及分析记录生命周期 Batch 4.7 已完成；下一主线为 Batch 4.8 质量、安全与成本

## 0. 路线调整与结论

当前产品已经完成单视频导入、真实媒体处理、混合分镜、ASR／OCR／字幕证据、逐镜头 VLM 理解、模型计费、工作区和分析记录持久化。下一阶段优先把这些分析结果转化为可审核、可回退、可继续编辑的生成任务。

原项目路线中的账号分析暂时后移，Phase 2 调整为“单视频生成闭环”：

1. 以一个已完成的分析版本为不可变基础。
2. 创建独立的创作方案，不修改原分析报告。
3. 上传人物、产品、服装、场景和风格参考资产。
4. 为每个分镜生成候选图片并逐一人工确认。
5. 图片全部确认后，为每个分镜生成候选视频并逐一人工确认。
6. 将确认的视频片段、原音轨、字幕和转场写入受控时间线。
7. 通过 FFmpeg 生成预览和最终成片。
8. 任一上游修改只创建新版本并标记受影响的下游结果过期，不覆盖或立即删除旧产物。

Phase 1 的 AnalysisRecord、AnalysisJob、AnalysisReport、PromptPackage 和 ReplacementVersion 继续作为分析域；Phase 2 新增生产域，二者只通过 record_id、base_analysis_id 和 source_prompt_package_id 建立引用。

## 1. 总体目标

### 1.1 用户目标

- 用户可以从一个已完成的分析记录创建多个创作方案。
- 用户可以为人物、产品、场景等上传参考图，并明确每张图的用途和适用镜头。
- 每个镜头独立维护图片提示词、视频提示词、连续性锁和参考资产绑定。
- 图片和视频均支持多个候选、人工确认、退回修改和重新生成。
- 所有分镜图片确认前，默认不允许批量进入视频生成阶段。
- 所有分段视频确认前，不允许生成最终成片。
- 关闭应用或重启服务后，创作方案、资产、候选、审批、费用和版本状态可以完整恢复。
- 用户可以查看修改影响范围，并从任意旧版本创建新分支。

### 1.2 系统目标

- 分析数据不可变，生成工作流单独版本化。
- 模型、Prompt、Schema、参考图和参数全部进入生成请求快照。
- 图片模型、视频模型和剪辑渲染器通过可替换接口接入。
- 相同输入可以按内容指纹复用缓存，避免重复计费。
- 每次调用保存预计费用、实际费用、耗时、重试和失败信息。
- 工作区数据库只保存相对路径，所有生成文件归档到对应记录下。
- 上游变化通过确定性依赖图传播 stale 状态。

### 1.3 Batch 4.1 范围

Batch 4.1 只实现工作流基础，不调用真实图片或视频生成模型：

- ProductionProject 及其版本、分支和步骤状态。
- ReferenceAsset 参考资产库和权利确认。
- ShotPlanRevision 与逐镜头创作配置。
- 依赖关系、审批状态和 stale 传播。
- 创作工作流页面、步骤条、参考资产页和分镜图片工作台。
- 使用真实分析关键帧作为明确标注的模拟候选，验证审核闭环。
- 完整持久化、重复打开、API 测试和 UI 构建验收。

以下内容不属于 Batch 4.1：

- 真实图片模型调用。
- 真实视频模型调用。
- 口型同步、声音克隆或 TTS。
- 完整非线性剪辑器。
- 最终 FFmpeg 成片渲染。
- 多人协作、云同步和权限系统。

## 2. 用户工作流

### 2.1 入口

已完成分析的报告页新增“创建创作方案”主操作。用户点击后：

1. 输入方案名称。
2. 选择基础分析版本和基础 Prompt Package。
3. 选择输出比例、目标分辨率和预算上限。
4. 选择要替换的实体及需要保持不变的属性。
5. 创建 ProductionProject 并进入创作工作流。

同一分析记录可以创建多个创作方案，例如“人物替换版”“产品替换版”“高质量版”和“低成本试验版”。

### 2.2 工作流步骤

工作流固定为六个步骤：

1. 创作方案
2. 参考资产
3. 分镜图片
4. 分段视频
5. 剪辑合成
6. 导出

每一步显示 draft、ready、generating、review_required、approved、stale 或 failed 状态。Batch 4.1 实现前三步和后续步骤的锁定占位状态。

### 2.3 默认推进规则

- 创作方案配置完整后才可进入参考资产。
- 所有必需参考资产完成权利确认后才可进入分镜图片。
- 所有必需分镜图片 approved 后才可进入分段视频。
- 所有必需视频片段 approved 后才可进入剪辑合成。
- 时间线校验通过后才可渲染导出。
- 被标记为 stale 的结果不满足步骤门禁。
- failed 可重试，但失败产物不能审批。

后续可以增加单镜头流水线模式，但首版坚持全局门禁，避免在图片仍可能修改时产生高额视频费用。

## 3. 领域模型

### 3.1 ProductionProject

表示一个独立创作方案，建议字段：

- id
- record_id
- video_id
- base_analysis_id
- source_prompt_package_id
- name
- status
- active_step
- current_revision_id
- output_aspect_ratio
- output_width
- output_height
- budget_limit_micros
- estimated_cost_micros
- actual_cost_micros
- created_at
- updated_at

基础分析版本创建后不可原地切换。若用户需要切换基础分析版本，应创建新的项目或分支。

### 3.2 ProductionRevision

保存一次创作方案快照：

- id
- project_id
- parent_revision_id
- revision_number
- change_kind
- change_summary
- snapshot_relative_path
- created_at

change_kind 第一版支持：

- project_created
- project_settings_changed
- reference_changed
- shot_plan_changed
- image_candidate_selected
- image_approved
- branch_created

每次影响已审批结果的修改必须创建新 Revision。草稿字段在尚未审批前可以自动保存，但点击审批时必须冻结成 Revision。

### 3.3 ReferenceAsset

保存用户上传的参考资产：

- id
- project_id
- type：person、wardrobe、product、scene、prop、style
- name
- description
- relative_path
- mime_type
- width
- height
- sha256
- tags
- rights_confirmed
- rights_note
- created_at
- archived_at

资产删除采用软归档。已被旧版本引用的文件不能物理删除，除非执行明确的工作区清理任务。

### 3.4 ReferenceBinding

描述参考资产如何参与某个镜头：

- id
- shot_plan_id
- reference_asset_id
- role：identity、product、scene、wardrobe、style、layout
- weight
- crop_hint
- notes

原始关键帧固定作为 layout 参考；新人物、产品或场景图通过其他角色绑定。Provider Adapter 后续把标准角色映射为具体模型参数。

### 3.5 ShotPlan

每个分析镜头对应一条创作计划：

- id
- project_id
- revision_id
- source_shot_id
- index
- source_keyframe_url
- start_seconds
- end_seconds
- duration_seconds
- image_prompt
- image_negative_constraints
- video_prompt
- video_negative_constraints
- locks
- required
- image_status
- video_status
- approved_image_candidate_id
- approved_video_candidate_id
- created_at
- updated_at

image_prompt 和 video_prompt 必须分开。图片提示词描述静态画面、身份、产品、构图和灯光；视频提示词描述动作过程、运镜、节奏、时长和结束状态。

### 3.6 GenerationRun

图片和视频共用的调用记录骨架：

- id
- project_id
- shot_plan_id
- kind：image 或 video
- provider
- model
- model_snapshot
- prompt_version
- schema_version
- pricing_version
- request_fingerprint
- input_snapshot_relative_path
- status
- estimated_cost_micros
- actual_cost_micros
- latency_ms
- retry_count
- error_code
- error_message
- created_at
- completed_at

Batch 4.1 建表并支持 simulated 类型，不接真实 Provider。

### 3.7 GenerationCandidate

- id
- generation_run_id
- ordinal
- kind
- relative_path
- thumbnail_relative_path
- width
- height
- duration_seconds
- sha256
- metadata_relative_path
- status
- created_at

候选状态支持 ready、selected、rejected 和 archived。选择候选不等于审批；审批必须产生 ApprovalEvent。

### 3.8 ApprovalEvent

- id
- project_id
- revision_id
- shot_plan_id
- candidate_id
- target_kind：image 或 video
- decision：approved 或 rejected
- reason
- created_at

审批记录不可更新或删除。退回修改会创建新的审批事件和新 Revision。

## 4. 状态机与失效传播

### 4.1 单项状态

~~~text
draft → ready → generating → review_required → approved
                           ↘ failed
approved → stale
~~~

- draft：配置不完整。
- ready：输入完整，可以提交生成。
- generating：任务运行中。
- review_required：已有候选，等待人工确认。
- approved：已冻结一个候选。
- stale：上游输入已变化，旧结果仍保留但不可继续推进。
- failed：本次任务失败，可从相同输入或修改后输入重试。

### 4.2 失效矩阵

| 修改内容 | 标记为 stale 的范围 | 不受影响 |
|---|---|---|
| 修改单镜头图片提示词 | 该镜头图片审批、视频和最终渲染 | 其他镜头 |
| 更换人物或产品参考资产 | 使用该资产的镜头及其下游 | 未绑定该资产的镜头 |
| 修改全局比例、风格或连续性锁 | 全部镜头图片、视频和时间线渲染 | 原分析报告 |
| 更换已审批图片候选 | 对应视频和最终渲染 | 其他镜头图片 |
| 修改单镜头视频提示词 | 对应视频和最终渲染 | 图片审批及其他镜头 |
| 修改裁剪、顺序或转场 | 预览与最终渲染 | 图片和视频审批 |
| 切换基础分析版本 | 创建新项目或分支 | 原项目所有版本 |

### 4.3 传播规则

- 先计算 ChangeImpact，再执行写入。
- API 返回 impacted_shot_ids、stale_candidate_ids 和 stale_stage_ids。
- UI 在保存前展示影响范围，不使用阻断式弹窗；在右侧影响面板中确认。
- 执行修改时，在一个数据库事务中写 Revision、业务变更和 stale 状态。
- stale 只改变可用状态，不删除原文件。
- 如果用户撤销尚未审批的草稿修改，可恢复上一个 Revision 指针。
- 如果用户要恢复已审批旧版本，应从旧 Revision 创建分支。

## 5. 工作区目录

沿用现有 UUID 物理目录和相对路径策略：

~~~text
<workspace>/
├─ .viraldna/
│  ├─ workspace.json
│  └─ workspace.db
└─ records/
   └─ <record_id>/
      ├─ source/
      ├─ analyses/
      ├─ productions/
      │  └─ <project_id>/
      │     ├─ project.json
      │     ├─ references/
      │     │  └─ <asset_id>/
      │     │     ├─ original.<ext>
      │     │     ├─ thumbnail.webp
      │     │     └─ metadata.json
      │     ├─ revisions/
      │     │  └─ <revision_id>.json
      │     ├─ shots/
      │     │  └─ <shot_plan_id>/
      │     │     ├─ plan.json
      │     │     ├─ images/
      │     │     │  └─ <run_id>/
      │     │     └─ videos/
      │     │        └─ <run_id>/
      │     ├─ timelines/
      │     ├─ renders/
      │     └─ exports/
      └─ exports/
~~~

要求：

- 上传文件使用 UUID 对象键，不使用原文件名作为物理路径。
- 所有路径通过 WorkspaceManager 解析并校验不能逃逸工作区。
- 参考图生成缩略图，列表页不直接加载原始大图。
- project.json 和 revision JSON 作为可迁移快照，SQLite 是查询和状态主索引。
- 文件写入继续使用临时文件、校验和原子替换。

## 6. API 设计

### 6.1 创作方案

- POST /api/v1/records/{record_id}/productions
- GET /api/v1/records/{record_id}/productions
- GET /api/v1/productions/{project_id}
- PATCH /api/v1/productions/{project_id}
- POST /api/v1/productions/{project_id}/branches
- GET /api/v1/productions/{project_id}/revisions
- GET /api/v1/productions/{project_id}/revisions/{revision_id}

创建接口必须验证 base_analysis_id 属于当前记录且已完成，并把基础分析、Prompt Package 和镜头列表冻结到首个 Revision。

### 6.2 参考资产

- POST /api/v1/productions/{project_id}/references
- GET /api/v1/productions/{project_id}/references
- PATCH /api/v1/references/{asset_id}
- DELETE /api/v1/references/{asset_id}
- GET /api/v1/references/{asset_id}/content
- GET /api/v1/references/{asset_id}/thumbnail

上传接口使用 multipart/form-data，限制格式、文件大小、像素和数量，并通过真实文件头验证媒体类型。

### 6.3 分镜创作计划

- GET /api/v1/productions/{project_id}/shots
- GET /api/v1/production-shots/{shot_plan_id}
- PATCH /api/v1/production-shots/{shot_plan_id}
- POST /api/v1/production-shots/bulk-update
- POST /api/v1/productions/{project_id}/change-impact

PATCH 默认保存草稿。若修改会使已审批结果过期，客户端先调用 change-impact，确认后携带 expected_revision_id 提交，服务端执行乐观并发校验。

### 6.4 模拟图片审核闭环

Batch 4.1 提供：

- POST /api/v1/production-shots/{shot_plan_id}/image-runs
- GET /api/v1/generation-runs/{run_id}
- POST /api/v1/generation-candidates/{candidate_id}/select
- POST /api/v1/generation-candidates/{candidate_id}/approvals

image-runs 在 simulated 模式下复制或引用该镜头真实关键帧，生成明确标注的模拟候选和零费用 GenerationRun。接口契约与 Batch 4.2 真实图片 Provider 保持一致。

### 6.5 工作流推进

- GET /api/v1/productions/{project_id}/gate-status
- POST /api/v1/productions/{project_id}/advance

服务端是门禁最终判断方。前端禁用按钮只能改善体验，不能替代后端校验。

## 7. 模型与渲染接口预留

Batch 4.1 只定义契约并实现 simulated Provider。Batch 4.2 的图片生成支持两种可切换执行模式：

1. `remote_api`：通过国内大模型平台的官方 API 调用图片生成或图片编辑模型。
2. `local_tool`：调用本机已安装且已完成登录／授权的图片生成工具或 CLI，例如为 Codex imagegen 一类工具提供符合本项目协议的包装器。

两种模式共用业务门面，ShotPlan、候选、审批、门禁和 UI 不判断具体执行方式：

~~~text
ImageGenerationGateway.validate(config) -> ValidationResult
ImageGenerationGateway.capabilities(config) -> CapabilitySnapshot
ImageGenerationGateway.estimate(request) -> CostEstimate
ImageGenerationGateway.submit(request) -> GenerationHandle
ImageGenerationGateway.poll(handle) -> GenerationResult
ImageGenerationGateway.cancel(handle) -> CancelResult

VideoGenerationProvider.generate(request) -> GenerationResult
TimelineRenderer.render(timeline) -> RenderResult
~~~

统一 GenerationRequest 包含：

- project_id、shot_plan_id 和 revision_id
- Prompt IR 和编译后的模型 Prompt
- ReferenceInput 列表
- 输出比例、分辨率、时长和 Seed
- Provider、模型和能力快照
- 预算上限
- 输入文件哈希

ReferenceInput 包含 role、asset_id、relative_path、weight、crop_hint 和 sha256。模型目录以后增加以下能力字段：

- image_to_image
- multi_reference
- max_reference_images
- start_frame
- end_frame
- supported_aspect_ratios
- supported_durations
- native_audio
- maximum_resolution

每次 GenerationRun 额外冻结：

- execution_mode：remote_api 或 local_tool。
- provider_id、adapter_id 和 adapter_version。
- 远端模型 ID 或本机 tool_id、tool_version 和 protocol_version。
- 能力快照、编译后请求、输入文件哈希和执行配置摘要。
- cost_source：provider_reported、configured_rate、unmetered 或 unknown。

业务层不得直接判断具体模型 ID、CLI 名称或可执行文件路径，应根据能力目录和 Adapter 编译请求。

### 7.1 国内大模型 API 模式

- 每个平台实现独立 RemoteImageProvider Adapter，首批只接入一个国内平台，后续可以增加百炼、火山等实现。
- Adapter 负责认证、区域与 Endpoint、模型参数映射、文件上传、任务轮询、取消、错误标准化和用量解析。
- API Key 继续通过 GUI 保存和校验，不写入 GenerationRun、日志、Revision 或导出文件。
- 保存配置时执行低成本认证／能力校验；可能产生费用的生成校验必须在界面明确提示。
- 调用前使用价格目录计算预计费用并执行预算门禁，调用后记录平台返回的实际用量和费用。
- 网络超时、限流、服务繁忙和内容安全错误使用不同错误码；只有明确可重试错误进入指数退避。

### 7.2 本机工具／CLI 模式

- LocalToolImageProvider 是通用进程 Adapter，不把业务代码绑定到 Codex、某个脚本或某个厂商 CLI。
- 若目标工具没有稳定 CLI，先提供一个符合本项目协议的包装器；应用不直接依赖 Codex 内部工具或非公开接口。
- 应用在单次 run 目录写入 `request.json` 和只读输入清单，然后直接启动已配置的可执行文件及固定参数；不使用 shell 字符串拼接。
- 推荐调用形式：`<executable> generate --request <request.json> --output <run-output-dir>`。
- CLI 必须返回版本化 `result.json`，至少包含状态、候选相对路径、媒体类型、宽高、SHA-256、工具版本、可选用量和可选费用。
- 只接收 run 输出目录内部的文件；写入候选前重新校验路径、文件头、尺寸、哈希、数量和最大体积。
- 可执行文件或 Adapter 必须来自用户确认的允许列表；参数使用数组传递，环境变量使用最小允许列表，不把 API Key 或工作区外路径写入命令行。
- 设置页提供“检测工具”，检查文件是否存在、版本、协议版本和能力；真实冒烟生成单独触发，避免校验时意外计费。
- 支持超时、取消、并发上限、退出码、标准错误截断和 Windows 进程树回收；工具失败不能留下已完成候选状态。
- 本机工具不等于免费。若 CLI 自身调用云服务但不能返回用量，cost_source 必须为 unknown，界面明确提示并由预算策略阻止或要求人工确认，不能记为零费用。

### 7.3 双模式配置与切换

- “模型与设置”增加图片生成执行模式切换，分别展示国内 API 配置和本机工具配置。
- 国内 API 配置包括平台、区域、模型、Endpoint、API Key 和默认候选数量。
- 本机工具配置包括 Adapter、可执行文件、固定参数模板、超时、并发上限和输出协议版本。
- 配置校验结果保存 provider/tool 版本和能力快照，不保存密钥明文或任意命令字符串。
- 项目保存默认执行模式；单次 GenerationRun 可以显式覆盖，但覆盖前必须重新显示能力差异和费用信息。
- 请求指纹必须包含 execution_mode、Adapter 版本、模型／工具版本和能力快照，避免跨模式错误复用缓存。
- 两种模式都写入相同 GenerationRun、GenerationCandidate、ApprovalEvent 和成本台账，前端审批流程保持一致。

## 8. UI 设计

### 8.1 页面入口与导航

- 报告页主操作增加“创建创作方案”。
- 分析记录详情增加“分析报告／创作方案”二级切换。
- 创作方案有独立页面状态，不继续扩充现有报告标签栏。
- 页面保持现有紫白配色、卡片、按钮、图标和间距语言。

### 8.2 工作流页头

展示：

- 方案名称和状态。
- 基础分析版本。
- 当前 Revision。
- 预计成本和实际成本。
- 自动保存状态。
- “版本历史”“创建分支”和后续“导出”操作。

页头下方使用六步步骤条。步骤同时显示名称、完成状态和未满足条件数量。

### 8.3 创作方案页

- 左侧显示原视频信息和基础分析版本。
- 中间设置输出比例、分辨率、预算和目标替换元素。
- 右侧显示全局连续性锁和修改影响。
- 保存草稿不会推进；点击“确认方案”冻结 Revision。

### 8.4 参考资产页

- 按人物、服装、产品、场景、道具和风格分组。
- 支持拖拽或选择文件上传。
- 资产卡显示真实缩略图、名称、标签、尺寸、权利状态和被多少镜头引用。
- 点击资产后在右侧检查器编辑描述、标签、适用镜头和权利说明。
- 缺少必需资产时，步骤条显示具体阻塞数量。

### 8.5 分镜图片工作台

桌面端三栏：

1. 左侧分镜导航：原缩略图、序号、时长、状态、当前候选。
2. 中间对比区：原关键帧、当前候选、候选切换和放大检查。
3. 右侧检查器：图片提示词、负面约束、参考绑定、锁定项、成本和操作。

核心操作：

- 保存镜头草稿。
- 创建模拟候选。
- 选择候选。
- 退回修改并记录原因。
- 确认当前分镜。
- 上一个／下一个待确认镜头。
- 筛选待配置、待确认、已确认、已过期和失败。

“保存草稿”和“确认此分镜”必须视觉和语义分离。确认按钮只有在已选择候选且输入快照有效时可用。

### 8.6 版本与影响面板

- 使用右侧抽屉，不以模态框作为默认入口。
- 版本列表显示 Revision、变更摘要、时间和受影响镜头。
- 选择旧 Revision 可以只读预览。
- “从此版本创建分支”生成新的 ProductionProject 分支。
- 修改已审批输入前，影响面板显示将变 stale 的镜头和阶段。

### 8.7 响应式

- 工作台按自身可用宽度响应，不按整个浏览器视口误判：900px 以上使用三栏。
- 621～900px 保留分镜列表和主画布，检查器移动到下方双列区域。
- 620px 以下改为单列：镜头选择、画面对比、配置和操作按任务顺序排列。
- 所有触控操作目标不小于 44px。
- 手机上不隐藏审批、退回、版本和成本等核心功能。

## 9. Batch 4.1 开发任务

### 9.1 数据库与迁移

- 将工作区 schema_version 升级一个显式版本。
- 新增 production_projects。
- 新增 production_revisions。
- 新增 reference_assets。
- 新增 shot_plans。
- 新增 reference_bindings。
- 新增 generation_runs。
- 新增 generation_candidates。
- 新增 approval_events。
- 为 project_id、record_id、revision_id、shot_plan_id 和状态字段建立索引。
- 迁移失败时保留旧数据库并返回可读错误。
- 旧工作区升级后不自动创建创作方案。

### 9.2 后端领域层

- 在 models.py 增加生产域请求、响应和状态模型。
- 新增 production.py，负责状态机、门禁、Revision 和 ChangeImpact。
- 新增 generation.py，定义 Provider 契约、请求快照和模拟 Provider。
- 扩展 workspace.py，解析 productions 目录和参考资产路径。
- 扩展 sqlite_store.py，保存生产域表、事务和查询。
- 扩展 main.py，注册生产域 API。
- 复用现有中文标准化、模型成本字段和 UUID 路径规则。

### 9.3 前端

- App 状态增加当前 ProductionProject、Revision、步骤和 ShotPlan。
- 报告页增加创建创作方案入口。
- 新增创作方案列表和重复打开入口。
- 新增 ProductionWorkspace 页面壳、页头和步骤条。
- 新增 ProjectSetupStep。
- 新增 ReferenceAssetsStep。
- 新增 ShotImageWorkspace。
- 新增 VersionHistoryDrawer 和 ChangeImpactPanel。
- 沿用现有 API 请求、Toast、按钮和卡片样式。
- 不在 Batch 4.1 引入新的前端状态管理库或路由库；先沿用当前单页状态结构。

### 9.4 自动化测试

后端单元测试：

- 状态机合法和非法转换。
- 全局修改与单镜头修改的 stale 传播。
- 旧 Revision 不可修改。
- 创建分支不会改变源项目。
- 参考资产路径不能逃逸工作区。
- 相同哈希资产可以检测重复但不误删旧引用。
- 资产软归档后旧 Revision 仍可读取。
- 模拟 GenerationRun 费用为零且请求快照完整。
- 未审批全部必需镜头时 advance 被拒绝。

API 集成测试：

- 从已完成分析创建创作方案。
- 上传、编辑和读取参考资产。
- 编辑 ShotPlan 并重新打开恢复。
- 创建候选、选择、审批和退回。
- 修改参考资产后只使绑定镜头 stale。
- expected_revision_id 冲突返回明确错误。
- 服务重启后项目、候选和审批仍可查询。

前端验证：

- npm run test:web。
- npm run build:web。
- 桌面、820px 和390px 三种宽度视觉检查。
- 创建方案到四个模拟图片全部确认的浏览器闭环。
- 浏览器控制台无错误。

## 10. Batch 4.1 实施顺序

1. 冻结生产域模型、状态机和失效矩阵。
2. 设计 SQLite 迁移和工作区目录。
3. 实现 ProductionProject、Revision 和 ReferenceAsset 持久化。
4. 实现 ShotPlan、ReferenceBinding 和 ChangeImpact。
5. 实现模拟 GenerationRun、Candidate 和 ApprovalEvent。
6. 完成生产域 API 和契约测试。
7. 完成报告入口、工作流页头和步骤条。
8. 完成参考资产页。
9. 完成分镜图片三栏工作台和审批流程。
10. 完成版本抽屉、分支和 stale 提示。
11. 运行单元测试、API 集成测试、前端构建和响应式验收。
12. 使用目标四分镜样本执行完整人工验收。

第 1～6 项完成前不接真实图片模型。真实 Provider 从 Batch 4.2 开始，以免模型差异掩盖工作流和版本问题。

## 11. Batch 4.1 验收标准

使用记录 2257d6708577851e5cff45bdcc12c9fb_raw 验收：

- 可以基于指定分析版本创建一个创作方案。
- 自动创建四条 ShotPlan，并正确引用四个真实分镜关键帧。
- 可以上传至少一组人物或产品参考图并完成权利确认。
- 可以把资产绑定到指定镜头或全部镜头。
- 每个镜头可以编辑独立图片提示词和锁定项。
- 可以创建真实关键帧模拟候选、选择候选并审批。
- 四个必需镜头未全部审批前不能进入分段视频。
- 四个镜头全部审批后 gate-status 允许进入下一阶段。
- 修改只绑定到一个镜头的参考资产，仅该镜头变 stale。
- 修改全局比例后，四个镜头全部变 stale。
- 旧审批结果和文件仍可查看。
- 可以从审批前 Revision 创建分支。
- 关闭页面并重启 API 后可以恢复所有状态。
- 模拟阶段不产生模型费用。
- 原 AnalysisReport、PromptPackage 和分析版本不发生改变。
- 后端测试、前端测试和生产构建全部通过。

## 12. 后续批次

### Batch 4.2：图片生成闭环

- 建立统一 ImageGenerationGateway，支持 `remote_api` 和 `local_tool` 两种执行模式。
- `remote_api` 首批接入一套国内图片生成／编辑 Provider，并保留后续平台 Adapter 扩展点。
- `local_tool` 实现安全的本机进程 Adapter 和版本化 JSON 输入／输出协议，可接符合协议的 Codex imagegen 类包装器或其他图片 CLI。
- 设置页支持模式切换、国内平台 API Key 校验、本机工具路径／版本／能力检测和项目默认模式。
- 两种模式都支持原关键帧、修改提示词、多参考资产、二至四个候选和统一人工审批。
- 统一实现异步状态、取消、超时、失败重试、请求指纹、缓存和可恢复任务。
- 国内 API 记录预计与实际费用；本机工具按 provider_reported、configured_rate、unmetered 或 unknown 明确记录，unknown 不得伪装为零费用。
- 增加图片文件安全校验、尺寸检查、主体一致性、产品形态和文字异常检查。

Batch 4.2 拆分为：

1. Batch 4.2.1：双模式 Gateway、能力目录、配置模型和 GUI。
2. Batch 4.2.2：首个国内大模型 Remote Adapter、轮询和真实计费。
3. Batch 4.2.3：本机工具 Local Adapter、CLI 协议、安全执行和假 CLI 集成测试。
4. Batch 4.2.4：统一候选 UI、容错、质量检查和四分镜双模式验收。

### Batch 4.3：分镜编排与提示词资产关联

- 分镜支持新增、复制、舍弃、恢复和排序。
- 原始关键帧与 AI 生成图在同一工作台直接选择。
- 图片提示词支持通过 `@资产` 保存稳定资产关联。
- 参考资产显示真实缩略图，并进入生成输入快照。
- 该批次已实现并完成自动化验收。

### Batch 4.4：账户、逻辑工作区与混合资产库

- 增加一个稳定的默认账户，并保留未来登录和服务端身份接口。
- 将工作区从“一个本地路径”升级为逻辑空间；当前本地目录作为一个存储位置。
- 建立 `StorageObject` 与 `ObjectReplica`，允许未来同一文件同时具有本地和云端副本。
- 增加工作区级资产库、一级目录、分页、缩略图和跨项目复用。
- 当前只实现 `local_only` 和本地文件驱动，不接真实云端和同步服务。
- 详细执行方案见《Phase2_Batch4.4_账户工作区与混合资产库执行计划.md》。

### Batch 4.5：分段视频闭环

#### Batch 4.5.1：视频生成基础架构（已完成）

- 增加与厂商无关的 `VideoGenerationAdapter` 契约、请求／结果模型和统一 Gateway。
- 仅启用零模型费用的 `simulated` Provider：将已审批分镜图片生成无音频静态帧 MP4，用于验证完整任务闭环，不宣称是 AI 生成视频。
- 使用已审批图片、视频提示词、负面约束、时长和输出尺寸构建不可变输入快照与请求指纹。
- 复用 GenerationRun、GenerationCandidate、ApprovalEvent 和 Revision，持久化候选视频、缩略图、质量报告、状态、重试、取消和费用快照。
- 增加分段视频任务 API、候选媒体读取、选择、审批、退回、取消采用、重试和服务重启恢复。
- 增加“分段视频”工作台，支持逐镜头播放、多个候选切换、下载、审核和重新生成。
- 所有必需分镜视频 approved 后才允许进入 `editing`；取消采用会回退到 `shot_videos` 并使后续结果失效。
- 每个镜头独立生成，单镜头失败不阻塞其他镜头的任务执行。

Batch 4.5.1 不调用真实视频模型，不生成动作、声音或口型；模拟 MP4 只用于验证架构、状态机、媒体播放和人工审核。

#### Batch 4.5.2：国内视频模型远程 API（已完成）

- 已接入百炼 Wan 2.7、MiniMax H3、MiniMax Hailuo 2.3／Fast 的 `remote_api` 适配层；百炼完成真实调用验收。
- MiniMax H3 使用独立 `/v2` 多模态协议，Hailuo 使用 `/v1` 协议，两者的请求实现物理隔离。
- Seedance 2.0／2.5 保留稳定模型别名和独立 Adapter；在官方 API 未 GA／Model ID 未核验前显示“待开放”并禁止提交。
- 通过现有 Gateway 和 Provider Registry 解耦业务服务、厂商请求格式、模型标识与错误结构。
- 已实现 GUI API Key、官方 Endpoint、默认模型／分辨率、单镜头临时切换、费用估算和余额不足提示。
- 已显式校验图生视频、时长、分辨率、画幅和候选数；不支持参数在调用前阻止。
- 已保存 ProviderTask、请求 ID、模型／能力／价格快照、用量、预计／实际费用和标准错误，并支持不重复提交的重启恢复。
- 真实候选沿用播放、下载、选择、审批、退回、取消采用和阶段门禁。

Batch 4.5.2 **暂不支持 `local_tool` 本机 CLI／工具调用**：

- 公共请求模型、GUI 设置和执行器选择中不提供 `local_tool` 选项。
- 不实现本机工具发现、自动配置、进程启动、沙箱、代理、超时或本机费用预检。
- 架构层只保留 Provider Adapter 协议；未来若明确开启本机视频工具，可新增独立适配器而不修改生产域状态机。

#### Batch 4.5.3：视频体验与音轨衔接（已完成）

- 已增加候选入点／出点、封面帧提取和基础技术质检；候选原文件保持不可变，剪辑准备参数独立版本化保存。
- 已增加逐分镜剪辑准备面板；视频审批完成后仍需通过裁剪时长、文件质量和音轨可用性门禁，才计入“可交接”。
- 已按原分镜时间范围映射原音轨、对白和字幕；连续区间采用连续原音轨，有缺口或混合静音时采用逐镜头映射。
- 推进到 `editing` 时生成 `timelines/editing-handoff.json`，保存片段顺序、裁剪、变速、封面、音轨和文本证据，供 Batch 4.6 直接消费。
- 口型同步、声音克隆、TTS 和生成视频原生音频混合继续后移，不纳入本批。

### Batch 4.6：剪辑与渲染

- [x] 4.6.1：定义并持久化正式 `timeline.json` 和不可变 `TimelineRevision` 快照。
- [x] 4.6.2：实现查询、受控修改、校验、历史查看、历史恢复与乐观锁 API。
- [x] 4.6.3：实现视频、原音轨、字幕和属性检查器组成的受控时间线 UI。
- [x] 4.6.4：实现源音轨映射、字幕轨、直接切换、淡入淡出和叠化。
- [x] 4.6.5：使用 FFmpeg 生成低清预览，保存 `RenderJob` 并接入账户通知。
- [x] 4.6.6：最终高清成片、导出产物、下载与归档。

4.6.1～4.6.5 的实现边界和验收流程见 [Batch 4.6.1～4.6.5：剪辑时间线与低清预览执行验收](./Phase2_Batch4.6.1-4.6.5_剪辑时间线与低清预览执行验收.md)。

4.6.6 的实现边界和验收流程见 [Batch 4.6.6：最终高清渲染与导出执行验收](./Phase2_Batch4.6.6_最终高清渲染与导出执行验收.md)。

### Batch 4.7：分析记录生命周期与批量管理（已完成）

- 当前记录、已归档和回收站三种生命周期。
- 高密度单列列表、筛选、排序、分页和创作方案数量。
- 单条及批量归档、恢复、移入回收站和永久删除。
- 共享视频与资产对象保护、缩略图稳定加载和账户消息通知。

详细实现和人工验收见 [Batch 4.7：分析记录生命周期与批量管理执行验收](./Phase2_Batch4.7_分析记录生命周期与批量管理执行验收.md)。

### Batch 4.8：质量、安全与成本

- 跨镜头人物、服装、产品和场景连续性检查。
- 黄金样本回归和全链路恢复测试。
- 人物肖像和素材权利审计。
- 工作区配额、归档、删除和恢复。
- 项目、阶段、镜头和单次调用四级成本报表。

## 13. 风险与既定决策

### 13.1 多参考图能力不统一

不同模型支持的参考图数量和角色不同。业务层统一保存 ReferenceInput，Provider Adapter 负责能力映射；能力不足时明确阻止调用或给出降级方案，不静默丢弃参考图。

### 13.2 上游修改导致重复计费

任何会使已审批结果 stale 的保存动作都先显示 ChangeImpact。批量生成前再次显示预计费用和预算余额。

### 13.3 图片一致不等于视频一致

图片审批只证明关键帧可接受。视频阶段仍要独立检查人物漂移、产品变形、动作物理性和时长。

### 13.4 音频和口型

第一版分段视频默认不负责重新生成对白。剪辑阶段保留原音轨、现有字幕和时间结构。TTS、声音克隆和口型同步作为独立后续能力。

### 13.5 不做完整剪辑器

产品定位仍是内容分析和生成工作台。首版剪辑只提供完成生成闭环所需的排序、裁剪、转场、音量、字幕和渲染，不复制专业 NLE 的全部能力。

## 14. 执行状态

- [x] 总体生成工作流方案确认
- [x] Batch 4.1 数据、API、UI和验收任务拆解
- [x] 生产域数据模型与 SQLite 迁移
- [x] 工作区 productions 目录
- [x] ProductionProject 与 Revision API
- [x] ReferenceAsset 与上传 API
- [x] 创作方案入口、基础设置、参考资产和版本分支 UI
- [x] 本批前端工具测试、生产构建与响应式验收
- [x] ShotPlan、绑定和 ChangeImpact
- [x] 模拟 GenerationRun 与审批 API
- [x] 分镜图片工作台与审批 UI
- [x] ChangeImpact 与 stale 交互
- [x] Batch 4.1 全链路自动化测试
- [x] 四分镜样本人工验收
- [x] Batch 4.5.1 视频 Provider 抽象与模拟适配器
- [x] 视频任务、候选、审核、回退和阶段门禁 API
- [x] 分段视频播放、下载与人工审核工作台
- [x] Batch 4.5.2.1 稳定模型目录、能力快照和版本化价格目录
- [x] Batch 4.5.2.2 ProviderTask 持久化、幂等提交和重启恢复
- [x] Batch 4.5.2.3 GUI Key 校验、默认模型和默认分辨率
- [x] Batch 4.5.2.4 百炼 Wan 2.7 Adapter 与真实链路验收
- [x] Batch 4.5.2.5 Seedance 2.0／2.5 稳定别名与待开放保护
- [x] Batch 4.5.2.6 MiniMax H3／Hailuo 协议隔离与费用模型
- [x] Batch 4.5.2.7 单镜头模型切换、费用、余额和结果 UI
- [x] Batch 4.5.2.8 自动化测试、文档和人工验收清单

## 15. Batch 4.1 第一部分执行记录（2026-08-04）

已完成：

- 新增统一的工作区 Schema 版本常量，版本由 1 升级为 2。
- 新增 ProductionProject、ProductionRevision、ReferenceAsset、ReferenceBinding、ShotPlan、GenerationRun、GenerationCandidate 和 ApprovalEvent 模型。
- 新增生产步骤、工作流状态、参考资产类型、参考角色、生成类型、候选状态和审批决策枚举。
- 所有生产域文件路径在模型层执行相对路径、父目录逃逸和 Windows 盘符校验。
- SQLite 初始化升级为显式事务迁移；旧 v1 数据原样保留，迁移失败会回滚。
- 新增八张生产域 JSON 记录表和按 record_id、project_id、shot_plan_id、generation_run_id 建立的查询索引。
- SQLiteStore 和 InMemoryStore 已具备生产域保存、读取和列表契约。
- WorkspaceManager 新增 productions、references、revisions、shots、timelines、renders 和 exports 目录工具。
- 工作区元数据升级到 Schema 2；未来版本工作区和数据库会被明确拒绝，不会被静默降级。

验证结果：

- 新增生产域基础专项测试：6 项通过。
- 后端全量测试：65 项通过。
- Ruff 全量检查：通过。
- 当前活动工作区未被手动迁移；下次使用新版 API 启动时由 SQLiteStore 自动执行 v1→v2 迁移。

本部分尚未新增 HTTP API 或前端页面，下一部分从 ProductionProject、Revision 和 ReferenceAsset 服务/API 开始。

## 16. Batch 4.1 第二部分执行记录（2026-08-04）

已完成：

- 新增 ProductionService，集中处理创作方案、Revision、历史版本分支和参考资产生命周期。
- 新增 13 个生产域 HTTP API，覆盖方案创建／列表／详情／设置更新、Revision 列表／详情、历史版本分支，以及参考资产上传／列表／编辑／软归档／原图／缩略图读取。
- 创建方案时校验分析版本属于当前记录且已经完成，并在首个不可变 Revision 中冻结基础分析概览、实体、Prompt Package 和完整镜头列表。
- 方案和参考资产写接口使用 expected_revision_id 执行乐观并发检查；过期页面提交会收到 409，不会覆盖新版本。
- 新增 save_production_bundle，ProductionProject、ProductionRevision、参考资产、分镜和绑定可以在同一 SQLite 事务内提交；InMemoryStore 保持相同契约。
- 每次方案设置、参考资产新增、编辑或归档都会创建新 Revision，并以原子文件替换写入 revisions/{revision_id}.json 和 project.json。
- 历史 Revision 可以只读打开，也可以创建独立分支；分支记录来源项目和来源版本，并复制该历史快照中的有效参考图、ShotPlan 和绑定关系。
- 参考图上传支持 JPG、PNG 和 WebP，通过真实图片内容而不是扩展名校验格式；限制 15 MB、16384 像素、6400 万像素、静态图片和每方案 50 个有效资产。
- 上传时强制权利确认，生成最长边 480 像素的独立 WebP 缩略图，API 响应不暴露工作区内部相对路径。
- 参考资产使用软归档；归档后默认列表隐藏，但历史 Revision、原图和缩略图仍然可读取。
- 方案名称、资产名称、说明、标签和权利说明统一转换为简体中文。
- 工作区文件读写兼容 Windows 扩展长度路径，避免较深工作区下的参考资产路径超过传统 MAX_PATH。
- Pillow 已加入 API 运行依赖，用于安全解码、方向校正和缩略图生成。

验证结果：

- 新增生产域服务与 API 专项测试：4 项通过。
- 覆盖图片真实格式与 MIME 校验、缩略图、分析归属、未完成分析拒绝、Revision 冲突、方案更新、参考图上传／编辑／归档、历史版本分支和 SQLite 重启恢复。
- 后端全量测试：69 项通过。
- Ruff 全量检查：通过。
- 未修改当前活动工作区中的现有业务数据；只有通过新增 API 创建方案时才会产生 productions 内容。

本部分未实现 ShotPlan 编辑、ReferenceBinding 编辑和 ChangeImpact/stale 计算。下一部分从这三项服务与 API 开始，然后再接模拟图片候选和人工审批闭环。

## 17. Batch 4.1 第三部分执行记录（2026-08-04）

已完成：

- 在分析报告页增加“分析报告／创作方案”二级工作区切换，并在报告页头提供“创建方案”快捷入口。
- 创作方案列表使用真实 ProductionProject API，可按当前分析记录查询、打开已有方案，并明确显示空状态、加载状态和失败状态。
- 新增创建方案弹窗，可设置方案名称、9:16／16:9／1:1／4:5 输出画幅、分辨率和预算上限；画幅切换会自动给出对应默认分辨率。
- 新增六步工作流步骤条；“方案设置”和“参考资产”已开放，分镜图片、分段视频、剪辑合成与最终导出保持锁定，避免在后端门禁完成前产生错误推进。
- 新增方案设置页，可修改名称、画幅、分辨率和预算，并携带 expected_revision_id 执行并发保护。
- 新增参考资产页，支持人物、服装、产品、场景、道具和风格分类，提供 JPG／PNG／WebP 上传、权利确认、说明与标签编辑、缩略图展示和软归档。
- 新增版本历史页，可查看 Revision 摘要和变更类型、只读预览任意历史版本，并从指定历史版本创建独立分支。
- UI 沿用现有紫白配色、卡片、按钮和间距语言；桌面、820px 和 390px 视口均无页面横向溢出。
- 修复 React StrictMode 下首次点击“创建方案”时弹窗被重复挂载副作用关闭的问题。

验证结果：

- 前端测试：12 项通过，其中新增 5 项创作工作流工具测试，覆盖画幅尺寸、预算换算与校验、标签规范化、简体中文标签和后续步骤锁定。
- 前端生产构建：通过，Vite 完成 4574 个模块转换并生成 Sites 托管产物。
- 浏览器实测目标记录 2257d6708577851e5cff45bdcc12c9fb_raw：入口可打开弹窗，默认名称正确，9:16 与 16:9 尺寸联动正确；测试过程中未提交方案，未写入样本业务数据。
- 本地页面控制台未发现 ViralDNA 应用错误；仅观察到浏览器扩展自身的警告。

本部分没有实现 ShotPlan／ReferenceBinding 编辑、ChangeImpact／stale 传播、模拟图片候选和审批门禁。下一部分继续完成这些后端能力及对应的分镜图片工作台。

## 18. Batch 4.1 第四部分与最终验收记录（2026-08-04）

已完成：

- 创建创作方案时按基础 AnalysisReport 自动创建 ShotPlan；每个计划冻结源镜头、真实关键帧、时间范围、图片提示词、视频提示词、负面约束和连续性锁。
- 旧方案首次读取时可安全补建缺失的 ShotPlan 和 Revision，不修改原 AnalysisReport、PromptPackage 或分析版本。
- 新增 ShotPlan 单条与批量编辑、ReferenceBinding 全量替换、绑定角色和权重校验，以及工作区内资产归属、归档状态和权利状态校验。
- 新增 ChangeImpact 预检；全局画幅／尺寸修改影响全部镜头，参考资产修改只影响已绑定镜头。已审批输入变更必须显式确认，确认后保留旧候选和审批文件并把受影响镜头标记为 stale。
- 新增零费用模拟图片 Provider：以真实源关键帧生成带候选标识的 JPEG 和 WebP 缩略图，保存不可变输入快照、参考资产哈希、请求指纹、Provider、模型和零成本字段。
- 新增 GenerationRun、GenerationCandidate 和 ApprovalEvent 完整持久化与 API，支持生成、选择、审批、退回和服务重启恢复。
- 新任务会归档旧任务中已选择的候选；旧任务、已归档、已退回、已失效和已被替代的候选不能再次选择或审批。
- 已审批候选不能重复审批；已经推进到分段视频的方案不能重复推进，避免重复 Revision 和审批事件。
- 四个必需镜头全部审批前，gate-status 阻止进入分段视频；全部审批后允许一次性推进到 shot_videos。
- 从历史 Revision 创建分支时复制方案配置、ShotPlan 和绑定，但清空源方案候选 ID 与审批状态，避免跨方案悬空文件引用。
- 新增分镜图片工作台：左侧镜头状态导航，中间原关键帧／候选对比与候选选择，右侧提示词、负面约束、锁定项、参考绑定和必需门禁配置。
- 新增审批、退回原因、过期提醒、影响确认面板、进度统计和阶段推进反馈；审批后操作会锁定，重新编辑已审批输入前会显示影响范围。
- 工作台改为容器响应式；在右侧 VLM 建议栏存在时仍能按真实可用宽度切换为两栏，消除检查器越界。报告页头操作按钮禁止逐字换行。
- 候选媒体地址切换后会重置加载失败状态；已归档候选显示明确状态并禁用操作。

自动化验证：

- 后端全量测试：70 项通过；覆盖自动 ShotPlan、绑定、候选、审批、退回、门禁、stale 传播、旧候选拒绝、重复审批／推进拒绝、历史分支清理和 SQLite 重启恢复。
- Ruff 全量检查：通过。
- 前端测试：13 项通过。
- 前端生产构建：通过，Vite 完成 4575 个模块转换并生成 Sites 托管产物。

目标样本验收：

- 使用记录 `2257d6708577851e5cff45bdcc12c9fb_raw` 和分析版本 `63298ef3-97f8-4dd3-a8b3-d1181cbb8a53` 创建 `Batch 4.1 验收方案`。
- 自动恢复 4 条真实 ShotPlan，镜头范围为 0.0～3.5 秒、3.5～8.8 秒、8.8～15.3 秒和 15.3～18.3 秒，均显示对应真实关键帧。
- 保存 1 项已确认权利的人物参考资产并绑定到第一个镜头。
- 每个镜头生成 2 个零费用模拟候选，完成人工选择和审批；门禁从 0/4 正确推进到 4/4。
- 成功推进到 `shot_videos`，界面显示“已进入分段视频”并禁止重复推进。
- API 重启并重新打开页面后，方案恢复到 Revision 16；4 条审批、候选缩略图、参考绑定和阶段状态均可读取。
- 方案实际模型成本保持为 0；浏览器控制台未发现 ViralDNA 应用错误，仅有浏览器扩展自身警告。

Batch 4.1 到此完成。当前候选是用于验证工作流、版本、文件和门禁的真实关键帧模拟产物，不是大模型重绘结果；接入国内图片生成 API 或本机工具／CLI、真实计费口径、重试和质量检查属于 Batch 4.2。

## 19. Batch 4.2 当前执行记录（2026-08-04）

已实现统一 ImageGenerationGateway、DashScope Qwen Image Remote Adapter、安全本机 CLI Adapter、GUI 双模式设置、API Key 校验、模型能力与价格快照、真实费用门禁、未知成本确认、统一候选 UI、稳定请求指纹、候选缓存复用以及文件／画幅基础质量报告。

## 20. Batch 4.2.4 与 Batch 4.4 收尾记录（2026-08-06）

- 图片生成改为持久化 queued/running 后台任务，创建接口返回 HTTP 202，前端恢复轮询；
- 增加取消、重试、重启恢复、SQLite 原子 claim 和跨 API worker 的本机工具并发槽位；
- 增加可选 VLM 语义质检、结构化人工审核证据、预算门禁和额外 Token／费用归集；
- 完成工作区资产 `ProjectAssetLink`、旧 ReferenceAsset 零拷贝幂等迁移和 Production Snapshot v2；
- 使用 `FakeCloudStorageDriver` 验证同一对象多副本、幂等复制、`download_required` 和 `unavailable`，但未连接真实云端；
- 后端 110 项测试、Ruff、前端 23 项测试、生产构建与本地浏览器冒烟通过；
- 真实百炼／ImageGen 单镜头和四分镜出图仍需用户按人工验收流程明确触发，因为会产生费用或消耗订阅配额。

详细实现边界见 `docs/Phase2_Batch4.2_图片生成双模式执行验收.md` 和 `docs/Phase2_Batch4.4_账户工作区与混合资产库执行计划.md`；人工步骤见 `docs/Phase2_Batch4.4.4_4.4.5与4.2.4_人工验收.md`。

## 21. Batch 4.5.1 执行记录（2026-08-06）

- 完成视频 Provider 抽象、模拟适配器、不可变输入快照、请求指纹、能力／费用快照和质量报告。
- 完成视频任务排队、执行、取消、重试、重启恢复、候选文件与缩略图持久化。
- 完成视频候选选择、审批、退回、取消采用、Revision 记录和 `shot_videos → editing` 门禁。
- 完成分段视频工作台、原生播放器、竖屏完整显示、下载、逐镜头状态和提示词编辑。
- 视频公共执行模式当前只接受 `simulated` 和 `remote_api`；Batch 4.5.2 不提供 `local_tool`，内部 Adapter 仅作为未来扩展点。
- 后端全量 118 项、前端 27 项、Ruff 和生产构建全部通过。
- 本地真实 FFmpeg 预验收生成 1080 × 1920、3.52 秒模拟 MP4，并完成选择、确认采用和取消采用闭环。

详细实现与人工验收步骤见 `docs/Phase2_Batch4.5.1_视频生成基础架构执行验收.md`。

## 22. Batch 4.5.2 执行记录（2026-08-07）

- 完成稳定视频模型目录、版本化价格目录、统一费用估算和未知费用确认。
- 工作区 Schema 升级到 v5；每个候选持久化独立 ProviderTask，上游任务可在服务重启后继续轮询。
- 完成百炼、火山方舟和 MiniMax 的独立 Client、请求映射、错误映射和 Adapter 目录。
- 完成百炼 Wan 2.7 真实 2 秒 720P 调用：生成 720 × 1280 MP4，预计与归集实际费用均为 ¥1.20。
- 完成 MiniMax H3 `/v2` 与 Hailuo `/v1` 协议隔离；H3 支持 768P／2K、4～15 秒和官方按秒价格。
- Seedance 2.0／2.5 因官方 API 状态未满足上线条件而保持禁用，避免使用体验 ID 误调用。
- 设置页支持默认视频模型、分辨率和三家 Key；分镜页支持单次模型切换、费用提示、结果模型标签和余额错误。
- 视频 `local_tool` 仍只保留内部接口，不进入公共 API 或 GUI。

详细架构、模型状态、真实测试记录和人工验收步骤见 `docs/Phase2_Batch4.5.2_国内视频模型远程API执行验收.md`。
