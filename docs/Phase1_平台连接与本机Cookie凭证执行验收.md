# Phase 1 平台连接与本机 Cookie 凭证执行验收

> 状态：1～9 已实现，等待人工验收
> 范围：抖音、小红书、TikTok、Instagram 公开链接采集所需的本机登录状态
> 原则：匿名优先、用户授权、本机保存、按平台隔离、不绕过平台验证

## 1. 执行计划与结果

| # | 工作项 | 交付结果 |
|---|---|---|
| 1 | 账户与设备范围 | 平台连接绑定默认账户与当前设备；数据模型保留未来多账户、云端设备同步边界。 |
| 2 | GUI 配置入口 | 左侧“系统 → 平台连接”提供四个平台的独立状态、配置、验证、策略和断开操作。 |
| 3 | 独立文件导入 | 支持 Netscape `cookies.txt`，按所选平台过滤域名，拒绝空文件、错误编码、过期或无匹配 Cookie。 |
| 4 | 旧配置迁移 | 首次启动读取旧 `VIRAL_DNA_YTDLP_COOKIE_FILE`，按四个平台域名分别提取 Cookie，不覆盖已有连接。 |
| 5 | 浏览器自动检测 | 枚举 Chrome、Edge、Firefox、Brave 及 Profile；用户授权后才读取所选 Profile。 |
| 6 | 健康检查 | 状态分为未配置、待验证、已读取、可用、已失效、错误，并保存可操作错误码。 |
| 7 | 采集凭证重试 | 先匿名采集；仅在平台要求登录时，按平台和策略使用凭证重试。 |
| 8 | 新建分析联动 | 链接输入框显示对应平台状态；鉴权失败可进入配置并重试原视频记录。 |
| 9 | 安全、测试与文档 | Windows DPAPI 加密、临时文件回收、API 脱敏、单元/接口/前端测试及本文档。 |

## 2. 产品交互

### 2.1 平台连接页

“平台连接”位于系统导航，不占用第一期的四个主导航。页面固定显示抖音、小红书、TikTok、Instagram 四张平台状态卡：

- 当前连接方式：浏览器 Profile 或本机加密 `cookies.txt`；
- Cookie 数量、最近验证、最近采集成功时间；
- 使用策略：平台要求登录时使用、始终使用、暂停使用；
- 检查状态、更新、断开；
- 设备本地和隐私提示。

配置抽屉提供两种方式：

1. 自动读取浏览器：检测已安装浏览器和 Profile，用户勾选授权后读取；
2. 导入文件：选择 Netscape 格式 `cookies.txt`，后端校验、过滤并加密保存。

已配置连接可粘贴同平台测试链接做真实在线验证。不填写测试链接时只检查本机 Cookie 可读取性，不请求平台。

### 2.2 新建分析页

粘贴受支持链接后，页面识别平台并显示：

- 当前平台；
- 未配置、待验证、可用、失效等状态；
- “配置平台”或“更新连接”入口。

未配置并不阻止公开链接采集。发生登录类错误后，错误区提供：

- 配置对应平台；
- 更新后重试。

重试复用已经创建的视频记录，只创建新的分析版本，避免分析记录列表出现重复条目。

## 3. 数据与存储设计

### 3.1 元数据

连接元数据以 `account_id + device_id + platform` 为隔离键，默认路径：

```text
%LOCALAPPDATA%/ViralDNA/platform-connections.json
```

元数据只包含：连接来源、浏览器/Profile 标签、策略、Cookie 数量、过期时间、健康状态、错误码和时间戳。它不包含 Cookie 值。

可选覆盖变量：

```text
VIRAL_DNA_PLATFORM_CONNECTIONS_PATH=
```

### 3.2 密钥内容

导入文件过滤后使用当前 Windows 用户的 DPAPI 加密，默认路径：

```text
%LOCALAPPDATA%/ViralDNA/secrets/platforms/<account>/<device>/<platform>.dpapi
```

可选覆盖变量：

```text
VIRAL_DNA_PLATFORM_SECRET_ROOT=
```

分析时才将加密内容解密到随机临时文件；采集结束后无论成功或失败都删除临时文件。浏览器方式只保存 Profile 定位信息，Cookie 值仍由浏览器管理。

### 3.3 云端扩展边界

当前实现完全本地。接口已经把“连接元数据”和“凭证密文”分离，未来可以：

- 仅同步非敏感连接状态；
- 将云端密钥存储实现为新的 `PlatformSecretStore`；
- 通过设备 ID 区分本机和云端运行节点；
- 不改变链接采集器的凭证解析协议。

本期不上传 Cookie，不实现跨设备同步。

## 4. 采集策略

默认策略是 `on_auth_required`：

```text
公开视频链接
  → 匿名 yt-dlp 采集
  → 成功：进入媒体分析
  → 平台要求登录：解析该平台连接
  → 使用浏览器 Profile 或临时 Cookie 文件重试
  → 更新平台健康状态
```

另有：

- `always`：首次请求即使用平台连接，适合平台持续要求登录的环境；
- `disabled`：暂时不向采集器提供连接。

每个平台连接只会发送给该平台白名单域名，不会跨平台复用。链接跳转到不受支持站点或其他平台时立即终止。

## 5. 浏览器自动读取边界

支持检测：

