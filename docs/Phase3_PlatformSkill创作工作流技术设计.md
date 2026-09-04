# Phase 3：Platform Skill 创作工作流技术设计

更新时间：2026-09-03

状态：设计基线，待按批次实施

适用范围：ViralDNA Web、FastAPI、Worker、工作区 SQLite、平台 Skill 目录

## 1. 结论与关键决策

本阶段在现有“原视频分析与复刻”之外增加第二条项目入口：“从 Platform Skill 创作”。两条入口在前半段保持独立，在形成标准化 **ProductionSeed** 后汇入同一套图片生成、视频生成、剪辑、音频、字幕和导出能力。

| 主题 | 设计结论 |
| --- | --- |
| Skill 归属 | Skill 属于平台，不属于某个账户；账户只能浏览、收藏和使用 |
| Skill 版本 | 已发布版本不可变；项目保存完整版本快照和内容摘要，不被平台后续更新影响 |
| 项目模型 | 引入统一 Project，区分 analysis 与 skill 两种 kind |
| 分析依赖 | Skill 项目不创建假视频、假 AnalysisRecord 或假分析报告 |
| 工作流汇合点 | Analysis 与 Skill 都转换成 ProductionSeed，再创建 ProductionProject |
| 风格控制 | Skill 是平台配方；每个项目还必须编译自己的 Style Bible |
| 素材真实性 | Logo、包装、法律文字、认证标识等 exact 素材必须确定性合成，不能依赖模型重绘 |
| 模型与分辨率 | 图片模型、视频模型及对应分辨率由用户主动选择；不得静默选择便宜模型、360p 草稿或替代 Provider |
| 自动化 | 默认 guided；full_auto 必须显式开启并设置预算上限 |
| 时间基准 | 新分镜契约以整数帧为真值，秒数只用于展示 |
| 状态语义 | 执行、系统校验、人工审核分成三个互不冒充的状态轴 |
| 失效传播 | 所有派生产物保存 input_hash 和依赖边，只使受影响分支 stale |
| 音频顺序 | 先锁画面，再生成或选配乐、旁白和音效，最后依据最终语音生成字幕 |
| 前端入口 | 左侧导航新增“Skill 广场”；Skill 项目不显示“分析报告” |
| 兼容策略 | 现有分析项目行为保持不变；物理目录暂时继续使用 records/<project_id>，避免一次性搬迁 |

## 2. 目标与非目标

### 2.1 目标

用户提供“品牌 + 基础素材 + 目标”，选择一个平台 Skill 后，可以完成：

1. 创作简报；
2. 项目风格确认；
3. 大纲和分镜方案；
4. 分镜图片；
5. 分段视频；
6. 视频剪辑；
7. 配乐、旁白、音效和字幕；
8. 最终导出。

系统同时满足：

- 与现有分析型项目共存；
- 可中断、可恢复、可重试、可审计；
- 产物有明确版本、来源、成本和权利状态；
- 单镜头修改不会无条件重做整个项目；
- 平台 Skill 更新不会改变进行中的项目；
- 后半程优先复用现有生成、候选、版本、时间线和导出能力。

### 2.2 非目标

Phase 3 首版不包含：

- 账户自行创建、上传或出售 Skill；
- 在 Skill 中执行 Python、Shell、JavaScript 或任意网络请求；
- 把 Skill 实现成 Codex 的 SKILL.md；
- 在项目页面暴露内部文件夹或 Worker 命令；
- 未经用户确认自动切换模型、Provider、成本档或分辨率；
- 未经授权自动发布成片、购买媒体或覆盖线上资产；
- 把 AI 检查显示为“人工质检通过”；
- 首版实现完整专业 NLE、多用户实时协同或自由节点工作流。

## 3. 术语

| 名称 | 含义 |
| --- | --- |
| Platform Skill | 平台发布的风格与流程配方，只含声明式数据 |
| SkillVersion | 某个 Skill 的不可变已发布版本 |
| SkillVersionSnapshot | 项目启动时保存的 SkillVersion 完整快照 |
| CreativeBrief | 品牌、目标、受众、渠道、时长、素材与约束组成的项目简报 |
| CreativeTreatment | 将简报转成叙事方向、节奏、视觉方法和声音方法的创意方案 |
| Style Bible | 由 Skill、品牌、目标和参考素材编译出的项目级风格锁 |
| Look Test | 批量生图前，用代表性分镜生成的完整画幅风格测试 |
| Shot Manifest | 使用稳定镜头 ID 和整数帧描述的分镜生产清单 |
| ProductionSeed | 分析流或 Skill 流向现有 Production 模块提交的统一输入 |
| Run Contract | 本次运行实际选择的模型、Provider、分辨率、候选数、预算和自动化模式 |
| Artifact | 简报、提示词、图片、视频、音频、字幕、时间线或导出文件等版本化产物 |
| GateDecision | 用户对阶段结果作出的批准、退回或显式跳过决定 |
| DeliveryManifest | 最终交付文件、哈希、媒体参数、权利和质检证据清单 |

## 4. 总体架构

~~~text
                         Platform Control Plane
                    ┌─────────────────────────────┐
                    │ Skill Catalog               │
                    │ Skill Versions / Resources  │
                    │ Publish / Deprecate         │
                    └──────────────┬──────────────┘
                                   │ published snapshot
                                   ▼
┌──────────────────────┐   ┌──────────────────────────────┐
│ Analysis Project     │   │ Skill Project                │
│ source video         │   │ skill + brand + assets       │
│ analysis report      │   │ objective + references       │
└──────────┬───────────┘   └──────────────┬───────────────┘
           │                              │
           │ AnalysisProductionSeedBuilder│ Skill Workflow
           │                              │ brief → style → shots
           └──────────────┬───────────────┘
                          ▼
                   ┌──────────────┐
                   │ProductionSeed│
                   └──────┬───────┘
                          ▼
              Existing Production Domain
      reference assets → images → videos → timeline
                          │
                          ▼
        picture lock → audio/captions → export package
~~~

### 4.1 两条入口

**分析型项目**

- 必须有源视频；
- 继续产生分析报告、证据、爆点和原视频分镜；
- 从已批准分析版本构建 AnalysisProductionSeed；
- 现有“创作意图”仍只修改视频提示词，不反向修改图片提示词。

**Skill 型项目**

- 必须选择已发布的 Platform Skill；
- 不要求源视频，可选上传参考视频；
- 参考视频理解是隐藏的素材处理能力，不创建分析报告页面；
- 使用 CreativeBrief、Style Bible 和 Shot Manifest 构建 SkillProductionSeed；
- 新项目字段使用“项目目标／创作简报”，不复用分析流中只作用于视频提示词的“创作意图”语义。

### 4.2 控制面与项目面分离

平台 Skill 目录属于控制面，项目工作区属于项目面。

