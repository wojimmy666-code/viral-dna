# viraldnastudio.com 手动 IIS 配置包

适用日期：2026-09-10。目标服务器目录：`C:\Projects\ViralDNA`；IIS 站点和应用程序池名称：`ViralDNA`。若实际名称不同，只在 IIS 中选择你的真实站点，并相应修改参考片段的 `location path`，不要调整其他网站。

本包只提供可手动应用的 IIS 配置和 API 域名设置，不安装组件、不运行命令、不修改证书绑定、不启动服务，也不包含任何密码、私钥、用户数据或模型密钥。

## 先看这一项：配置完成不等于应用已启动

目前项目的旧版 `04-configure-iis.bat` / `05-run.bat` 使用自动管理 IIS 的部署控制器：它要求站点所有权记录、仅一个绑定，并严格匹配自动生成的 `web.config`。本包不修改控制器，也不创建虚假的所有权记录。

因此，采用本包后，**不要运行旧版 04 / 05 入口，也不要自行修改 `deploy.json` 来尝试跳过校验**。完成下列设置后使用 [手动 IIS 启动更新包](../../手动IIS启动更新包.md)升级控制器，再运行更新后的 05。尤其不要仅设置 `Iis.Enabled=false`：旧代码会同时切换内部 Caddy 模板，影响 HTTPS 和原始域名传递。

本包可完成下列 IIS 准备工作；编译和服务启动使用上述独立控制器更新包。DNS、证书、现有 HTTPS 绑定和已经成功执行的 02 / 03 步骤无需重做。

## 文件怎么用

| 文件 | 用途 | 服务器目标 |
| --- | --- | --- |
| [web.config](web.config) | 新站点的完整代理规则 | `C:\Projects\ViralDNA\.server\iis\site\web.config` |
| [applicationHost.ViralDNA.location.xml](applicationHost.ViralDNA.location.xml) | 站点级设置参考片段；优先按下文在 IIS 管理器设置 | **不复制到网站目录，不覆盖服务器的 applicationHost.config** |
| [api.env.merge.txt](api.env.merge.txt) | 只合并一项 CORS 域名设置 | 编辑现有 `.server\config\api.env`，保留其他所有设置 |

不要把整个配置包解压到 IIS 公开目录；该目录只放 `web.config`。参考片段、说明和环境配置留在网站目录之外。

## 1. 保留现有网站，准备回退

1. 在 IIS 管理器中只选择新建的 `ViralDNA` 网站；首次账号初始化和内部服务验证完成前，先保持该站点停止。
2. 不停止原网站，不执行 `iisreset`，不重新导入或替换原网站证书。
3. 核对新站点物理路径为 `C:\Projects\ViralDNA\.server\iis\site`，不是整个项目根目录。
4. 修改前，把新站点已有的 `web.config`、现有 `api.env`、服务器 `applicationHost.config` 备份到网站目录之外，例如 `.server\backups\manual-iis-before` 下的独立时间戳子目录。不要覆盖旧备份。
5. 记录本次将修改的新站点设置及原值；服务器上其他人同时改过 IIS 时，不要用旧的完整 `applicationHost.config` 回滚全服务器，应只回退本次 ViralDNA 站点的设置。

`api.env` 和 IIS 备份可能包含敏感配置，不放到网站目录，不提交 GitHub。

## 2. 确认反向代理组件

在 IIS 管理器服务器节点检查已安装 URL Rewrite 和 Application Request Routing（ARR）。新站点应能看到“URL 重写”。

服务器节点 → Application Request Routing Cache → Server Proxy Settings，检查 **Enable proxy** 已启用。你已有其他代理网站，可能已经启用，不要重复修改其他选项。

