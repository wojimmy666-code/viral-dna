# Phase 2 · Batch 4.5.2 国内视频模型远程 API 执行与验收

更新时间：2026-08-10

状态：4.5.2.1～4.5.2.8 已实现；百炼真实链路已通过；MiniMax H3、Seedance 2.0／Fast／Mini 已开放有序多图入口，等待用户最低成本人工验收

## 1. 本批目标与边界

本批把 Batch 4.5.1 的模拟视频闭环升级为可切换的国内远程视频模型执行层。业务层仍只处理项目、分镜、任务、候选、审批、版本和成本，不直接依赖厂商请求格式。

本批明确不提供视频 `local_tool`：

- 公共 API 和 GUI 只提供 `simulated` 与 `remote_api`。
- 保留 `VideoGenerationAdapter`／`VideoProviderAdapter` 扩展接口，但不实现本机 CLI 发现、进程启动或沙箱。
- 未配置 API Key 的 Provider 可以保留空配置；只有实际选择该 Provider 生成时才阻止提交。

## 2. 4.5.2.1～4.5.2.8 完成情况

### 4.5.2.1 模型目录、能力与价格目录

- 使用稳定 `model_alias` 隔离业务数据与厂商 Model ID。
- 每个模型冻结 Provider、Model ID、能力、分辨率、时长、候选数、Prompt 上限和价格版本。
- 价格以整数微元保存，避免浮点金额误差。
- 已知刊例价在提交前估算；未知价格必须显式确认，不能显示为 ¥0。
- `Seedance 2.0`、`Seedance 2.0 Fast`、`Seedance 2.0 Mini` 已使用官方 Model ID 开放；`Seedance 2.5` 在未完成当前工作流能力验收前继续标记为不可用。

### 4.5.2.2 Provider 任务持久化与幂等恢复

- 工作区 Schema 升级到 v5，新增 `video_provider_tasks`。
- 每个候选对应一个独立 ProviderTask，保存提交指纹、上游任务 ID、状态、用量、错误和成本。
- 提交前先写入本地 `pending_submission`，拿到上游 ID 后再更新为 `submitted`。
- 服务重启后优先恢复已有上游任务并继续轮询，不重复提交和扣费。
- 如果提交结果不明确且没有上游任务 ID，任务进入人工核对状态，不自动重提。
- 多候选允许部分成功；失败候选保留错误，成功候选仍可进入人工审核。

### 4.5.2.3 GUI 设置与校验

- “模型与设置”新增“分段视频生成”区域。
- 可启用／停用真实视频生成，设置默认模型和默认分辨率。
- 百炼、火山方舟和 MiniMax 的 Key、官方 Endpoint 分开保存。
- Key 留空表示沿用旧值；未配置的 Provider 允许保存为空。
- 新 Key 保存前执行免费凭证校验；现有 Key 也可单独校验并记录校验时间。
- Endpoint 使用官方 HTTPS 域名允许列表，避免把 Key 发送到任意地址。
- Key 不进入项目、Revision、GenerationRun、ProviderTask、日志或导出文件。

### 4.5.2.4 阿里云百炼 Wan 2.7

- 独立实现 `bailian/client.py`、`request_mapper.py`、`error_mapper.py` 和 `adapter.py`。
- 使用异步图生视频接口，首帧以内嵌 Data URL 发送。
- 支持 720P／1080P、2～15 秒整数时长、任务轮询、取消、下载和错误标准化。
- 720P 按 ¥0.60／秒、1080P 按 ¥1.00／秒预估和归集费用。
- 已使用当前百炼配置完成一次真实 2 秒 720P 测试。

### 4.5.2.5 Seedance 2.0／Fast／Mini／2.5

- 已建立独立的火山方舟 Client、请求映射、错误映射和 Adapter 文件。
- `seedance_2_0`、`seedance_2_0_fast`、`seedance_2_0_mini` 使用官方 Model ID，并通过火山方舟 `/contents/generations/tasks` 提交任务。
- 每张画面以 `role=reference_image` 按图号顺序写入 `content[]`；Provider 提示词把系统“图1～图9”映射为“图片1～图片9”。
- Seedance 2.0／Fast 当前声明最多 9 张有序参考图、4～15 秒、480P／720P／1080P；Mini 声明最多 9 张有序参考图、4～15 秒、480P／720P。费用暂以 Provider 用量为准，生成前必须确认未知费用。
- `seedance_2_5` 官方服务已经开放，但当前有序多图请求、Model ID 与参数边界尚未完成接入验收，因此继续显示不可用。
- Seedance 供应商托管虚拟人物目录、分镜绑定和请求映射已完成；人物身份统一来自托管演员，动作、空间与遮挡来自全场景深度视频，原始真人参考不会提交。目录配置见 [Seedance 托管演员与全场景深度绑定](./Phase2_Seedance供应商托管虚拟资产目录与分镜绑定_执行验收.md)，跨模型策略见 [全场景深度控制与资产重建](./Phase2_全场景深度控制与资产重建_执行验收.md)。

### 4.5.2.6 MiniMax H3 与 Hailuo

