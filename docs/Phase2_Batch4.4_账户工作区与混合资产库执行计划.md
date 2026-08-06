# Phase 2 · Batch 4.4 账户、逻辑工作区与混合资产库执行计划

更新时间：2026-08-06

阶段状态：Batch 4.4.1～4.4.5 已完成；当前仍只启用本地存储，真实云端 Provider 明确保留为后续实现。

## 1. 批次定位

Batch 4.4 在继续分段视频生成之前，先补齐账户、工作区和资产库的基础设施，使人物、产品、服装、场景等参考资产可以跨创作方案复用，并为未来“部分文件在本地、部分文件在云端”的混合工作区保留稳定扩展点。

本批只实现单机、本地存储和一个默认账户，不实现登录、权限、真实云端上传和自动同步。但是业务模型、文件引用、API 和 UI 状态不得把“工作区”写死为一个物理目录，也不得把资产写死为一个本地相对路径。

## 2. 当前基线

当前系统已经具备：

- 一个可由 GUI 切换的活动本地工作区；
- 工作区内 SQLite 数据库和相对路径安全校验；
- 分析记录、创作方案、分镜、参考资产和生成候选持久化；
- 项目级 `ReferenceAsset`、真实缩略图、`ReferenceBinding` 和提示词 `@资产` 关联；
- 所有核心实体使用 UUID，创作方案使用不可变 Revision 和乐观并发控制。

当前限制：

- `WorkspaceManager` 同时承担逻辑工作区、活动目录和本地文件解析职责；
- API 只能表达一个活动路径，账户无法管理多个已登记工作区；
- `ReferenceAsset` 归属于单个项目，不能作为账户／工作区资产复用；
- `ReferenceAsset.relative_path`、缩略图路径和其他业务模型直接依赖本地工作区；
- 一个逻辑文件无法表达本地副本、云端副本和本地缓存等多份实体；
- FFmpeg、VLM、本机 CLI 和下载接口直接依赖可访问的本地路径。

## 3. 已确认的产品与架构决策

### 3.1 账户

- 第一版只有一个自动创建的默认账户，不做注册、登录、角色和权限。
- 默认账户拥有工作区、项目、分析记录、资产和模型费用记录。
- 所有新增业务实体必须包含明确的 `account_id` 或可通过 `workspace_id` 稳定追溯到账户。
- 账户接口保留服务端身份接入点，但本批不签发 Token，也不模拟多用户切换。

### 3.2 工作区

- `Workspace` 是逻辑业务空间，不等同于一个磁盘目录或一个 Bucket。
- 一个账户可登记多个工作区，但同一时间仍只有一个活动工作区。
- 一个工作区可以拥有多个 `StorageLocation`。
- 当前只创建一个本机 `local_filesystem` 存储位置。
- 未来工作区可使用 `local`、`cloud` 或 `hybrid` 元数据模式；本批固定为 `local`。

### 3.3 文件和副本

- 资产、源视频、缩略图、音频、字幕、生成图和导出文件统一引用逻辑 `StorageObject`。
- `StorageObject` 不保存物理路径；物理位置由一个或多个 `ObjectReplica` 表达。
- “上传到云端”表示为同一个 `StorageObject` 增加云端副本，不创建新资产，也不改变项目引用。
- “释放本地空间”表示删除本地副本；只有存在校验成功的其他副本时才允许执行。
- 逻辑目录改名或移动只修改元数据，不移动底层文件。

### 3.4 资产

- `Asset` 是工作区级可复用实体，目录只是组织方式。
- 项目通过 `ProjectAssetLink` 使用资产，不复制资产文件。
- 分镜绑定和提示词 `@资产` 最终使用稳定 `asset_id`，显示名称只作为可读标签。
- 资产采用软归档；被 Revision、分镜或生成输入快照引用时不得物理删除唯一健康副本。

## 4. 三层架构

```text
账户控制面 Account Catalog
├─ 默认账户
├─ 设备安装实例
├─ 已登记工作区
└─ 当前活动工作区

工作区元数据面 Workspace Catalog
├─ 项目、分析记录、分镜和 Revision
├─ 资产目录、资产和项目资产关联
├─ 存储位置、存储对象和副本记录
└─ 版本、软删除和未来同步游标

文件数据面 Object Storage
├─ 当前：本地文件系统驱动
├─ 未来：OSS／COS／S3／服务端驱动
└─ 本地物化缓存
```