- Google Chrome；
- Microsoft Edge；
- Mozilla Firefox；
- Brave。

浏览器检测只枚举安装目录、Profile 路径和显示名称。只有用户在 GUI 中选择 Profile、确认授权并保存时，才检查该平台 Cookie。

以下情况会明确失败，不尝试降低系统安全设置：

- 浏览器数据库被进程占用；
- Chrome/Edge App-Bound Encryption 阻止解密；
- Profile 已删除或 Cookie 不存在；
- 登录已过期。

推荐回退方式是由用户手工导出 Netscape `cookies.txt` 后在 GUI 导入。

## 6. API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/settings/platform-connections` | 查询当前账户、设备的四个平台状态 |
| GET | `/api/v1/settings/platform-connections/browsers` | 检测浏览器和 Profile |
| PUT | `/api/v1/settings/platform-connections/{platform}/browser` | 授权并保存浏览器连接 |
| POST | `/api/v1/settings/platform-connections/{platform}/cookies` | 导入独立 `cookies.txt` |
| PATCH | `/api/v1/settings/platform-connections/{platform}/strategy` | 修改使用策略 |
| POST | `/api/v1/settings/platform-connections/{platform}/validate` | 本地检查或在线链接验证 |
| DELETE | `/api/v1/settings/platform-connections/{platform}` | 删除该设备上的连接和密文 |

所有响应只返回摘要，不返回 Cookie 值、导入内容或解密临时路径。

## 7. 主要错误码

| 错误码 | 用户动作 |
|---|---|
| `link_auth_required` | 配置或更新当前平台登录状态后重试 |
| `platform_browser_cookie_locked` | 关闭浏览器后台进程后重试，或改用文件导入 |
| `platform_browser_cookie_decryption_failed` | 改用 Netscape `cookies.txt` |
| `platform_browser_cookie_missing` | 在所选 Profile 登录对应平台 |
| `platform_browser_profile_missing` | 重新检测并选择 Profile |
| `platform_cookie_expired` | 重新登录并导出文件 |
| `platform_cookie_missing` | 确认文件属于当前平台 |
| `platform_cookie_file_invalid` | 使用 Netscape 格式重新导出 |
| `platform_cookie_secret_missing` | 重新配置该平台 |
| `platform_connection_test_failed` | 确认测试链接公开可访问后重试 |

## 8. 自动化验证

已覆盖：

- 域名过滤、过期 Cookie 丢弃、错误文件拒绝；
- 抖音、小红书、TikTok、Instagram 独立保存；
- 旧统一文件按平台拆分且不覆盖新配置；
- 浏览器 Profile 检测不读取 Cookie 值；
- 浏览器授权和凭证会话；
- Windows DPAPI 加密往返，磁盘文件不含测试明文；
- 解密临时文件退出上下文后删除；
- 匿名优先、鉴权后重试及平台错误翻译；
- API 响应不泄露 Cookie 值；
- 前端平台识别、伪装域名拒绝、健康状态和登录错误映射。

## 9. 人工验收流程

### A. 页面与隔离

1. 打开“系统 → 平台连接”。
2. 确认四个平台分别显示状态，且顶部明确“仅此设备”。
3. 配置其中一个平台，确认另一个平台状态不变。
4. 刷新页面，确认连接状态保留。

### B. 浏览器自动读取

1. 先在 Chrome/Edge/Firefox/Brave 登录需要配置的平台。
2. 点击“自动检测浏览器”，确认能看到浏览器和 Profile。
3. 选择 Profile、勾选授权、点击“读取并保存”。
4. 成功时确认卡片显示 Cookie 数量和验证时间。
5. 若提示浏览器占用或安全保护，确认错误给出关闭后台或改用文件的操作，而非笼统“请求失败”。

### C. 文件导入

1. 选择平台并导入 Netscape `cookies.txt`。
2. 用错误格式、另一平台文件、过期文件各测试一次，确认提示准确。
3. 导入正确文件，确认卡片显示“本机加密 cookies.txt”。
4. 在浏览器开发者工具检查状态接口，确认响应中没有 Cookie 值和本机密文路径。

### D. 链接采集与重试

1. 在新建分析页依次粘贴四个平台链接，确认输入框下显示对应连接状态。
2. 切换不同平台链接，确认连接状态同步切换且不会串用。
3. 用无需登录的公开链接验证匿名采集仍可成功。
4. 用要求登录的链接触发失败，确认出现“配置平台 / 更新后重试”。
5. 更新连接后点击重试，确认复用原分析记录，仅增加分析版本。

### E. 断开与安全

1. 断开一个平台，刷新后确认只清除该平台。
2. 检查工作区、分析报告和导出文件，不应出现 Cookie 内容。
3. 如曾配置旧 `VIRAL_DNA_YTDLP_COOKIE_FILE`，首次启动后确认四个平台按实际域名分别迁移；已有 GUI 配置不被覆盖。

## 10. 已知限制

- 平台页面结构、风控和浏览器加密策略变化后，需要重新执行真实链接验收。
- 自动读取只使用当前操作系统用户可访问的浏览器 Profile。
- 本期不提供浏览器扩展、不自动绕过验证码、不上传或同步 Cookie。
- 在线验证会真实请求用户提供的平台链接；仅本地检查不会访问平台。