- 控制面保存 Skill、版本、封面、示例和平台资源；
- 项目面保存用户输入、版本快照、品牌快照、素材绑定、生成产物和审核记录；
- 项目运行只读取自己的 SkillVersionSnapshot，不在运行中读取“最新 Skill”；
- Skill 被下架后，已有项目仍可读取其快照；若因合规原因被 blocked，则禁止新的付费生成，并显示阻断原因。

## 5. 核心领域模型

### 5.1 Project

统一项目外壳：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 项目稳定 ID；迁移时沿用现有 AnalysisRecord.id |
| account_id | UUID | 项目所属账户 |
| kind | analysis / skill | 项目入口类型 |
| name | string | 项目名称 |
| folder_id | UUID? | 项目文件夹 |
| lifecycle | active / archived / trashed | 生命周期 |
| workflow_status | draft / active / completed / blocked / failed | 总体状态 |
| active_stage | string | 当前用户可见阶段 |
| source_binding | object | kind 对应的来源引用 |
| created_at / updated_at | datetime | 审计时间 |
| last_opened_at | datetime? | 最近打开 |

source_binding 按 kind 校验：

~~~json
{
  "kind": "analysis",
  "video_id": "uuid",
  "latest_analysis_id": "uuid",
  "source_type": "douyin"
}
~~~

~~~json
{
  "kind": "skill",
  "skill_id": "platform.product-cinematic",
  "skill_version_id": "uuid",
  "skill_version_digest": "sha256:...",
  "active_skill_run_id": "uuid"
}
~~~

Skill 项目不允许出现占位 video_id 或 analysis_id。

### 5.2 Platform Skill

**Skill**

- id：稳定平台 ID；
- slug：URL 标识；
- name、summary、category、tags；
- cover_resource_id；
- lifecycle：draft、published、deprecated、blocked；
- current_published_version_id；
- owner_scope 固定为 platform；
- created_by、created_at、updated_at。

**SkillVersion**

- id、skill_id；
- version：语义版本展示值；
- revision_number：平台内部单调递增序号；
- api_version：viraldna.video-skill/v1；
- manifest_json；
- content_digest；
- changelog；
- status：draft、published、deprecated、blocked；
- published_at、published_by。

规则：

- draft 可编辑；
- publish 后内容和资源摘要不可变；
- 修改必须创建新版本；
- deprecated 版本不能用于新建项目，但不破坏已有项目；
- blocked 版本按平台合规策略阻止新的生成调用。

**SkillResource**

- id、skill_version_id、resource_key；
- type：image、video、font、palette、text、example；
- mime_type、byte_size、sha256；
- storage_uri；
- rights_metadata；
- width、height、duration、fps 等可选媒体元数据。

**SkillVersionSnapshot**

- project_id、skill_version_id；
- manifest_json；
- content_digest；
- resource_digest_map；
- copied_at。

它是项目可复现性的最终依据。

### 5.3 品牌、简报与素材

现有 CategoryProfile 继续作为账户级品牌资料来源；Skill 项目创建后生成不可变 **BrandSnapshot**，避免品牌档案后续编辑静默改变项目。

**CreativeBriefRevision**

- project_id、revision_number；
- brand_snapshot_id；
- objective；
- audience；
- distribution_channel；
- target_duration_frames；
- output_aspect_ratio；
- language、locale；
- creative_basis：brand_led、reference_led、hybrid；
- call_to_action；
- required_messages；
- forbidden_messages；
- selected_asset_usage_ids；
- notes；
- input_hash；
- created_by、created_at。

**AssetUsage**

- project_id、asset_id；
- role：product_hero、logo、packaging、person、scene、reference_video、music 等；
- fidelity；
- rights_status；
- allowed_distribution；
- consent_status；
- allowed_transformations；
- claim_evidence_ids；
- required_in_shot_keys；
- snapshot_sha256。

**ClaimEvidence**

- id、project_id；
- claim_text；
- status：approved、restricted、forbidden、unverified；
- evidence_asset_ids；
- allowed_channels；
- required_disclaimer；
- approved_by、approved_at。

未经证据支持的认证、产能、疗效、排名和工艺事实不得由模型补写。

### 5.4 创意方案、Style Bible 与 Look Test

**CreativeTreatmentRevision**

- 核心创意；
- 叙事结构；
- 开场钩子；
- 节奏曲线；
- 视觉方法；
- 产品／人物呈现原则；
- 声音方向；
- CTA；
- 风险和取舍；
- 来源输入摘要。

**StyleBibleRevision**

- skill_version_digest；
- brand_snapshot_digest；
- brief_revision_id；
- reference_fact_digests；
- palette、typography、lighting、composition、camera、motion、texture、rhythm；
- product_identity_lock、character_identity_lock；
- positive_lock；
- negative_lock；
- image_prompt_rules；
- video_prompt_rules；
- validation_checklist；
- input_hash、content_hash。

Style Bible 是项目级编译结果，不等同于 Skill 原文，也不等同于一个长提示词。

**LookTest**

- style_bible_revision_id；
- representative_shot_keys；
- run_contract_revision_id；
- candidate_ids；
- selected_candidate_ids；
- execution_status；
- validation_status；
- review_status；
- decision_note。

默认生成两个代表性完整画幅图片：一个主视觉镜头、一个包含人物或复杂空间关系的镜头。Skill 可以将 Look Test 标为可选，但跳过必须形成显式 GateDecision。Look Test 不是低分辨率视频草稿。

### 5.5 Run Contract

RunContractRevision 保存本次真实执行条件：

- image_provider_connection_id、image_model_id；
- image_width、image_height；
- video_provider_connection_id、video_model_id；
- video_width、video_height；
- video_fps、每类镜头时长能力；
- candidate_count_by_stage；
- text_model_selection；
- audio_source_strategy；
- subtitle_strategy；
- automation_mode：guided、full_auto；
- budget_limit_micros；
- estimated_cost_micros、estimate_status；
- allow_provider_fallback，首版固定 false；
- created_by、created_at。

图片和视频模型及分辨率没有隐式默认值。系统可以展示 Skill 所需能力和推荐项，但用户必须确认实际选择。

### 5.6 运行、步骤、门禁与产物

**SkillRun**

- id、project_id；
- skill_version_snapshot_id；
- run_contract_revision_id；
- current_stage；
- execution_status；
- started_at、updated_at、completed_at；
- cancel_requested_at；
- last_error；
- resume_token。

**SkillStepRun**

- id、skill_run_id；
- stage、operation；
- attempt；
- input_hash；
- execution_status；
- validation_status；
- review_status；
- progress；
- provider、model、request_id；
- estimated_cost_micros、actual_cost_micros；
- started_at、completed_at；
- error_code、error_message、retryable；
- output_artifact_ids。

**GateDecision**

- project_id、skill_run_id、gate；
- decision：approve、request_revision、skip；
- actor_type：user、platform_admin、system；
- actor_id；
- note；
- related_revision_ids；
- created_at。