### 4.1 账户控制面

账户控制面需要独立于任何一个工作区，否则应用在打开工作区之前无法列出和切换工作区。

本批实现 `LocalAccountCatalogRepository`，保存默认账户、安装实例、工作区登记信息和活动工作区 ID。绝对本地路径只保存在当前设备的工作区登记记录中，不写入项目快照，不随工作区导出，也不上传到未来服务端。

未来可增加 `RemoteAccountCatalogRepository`，但账户和工作区服务不依赖具体实现。

### 4.2 工作区元数据面

当前继续使用工作区内 `.viraldna/workspace.db` 作为权威元数据源，通过 `WorkspaceRepository` 访问。

未来预留：

- `LocalWorkspaceRepository`：当前 SQLite；
- `RemoteWorkspaceRepository`：服务端工作区；
- `HybridWorkspaceRepository`：本地缓存加服务端增量同步。

本批不实现元数据同步，但新增实体统一使用 UUID、UTC 时间、`version` 和 `deleted_at`，避免以后为了冲突合并重做主键和删除语义。

### 4.3 文件数据面

业务服务不能再通过 `Path(workspace_root, relative_path)` 直接读取新文件。所有新文件读写必须进入 `StorageManager`，由它选择存储位置和健康副本。

FFmpeg、VLM 和本机 imagegen 等必须使用本地路径的工具统一调用 `materialize_local(storage_object_id)`。当前直接返回本地副本路径；未来云端文件会先下载到受管理的本地缓存。

## 5. 数据模型

### 5.1 Account

```text
id
display_name
status                 active / disabled
version
created_at
updated_at
deleted_at
```

默认账户在首次启动时生成并持久化 UUID，不使用每次启动变化的临时 ID。

### 5.2 DeviceInstallation

```text
id
account_id
name
platform
app_version
last_seen_at
created_at
```

本地副本必须关联设备安装实例，因为“本地可用”只对某一台设备成立。

### 5.3 Workspace

```text
id
account_id
name
catalog_mode            local / cloud / hybrid
default_storage_policy
version
created_at
updated_at
deleted_at
```

`Workspace` 不保存唯一 `root_path`。

### 5.4 WorkspaceRegistration

保存在账户控制面，用于当前设备找到工作区：

```text
id
workspace_id
device_id
locator_type            local_directory / remote_endpoint
local_root              仅本机可见
availability
last_opened_at
```

现有 `VIRAL_DNA_WORKSPACE_ROOT` 在迁移后仅作为首次登记兼容来源，不再是工作区身份。

### 5.5 StorageLocation

```text
id
workspace_id
name
provider_type           local_filesystem / oss / cos / s3 / server
device_id               云端位置为空
status                  online / offline / error
capabilities            read / write / signed_url / multipart_upload
config_reference        密钥或配置引用
priority
version
created_at
updated_at
```

普通 DTO 不返回本地根路径、Bucket、Object Key 或密钥。

### 5.6 StorageObject

```text
id
workspace_id
object_type             source_video / thumbnail / asset_image / generated_image /
                        audio / subtitle / analysis_file / export_file
original_filename
mime_type
size_bytes
sha256
version
created_at
deleted_at
```

文件内容发生变化时创建新的 `StorageObject`，不原地覆盖旧内容。

### 5.7 ObjectReplica

```text
id
storage_object_id
storage_location_id
object_key
state                   pending / uploading / available / missing / failed / deleting
etag
checksum
is_cache
is_pinned
last_verified_at
created_at
updated_at
```

`object_key` 只对对应存储驱动有意义，不进入项目快照和普通业务响应。

### 5.8 AssetFolder

```text
id
workspace_id
parent_id               本批固定为空，只支持一级目录
name
sort_order
version
created_at
updated_at
deleted_at
```

同一工作区同一级目录名称唯一。

### 5.9 Asset

```text
id
workspace_id
folder_id
content_object_id
thumbnail_object_id
type                    person / product / clothing / scene / logo / other
name
description
tags
rights_confirmed
rights_note
version
created_at
updated_at
archived_at
```