- Provider 共用一个 Key，但 H3 与 Hailuo 使用物理隔离的请求映射。
- `MiniMax-H3` 使用 `/v2/video_generation` 多模态 `content[]` 协议，以及 `/v2/query/video_generation/{task_id}` 查询接口。
- H3 支持 768P／2K、4～15 秒整数时长；全能参考模式按 `reference_image` 顺序提交最多 9 张图片，并显式传递目标画幅。
- H3 排队任务支持官方 DELETE 取消；运行中的任务按官方限制可能无法取消。
- Hailuo 2.3／2.3 Fast 继续使用 `/v1/video_generation`、旧查询和文件检索流程。
- H3 价格为 768P ¥0.50／秒、2K ¥0.80／秒；Hailuo 使用官方固定时长价格矩阵。
- 当前未配置 MiniMax Key，因此只完成契约、请求映射、费用和单元测试，未产生 MiniMax 实际费用。

### 4.5.2.7 分镜 UI、费用与错误反馈

- 每个分镜可以临时选择模型和该模型支持的分辨率，不修改全局默认值。
- 生成前显示模型、Provider、Key 配置状态和本次预计费用。
- 结果卡显示实际使用的 Provider、模型、时长、尺寸和实际／估算费用。
- ProviderTask 进度显示已完成任务数；单个候选失败不会伪装成成功。
- 余额不足统一映射为 `video_provider_balance_insufficient`，界面显示“API 余额不足”。
- 未知费用必须人工确认；已知费用继续走项目预算门禁。
- 真实候选沿用播放、下载、选择、退回、确认采用和取消采用流程。

### 4.5.2.8 测试、实测与文档

- Provider 目录、费用、空 Key、Key 校验、余额错误、幂等恢复和模糊提交均有单元测试。
- MiniMax H3 的 `/v2` 多模态请求结构和 `2K` 请求校验有专项测试。
- 后端全量 127 项、前端 29 项、Ruff 和前端生产构建全部通过。
- 使用真实百炼任务验证提交、轮询、下载、候选持久化、模型标签和成本归集。
- 已通过本地页面检查设置区域与分镜视频工作台；未触发第二次付费任务。

## 3. 模型可用状态

| 模型别名 | Provider | 当前状态 | API 协议 | 价格口径 |
|---|---|---|---|---|
| `bailian_wan_2_7_r2v` | 百炼 | 可用，已实测 | DashScope `/api/v1` 异步任务 | 720P ¥0.60／秒；1080P ¥1.00／秒 |
| `minimax_h3` | MiniMax | 可用，待付费实测 | MiniMax `/v2` 全能参考任务 | 768P ¥0.50／秒；2K ¥0.80／秒 |
| `minimax_hailuo_2_3` | MiniMax | 不可用于当前流程 | MiniMax `/v1` 单首帧任务 | 不启用 |
| `minimax_hailuo_2_3_fast` | MiniMax | 不可用于当前流程 | MiniMax `/v1` 单首帧任务 | 不启用 |
| `seedance_2_0` | 火山方舟 | 可用，待付费实测 | 方舟 `/api/v3` 全能参考任务 | Provider 用量回传，生成前确认未知费用 |
| `seedance_2_0_fast` | 火山方舟 | 可用，待付费实测 | 方舟 `/api/v3` 全能参考任务 | Provider 用量回传，生成前确认未知费用 |
| `seedance_2_0_mini` | 火山方舟 | 可用，待付费实测 | 方舟 `/api/v3` 全能参考任务 | Provider 用量回传，生成前确认未知费用 |
| `seedance_2_5` | 火山方舟 | 待当前工作流验收 | Adapter 已预留 | 未启用 |

官方依据：

