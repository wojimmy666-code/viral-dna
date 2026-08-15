# Phase 2 · Seedance 供应商托管虚拟资产目录与分镜绑定

更新时间：2026-08-15

状态：基础架构、火山方舟目录接入、分镜绑定、模型人物参考策略、图片／视频白模与 Seedance 请求映射已完成；等待使用具备高级创作权限的真实账号人工验收

人物参考的跨模型策略、图片／视频白模与服务端最终安全门，统一见 [视频人物参考策略与图片／视频白模代理](./Phase2_视频人物参考策略与图片视频白模代理_执行验收.md)。本文聚焦火山方舟托管资产目录和分镜绑定。

## 1. 目标

当普通真人参考图被 Seedance 拒绝时，ViralDNA 可以改用火山方舟已审核的虚拟人物或已验证真人资产。用户不需要复制、粘贴资产 ID，而是在分镜视频工作台直接浏览供应商目录并绑定人物身份。

本功能只管理“供应商托管资产的引用关系”，不复制供应商资产到 ViralDNA 本地资产库，也不把它伪装成本地图片资产。

## 2. 领域抽象

### 2.1 模型能力

每个视频模型通过 `managed_assets` 声明能力，而不是在页面中判断模型名称：

- `supported`：是否支持供应商托管资产。
- `provider`：目录所属供应商；本期为 `volc_ark`。
- `catalog_provider`：目录读取适配器。
- `asset_kinds`：`virtual_person`、`verified_person`。
- `roles`：本期只实现 `actor_identity`。
- `maximum_bindings`：单个分镜最多可绑定的托管资产数；本期为 1。
- `reference_transport`：本期为 `asset_uri`。
- `requires_matching_project`：目录资产与推理 API Key 是否必须属于同一个 ProjectName。

未声明该能力的模型不会显示托管人物选择入口，也不能携带托管资产提交任务。以后新增其他供应商时，只增加目录适配器、模型能力和请求映射，不修改分镜业务模型。

### 2.2 分镜绑定

`ShotPlan.managed_asset_bindings` 保存稳定引用，包含：

- Provider、Asset ID、Asset URI。
- 资产类型、媒体类型和用途角色。
- 资产名、分组名、预览图、ProjectName 等显示快照。
- 绑定时间。

保存绑定时后端会重新向供应商查询资产，不能仅信任浏览器传来的 ID、状态和类型。只有存在、状态为 Active、ProjectName 匹配且类型受支持的资产才能写入分镜。

变更或清除绑定会创建新的分镜 Revision，并使旧的视频生成结果进入过期状态；历史候选仍保留，不会被物理删除。

## 3. 凭证与权限

火山方舟视频推理 API Key 与资产目录 AK/SK 是两套凭证：

- 视频生成继续使用已有方舟 API Key。
- 资产目录使用 Access Key、Secret Key、Region、ProjectName，通过火山 OpenAPI HMAC 签名访问。
- Secret Key 只保存在本机运行配置中，不进入项目、Revision、GenerationRun、日志、通知或导出文件。
- 页面只回显脱敏 Access Key，不回显 Secret Key。

账号需要开通高级创作能力，并给 AK/SK 配置资产相关权限，例如 `ark:*Asset*`。资产的 ProjectName 必须与视频推理 API Key 所属 ProjectName 一致，否则供应商可能在提交生成任务时拒绝请求。

## 4. Provider 目录适配器

本期实现 `managed_assets/volc_ark.py`，负责：

- `ListAssetGroups`：读取虚拟人物或已验证真人分组。
- `ListAssets`：分页读取资产、预览图、状态和媒体类型。
- `GetAsset`：保存绑定前进行权威复核。
- 将火山错误统一映射为 ViralDNA 错误码，不向前端泄露签名、AK/SK 或原始请求头。

ViralDNA 接口：

- `GET /api/v1/managed-assets/providers/volc_ark/status`
- `GET /api/v1/managed-assets/providers/volc_ark/catalog`
- `GET /api/v1/managed-assets/providers/volc_ark/assets/{asset_id}/preview`

目录接口支持 `kind`、`group_id`、`query`、`page` 和 `page_size`。页面只展示可用于推理的 Active 资产，支持虚拟人物／已验证真人、分组、搜索和分页。

火山返回的素材 URL 有时效性。分镜绑定只保存它作为审计快照；绑定卡使用 ViralDNA 的稳定预览入口按需调用 `GetAsset` 获取新 URL，再以短时私有缓存重定向，避免数小时后缩略图失效。

## 5. Seedance 请求映射

选择托管人物后，Seedance 请求将供应商资产放在普通参考图之前：

```json
{
  "type": "image_url",
  "image_url": { "url": "asset://asset-..." },
  "role": "reference_image"
}
```

若供应商资产是视频，则使用 `video_url` 与 `reference_video`。Provider Prompt 只使用“图片1”或“视频1”引用该身份源，不会把 Asset ID 写入自然语言提示词。

人物身份与本地素材规则：