### 5.10 ProjectAssetLink

```text
id
project_id
asset_id
usage_role
created_at
archived_at
```

同一项目和资产只有一条有效关联。`ReferenceBinding` 可以继续描述某个分镜如何使用资产。

## 6. 存储策略与状态

预留策略：

- `local_only`：只保存本地副本，本批唯一可写策略；
- `cloud_only`：只保存云端副本；
- `local_preferred`：优先本地，没有时读取云端；
- `cloud_preferred`：权威副本在云端，本地按需缓存；
- `mirrored`：要求本地和云端各有健康副本；
- `on_demand_cache`：云端文件在使用时物化到本地缓存。

面向 UI 的 `sync_state` 由副本实时计算，不作为另一个权威状态保存：

```text
local_only / cloud_only / syncing / synced /
download_required / upload_failed / unavailable
```

本批所有上传请求若传入非 `local_only` 策略或非本地目标位置，返回明确的“不支持”错误，不静默降级。

## 7. 后端接口边界

### 7.1 Repository

```python
class AccountCatalogRepository(Protocol):
    async def get_current_account(...): ...
    async def list_workspaces(...): ...
    async def register_workspace(...): ...
    async def set_active_workspace(...): ...

class WorkspaceRepository(Protocol):
    async def list_assets(...): ...
    async def save_asset(...): ...
    async def save_storage_bundle(...): ...
```

业务服务不直接导入 `SQLiteStore`。

### 7.2 StorageDriver

```python
class StorageDriver(Protocol):
    async def put(...): ...
    async def open_read(...): ...
    async def stat(...): ...
    async def delete_replica(...): ...
    async def test_connection(...): ...
```

本批实现 `LocalFileStorageDriver`。驱动负责路径边界、防目录逃逸、原子写入、校验和验证和临时文件清理。

### 7.3 StorageManager

```python
class StorageManager:
    async def save_object(...): ...
    async def resolve_readable_replica(...): ...
    async def materialize_local(...): ...
    async def get_availability(...): ...
    async def archive_object(...): ...
```

删除副本属于存储操作，归档资产属于业务操作，两者不得混为一个 API。

### 7.4 ContentResolver

下载、缩略图、VLM 输入和本机工具统一通过 `ContentResolver` 获取内容。浏览器使用稳定内容 URL；内部工具通过它获得短期本地路径或可读流。

## 8. API 设计

### 8.1 当前上下文与工作区

```http
GET  /api/v1/context
GET  /api/v1/accounts/current
GET  /api/v1/workspaces
POST /api/v1/workspaces/validate-local
POST /api/v1/workspaces/register-local
PUT  /api/v1/context/active-workspace
GET  /api/v1/workspaces/{workspace_id}/storage-locations
```

现有 `/api/v1/workspace`、`/workspace/validate` 和 `PUT /workspace` 在本批保留为兼容接口，由新服务实现，并标记为待废弃。

### 8.2 资产目录

```http
GET    /api/v1/workspaces/{workspace_id}/asset-folders
POST   /api/v1/workspaces/{workspace_id}/asset-folders
PATCH  /api/v1/asset-folders/{folder_id}
DELETE /api/v1/asset-folders/{folder_id}
```

删除非空目录时默认拒绝；必须先移动资产或显式选择移动到“未分类”。

### 8.3 资产

```http
GET    /api/v1/workspaces/{workspace_id}/assets
POST   /api/v1/workspaces/{workspace_id}/assets
GET    /api/v1/assets/{asset_id}
PATCH  /api/v1/assets/{asset_id}
DELETE /api/v1/assets/{asset_id}
GET    /api/v1/assets/{asset_id}/content
GET    /api/v1/assets/{asset_id}/thumbnail
```

列表接口从第一版开始支持 `page`、`page_size`、`folder_id`、`type`、`query`、`storage_state` 和 `include_archived`。

上传请求预留：

```json
{
  "folder_id": "uuid-or-null",
  "target_location_id": "local-location-uuid",
  "storage_policy": "local_only"
}
```

### 8.4 项目资产关联

```http
GET    /api/v1/productions/{project_id}/assets
POST   /api/v1/productions/{project_id}/assets/{asset_id}/link
DELETE /api/v1/productions/{project_id}/assets/{asset_id}
```