- [百炼 Wan2.7-I2V 模型与价格](https://help.aliyun.com/zh/model-studio/wan2-7-i2v)
- [百炼 Wan 图生视频调用说明](https://help.aliyun.com/zh/model-studio/image-to-video-general-api-reference)
- [MiniMax H3 视频生成说明](https://platform.minimaxi.com/docs/guides/video-generation)
- [MiniMax H3 V2 创建任务](https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create)
- [MiniMax 视频按量价格](https://platform.minimaxi.com/docs/guides/pricing-paygo)
- [火山引擎 Seedance 2.0 API 全面上线说明](https://developer.volcengine.com/articles/7628567056649125942)
- [Seedance 2.0 可信素材与 `reference_image` 请求示例](https://www.volcengine.com/docs/82379/2315856?lang=zh)
- [Seedance 2.0／Mini 分辨率与时长说明](https://www.volcengine.com/activity/seedance2)

## 4. 主要接口

- `GET /api/v1/settings/video-generation`
- `PUT /api/v1/settings/video-generation`
- `POST /api/v1/settings/video-generation/providers/{provider}/validate`
- `POST /api/v1/video-generation/estimate`
- `POST /api/v1/production-shots/{shot_plan_id}/video-runs`
- `GET /api/v1/generation-runs/{run_id}`
- `POST /api/v1/generation-runs/{run_id}/cancel`
- `POST /api/v1/generation-runs/{run_id}/retry`
- `GET /api/v1/generation-candidates/{candidate_id}/content`

## 5. 百炼真实验收记录

- 测试模型：`wan2.7-i2v-2026-04-25`
- 请求：1 个候选、2 秒、720P、9:16 起始帧
- GenerationRun：`43b1958a-eb66-4ba5-a174-574d870c5dcf`
- Candidate：`7e5b6945-fd00-43e2-adae-5dbdda75ba72`
- 结果：`completed`，ProviderTask 为 `succeeded`
- 输出：720 × 1280、2.0 秒、MP4 约 1.85 MB
- 预计费用：¥1.20
- 归集实际费用：¥1.20，来源 `configured_rate`
- 下载接口支持 Range 请求，浏览器可播放和下载。

由于百炼任务响应提供视频时长但不直接提供订单金额，当前“实际费用”是按成功输出时长与本批冻结的官方单价计算，并通过 `configured_rate` 明确标识，不冒充 Provider 账单回传值。

## 6. 人工验收流程

### 6.1 设置页

1. 打开“模型与设置 → 分段视频生成”。
2. 确认默认模型是“百炼 Wan 2.7 多图参考视频”，默认分辨率是 720P。
3. 确认百炼显示“已连接／已校验”，Key 只显示掩码。
4. 确认火山方舟和 MiniMax 未配置时仍可保存为空。
5. 确认下拉框可选择百炼 Wan 2.7、Seedance 2.0、Seedance 2.0 Fast、Seedance 2.0 Mini 与 MiniMax H3；Seedance 2.5、Hailuo 2.3／Fast 不可选。
6. 切换到 Seedance 2.0／Fast，确认分辨率显示 480P／720P／1080P、时长只能选择 4～15 秒；切换到 Mini，确认仅显示 480P／720P、时长同样为 4～15 秒。
7. 从 1080P 模型切换到 Mini 时，应自动回落到 720P；原时长低于 4 秒时，应自动调整到 4 秒并给出说明。

### 6.2 分镜视频页

1. 打开记录 `2257d6708577851e5cff45bdcc12c9fb_raw`。
2. 进入“创作方案 → Batch 4.1 验收方案 → 分段视频”。
3. 选择分镜 1，确认结果卡显示“百炼 · 百炼 Wan 2.7 图生视频 · 实际 ¥1.20”。
4. 播放候选，确认 2 秒竖屏视频完整显示且可拖动进度条。
5. 点击下载，确认 MP4 可以在本机打开。
6. 点击“选择此候选”，但是否“确认采用”由人工决定；本次自动验收没有替用户审批。

### 6.3 空 Key 与错误反馈

1. 在未配置 MiniMax Key 的情况下临时选择 MiniMax H3。
2. 确认生成按钮被阻止，并明确提示需要到设置页配置 Key。
3. 若后续配置余额不足的 Key，确认任务显示“API 余额不足”，而不是“请求失败”或“¥0”。

## 7. 已知边界与后续工作

- MiniMax H3 与 Seedance 2.0／Fast／Mini 尚未全部执行付费冒烟；配置后建议分别只做一次最低时长、单候选验收。
- Seedance 2.5 与 Hailuo 2.3／Fast 不满足当前有序多图工作流，仍不可选，也不会自动降级成单首帧。
- 本批不生成对白、配音、口型或原生音频。
- 本批不实现首尾帧、视频参考、音频参考和 H3 Context-IR；接口能力可在后续扩展。
- 视频候选仍需人工审批；模型成功不等于人物、产品、动作和物理一致性合格。
- 下一主线为 Batch 4.5.3 视频体验与音轨衔接，之后进入 Batch 4.6 剪辑与渲染。

## 8. 账户消息与紧凑候选布局

### 8.1 页面布局

- 下载入口改为视频右上角悬浮图标，播放器仍保留原生播放、暂停和进度控制。
- 预计费用、Provider 和 Key 状态并入生成操作行；实际费用、模型、时长和分辨率并入候选审核行。
- 页面不再渲染“生成完成／失败”大卡，释放候选预览的纵向空间。

### 8.2 账户级通知

- 通知保存在独立 SQLite 仓储中，并以服务端当前 `account_id` 隔离；仓储协议已为未来云端通知服务预留替换边界。
- 图片／视频任务的排队、执行、成功、失败、取消以及余额不足均写入同一个可幂等更新的事件消息。
- 顶部消息中心支持未读数量、全部／进行中／失败筛选、单条已读、全部已读和业务深链；新完成或失败事件同时显示短暂 Toast。
- 通知 payload 禁止保存 API Key、Token、Authorization、密码或其他凭据字段。

### 8.3 人工验收补充

1. 在“分段视频”中确认下载图标位于候选视频右上角，页面中没有独立的完成状态大卡。
2. 确认生成操作行显示预计费用和 Provider，候选审核行显示模型与实际／预计费用。
3. 完成、失败或取消一次任务，确认右上角出现 Toast，铃铛未读数增加，消息中心出现对应记录。
4. 点击消息中的“查看候选”，确认直接定位到对应创作方案、分段视频和分镜；余额不足消息应跳转模型设置。
5. 标记单条或全部已读，确认未读数同步减少；切换默认账户后不得看到其他账户的消息。