- 供应商托管人物是唯一身份来源。
- 原始真人或身份不明的本地参考图、原视频不会提交给 Seedance。
- 姿态、动作和运动节奏可选用身份去除校验通过的图片／视频白模；场景、产品等素材必须明确分类为无人内容。
- 白模只传递动作、位置、构图与节奏，禁止作为身份、年龄、五官或服装来源。
- 托管资产与安全代理共同计入模型的最大参考素材数量。
- 白模生成失败时必须阻止或改为只使用托管演员，不能自动回退到原始真人素材。

这条映射只存在于 Seedance Provider 文件中；其他视频模型不会收到 `asset://`。

## 6. GUI 与交互

### 6.1 模型与设置

火山方舟设置中新增“托管虚拟资产目录”：

- Access Key、Secret Key。
- Region：北京或上海。
- ProjectName。
- 保存时调用目录 API 校验凭证、权限和项目配置。

校验失败时保留旧的有效配置，并显示可操作的权限、区域或 ProjectName 错误。

### 6.2 分镜视频工作台

- 兼容模型显示“托管人物身份”卡片。
- 点击后从右侧打开供应商资产抽屉。
- 可按虚拟人物／已验证真人、分组和名称筛选。
- 卡片展示供应商缩略图、名称、分组与类型，不提供手动 Asset ID 输入框。
- 选择后立即保存到当前分镜 Revision。
- 清除或更换资产时，已生成视频按既有变更影响机制标记为过期。
- 当前模型不兼容已绑定资产时，界面阻止生成并提供切换到兼容 Seedance 模型的入口。
- Seedance 模型显示“托管演员 + 无身份动作”策略，可分别生成图片白模和原分镜视频白模。
- MiniMax／百炼等允许原始人物参考的模型显示“原始素材可用”，不强制生成白模。

## 7. 错误和安全边界

- 未配置 AK/SK：提示前往模型设置，不请求目录。
- AK/SK 无效：提示重新配置目录凭证。
- 缺少 IAM／高级创作权限：提示在火山控制台授权。
- Region 或 ProjectName 不匹配：提示修正配置，不能绕过校验保存绑定。
- 资产处理中、失败、下线或不存在：不能绑定。
- 模型不支持该资产类型／角色／传输协议：生成前阻止请求。
- Provider 暂时不可用：保留已有分镜绑定和历史候选，可稍后重试。

ViralDNA 不尝试通过改图、改提示词或伪造身份绕过 Seedance 真人安全策略；只能使用供应商认可的托管虚拟人物或已验证真人流程。

## 8. 人工验收

### 8.1 设置与目录

1. 打开“模型与设置 → 分段视频生成 → 火山方舟”。
2. 填写视频 API Key；在“托管虚拟资产目录”填写具有权限的 AK、SK、Region、ProjectName。
3. 保存，确认显示目录凭证已验证；刷新页面后 Secret Key 不应回显。
4. 故意使用错误 ProjectName 或无权限 AK/SK，确认保存失败且给出明确错误。

### 8.2 浏览与绑定

1. 打开一个创作方案的“分段视频”阶段，选择 Seedance 2.0／Fast／Mini 中声明支持托管资产的模型。
2. 打开“托管人物身份”，确认能看到供应商分组、缩略图、虚拟／真人类别、搜索和分页。
3. 选择一个 Active 虚拟人物；刷新页面，确认分镜仍显示相同资产。
4. 切换到不支持托管资产的模型，确认系统阻止生成并解释模型不兼容。
5. 清除绑定，确认分镜保存成功且旧视频候选被标记为过期而非删除。

### 8.3 实际生成

1. 绑定一个虚拟人物；原始真人关键帧可以保留在项目中作为创作依据，但不应直接提交给 Seedance。
2. 可选生成图片白模或当前分镜的原视频白模；不需要动作代理时也可以仅使用托管人物和文字提示词。
3. 生成一个最低成本视频候选。
4. 在供应商任务详情中确认请求使用 `asset://...` 作为第一个身份参考，并且没有原始真人图片或原视频。
5. 确认自然语言 Prompt 使用“图片1”／“视频1”，没有出现 Asset ID；白模只被描述为无身份动作参考。
6. 检查输出人物身份来自托管人物；启用白模时只影响动作、构图和运动节奏。
7. 更换托管人物或停用白模后重新生成，确认新 Revision 和新候选不覆盖历史结果。

## 9. 自动回归

- 后端全量测试通过。
- Python Ruff 检查通过。
- 前端 122 项测试通过。
- 前端生产构建通过。
- 新增专项覆盖：模型能力、HMAC 签名、目录过滤、分镜绑定、引用顺序、图片／视频托管资产映射、身份 Prompt、GUI 无手工 ID、设置凭证隔离与参考数量门禁。

## 10. 官方依据

- [火山方舟资产管理](https://www.volcengine.com/docs/82379/2333565?lang=zh)
- [列出资产分组](https://www.volcengine.com/docs/82379/2318272?lang=zh)
- [列出资产](https://www.volcengine.com/docs/82379/2318273?lang=zh)
- [Seedance 参考素材请求](https://www.volcengine.com/docs/82379/2315856?lang=zh)
- [资产权限与使用约束](https://www.volcengine.com/docs/82379/2377608?lang=zh)