只有用户或具有对应权限的平台管理员能把 review_status 设置为 approved。system 只能记录技术性 gate 或 skip 条件，不能冒充人工批准。

**Artifact**

- id、project_id；
- kind；
- revision_number；
- source_step_run_id；
- storage_uri、mime_type、byte_size；
- content_hash；
- input_hash；
- producer_version；
- provider、model、generation_parameters；
- selected、stale；
- provenance；
- created_at。

**ArtifactDependency**

- artifact_id；
- depends_on_type；
- depends_on_id；
- depends_on_digest。

### 5.7 Shot Manifest 与 ProductionSeed

**ShotManifestRevision** 是 Skill 前半程的最终结构化输出。每个镜头包含：

- stable_shot_key；
- order；
- narrative_role；
- start_frame、duration_frames；
- handle_in_frames、handle_out_frames；
- description；
- image_prompt、image_negative_constraints；
- video_prompt、video_negative_constraints；
- image_asset_usages；
- video_reference_usages；
- exact_overlay_instructions；
- continuity_group_ids；
- dialogue_or_voiceover；
- caption_intent；
- output_mode；
- required_model_capabilities；
- input_hash。

**ProductionSeed**

- schema_version：viral-dna-production-seed/v1；
- id、owner_project_id；
- origin_type：analysis、skill_run；
- origin_id；
- name；
- output_aspect_ratio、output_width、output_height、fps；
- style_bible_snapshot；
- reference_assets；
- shots；
- audio_intent；
- subtitle_intent；
- content_hash；
- created_at。

ProductionSeed 一经消费即不可变；上游修改会生成新 seed 和新的 ProductionRevision，而不是覆盖历史。

## 6. 状态机与人工门禁

### 6.1 三个状态轴

| 状态轴 | 值 | 回答的问题 |
| --- | --- | --- |
| execution_status | pending、running、succeeded、failed、blocked、skipped、stale | 任务有没有执行成功 |
| validation_status | unchecked、passed、warning、failed | 系统规则或模型检查结果如何 |
| review_status | unreviewed、needs_revision、approved | 人是否接受结果 |

典型组合：

- succeeded + warning + approved：系统有提醒，但用户接受；
- succeeded + failed + unreviewed：产物已生成，但不能推进；
- failed + unchecked + unreviewed：执行失败，没有可审核结果；
- stale + unchecked + needs_revision：上游变化，旧产物保留但不得作为当前结果。

### 6.2 用户可见阶段

| 内部阶段 | UI 名称 | 退出门禁 | 主要产物 |
| --- | --- | --- | --- |
| creative_brief | 创作简报 | G0 brief_approved | CreativeBrief、AssetUsage、RunContract |
| style_confirmation | 风格确认 | G1 style_approved | Treatment、Style Bible、Look Test |
| storyboard_design | 分镜方案 | G2 storyboard_approved | Outline、Shot Manifest、ProductionSeed |
| shot_images | 分镜图片 | G3 images_approved | 图片候选与采用结果 |
| shot_videos | 分段视频 | G4 videos_approved | 视频候选与采用结果 |
| editing | 视频剪辑 | G5 picture_locked | 时间线画面锁定版本 |
| audio_caption | 配乐字幕 | G6 audio_caption_approved | 音乐、旁白、音效、字幕、混音预览 |
| export | 导出 | G7 delivery_approved | 最终视频与 DeliveryManifest |

### 6.3 推进规则

进入下一阶段必须同时满足：

1. 当前阶段必需操作 execution_status 为 succeeded 或被允许 skipped；
2. validation_status 不是 failed；
3. 需要人工门禁时 review_status 为 approved；
4. 所有硬性权利、预算和模型能力检查通过；
5. 当前输入哈希与已批准产物 input_hash 一致。

退回规则：

- request_revision 不删除旧产物；
- 上游输入修改后，受影响下游标为 stale；
- stale 产物可比较、复制设置或恢复，但不能成为当前门禁依据；
- 重新批准必须引用新的 revision。

## 7. 依赖图、哈希与局部失效

### 7.1 哈希规则

input_hash 使用以下内容的规范化 JSON 计算 SHA-256：

- 直接输入对象的内容摘要；
- 所有依赖产物的 content_hash；
- SkillVersionSnapshot digest；
- PromptCompiler 和规则版本；
- 实际 Provider、模型、分辨率及影响输出的参数；
- 随机种子；
- 素材二进制 sha256；
- 用户选择和显式跳过决定。

时间戳、显示名称、请求进度等非语义字段不得进入 input_hash。

### 7.2 失效矩阵

| 发生变化 | 必须 stale | 不应 stale |
| --- | --- | --- |
| 品牌或项目目标 | Style Bible 及其全部下游 | 原始素材文件 |
| 素材权利状态 | 使用该素材的镜头、导出门禁 | 未引用该素材的镜头 |
| Style Bible | Look Test、分镜方案、全部生成与导出 | CreativeBrief 历史 |
| 大纲结构 | Shot Manifest 及其下游 | 已批准 Style Bible |
| 单镜头图片提示词 | 该镜头图片、依赖该图的视频、对应时间线片段与导出 | 其他镜头候选 |
| 单镜头视频提示词 | 该镜头视频、对应时间线片段与导出 | 已批准图片及其他镜头 |
| 采用图片变化 | 该镜头视频和后续 | 其他镜头图片 |
| 采用视频变化 | 当前时间线、混音、字幕和导出 | 已生成但未采用的其他候选 |
| 镜头顺序或时长 | 时间线、配乐、旁白、字幕和导出 | 已生成的静态图片 |
| picture lock 变化 | 音频、字幕、导出 | 已保存的视频候选 |
| 配乐或字幕变化 | 混音预览与导出 | picture lock |

依赖传播使用 ArtifactDependency 图，不使用“阶段编号大于当前阶段就全部清空”的粗粒度策略。

### 7.3 重试

- 网络、限流和 Provider 临时错误：指数退避，最多 3 次；
- 质量未达标：最多 2 次定向修订；
- 每次质量重试只改变一个有诊断依据的变量；
- 始终保留当前最佳候选；
- 需要更换模型、Provider、分辨率或增加预算时暂停并请求用户确认；
- 达到上限后进入 blocked，不进行无限循环。

## 8. 帧级时间与稳定镜头身份

### 8.1 真值规则

- Shot Manifest、ProductionSeed 和新时间线以整数帧为真值；
- fps 是项目输出契约的一部分；
- start_frame、duration_frames 决定时间；
- 秒数由 frame / fps 计算，只用于 API 兼容和 UI 展示；
- stable_shot_key 创建后永不因排序改变；
- order 可变，显示“分镜 1、2、3”由 order 动态计算；
- 新增镜头生成新的 stable_shot_key，复制镜头也不复用原 key。

### 8.2 生成手柄

分段视频生成范围：

