# 手动 IIS：启动工具更新包

状态：2026-09-10。适用于已经完成域名、证书、IIS 反向代理和 api.env 域名配置的 `C:\Projects\ViralDNA`。这是小型控制器更新，不是重新部署整个工具包，也不是业务数据迁移。

## 先做什么

1. 解压 `ViralDNA-manual-iis-update.zip`。建议把解压得到的整个 `ViralDNA-manual-iis-update` 文件夹放在 `C:\Projects\ViralDNA\.server\updates\` 下；没有 `updates` 目录时新建。
2. 关闭已打开的 ViralDNA 部署菜单。首次初始化前，在 IIS 管理器中只停止 **ViralDNA** 网站；不要停止原网站。
3. 右键以管理员身份运行更新包内的 `01-install-update.bat`，等它显示 `Update completed`。
4. 然后右键以管理员身份运行 **服务器原位置**的 `C:\Projects\ViralDNA\.server\setup\05-run.bat`，选择 **2：编译 + 启动**。不要直接运行更新包 payload 目录里的 05。
5. 首次注册服务时，输入服务器当前 Windows 管理员账户的密码，不是网站 admin 密码或 PIN。密码不会写进本包或配置文件。

安装更新包不会访问 GitHub、安装依赖、创建账号、启停服务或操作 IIS。真正的依赖安装、编译和内部服务启动是在第 4 步执行；需要正常访问 npm / PyPI。之前 Git 已更新，不必为了这次启动选择 1。

## 第一次启动与初始化

首次启动未初始化的应用时：

- 脚本只读检查 `Iis.SiteName` 指定的网站已经停止；如果仍在运行，启动会终止并提示你手动停止，不会替你停站。
- API 和内部 Web 服务通过检查后，提示 `LOCAL SETUP REQUIRED`；这不是报错。
- 此时两个 Windows 服务暂不启用开机自启，IIS 不会被启动。

保持 IIS 网站停止，在服务器本机浏览器打开：

```text
http://127.0.0.1:8080/login
```

设置网站 admin 和首个个人／企业账户。前端登录名使用大陆 11 位手机号，密码至少 8 位；不需要初始化码。已有账号的实例不重复初始化，不要删除数据库重新设置。

初始化完成后：

1. 回部署菜单，如果仍显示“按任意键返回菜单”，先按任意键。
2. 选择 **3：启动**。它会按菜单约定先关闭再启动本项目内部服务，重新检查初始化状态，并启用这两个服务的开机自启。
3. 等待 `Accounts initialized` / 内部服务就绪提示，然后在 IIS 管理器中**手动启动 ViralDNA 网站**。
4. 运行 `C:\Projects\ViralDNA\.server\setup\06-check-https.bat`。
5. 检查通过后访问 `https://viraldnastudio.com/login`，验证登录、项目页面、图片／视频上传与读取、生成结果逐张刷新。后台入口是 `/admin/login`。

运行中的服务不依赖菜单窗口常开；菜单按 0 退出不关闭服务。IIS 网站是否随系统启动由你在 IIS 中维护，菜单不会改它的自动启动设置。

## 更新包实际修改什么

- 仅替换 `.server\setup` 中清单列出的 12 个控制器、入口和模板文件。新增只读 HTTPS 检查入口 `06-check-https.bat`。
- 在现有 `.server\config\deploy.json` 中合并：`Iis.ManagementMode = "Manual"`、`Iis.SiteUrl = "https://viraldnastudio.com"`、`Iis.AllowPublicAccess = true`。
- 顶层 `SiteUrl` 保持本机 HTTP，顶层 `AllowPublicAccess` 仍为 false；`Iis.Enabled` 仍为 true。手动模式不需要在 deploy.json 中维护证书指纹；真实证书继续由 IIS 管理，06 检查不跳过 TLS 验证。
- 保留 Windows 运行账户、数据和数据库路径、其他未知配置字段；不覆盖 `api.env`，不复制任何账号数据或私钥。
- **不修改**你已经配置好的 `.server\iis\site\web.config`、IIS 请求头允许列表、上传／缓存设置、域名绑定、证书、应用程序池或全局 ARR。
- 文件更新前校验清单和哈希，并把旧文件与原 deploy.json 备份到 `.server\backups\manual-iis-update-时间戳-唯一标识`。失败时尝试恢复本次已改动的文件，并保留备份；没有递归删除用户目录。

旧的 `04-configure-iis.bat` 不再需要运行。更新后即使误点该入口，手动模式也会在安装组件、初始化运行目录和修改 IIS 之前拒绝自动配置。

## 只读检查命令

如需在安装前查看是否满足更新条件，在服务器 PowerShell 中执行下列命令，替换路径为实际解压目录；`-Preview` 不写配置或复制文件：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Projects\ViralDNA\.server\updates\ViralDNA-manual-iis-update\install-manual-iis-update.ps1 -Preview
```

更新后，基础预检（不会启停服务或访问 GitHub）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Projects\ViralDNA\.server\setup\deploy-server.ps1 -Config C:\Projects\ViralDNA\.server\config\deploy.json -Action check
```

公开 HTTPS 检查也可直接执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Projects\ViralDNA\.server\setup\deploy-server.ps1 -Config C:\Projects\ViralDNA\.server\config\deploy.json -Action verify-public
```

它核对指定域名的正常 TLS 验证、登录页面、版本标识，以及 API 返回 `auth_mode=password`、`initialized=true`；不跟随重定向，不提交登录凭据，不改 IIS，不因检查失败停止任何服务。主域名通过不等于 www 已通过；需要 www 时另行验收证书和访问。

## 常见阻塞

| 提示／情况 | 处理 |
| --- | --- |
| 找不到 `.server\setup` 或 deploy.json | 解压包应安装到已完成 02 的服务器项目，不是本地测试目录；不要创建空配置绕过 |
| `CORS_ORIGINS must also include...` | 在原 api.env 的现有 CORS 行保留内部地址，并加入 `https://viraldnastudio.com`；不整份覆盖 |
| 更新时锁定失败 | 关闭其他更新程序和部署菜单，再重试；不要强制杀服务或删除锁文件 |
| 未找到手动 IIS 网站 | 检查 deploy.json 中的 `Iis.SiteName` 是否与实际站点名一致，不要更改原网站 |
| `Account setup is incomplete` | 只停止 ViralDNA 的 IIS 站点，再选 2 / 3；完成本机初始化 |
| 端口被未管理进程占用 | 根据端口查明占用程序；不要结束其他网站的进程 |
| 06 的 TLS / 域名错误 | 核对证书范围、有效期、SNI 和 DNS；不要跳过证书验证 |
| 06 返回 502 / 连接失败 | 先检查内部 8080 登录页面和两个服务，再检查新站点是否已启动 |
| 06 版本不一致 | 确认 DNS / IIS 代理指向当前服务器的 8080，不是旧服务或缓存 |

更新后不要重新运行原部署大包的完整性校验或 02 来“修复”哈希变化；旧清单对应旧版文件。未来证书续期、IIS 绑定变更继续手动维护，不需要重跑自动 IIS 配置。

## 验收范围

代码提供离线回归测试和更新包完整性校验。未连接真实服务器执行部署，不代表已经编译成功、服务已启动、TLS 已通过或真实上传／生成已验收。首次编译和服务注册由你在服务器执行，可能受到网络、端口或当前 Windows 账户权限影响。