现有 `/productions/{project_id}/references` 继续作为兼容入口：上传时先创建工作区资产，再创建项目关联；查询时返回项目已关联资产。

### 8.5 文件和副本

```http
GET /api/v1/storage-objects/{object_id}/content
GET /api/v1/storage-objects/{object_id}/replicas
```

未来预留但本批不开放写能力：

```http
POST /api/v1/storage-objects/{object_id}/replicas
POST /api/v1/storage-objects/{object_id}/sync
POST /api/v1/storage-objects/{object_id}/materialize
```

普通资产响应只返回：

```json
{
  "availability": {"local": true, "cloud": false},
  "sync_state": "local_only",
  "storage_policy": "local_only"
}
```

## 9. 资产管理 UI

### 9.1 信息架构

- 左侧主导航增加“资产库”。
- 页面顶部显示当前逻辑工作区、搜索、类型筛选、存储状态筛选和“上传资产”。
- 左栏显示“全部资产”“未分类”和用户创建的一级目录。
- 主区域使用缩略图网格；列表很多时使用服务端分页。
- 右侧详情抽屉显示预览、名称、类型、目录、标签、权利信息、项目引用和存储状态。

### 9.2 当前可操作能力

- 创建、改名和删除一级目录；
- 上传图片资产并生成独立缩略图；
- 资产改名、移动目录、修改类型和标签；
- 资产软归档和恢复；
- 从项目的参考资产区域打开资产库选择器；
- 项目内新上传资产自动进入资产库并建立项目关联。

### 9.3 未来状态预留

资产卡片和详情抽屉的数据结构支持：

- 仅本地；
- 仅云端；
- 已同步；
- 同步中；
- 需要下载；
- 同步失败。

“上传云端”“下载到本机”“保留本地副本”和“释放本地空间”本批不展示，不放置无效按钮。

## 10. 旧数据迁移

### 10.1 工作区身份

首次打开旧工作区时：

1. 读取当前活动根目录；
2. 为工作区生成并持久化稳定 `workspace_id`；
3. 在本地账户控制面登记该工作区；
4. 创建默认本地 `StorageLocation`；
5. 保留原目录结构，不移动现有文件。

迁移必须幂等；同一路径再次启动不得生成第二个工作区或第二个默认存储位置。

### 10.2 ReferenceAsset

现有项目级参考资产按以下方式升级：

1. 保留原 `ReferenceAsset.id` 作为新 `Asset.id`，避免破坏 `ReferenceBinding`、`@资产` 和 Revision 快照；
2. 将原 `project_id` 转换为 `ProjectAssetLink`；
3. 为原图创建 `StorageObject` 和本地 `ObjectReplica`；
4. 为缩略图创建独立 `StorageObject` 和本地 `ObjectReplica`；
5. 原 `relative_path` 作为本地副本的 `object_key`，不复制文件；
6. 原接口在兼容期返回新的工作区资产读模型。

若同一 SHA-256 在不同项目中存在，不在首次迁移时自动合并业务资产；文件内容可复用同一个存储对象，但资产名称、权利信息和项目引用保持独立，避免误合并人物或产品语义。

### 10.3 Schema

- Batch 4.4.1 将工作区 Schema 从 2 升级到 3；
- Batch 4.4.4 将 Schema 升级到 4，新增项目资产关联和异步生成任务所需字段；
- 新增账户／工作区标识、存储位置、存储对象、副本、资产目录、资产和项目资产关联表；
- 升级前创建 SQLite 备份；
- 迁移在单个事务中写入数据库，文件只做校验不做搬移；
- 新版本应用拒绝不完整迁移，旧版本继续按既有“未来版本拒绝降级”规则处理。

## 11. 分批执行计划

### Batch 4.4.1：默认账户与逻辑工作区

目标：把“活动路径”升级为“默认账户下的活动逻辑工作区”。

任务：

- 新增 `Account`、`DeviceInstallation`、`Workspace` 和 `WorkspaceRegistration`；
- 建立本地账户控制面 Repository；
- 为旧工作区补建稳定 `workspace_id` 和默认账户归属；
- 创建默认本地 `StorageLocation`；
- 新增 Context、账户、工作区列表、登记和切换 API；
- 保持现有工作区设置 UI 和旧 API 正常工作；
- 增加多工作区登记、重启恢复和重复迁移测试。