~~~text
generation_start = max(0, start_frame - handle_in_frames)
generation_duration = handle_in_frames + duration_frames + handle_out_frames
~~~

剪辑时间线默认裁掉手柄，用户可在衔接处取用。视频候选必须记录其绑定的已采用图片 sha256，图片变化后候选自动 stale。

### 8.3 与现有 ShotPlan 的迁移

现有 ShotPlan 保留 start_seconds、end_seconds、duration_seconds 作为兼容字段，并新增：

- stable_shot_key；
- order；
- timing_fps；
- start_frame；
- duration_frames；
- source_start_frame；
- source_duration_frames；
- handle_in_frames；
- handle_out_frames。

读取旧数据时只在缺少帧字段时执行一次确定性换算并写入新 revision。之后不得在帧和浮点秒之间来回取整。

## 9. 素材忠实度、权利与事实约束

### 9.1 忠实度

| fidelity | 用途 | 允许方式 |
| --- | --- | --- |
| exact | Logo、包装、法律文字、认证标识、UI 截图 | 原像素合成、遮罩、跟踪、透视变换；禁止生成式重绘 |
| identity_lock | 指定人物、产品外形 | 身份参考、受控重建、人工审核 |
| structural | 空间、构图、动作关系 | 可重建，但保留结构关系 |
| style_only | 色彩、材质、光线、摄影语言 | 只提取风格，不复制具体主体 |
| loose_reference | 灵感参考 | 可自由改编，仍受权利和品牌约束 |

如果当前合成或跟踪能力无法满足 exact，系统必须阻止“可公开交付”状态，并提示用户改为人工后期，不得显示已准确复现。

### 9.2 权利状态

每个外部素材必须记录：

- rights_status：confirmed、restricted、unknown、expired；
- owner_or_licensor；
- evidence_asset_id；
- allowed_distribution：internal、public、paid_media、trade_show；
- territory；
- valid_from、valid_until；
- transformation_allowed；
- 对人物素材记录 consent_status。

unknown 可以用于内部风格探索，但默认不能进入公开或付费媒体导出。

### 9.3 确定性合成

ExactOverlayInstruction 至少包含：

- asset_usage_id；
- shot_key；
- placement；
- scale_mode；
- start_frame、end_frame；
- tracking_mode：static、planar、point、manual_keyframes；
- occlusion_policy；
- blend_mode；
- safe_area；
- required_review。

渲染器执行合成，PromptCompiler 只描述预留区域，不要求生成模型“画出正确 Logo”。

## 10. ViralDNA Skill v1 格式

### 10.1 包格式

平台管理员可上传一个受限 ZIP 包：

~~~text
skill-package.zip
├─ skill.yaml
└─ resources/
   ├─ cover.webp
   ├─ sample-01.webp
   ├─ palette.json
   └─ references/
      └─ lighting.webp
~~~

skill.yaml 是唯一清单入口。ZIP 解包必须拒绝绝对路径、父目录跳转、符号链接、可执行文件和未声明资源。数据库是版本、发布和权限的真值；文件树不是业务数据库。

### 10.2 代表性清单

~~~yaml
api_version: viraldna.video-skill/v1
kind: VideoSkill

metadata:
  id: platform.cinematic-product-story
  version: 1.0.0
  name: 电影感产品故事
  summary: 用克制的电影摄影和清晰叙事呈现产品价值
  category: commercial
  tags: [product, cinematic, brand]
  locale: zh-CN
  cover_resource: cover

resources:
  - key: cover
    type: image
    path: resources/cover.webp
    mime_type: image/webp
    sha256: 0123456789abcdef
    purpose: catalog_cover
  - key: lighting_reference
    type: image
    path: resources/references/lighting.webp
    mime_type: image/webp
    sha256: fedcba9876543210
    purpose: style_reference
    fidelity: style_only

spec:
  intent:
    supported_goals:
      - product_launch
      - product_education
      - brand_story
    supported_channels: [douyin, xiaohongshu, wechat_channels]
    duration_seconds:
      min: 10
      max: 60
    aspect_ratios: ["9:16", "16:9", "1:1"]

  intake:
    required_fields:
      - brand
      - objective
      - audience
      - distribution_channel
      - target_duration
      - output_aspect_ratio
    creative_basis:
      allowed: [brand_led, reference_led, hybrid]
      recommended: hybrid
    asset_roles:
      - role: product_hero
        label: 产品主图
        media_types: [image]
        min_count: 1
        max_count: 8
        fidelity: identity_lock
      - role: logo
        label: 品牌 Logo
        media_types: [image]
        min_count: 0
        max_count: 2
        fidelity: exact
      - role: reference_video
        label: 风格参考视频
        media_types: [video]
        min_count: 0
        max_count: 3
        fidelity: style_only
    questions:
      - key: primary_message
        label: 观众看完后最应记住什么？
        type: long_text
        required: true
        max_length: 500

  narrative:
    outline_pattern:
      - key: hook
        target_duration_ratio: 0.15
        purpose: 在首屏建立问题或视觉悬念
      - key: reveal
        target_duration_ratio: 0.25
        purpose: 清楚揭示产品和使用情境
      - key: proof
        target_duration_ratio: 0.40
        purpose: 用已批准事实解释价值
      - key: resolution
        target_duration_ratio: 0.20
        purpose: 收束情绪并给出 CTA
    shot_count:
      min: 4
      max: 12

  style:
    visual_keywords:
      - restrained cinematic product photography
      - tactile material detail
      - intentional negative space
    palette_policy:
      source: brand_then_reference
      max_accent_colors: 2
    composition:
      principles:
        - one dominant subject per shot
        - reserve safe area for deterministic typography
    lighting:
      principles:
        - motivated soft key light
        - controlled specular highlights
    camera:
      allowed_motion: [locked, slow_push, slow_orbit, macro_slide]
      avoid_motion: [random_handheld, unmotivated_whip_pan]
    rhythm:
      cut_density: medium
      require_breathing_shot: true
    typography:
      render_mode: deterministic_overlay
      max_lines: 2
    positive_lock:
      - preserve product silhouette and material identity
      - maintain restrained premium lighting
    negative_lock:
      - no invented certifications or product claims
      - no generated logo or unreadable packaging text
      - no unexplained scene or identity changes

  prompt_rules:
    template_language: viraldna-template/v1
    allowed_variables:
      - brand.name
      - brief.objective
      - brief.audience
      - shot.description
      - shot.narrative_role
    image_sections:
      - subject_and_action
      - environment
      - composition
      - lighting_and_color
      - asset_fidelity
      - negative_constraints
    video_sections:
      - accepted_frame_binding
      - action_progression
      - camera_motion
      - temporal_continuity
      - audio_intent
      - negative_constraints

  continuity:
    default_locks:
      - product_identity
      - character_identity
      - wardrobe
      - screen_direction
      - palette
    allow_intentional_change_with_reason: true

  workflow:
    automation_default: guided
    automation_allowed: [guided, full_auto]
    look_test:
      required: true
      representative_count: 2
      use_output_aspect_ratio: true
    gates:
      - brief_approved
      - style_approved
      - storyboard_approved
      - images_approved
      - videos_approved
      - picture_locked
      - audio_caption_approved
      - delivery_approved

  generation_policy:
    user_must_select:
      - image_model
      - image_resolution
      - video_model
      - video_resolution
    allow_silent_provider_fallback: false
    image_capabilities:
      - multi_reference
      - aspect_ratio_control
    video_capabilities:
      - image_to_video
      - duration_control
    recommended_candidate_counts:
      look_test: 2
      shot_image: 2
      shot_video: 1

  audio:
    music:
      timing: after_picture_lock
      strategy: coherent_full_timeline_track
      allow_library: true
      allow_upload: true
    voiceover:
      enabled: optional
      timing: after_picture_lock
    sound_effects:
      enabled: optional
    mix:
      target_lufs: -14
      true_peak_dbtp: -1

  captions:
    source: final_speech_track
    deterministic_render: true
    safe_area_required: true
    max_lines: 2

  quality:
    hard_rules:
      - exact_assets_not_redrawn
      - no_unverified_claims
      - required_rights_confirmed_before_public_export
    continuity_dimensions:
      - product
      - person
      - wardrobe
      - action
      - screen_direction
      - lighting
      - palette

  delivery:
    require_manifest: true
    require_content_hashes: true
    require_media_probe: true
    subtitle_modes: [burned_in, sidecar]