ARR 的代理开关是服务器级设置；如果尚未启用，应先评估其他站点，再手动启用。不要为本次配置顺便调整服务器级 `preserveHostHeader`、超时或缓冲设置。依据：[微软 ARR 反向代理配置](https://learn.microsoft.com/en-us/iis/extensions/url-rewrite-module/reverse-proxy-with-url-rewrite-v2-and-application-request-routing)。

## 3. 允许新站点传递三个请求头

使用服务器本机管理员打开 IIS 管理器：

1. 左侧选择 **网站 → ViralDNA**，不是旧网站。
2. 打开 **URL 重写**。
3. 右侧点击 **查看服务器变量（View Server Variables）**。
4. 添加以下变量；已存在或已继承的条目不要重复添加，也不要删除其他已有条目：

```text
HTTP_X_FORWARDED_PROTO
HTTP_X_FORWARDED_HOST
HTTP_X_FORWARDED_FOR
```

5. 返回规则列表。

这些设置必须通过管理员管理的允许列表写入，不能直接把 `allowedServerVariables` 加进站点 `web.config` 代替授权。漏做这一步，代理规则可能报 500.50。依据：[微软服务器变量允许列表](https://learn.microsoft.com/en-us/iis/extensions/url-rewrite-module/setting-http-request-headers-and-iis-server-variables)。

参考片段中的 `<location path="ViralDNA">` 表示设置仅作用于新站点。如果手工编辑系统 IIS 配置，只合并这个站点的设置：已有相同 location 时合并进去；继承的允许变量无需再添加。**不要用参考片段覆盖整个 `C:\Windows\System32\inetsrv\config\applicationHost.config`。**

## 4. 设置上传、错误响应和缓存

仍然选择 **ViralDNA** 网站，在“配置编辑器”逐项设置下表。将更改保存到 `ApplicationHost.config` 中该站点的 location（通常显示为 `<location path="ViralDNA">`），不解锁整个服务器的配置节。

| 配置节 | 属性 | 值 |
| --- | --- | --- |
| `system.webServer/security/requestFiltering` | 展开 `requestLimits` → `maxAllowedContentLength` | `2147483648` |
| `system.webServer/httpErrors` | `existingResponse` | `PassThrough` |
| `system.webServer/urlCompression` | `doStaticCompression`、`doDynamicCompression` | 都为 `False` |
| `system.webServer/caching` | `enabled`、`enableKernelCache` | 都为 `False` |

如界面不允许写入这些站点级设置，不要直接解除全局锁定；由管理员按参考片段仅合并该站点 location。

上传值是单次 HTTP 请求的 2 GiB 上限，不是用户存储配额，也不保证单个恰好 2 GiB 的文件能上传（请求还含表单开销）；应用文件限制和账户总容量仍然生效。依据：[微软请求大小限制](https://learn.microsoft.com/en-us/iis/configuration/system.webserver/security/requestfiltering/requestlimits/)。

本站不使用 IIS 输出缓存，并避免额外 IIS 压缩影响实时响应；内部 Caddy 模板仍负责自身的内容编码。依据：[微软 IIS 缓存配置](https://learn.microsoft.com/en-us/iis/configuration/system.webserver/caching/)。

## 5. 放置新站点 web.config

把本包的 `web.config` 复制到：

```text
C:\Projects\ViralDNA\.server\iis\site\web.config
```

如果该目标已有文件，先按第 1 步备份，再只替换这个新站点的文件。**原网站包含 `/training`、`/oa` 等规则的 `web.config` 完全不动。**

配置的行为：

- `https://viraldnastudio.com/...` 转发到 `http://127.0.0.1:8080/...`。
- 同样接受 `https://www.viraldnastudio.com/...`，前提是已为 www 配置 DNS、证书覆盖和 IIS 主机名绑定；没有 www 绑定时不需要为使用主域名而额外添加。
- 已绑定的 HTTP 域名使用 307 跳转到同一域名的 HTTPS，保留请求方法、路径和查询参数。协议判断来自 IIS 自身，不信任浏览器提交的 `X-Forwarded-Proto`。
- 转发时覆盖协议、原始域名和客户端 IP 请求头，供内部 Caddy / API 正确处理 HTTPS 登录。
- 未匹配的域名或协议返回 400，避免该站点意外处理原网站或未知主机名的请求。
- 不提供 IIS 的 `127.0.0.1:8081` 初始化入口；首次初始化应在服务器本机直接访问内部服务 `http://127.0.0.1:8080/login`，期间保持该 IIS 站点停止。

307 对应 URL Rewrite 的 `Temporary` 类型；配置依据：[微软 URL Rewrite 规则参考](https://learn.microsoft.com/en-us/iis/extensions/url-rewrite-module/url-rewrite-module-configuration-reference)。

如出现新站点目录读取权限不足，只给 `IIS AppPool\ViralDNA`（对应真实应用程序池名）该 `iis\site` 目录的读取与执行权限；不要授予整个 `.server` 或项目目录的访问权限。

## 6. 合并 API 域名设置

用文本编辑器打开服务器现有文件：

```text
C:\Projects\ViralDNA\.server\config\api.env
```

找到现有的 `VIRAL_DNA_CORS_ORIGINS=` 行，把两个 HTTPS 域名加入，最终结果可参照 [api.env.merge.txt](api.env.merge.txt)。保留内部 `127.0.0.1` 地址以及其他确实需要的已授权来源；同一个键只保留一行，不使用 `*`。

不要直接用本包片段覆盖整个 `api.env`；保持 `VIRAL_DNA_AUTH_MODE=password`，所有账户目录、数据库路径、平台密钥和模型参数保持原样。此项会在应用下一次受控启动 / 重启后生效，复制文件不会让运行中的进程自动重载环境变量。

现有 `deploy.json` 本次保持不动：它还对应旧版自动管理 IIS 的控制器。后续启动方案需要保留内部回环监听、受信代理头处理、本机账号初始化和公开入口检查；当前不能靠一个 JSON 开关直接实现。

## 7. 配置后如何核验

在兼容的应用启动流程准备好之前，完成文件放置后先保持 ViralDNA 站点停止，原网站照常运行。以下验收是在内部应用已经启动之后进行，不表示本包已经启动应用。

1. 在服务器本机访问 `http://127.0.0.1:8080/login`：应看到 ViralDNA 页面，而不是其他服务。
2. 本机打开 `http://127.0.0.1:8080/api/v1/auth/status`，确认 `auth_mode` 为 `password`；首次初始化完成后 `initialized` 必须为 `true`。
3. 初始化完成后，在 IIS 中仅启动 ViralDNA 站点；访问 `https://viraldnastudio.com/login`，检查证书域名和有效期，确认页面可用。
4. 登录并刷新项目路由，检查图片 / 视频上传和读取、生成结果逐张刷新；开发者工具中确认 HTTPS 会话 Cookie 含 Secure 标记。
5. 若启用 www，也单独验证 www 的 HTTPS 证书及访问。主域名和 www 的登录 Cookie 不保证共用，建议日常统一使用不带 www 的主域名。
6. 从另一台电脑确认账户初始化入口不可被远程执行，并回归原网站的登录和主要页面。

只保留需要的公网 80 / 443；8000、8080、8081、18080、12019 不应向公网开放。当前内部 Caddy 必须使用支持 IIS 的受信代理配置，不能改为直接监听公网。

## 常见情况

| 情况 | 优先检查 |
| --- | --- |
| 502 / 502.3 | 内部 `127.0.0.1:8080` 是否已运行、端口是否被其他进程占用；不要靠重装证书处理 |
| 500.50 | 三个允许的服务器变量是否已在正确站点生效，查看详细错误 |
| 500.19 / 0x80070021 | 配置节锁定或写入位置不正确；按站点 location 配置，不解除全局锁定 |
| 500.19 / 0x800700b7 | 相同配置项重复，常见于已有或继承的变量被重复添加 |
| 401.3 / 0x80070005 | 新站点物理目录或配置文件的只读权限 |
| 404.13 / 413 | IIS 单次请求限制、应用文件限制、账户容量，分别核对 |
| 400 | 使用了 IP、localhost、错误端口或非预期域名；本站仅代理配置好的公开 HTTPS 域名 |
| HTTPS 页面能开但登录异常 | 请求头允许列表、内部 Caddy 对代理头的信任、API 域名设置与 Cookie |
| 实时进度延迟或长任务超时 | IIS 本站缓存 / 压缩、已有 ARR 的服务器级缓冲和超时；先确认原因，修改全局 ARR 前评估其他网站 |

本包没有修改 ARR 的服务器级缓冲和超时，因此不能仅凭这份站点配置保证所有实时流和长请求都已适配。

## 已验证的范围

本地可检查 XML 结构、规则匹配、域名范围、代理目标、转发头以及环境变量片段；并未连接你的服务器执行 IIS、TLS、登录、上传或实时流验收。配置文件检查通过不代表生产服务已上线。