完成标准：用户行为不变，但 API 已能区分账户、工作区身份和当前设备上的本地登记。

### Batch 4.4.2：统一存储对象与本地驱动

目标：业务实体不再把本地路径作为文件身份。

任务：

- 新增 `StorageLocation`、`StorageObject` 和 `ObjectReplica`；
- 实现 `LocalFileStorageDriver`、`StorageManager` 和 `ContentResolver`；
- 实现 `materialize_local()`；
- 新上传文件采用存储对象接口和原子写入；
- 下载、缩略图和内部媒体处理改为对象 ID 解析；
- 增加路径逃逸、文件缺失、校验和错误和副本状态测试。

完成标准：新增业务代码不直接拼接工作区根路径；替换为假云端驱动时不需要修改资产和项目服务。

### Batch 4.4.3：工作区资产库与目录 UI

目标：提供独立资产管理模块。

任务：

- 新增 `AssetFolder`、`Asset` CRUD 和分页查询；
- 实现一级目录、未分类、搜索、类型筛选和归档；
- 实现缩略图网格、详情抽屉、上传和编辑 UI；
- 显示“仅本地”状态并预留其他状态字段；
- 增加目录重名、非空删除、分页和响应式测试。

完成标准：资产数量增长后仍可分页查询、按目录管理和重复打开。

### Batch 4.4.4：项目引用与旧资产迁移

目标：资产库成为分镜参考资产的唯一来源。

任务：

- 新增 `ProjectAssetLink`；
- 迁移现有 `ReferenceAsset`，保留原 UUID；
- 项目参考资产区改为资产库选择器加快速上传；
- `ReferenceBinding`、`@资产`、生成快照和 Revision 继续稳定引用；
- 兼容旧 Reference API；
- 增加跨项目复用、改名不破坏绑定和迁移幂等测试。

完成标准：同一资产可被多个项目引用，不产生文件副本；旧项目可以无感继续打开和生成。

### Batch 4.4.5：混合存储扩展缝验证

目标：验证未来增加云端不会重构业务层。

任务：

- 实现仅用于测试的 `FakeCloudStorageDriver`；
- 验证同一对象同时存在本地和模拟云端副本；
- 验证本地副本缺失时返回明确的 `download_required` 或 `unavailable`；
- 验证移动逻辑目录不会改变 `object_key`；
- 验证项目快照只保存对象 ID 和校验和，不保存绝对路径或临时 URL；
- 输出云端 Provider 接入清单，但不连接真实服务。

完成标准：新增真实 OSS／COS 驱动时，项目、资产、分镜和生成服务接口无需改变。

## 12. 测试计划

### 12.1 单元测试

- 默认账户只创建一次；
- 工作区 ID 在路径改名和重启后保持稳定；
- 本地登记只对当前设备有效；
- 一级目录约束、重名和软删除；
- 存储对象与副本状态推导；
- 本地驱动原子写、范围校验和 SHA-256 校验；
- `materialize_local()` 命中本地副本和缺少本地副本；
- 唯一健康副本保护；
- 项目资产关联和 `@资产` 稳定 ID；
- 旧 ReferenceAsset 迁移幂等。

### 12.2 API 测试

- Context、工作区登记、切换和兼容接口；
- 资产目录 CRUD；
- 资产分页、搜索、移动、归档和恢复；
- 内容及缩略图响应不泄露物理路径；
- 不支持的云端策略返回明确错误；
- 项目关联和解除关联不删除资产；
- 被 Revision 使用的资产不能物理删除唯一副本。

### 12.3 前端测试

- 资产库导航、目录筛选和分页；
- 上传、改名、移动、归档和恢复；
- 缩略图失败回退；
- 项目资产选择器和 `@` 菜单；
- “仅本地”状态展示；
- 窄屏时目录和详情面板可用。

### 12.4 回归测试

- 本地文件和抖音／小红书链接分析；
- 分析记录保存、分页、缩略图和重复打开；
- 分镜关键帧、图片生成和候选选择；
- 本机 imagegen 和国内模型两种模式；
- 工作区切换、API 重启恢复和旧项目加载；
- 前端生产构建和后端全量测试。