~~~

### 10.3 清单校验

导入时必须校验：

- api_version 和 kind；
- metadata.id、version 和平台唯一性；
- 所有 resource path 位于 resources/ 内；
- 清单 sha256 与文件一致；
- 资源 MIME、大小、分辨率和时长限制；
- 枚举、字符串长度、数组数量和模板变量白名单；
- gate 顺序与平台支持的工作流一致；
- 不允许命令、脚本、环境变量、密钥、Provider base_url 或回调 URL；
- 不允许指定账户私有 asset_id；
- 不允许在清单中硬编码实际模型凭证；
- generation_policy 不得关闭用户对模型与分辨率的确认；
- exact 资源必须声明确定性渲染方式；
- 发布前执行结构校验、资源校验、安全校验和示例运行。

### 10.4 模板语言边界

viraldna-template/v1 只支持白名单字段的字符串插值：

- 无循环；
- 无函数；
- 无文件访问；
- 无网络访问；
- 无条件执行代码；
- 无动态对象遍历；
- 未知变量直接校验失败。

优先由 PromptCompiler 拼装结构化 prompt sections，而不是让 Skill 保存一整段不可解释的提示词。

## 11. Prompt 编译与语义隔离

PromptCompiler 的输入优先级：

1. 平台安全和事实规则；
2. AssetUsage、权利和 ClaimEvidence；
3. 项目 Style Bible；
4. 当前 Shot Manifest；
5. 用户对当前镜头的显式修改；
6. 模型适配器格式化。

不得让低优先级输入覆盖权利、事实和 exact 资产规则。

图片和视频提示词分开编译：

- 图片提示词描述静态主体、场景、构图、光线、色彩和资产约束；
- 视频提示词绑定已采用图片哈希，描述动作进程、运镜、时间连续性和声音策略；
- 修改视频提示词不重写图片提示词；
- Skill 项目上游的 CreativeBrief 会参与首次分镜设计，但一旦 Shot Manifest 获批，后续“视频创作意图”只影响视频分支；
- 分析型项目继续保持现有“创作意图仅作用于原始视频提示词”的规则。

## 12. 与现有 Production 的汇合

### 12.1 Builder 接口

~~~text
ProductionSeedBuilder
├─ AnalysisProductionSeedBuilder
│  └─ completed analysis + prompt package + source ranges
└─ SkillProductionSeedBuilder
   └─ approved brief + style bible + shot manifest
~~~

ProductionService 新增 create_project_from_seed(seed)，原 create_project() 改为：

1. 校验已完成分析；
2. 调用 AnalysisProductionSeedBuilder；
3. 调用 create_project_from_seed。

Skill 工作流在 G2 通过后：

1. 调用 SkillProductionSeedBuilder；
2. 保存不可变 ProductionSeed；
3. 调用 create_project_from_seed；
4. 将 Skill Project 的后半程绑定到返回的 ProductionProject。

### 12.2 ProductionProject 演进

新增：

- owner_project_id；
- origin_type；
- origin_id；
- production_seed_id；
- style_bible_revision_id；
- timing_fps。

现有 record_id 暂时作为 owner_project_id 的兼容别名。以下字段改为仅分析来源必需：

- video_id；
- base_analysis_id；
- prompt_source_analysis_id；
- source_prompt_package_id。

模型校验：

- origin_type=analysis 时要求分析字段齐全；
- origin_type=skill_run 时禁止伪造分析字段，并要求 production_seed_id 和 style_bible_revision_id。

### 12.3 Seed 到 ShotPlan 映射

| ProductionSeed.shot | ShotPlan |
| --- | --- |
| stable_shot_key | stable_shot_key、source_shot_id 兼容值 |
| order | order、index 展示兼容值 |
| frame timing | 新帧字段和秒数投影 |
| image prompt | image_prompt、image_negative_constraints |
| video prompt | video_prompt、video_negative_constraints |
| asset usages | prompt mentions、managed bindings、exact overlays |
| continuity locks | locks 与连续性快照 |
| output mode | output_mode |

Skill 镜头的 source_kind 新增 skill_generated，不使用 blank 冒充。

## 13. 时间线 v3、配乐和字幕

### 13.1 正确生产顺序

~~~text
采用分段视频
  → 生成无配乐画面粗剪
  → 调整节奏与转场
  → G5 picture lock
  → 选择或生成一条全片一致的配乐
  → 可选旁白与音效
  → 基于最终语音生成字幕
  → 混音预览
  → G6 人工批准
  → 最终导出
~~~

禁止在画面时长仍频繁变化时反复生成最终配乐和字幕。

### 13.2 Timeline v3

在现有 viral-dna-timeline/v2 上新增：

- frame_rate 分数表示；
- clip 的 frame timing；
- picture_lock_revision_id；
- A1 clip audio：采用视频候选自带音频、源片段音频或静音；
- A2 narration：旁白片段；
- A3 music：全片配乐，可裁剪、循环、淡入淡出；
- A4 sfx：多个音效片段；
- T1 subtitles：绑定最终 speech revision；
- exact overlay track；
- mix_revision_id；
- audio loudness 与 peak 检查结果。

v2 保留给既有项目；新 Skill 项目直接创建 v3。稳定后再为分析项目提供显式升级，不在读取时静默改写。

### 13.3 音频规则

