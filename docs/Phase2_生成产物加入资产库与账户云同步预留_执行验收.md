# Phase 2：生成产物加入资产库与账户云同步预留

## 1. 目标与边界

本批次允许把以下中间产物加入资产库：

- 分镜 AI 图片候选；
- 分段视频候选；
- 全场景深度控制视频。

当前仍是单机、本地优先实现。产物不会上传到云端，也不会自动跨设备同步；但数据归属、存储对象、引用关系、同步状态和调度接口均按“未来属于某个账户，并可拥有本地或云端副本”设计。

## 2. 核心原则

### 2.1 账户是最终归属边界

`Asset`、`GeneratedArtifact`、`StorageObject`、`ObjectReplica`、`StorageObjectReference` 和 `AssetProvenance` 均保存 `account_id`。`workspace_id` 表示产物最初所在的工作区，而不是未来云端资产的唯一归属。

当前新增资产使用 `scope=workspace`。未来可在不改变资产 ID 的情况下增加 `scope=account`，让同一账户下的多个工作区引用同一资产。

### 2.2 逻辑资产与物理文件分离

```text
生成候选 / 深度控制记录
        │
        ▼
GeneratedArtifact ────── AssetProvenance
        │                        │
        ▼                        ▼
StorageObject ◄──── StorageObjectReference ──── Asset
        │
        ├── ObjectReplica（本地）
        └── ObjectReplica（未来云端）
```

- `GeneratedArtifact`：冻结生成时的模型、提示词、成本、输入资产和项目上下文。
- `Asset`：用户在资产库中管理的名称、目录、标签、类型和权利状态。
- `StorageObject`：内容寻址后的逻辑文件。
- `ObjectReplica`：同一逻辑文件在本机或未来云端存储位置的副本状态。
- `StorageObjectReference`：显式记录谁正在使用文件，避免清理候选时误删资产文件。
- `AssetProvenance`：资产的可追溯生成快照。

### 2.3 本地加入采用持久硬链接

加入资产库时不会重新复制大文件。系统在工作区的 `objects/` 目录建立持久硬链接，再把该路径登记为资产副本。因此：

- 加入速度与文件大小基本无关；
- 不重复占用同等磁盘空间；
- 原候选文件被清理后，资产副本仍可读取；
- 如果文件系统不支持硬链接，接口明确返回 `zero_copy_unavailable`，不会悄悄退化成不受控复制。

## 3. 数据模型

### 3.1 Asset 新字段

| 字段 | 作用 |
| --- | --- |
| `account_id` | 资产所属账户 |
| `scope` | `workspace` 或未来的 `account` |
| `media_kind` | `image`、`video`、`depth_video` |
| `content_type` | 人物、产品、场景、动作参考、空间深度等语义类型 |
| `origin_kind` | 用户上传、AI 图片、AI 视频、深度生成或平台导入 |
| `origin_artifact_id` | 关联 `GeneratedArtifact` |
| `rights_basis` | 用户确认、系统生成或待复核 |
| `duration_seconds/fps/codec` | 视频类媒体元数据 |

### 3.2 云同步预留

`ObjectReplica` 已预留：

- `last_synced_at`；
- `remote_version`；
- `upload_session_id`；
- `error_code` / `error_message`；
- `state`（上传中、可用、缺失、失败、删除中等）。

`ReplicaSyncScheduler` 是同步调度边界。当前注入 `LocalOnlySyncScheduler`，只保持本地状态，不执行网络操作；未来替换为云端实现即可，无需改生成工作台或资产库调用方。

## 4. API

### 4.1 单个加入

`POST /api/v1/assets/from-generated-artifact`

```json
{
  "kind": "image_candidate",
  "source_entity_id": "候选 ID",
  "shot_plan_id": "分镜 ID",
  "folder_id": null,
  "asset_type": "person",
  "name": "分镜 1 生成人物"
}
```

接口按“账户 + 产物类型 + 来源 ID”幂等；重复调用返回原资产，并设置 `already_existed=true`。

### 4.2 批量加入

`POST /api/v1/assets/from-generated-artifacts/batch`

单次最多 50 项，适合后续增加“把本批次全部加入资产库”。

### 4.3 状态与来源

- `POST /api/v1/assets/generated-artifact-status`：判断按钮是否应显示“已在资产库”。
- `GET /api/v1/assets/{asset_id}/provenance`：读取模型、提示词、输入资产、成本、项目与分镜来源；接口会校验当前账户。

## 5. UI 行为

- 分镜图片候选、视频候选和深度控制视频均提供“加入资产库”。
- 请求中显示“正在加入”；完成后锁定为“已在资产库”；重复打开页面会通过状态接口恢复。
- 图片候选默认进入“其他”；视频候选进入“动作参考”；深度视频进入“空间深度”。
- 默认进入“未分类”，后续可在资产库移动到一级目录、改名和加标签。
- 资产详情可预览图片或播放视频，并显示时长、来源、媒体类型和本地同步状态。

## 6. 未来云端实现路径

1. 增加账户级 `StorageLocation(scope=account)`，配置对象存储 Provider。
2. 实现 `CloudReplicaSyncScheduler`，把本地可用副本加入上传队列。
3. 上传完成后新增或更新云端 `ObjectReplica`，写入 `remote_version`、校验和与同步时间。
4. 资产列表按账户查询，并根据 `Asset.scope` 合并工作区资产和账户资产。
5. 下载端优先使用本地副本；只有云端可用时进入 `download_required`，按需缓存到当前设备。
6. 删除资产前依据 `StorageObjectReference` 计算引用数；只有无引用且符合保留策略时才回收物理副本。

明确不做：当前批次不上传任何文件、不实现登录与权限、不实现跨设备冲突合并、不将 `FakeCloudStorageDriver` 当成真实云存储。

## 7. 人工验收

### 7.1 图片候选

1. 打开创作方案的“分镜图片”。
2. 切换到任一 AI 历史候选。
3. 点击“加入资产库”。
4. 确认按钮变为“已在资产库”。
5. 打开资产库，确认未分类中出现该图片，来源为“ViralDNA 生成”。

### 7.2 视频候选

1. 进入“分段视频”，选择一个已生成的视频候选。
2. 点击“加入资产库”。
3. 在资产库确认类型为“动作参考”，详情可播放，时长正确。

### 7.3 深度视频

1. 打开深度控制区域，确保已有已完成的深度视频。
2. 点击“加入资产库”。
3. 在资产库确认类型为“空间深度”，详情可播放。

### 7.4 幂等与持久性

1. 刷新页面后确认已加入按钮仍为完成状态。
2. 对同一候选重复调用加入接口，确认没有产生第二条资产。
3. 清理原候选后，确认资产库内容仍可打开。

### 7.5 账户与同步边界

1. 查看资产接口响应，确认带有 `account_id`、`scope`、`origin_kind` 与 `sync_state`。
2. 当前所有新增产物应显示 `local_only`，不得显示“已同步云端”。

## 8. 自动回归

- 后端：`test_generated_asset_promotion.py` 覆盖幂等、账户归属、来源快照与源文件删除后的可读性。
- 资产库：原有上传、目录、分页、归档和内容安全 URL 回归继续执行。
- 前端：生产构建必须通过，保证三个工作台入口和视频资产预览可打包。