## 13. 安全、隐私与成本

- 云端凭据未来存入本机密钥配置或服务端 Secret Manager，`StorageLocation` 只保存配置引用和 `credential_configured` 状态；
- 绝对路径、Bucket、Object Key、API Key 不进入普通响应、Revision 或导出包；
- 文件上传继续执行 MIME、扩展名、像素、大小、解码和内容边界校验；
- 物理删除前检查所有引用和健康副本；
- 未来每个存储位置可增加 `usage_bytes`、`quota_bytes`、上传／下载流量和费用统计；本批不计算云存储费用；
- 本地缓存属于可回收副本，原始本地唯一副本不标记为缓存。

## 14. 本批不实现

- 注册、登录、团队成员、角色和权限；
- 真实 OSS、COS、S3 或 ViralDNA 服务端；
- 云端上传、断点续传、后台同步和跨设备下载；
- 元数据冲突合并、离线编辑同步和多人协作；
- 二级及更深资产目录；
- 自动内容识别、资产去重合并和智能打标签；
- 资产市场、团队共享库和公开链接。

## 15. 最终验收标准

- 系统存在稳定的默认账户和逻辑工作区 ID；
- 当前本地目录被表示为一个存储位置，而不是工作区本身；
- 资产库支持一级目录、分页、搜索、缩略图、改名、移动和软归档；
- 同一资产可被多个项目使用，项目引用不复制文件；
- 新资产、缩略图和项目生成输入通过 `StorageObject` 访问；
- 普通 API 和项目快照不保存绝对路径或临时云端 URL；
- 旧项目、旧参考资产和现有工作区可自动、幂等升级；
- 假云端驱动证明同一文件可拥有多个副本且业务层无需修改；
- 未连接任何真实云端服务，也未引入登录和权限复杂度；
- 后端测试、前端测试和生产构建全部通过。

## 16. Batch 4.4.1 实施记录（2026-08-05）

本批已完成账户与逻辑工作区的基础层，尚未进入通用资产对象和云端存储实现：

- 增加稳定的默认账户、设备安装、逻辑工作区、工作区注册和存储位置模型；
- 增加本机账户目录，默认保存在系统应用数据目录，并支持通过 `VIRAL_DNA_ACCOUNT_CATALOG_PATH` 覆盖；
- 为工作区清单补充稳定的 `workspace_id`、`account_id`、名称和目录模式，重复启动与重复注册保持幂等；
- 工作区元数据升级至 Schema v3，保留原有目录结构、数据库和媒体文件，不执行数据搬移；
- 新增当前上下文、当前账户、工作区列表、本地工作区校验／注册／切换和存储位置查询 API；
- 原有 `/api/v1/workspace` 接口继续可用，并统一进入新的账户上下文和工作区注册流程；
- 为未来本地、云端和混合存储预留策略、Provider、能力和可用性字段，但本批不连接真实云服务；
- 增加账户目录持久化、稳定身份、幂等注册、跨账户保护、API 切换和旧接口兼容测试。

验证结果：

- 后端全量测试通过；
- Web 端 18 项测试通过；
- Web 生产构建通过；
- Ruff 针对性检查、Python 编译检查和 Git 差异检查通过。

## 17. Batch 4.4.2～4.4.3 实施记录（2026-08-06）

已完成统一本地对象存储和资产库：

- 新增 `StorageObject`、`ObjectReplica`、本地 `StorageLocation`、`LocalFileStorageDriver`、`StorageManager` 和统一内容解析；
- 新上传的资产原图和缩略图分别保存为逻辑对象，普通 API 只返回对象 ID、内容 URL、可用性和同步状态；
- 本地驱动执行路径边界、原子写入、SHA-256、媒体类型和副本健康检查；
- 资产库支持一级目录、未分类、分页、搜索、类型／存储状态筛选、软归档、恢复和详情编辑；
- 资产卡片和详情预览统一使用 `object-fit: contain`，竖版图片不裁切；上传成功后返回列表，不强制打开详情；
- 资产库页移除与资产管理无关的全局搜索和“新建分析”入口；
- 详情抽屉、上传弹窗和新建目录弹窗采用受控宽度，桌面与窄屏均不产生横向溢出。