- 每个视频候选必须记录 candidate_audio_available；
- 用户明确选择候选原音、源视频音频或静音；
- 生成模型是否生成新音频属于视频生成请求的显式参数；
- 不得因服务重启或候选切换回退到另一音频来源；
- 全片配乐默认是一条连续资产，而不是每个分镜单独生成；
- 旁白改变后字幕 stale；
- picture lock 改变后旁白、配乐、音效、字幕和混音 stale；
- 最终渲染以保存的 timeline revision 为唯一输入。

## 14. API 设计

### 14.1 Platform Skill 目录

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/v1/skills | 已发布 Skill 列表、分类、搜索和分页 |
| GET | /api/v1/skills/{slug} | Skill 详情和当前发布版本 |
| GET | /api/v1/skills/{slug}/versions/{version} | 可访问版本详情 |
| POST | /api/v1/skills/{skill_id}/favorite | 收藏 |
| DELETE | /api/v1/skills/{skill_id}/favorite | 取消收藏 |

收藏是账户覆盖层，不改变 Skill 的平台所有权。

### 14.2 项目与启动

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/v1/projects | 统一列出 analysis 与 skill 项目 |
| POST | /api/v1/projects | 创建项目外壳 |
| GET | /api/v1/projects/{project_id} | 项目详情和 kind 对应导航 |
| PATCH | /api/v1/projects/{project_id} | 名称、文件夹、生命周期 |
| POST | /api/v1/projects/{project_id}/skill-snapshot | 固定已发布 Skill 版本 |
| PUT | /api/v1/projects/{project_id}/brief | 新建 CreativeBrief revision |
| PUT | /api/v1/projects/{project_id}/run-contract | 新建 RunContract revision |
| PUT | /api/v1/projects/{project_id}/asset-usages | 更新项目素材用途 |
| POST | /api/v1/projects/{project_id}/preflight | 权利、能力和成本预检 |
| POST | /api/v1/projects/{project_id}/skill-runs | 启动或续跑 |

所有写请求携带 expected_revision_id 或 If-Match，生成请求同时支持 Idempotency-Key。

### 14.3 运行与审核

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/v1/skill-runs/{run_id} | 当前运行与各阶段状态 |
| GET | /api/v1/skill-runs/{run_id}/events | SSE 进度流 |
| POST | /api/v1/skill-runs/{run_id}/cancel | 请求安全取消 |
| POST | /api/v1/skill-runs/{run_id}/resume | 从可恢复点继续 |
| POST | /api/v1/skill-runs/{run_id}/steps/{step}/retry | 重试指定步骤 |
| POST | /api/v1/skill-runs/{run_id}/gates/{gate}/decision | 批准、退回或允许时跳过 |
| GET | /api/v1/projects/{project_id}/artifacts | 产物和 stale 状态 |
| GET | /api/v1/projects/{project_id}/dependency-impact | 修改前影响预览 |

### 14.4 平台管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/v1/admin/skills | 创建 Skill |
| POST | /api/v1/admin/skills/{id}/versions | 创建草稿版本 |
| PUT | /api/v1/admin/skill-versions/{id} | 编辑草稿 |
| POST | /api/v1/admin/skill-versions/{id}/validate | 校验清单和资源 |
| POST | /api/v1/admin/skill-versions/{id}/publish | 发布不可变版本 |
| POST | /api/v1/admin/skill-versions/{id}/deprecate | 停止新项目使用 |
| POST | /api/v1/admin/skill-versions/{id}/block | 合规阻断 |

平台管理接口只允许 platform_admin。

## 15. 数据存储与迁移

### 15.1 平台目录存储

生产环境使用平台 PostgreSQL 和对象存储：

- skills；
- skill_versions；
- skill_resources；
- skill_publication_events；
- account_skill_favorites。

本地开发可以使用只读 seed catalog adapter，但其契约必须与生产目录一致。封面和示例走 CDN 或签名对象 URL。

### 15.2 工作区 SQLite

当前工作区 Schema 为 v13。建议：

**v14：统一项目与 Skill 快照**

- projects；
- skill_version_snapshots；
- brand_snapshots；
- creative_brief_revisions；
- asset_usages；
- claim_evidence；
- run_contract_revisions。

**v15：运行、产物和依赖**

- skill_runs；
- skill_step_runs；
- gate_decisions；
- artifacts；
- artifact_dependencies；
- style_bible_revisions；
- look_tests；
- shot_manifest_revisions；
- production_seeds。

**v16：帧时间与 Timeline v3**

- 为 ProductionProject 和 ShotPlan 增加新契约字段；
- timeline v3 revisions；
- audio assets、mix revisions；
- delivery_manifests。

迁移必须事务化、可重复执行，并在打开更高版本工作区时拒绝降级写入。

### 15.3 既有 AnalysisRecord 迁移

- 为每个现有 AnalysisRecord 创建同 UUID 的 Project(kind=analysis)；
- 现有分析、视频、报告和物理文件引用不移动；
- AnalysisRecord API 暂由兼容适配器读取 Project 公共字段和分析专属数据；
- 生命周期修改在同一事务内同步旧读模型，直到旧接口退役；
- 项目列表改读 ProjectRepository；
- 不改变现有 /projects/{id} URL。

### 15.4 文件布局

首版继续使用内部目录 records/<project_id>：

~~~text
records/<project_id>/
├─ project/
│  ├─ skill-version-snapshot.json
│  ├─ brief/
│  ├─ style-bible/
│  └─ storyboard/
├─ assets/
├─ generations/
│  ├─ images/
│  ├─ videos/
│  └─ audio/
├─ timelines/
└─ delivery/
~~~

SQLite 保存业务状态和引用，JSON 与媒体文件是版本化产物或快照，不作为唯一业务真值。后续改名为 projects/<id> 必须另做可恢复迁移，不能和本阶段首批混在一起。

## 16. UI 与交互

### 16.1 左侧导航

建议顺序：

1. 新建项目；
2. 项目；
3. Skill 广场；
4. 资产库；
5. 设置。

Skill 广场使用 Compass、Sparkles 或 Blocks 类图标，与“项目”图标区分。侧边栏不增加“我的 Skill”；如果保留收藏，文案是“收藏”，只表示个人快捷入口。

### 16.2 Skill 广场

路由：

- /skills；
- /skills/:slug；
- /skills/:slug/start。

广场页面：

- 顶部输入框：“描述你想制作的视频，或选择一个 Skill 开始”；
- 分类：推荐、专业影视、商业广告、短剧漫剧、动漫游戏、音乐 MV、自媒体创作、通用；
- 搜索和筛选：渠道、画幅、目标时长、是否需要人物、素材要求；
- Skill 卡片：封面、名称、摘要、适用目标、素材要求、示例、使用量、收藏；
- 不展示账户所有者，不出现上传 Skill 或编辑 Skill。

详情页：

- 风格说明和适用场景；
- 输入素材要求；
- 典型工作流和人工审核点；
- 示例成片；
- 支持画幅、时长和所需生成能力；
- 预计调用范围，不承诺固定成本；
- “使用此 Skill”。

### 16.3 创建 Skill 项目

采用渐进式创建：

1. 选择 Skill 版本；
2. 选择或新建品牌档案，并创建 BrandSnapshot；
3. 填写项目目标、受众、渠道、时长、画幅和 CTA；
4. 按 Skill 声明的角色添加素材并确认权利与忠实度；
5. 主动选择图片模型、图片分辨率、视频模型、视频分辨率和候选数；
6. 展示能力兼容检查、预计成本、未知成本和预算上限；
7. 选择 guided 或显式开启 full_auto；
8. 创建项目。

如果必填模型或分辨率未选择，开始按钮保持不可用，并显示具体缺项。

### 16.4 Skill 项目工作区

顶部展示八阶段进度；阶段页面显示：

- 当前输入版本；
- 执行状态；
- 系统校验状态；
- 人工审核状态；
- 本阶段成本和耗时；
- 修改影响范围；
- 版本比较；
- 批准、退回、重试或在允许时跳过。

Skill 项目不渲染“分析报告”入口。直接访问分析报告路由时返回明确的 409 业务响应或导航到当前 Skill 阶段，而不是制造空报告。

### 16.5 分镜方案

页面同时支持：

- 大纲视图：叙事段落、时长比例、信息点；
- 分镜卡视图：稳定 shot key、显示顺序、时长、资产、图片提示词、视频提示词；
- 时间分配视图：以帧为存储、以秒和时间码展示；
- 局部重新编译；
- 修改前影响预览；
- 一键批准后生成 ProductionSeed。

### 16.6 后半程复用

G2 后进入现有 ProductionWorkflow：

- 分镜图片复用候选生成、采用和历史；
- 分段视频复用显式多模态引用、模型设置、候选与音频策略；
- 视频剪辑复用 VideoEditorWorkspace；
- 在 picture lock 后增加独立“配乐字幕”阶段视图，底层复用 Timeline 服务；
- 导出复用现有预览和最终渲染，并增加 DeliveryManifest。

### 16.7 项目列表

统一项目列表增加来源徽标：

- 视频分析；
- Skill · <Skill 名称>。

搜索、归档、回收站和文件夹对两种项目一致。筛选可按项目 kind 和 Skill 分类进行。

### 16.8 平台后台

新增平台管理页面：

- Skill 列表与发布状态；
- 版本差异；
- YAML 编辑或表单编辑；
- 资源上传和摘要校验；
- 示例绑定；
- 校验报告；
- 发布、弃用、阻断；
- 使用量、失败率、平均成本和用户退回点。

## 17. 模型能力、成本和预算

### 17.1 能力预检

开始付费阶段前检查：

- 连接是否可用；
- 模型是否支持所需输入模式；
- 参考图数量限制；
- 画幅、分辨率、时长和 fps；
- 是否支持生成音频；
- 并发和区域限制；
- 当前费率是否已知；
- 预计调用数是否超过预算。

能力不匹配时列出可选模型，由用户重新选择。系统不自动切换。

### 17.2 成本预检

成本按阶段和调用拆分：

- 文本规划；
- Look Test；
- 分镜图片；
- 分段视频；
- 音乐或语音；
- 预览渲染；
- 最终导出。

每项显示候选数、模型、分辨率、时长、单价来源、预计金额和是否未知。未知成本必须显示“未知”，不能显示 ¥0。

full_auto 必须：

- 显式开启；
- 设置硬预算上限；
- 达到 80% 时提示；
- 预计下一步会超限时 blocked；
- 模型或价格变化时重新确认。

## 18. 安全、权限和隐私

- Skill 发布仅限 platform_admin；
- 普通账户只读已发布 Skill；
- Skill 清单按严格 Schema 解析，禁止任意代码；
- ZIP 防路径穿越、解压炸弹和伪造 MIME；
- Skill 文本作为数据输入 PromptCompiler，不视为系统指令；
- 平台资源使用内容寻址和签名 URL；
- 项目资源遵循现有账户隔离；
- 日志不记录 API Key、Cookie、完整敏感提示词或签名 URL；
- 导出前检查素材权利、人物授权、ClaimEvidence 和分发渠道；
- 生成权限不等于发布权限；
- 版本 blocked、凭证撤销或权利过期时给出可恢复的业务阻断。

## 19. 可恢复性与可观测性

每个步骤记录：

- project_id、run_id、step_run_id；
- stage、operation、attempt；
- queue_wait_ms、provider_ms、postprocess_ms、total_ms；
- provider、model、request_id；
- 输入和输出哈希；
- 估算与实际成本；
- 错误码、重试原因；
- 产物 ID；
- 状态变更事件。

恢复原则：

- 状态先持久化再发布 SSE；
- Provider 请求使用幂等键或保存外部 request_id；
- 服务重启后 running 步骤先 reconcile，再决定继续、成功或失败；
- 已完成且 input_hash 相同的步骤不重复付费调用；
- 取消只停止尚未开始或 Provider 支持取消的任务，不删除已完成产物；
- Worker 租约超时后可被安全接管；
- 前端断线重连后从事件序号恢复，不依赖浏览器内存进度。

## 20. 分阶段实施

### Phase 3 Batch 5.1：统一项目、Seed 与帧契约

- 新增 ProjectRepository 和 Project API；
- v14 迁移现有 AnalysisRecord 为同 UUID 的 analysis Project；
- 定义 ProductionSeed 和两个 Builder；
- ProductionService 改为从 Seed 创建；
- ProductionProject 支持两种 origin；
- ShotPlan 增加 stable_shot_key 和帧字段；
- 不开放 Skill UI。

验收：

- 全部既有分析项目和 Production 测试保持通过；
- 创建分析 Production 的结果与改造前语义一致；
- 无 video_id 的 skill seed 可通过领域层创建 ProductionProject；
- 重排镜头不改变 stable_shot_key；
- 时间换算无累计漂移。

### Phase 3 Batch 5.2：平台 Skill 目录与 v1 Schema

- 新增 platform_skills 后端模块；
- 实现 manifest 校验、资源摘要、发布和弃用；
- 实现生产目录接口和本地 seed adapter；
- 增加 Skill 广场、详情、收藏；
- 增加后台版本发布 UI。

验收：

- 发布版本不可修改；
- 项目快照与平台后续更新隔离；
- 恶意路径、脚本和未声明资源导入失败；
- 普通账户不能发布 Skill；
- 广场不出现账户所有 Skill 的语义。

### Phase 3 Batch 5.3：简报、素材账本、Style Bible 与 Look Test