## 18. Batch 4.4.4 实施记录（2026-08-06）

项目引用与旧资产迁移已完成：

- 新增持久化 `ProjectAssetLink`，项目引用工作区资产时只新增关联，不复制原图或缩略图；
- 同一资产可被多个项目使用；解除某个项目的关联不会归档或删除全局资产；
- 项目参考资产区新增资产库选择器，并保留快速上传兼容入口；
- 原 `ReferenceAsset` API 继续可用，由 `ProjectAssetService` 转换为工作区资产和项目关联；
- 旧资产首次打开时保留原 UUID、`ReferenceBinding` 与提示词 `@资产` 关系；
- 迁移通过 `register_existing_local_object()` 注册既有受管理文件，不移动、不复制媒体字节，重复执行保持幂等；
- 资产改名和移动目录只修改资产元数据，不改变 `StorageObject`、`ObjectReplica.object_key` 或项目绑定；
- Production Snapshot 升级为 v2，只保存稳定资产 ID、对象 ID、SHA-256 和业务字段，不保存绝对路径、工作区相对路径、`object_key` 或临时 URL；
- 从旧 Revision 建立分支时仍可恢复资产引用，旧项目可继续打开、绑定和生成。

关键自动化覆盖：

- 旧资产 UUID 保留、幂等迁移和零拷贝；
- 跨项目复用不新增存储对象；
- 改名、移动目录后项目引用稳定；
- 解除关联不删除全局资产；
- 快照不泄露本机路径和副本定位信息。

## 19. Batch 4.4.5 实施记录（2026-08-06）

混合存储扩展缝验证已完成，但没有连接真实云端：

- 新增仅供测试使用的 `FakeCloudStorageDriver`，与本地驱动实现同一协议；
- `StorageManager.replicate_object()` 可把同一逻辑对象复制到模拟云端位置，重复同步保持幂等；
- 本地和模拟云端副本使用相同对象 ID、SHA-256 和稳定对象键语义；
- 本地副本缺失且云端健康时返回 `download_required`，所有副本不可用时返回 `unavailable`；
- `sync_state` 由副本状态实时计算，可表达 `local_only`、`cloud_only`、`synced`、`download_required` 和 `unavailable`；
- 业务层、项目引用、分镜绑定和快照均不依赖具体云厂商，新增真实驱动无需改变这些接口。

### 19.1 真实云端 Provider 后续接入清单

真实 OSS／COS／S3 驱动必须补齐以下能力后才能启用：

1. 使用本机密钥存储或服务端 Secret Manager，仅在 `StorageLocation` 保存凭据引用；
2. 实现流式上传、分片上传、断点续传、幂等重试和超时取消；
3. 上传完成后校验服务端 ETag／Checksum 与本地 SHA-256，不以 HTTP 200 直接判定健康；
4. 实现下载到临时文件、校验后原子进入本地缓存的 `materialize_local()`；
5. 通过短期签名 URL 或 API 流式响应提供浏览器内容，不把永久 Bucket／Object Key 暴露给普通 DTO；
6. 记录上传／下载任务、失败原因、重试次数、流量和存储费用；
7. 删除本地或云端副本前验证至少存在另一份健康非缓存副本，并检查 Revision 引用；
8. 增加跨设备并发、离线恢复、凭据过期、限流、部分分片失败和校验和不一致测试；
9. 真实 Provider 集成测试使用隔离 Bucket 和生命周期规则，默认测试套件不得产生云费用；
10. 上线前执行数据驻留、隐私、内容权利、访问日志和灾备审查。

## 20. 最终验证结果（2026-08-06）

- 后端全量测试：110 项通过；
- Ruff：`services/api` 全量通过；
- 前端测试：23 项通过；
- 前端生产构建与 Sites 产物准备：通过；
- 本地浏览器冒烟：Schema 4 工作区可加载，资产库无横向溢出，竖图原图／缩略图均为完整包含显示，VLM 质检开关可见，控制台无 ViralDNA 应用错误；
- 未调用真实百炼生图、真实 ImageGen 或真实云存储，因此没有产生新的模型或云存储费用。

Batch 4.4 至此完成。真实云端同步属于后续独立批次，不能把 `FakeCloudStorageDriver` 视为已接入云服务。