- 创建 Skill 项目向导；
- BrandSnapshot、CreativeBrief、AssetUsage、ClaimEvidence；
- RunContract 和成本／能力预检；
- Treatment 与 Style Bible 编译；
- Look Test 和 G0、G1；
- v15 运行、产物和依赖图。

验收：

- 未选模型或分辨率不能开始；
- exact、unknown rights、unverified claim 正确阻断；
- Look Test 使用用户选定画幅；
- AI 校验不显示为人工批准；
- 修改单一输入只使正确分支 stale。

### Phase 3 Batch 5.4：大纲、分镜与 Production 汇合

- 生成和编辑 Outline；
- 生成 Shot Manifest；
- 帧级时长分配和稳定镜头身份；
- 局部重编译；
- G2 后创建 SkillProductionSeed；
- 进入现有图片和视频生成模块；
- 增加 G3、G4。

验收：

- Skill 项目全过程没有 AnalysisReport；
- 图片／视频提示词独立；
- 采用图片哈希绑定视频候选；
- 单镜头重做不使其他镜头 stale；
- 后半程候选和版本能力与分析项目一致。

### Phase 3 Batch 5.5：Picture Lock、音频字幕与交付

- Timeline v3；
- 帧级剪辑和手柄；
- G5 picture lock；
- 连续配乐、可选旁白和音效；
- 最终语音驱动字幕；
- G6；
- DeliveryManifest 和 G7。

验收：

- picture lock 之前不能生成最终字幕；
- 音频来源不会静默改变；
- 画面变化正确使音频和字幕 stale；
- exact overlay 进入最终渲染；
- 导出包包含哈希、媒体参数、权利摘要和质检证据。

### Phase 3 Batch 5.6：自动化、恢复与规模化

- 显式 full_auto；
- 预算硬门禁；
- Worker 恢复和 Provider reconcile；
- 阶段级耗时与成本观测；
- Skill 运营分析；
- 黄金样本、故障注入和端到端回归。

验收：

- 服务重启不重复已确认的付费调用；
- 超预算自动 blocked；
- Provider 失败遵守重试上限；
- 更换模型必须用户确认；
- 可定位每个阶段的等待、模型和后处理耗时。

## 21. 测试与总体验收

### 21.1 后端自动测试

- Skill v1 Schema 正反例；
- ZIP 安全和资源摘要；
- 发布版本不可变；
- Project v14 迁移和回滚备份；
- analysis、skill 两类 source_binding 校验；
- ProductionSeed Builder 契约；
- 帧／秒转换和重排稳定性；
- 三状态轴和 Gate 状态机；
- 依赖图局部 stale；
- 幂等启动、重试、取消和恢复；
- 权利、ClaimEvidence 和 exact 阻断；
- 成本未知与预算上限；
- Timeline v3、混音和 DeliveryManifest。

### 21.2 前端自动测试

- Skill 广场搜索、分类、详情和收藏；
- 创建向导必填项和模型选择；
- Skill 项目不显示分析报告；
- 三状态轴文案不混淆；
- Gate 批准和退回；
- stale 影响提示；
- 大纲／分镜编辑和稳定 key；
- 后半程路由复用；
- picture lock、音频、字幕和导出门禁；
- 桌面、平板和手机响应式。

### 21.3 端到端样例

至少维护三套脱敏黄金项目：

1. brand_led：只有品牌和产品图片；
2. reference_led：带有权利确认的参考视频；
3. hybrid：品牌、产品、人物和风格参考混合。

每套验证：

- 从创建到导出；
- 中途修改一个镜头；
- 服务重启恢复；
- Provider 临时失败；
- 成本接近上限；
- Skill 发布新版本后旧项目保持一致；
- exact Logo 和已批准 Claim 不被模型改写。

### 21.4 完成定义

只有同时满足以下条件才算首版完成：

- 用户能在没有源视频和分析报告的情况下创建 Skill 项目；
- 项目可以从简报走到最终导出；
- 平台 Skill 不属于账户且版本可复现；
- 现有分析型项目无行为回归；
- 模型、分辨率和付费选择由用户确认；
- 人工批准与系统校验严格区分；
- 修改影响可解释且局部失效；
- 最终交付可追溯到 Skill、输入、模型、素材、权利和审核记录。

## 22. 首批代码边界

Batch 5.1 建议新增：

~~~text
services/api/src/viral_dna_api/
├─ projects/
│  ├─ contracts.py
│  ├─ repository.py
│  ├─ service.py
│  └─ routes.py
├─ production_seeds/
│  ├─ contracts.py
│  ├─ builders.py
│  └─ service.py
└─ migrations/
   └─ workspace_v14.py

apps/web/src/
├─ projects/
│  ├─ project-routes.js
│  ├─ project-api.js
│  └─ project-kind-ui.js
└─ skill-workflow/
   └─ contracts.js
~~~

第一批只建立统一项目、Seed 和时间契约，不同时实现 Skill 广场。这样可以先证明“没有分析报告也能合法进入 Production”，再叠加目录和生成式前半程。

现有 services/api/src/viral_dna_api/models.py 已较大，新领域对象应优先放入独立 contracts.py；通过现有 API 响应模型做兼容导出，避免继续扩大单文件。

## 23. 需要保留的参考启发与明确舍弃项

本设计吸收参考文档中的以下原则：

- brand_led、reference_led、hybrid 三种创作依据；
- Skill、项目 Style Bible、Run Contract 三层分离；
- Look Test；
- 素材忠实度、权利、授权和 ClaimEvidence；
- 稳定镜头 ID、帧时间和生成手柄；
- 三状态轴、阶段门禁和局部失效；
- 先 picture lock，再处理全片音频和字幕；
- 有上限的重试和保留最佳候选；
- DeliveryManifest。

明确不采用：

- 以 Markdown 文件树作为唯一数据库；
- 面向用户暴露脚本命令和内部目录；
- 在 Skill 内嵌可执行代码；
- 把产品描述成 Agent 或 Worker 命令系统；
- 默认完全自动执行；
- 静默替换 Provider、模型或分辨率；
- 把系统检查称为人工质检；
- 将生成权限等同于发布、采购或线上覆盖权限。

## 24. 默认建议与暂缓决策

以下作为首版默认：

- Platform Skill 只允许平台管理员发布；
- 项目固定 Skill 版本，不自动升级；
- guided 为默认；
- Look Test 默认为必需；
- exact 资产必须经过确定性合成；
- 图片和视频模型及分辨率必选；
- silent provider fallback 关闭；
- Skill 项目直接使用 Timeline v3；
- 分析项目保持 Timeline v2，后续显式升级；
- 账户品牌资料先复用 CategoryProfile，项目内保存 BrandSnapshot。

暂缓到后续版本：

- 用户自定义／私有 Skill；
- Skill 市场交易和创作者分成；
- 多人审批流；
- 自动发布到内容平台；
- 专业级多层 NLE；
- 将 records 物理目录整体迁名；
- 跨项目自动学习并修改已发布 Skill。
