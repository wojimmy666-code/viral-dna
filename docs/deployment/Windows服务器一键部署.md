# Windows 服务器一键部署

状态：部署控制器及离线测试已实现；尚未在真实目标服务器验收 Windows 服务、域名、证书或真实媒体任务。本文不表示已经上线。通用边界见 [服务器部署](服务器部署.md)，升级前先完成 [备份](升级备份与恢复.md)。

## 1. 两个固定入口

| 入口 | 用途 |
| --- | --- |
| [scripts/start.bat](../../scripts/start.bat) | 本地开发；保留 `--no-browser` 和已有托管模式 |
| [scripts/deploy-server.bat](../../scripts/deploy-server.bat) | Windows 正式部署；编译后的 Web、独立 API、项目专用 Windows 服务 |

`scripts/` 根目录只放这两个文件。内部按 `dev/`、`deploy/`、`imagegen/`、`checks/`、`tests/` 分类；不要直接双击内部实现文件。只复制部署入口到另一台机器时，必须同时带上完整的 `scripts/deploy/` 目录。

## 2. 首次准备（只需配置一次）

`C:\Projects\ViralDNA` 单目录 + IIS + 当前管理员部署，请优先按 [五步工具包流程](当前账户服务器工具包.md)操作。下文的独立目录配置保留给旧部署；不要把两种布局混合使用。新布局的配置、数据和工具均位于项目内的 `.server`，该目录不会参与 Git 或构建快照。

由部署管理员准备，不由脚本静默安装全局软件、创建用户、开放防火墙或改动其他站点：

- Windows Server、Windows PowerShell 5.1、Git for Windows、Node.js 20.19+、Python 3.11+、FFmpeg、ffprobe。
- 可信的 Caddy 2.x 和 WinSW 2.x x64 二进制。服务模板按 WinSW 2.x 编写，脚本会检查其文件主版本。Caddy 的 Windows 服务模式见 [官方说明](https://caddyserver.com/docs/running#windows-service)。
- 一个固定的本地／域 Windows 账户。可以直接使用服务器当前登录的管理员，不必新建用户；[当前账户准备脚本](../../scripts/deploy/prepare-server.ps1) 会填写当前身份并只补充该身份的“作为服务登录”权限。不使用 LocalSystem，不在升级时切换账户；DPAPI 凭据与 Windows 身份和机器绑定。使用管理员运行服务意味着服务也具有相应管理权限。
- 操作菜单的管理员账户具备 GitHub SSH 读取权限；预先核实 GitHub 主机指纹并配置 `known_hosts`。部署使用非交互 SSH，不接受未知主机密钥，不使用 HTTPS 回退。
- API 运行账户需要业务数据目录、API 配置目录的修改权限；API 保存设置会在配置目录内创建临时文件并原子替换原配置。使用当前管理员时沿用其管理权限；若另选非管理员账户，代码、工具和部署控制器只授予读／执行权限。

代码位于 `C:\Projects\ViralDNA`、使用当前管理员的简化流程见 [当前账户服务器工具包](当前账户服务器工具包.md)。工具包不包含本机密码、模型密钥、SSH 私钥或业务数据；首次注册服务仍需要输入一次当前 Windows 账户密码。

参考目录（迁移时必须使用已核实的真实数据位置）：

```text
D:\ViralDNA\
├─ code\                  Git 仓库，固定 main
├─ tools\                 已安装的工具，可由管理员单独维护
├─ config\api.env         API 私有配置，运行账户可读写
├─ data\                  账号、项目、媒体、SQLite、工作区与凭据
└─ deployment\            独立发布目录
   ├─ owner.json          仓库、服务前缀与运行账户 SID 绑定
   ├─ controllers\        每次菜单使用的完整控制器快照
   ├─ releases\           每次构建的源码快照、独立 .venv 与静态文件
   ├─ services\           API/Web 各自的 WinSW 包装器和配置
   ├─ bin\                固定的 Caddy 二进制副本
   ├─ control\            API 进程身份和本地停止请求
   ├─ caddy\              证书与 Caddy 状态
   └─ logs\               部署、API、Web 日志
```

代码与 deployment 目录不能互相嵌套；业务数据必须在两者之外。脚本拒绝盘符根目录、目录联接和符号链接，避免更新或进程归属判断指向错误位置。

## 3. 配置文件

将 [部署配置示例](../../scripts/deploy/config.example.json) 复制到：

```text
C:\ProgramData\ViralDNA\deployment\config.json
```

也可使用 `VIRAL_DNA_DEPLOY_CONFIG` 环境变量或入口参数 `-Config "绝对路径"`。默认配置文件位置与配置里的 `DeploymentRoot` 可以不同；实际配置不要提交 GitHub。

编辑以下内容：

- `RepositoryRoot`：待更新的仓库目录。首次克隆允许此目录不存在或为空；不接管非空的非 Git 目录。
- `DeploymentRoot`：专用发布目录。首次必须为空，或只含 `config.json`；后续通过 `owner.json` 校验归属，不自动认领未知文件。
- `EnvFile`：API 私有配置文件。参考 [API 配置示例](../../scripts/deploy/templates/api.env.example)，不要覆盖现有真实配置。
- `ServicePrefix`、`ServiceAccount`：本项目唯一服务前缀和固定运行账户。首次服务注册时交互输入该 Windows 账户密码；密码交给 Windows SCM，不进入命令参数或 XML。
- `Tools`：所有工具的绝对路径；`Npm` 指向 `node_modules/npm/bin/npm-cli.js`，不是 `npm.cmd`。脚本直接调用 Node，避免多层 shell 转义。
- `SiteUrl`：首次保持 `http://127.0.0.1:8080`，`AllowPublicAccess=false`。
- `ApiPort`、`ProbePort`、`CaddyAdminPort`：互不重复的专用端口，均为 loopback。不要与其他站点或开发环境共用端口。
- `LocalAI`：需要本地 ASR/OCR 时设为 `true`，否则不安装可选依赖。
- `StopTimeoutSeconds`、`HealthTimeoutSeconds`：默认各 120 秒，可在 10～1800 秒内配置。

API 配置必须明确认证模式、账户目录、身份数据库、工作区和凭据路径。CORS 精确包含 `SiteUrl` 与 `http://127.0.0.1:<ProbePort>`，不能使用 `*`。服务启动时显式加载该配置，避免 Windows 用户默认目录变化导致数据看似丢失。

## 4. 使用菜单

以管理员身份打开入口；从任何当前目录都可调用绝对路径。例如在仓库根目录：

```powershell
.\scripts\deploy-server.bat -Config "C:\ProgramData\ViralDNA\deployment\config.json"
```

按数字直接执行：

| 按键 | 操作 |
| --- | --- |
| 1 | 基础预检 → 关闭当前服务 → SSH 更新 main → 安装依赖／编译 → 配置服务 → 启动与健康检查 |
| 2 | 基础预检 → 关闭当前服务 → 用本地代码安装依赖／编译 → 配置服务 → 启动与健康检查 |
| 3 | 基础预检 → 关闭当前服务 → 启动最近一次成功构建的完整版本，不下载、不编译 |
| 4 | 关闭本项目 Web 与 API；已停止时可重复执行，不删除任何业务数据 |
| 0 | 退出菜单；不关闭已运行服务 |

1、2、3 都必须先确认旧实例退出。正在运行的生成任务可能中断；上游已经接受的任务不保证取消，也不自动提交付费重试。菜单选择表示确认本次停服，请在维护窗口执行。

操作失败后显示原因和日志位置并返回菜单。没有成功构建产物时，3 提示先选 1 或 2。第一次下载更新部署脚本后，当前菜单继续使用进入时的控制器快照；退出并重新打开菜单才加载新的控制器。

## 5. 首次开放公网

1. 保持本机 `SiteUrl`，执行 1 或 2，确认本机前端与后端健康检查通过。
2. 在服务器本机打开 `/login` 完成 [账户初始化](账户初始化.md)，核对实际旧数据归属。
3. 选择 4 关闭服务，再选择 0 退出菜单。管理员配置域名解析及 80/443 网络入口；不要开放 API、probe、admin 端口。
4. 将 `SiteUrl` 改为实际的 `https://域名`，设 `AllowPublicAccess=true`，同步修改 API CORS 来源。
5. 重新打开菜单，选择 3 启动已有版本。配置只在打开菜单时读取，修改配置后必须重新打开。脚本先确认 API 是密码模式且账户已初始化，再启动公网 Web；随后校验实际域名的 TLS 与发布版本响应头。

HTTPS 模式由本项目 Caddy 处理证书与反向代理。API 路径保留 `/api/` 前缀；前端路由支持 SPA 回退，缺失静态文件返回 404。证书签发依赖实际 DNS、出入站网络与权限，仍需目标服务器验收。代理行为参考 [Caddy 反向代理说明](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)。

## 6. 版本、关闭与失败处理

- GitHub 仅 SSH，origin 固定 `git@github.com:wojimmy666-code/viral-dna.git`。更新不切分支，不 push，不 stash，不 reset；脏工作区或非快进历史会阻止更新。
- 2 允许编译本地修改及未忽略的新文件；复制到新的发布目录后构建。删除的跟踪文件保持删除；私有 `.env`、依赖目录和运行数据不打包。每个版本记录提交号、本地修改标记、Python 依赖版本和构建时间。
- 构建成功才更新 `last-build.json`；失败产物不会被选项 3 使用，旧成功版本仍保留。1 更新成功而构建失败时，Git 源码可能已变更，但运行版本与源码目录分离，不会拿旧前端配新后端。
- `active.json` 仅记录最近通过完整启动检查的版本，不代表服务当前一定在运行。以菜单里的 Windows 服务状态为准。
- 启动失败会尝试关闭本次启动的本项目服务；无法安全关闭时明确报错，不强杀，不自动回滚数据库或业务文件。
- 控制器先验证服务包装器路径、服务账户和进程父子关系。API 停止还匹配 PID、创建时间、发布路径和本次实例随机令牌；通过私有本地控制文件触发正常退出，不开放 HTTP 关闭接口。
- Web 使用本项目私有管理端口请求 Caddy 正常退出。停止超时就终止操作，不继续启动，也不根据 Python/Node 进程名批量结束程序。Caddy 停止方式见 [官方命令说明](https://caddyserver.com/docs/command-line#caddy-stop)。
- 健康检查通过后才启用 Windows 服务开机启动；选择 4、或开始更新关闭服务时改为手动启动，避免重启服务器后复活维护中的旧版本。
- 停服不等同于备份。脚本不会清理旧发布目录、控制器快照或业务数据；管理员定期检查发布磁盘空间，核实引用关系后人工归档。不要删除当前或配置仍引用的旧版本。

更换服务前缀、账户、部署目录或控制端口前，先用原配置执行 4，再按单独迁移流程处理。不要通过修改 `owner.json` 绕过身份校验。通过 Windows 服务控制台强制停止属于管理员单独操作，可能受 WinSW 自身停止超时行为影响，不等同于本脚本的无强杀关闭路径。

## 7. 命令行与检查

只读检查不下载、不编译、不注册或重启服务：

```powershell
.\scripts\deploy-server.bat -Action status -Config "C:\ProgramData\ViralDNA\deployment\config.json"
.\scripts\deploy-server.bat -Action check -Config "C:\ProgramData\ViralDNA\deployment\config.json"
```

`check` 校验工具、配置、端口和已有服务归属；不会验证 SSH 实际联网、域名可达或“作为服务登录”的有效性。实际更新选项在停服前还会通过 SSH 做只读连通检查。

已完成首次注册后可非交互执行 `-Action update|build|start|stop -Yes`；`-Yes` 明确接受停服，不绕过路径、Git 或进程身份保护。自动化建议直接调用内部 PowerShell 入口获取退出码；`.bat` 在失败时会暂停，便于双击用户读取错误。

开发验证：

```powershell
npm run check:scripts
npm run test:launcher
npm run test:deploy
npm run check:docs
```

部署测试使用独立临时目录与模拟 Windows 服务，不连接 GitHub、不启停业务服务、不调用付费模型。这些测试不能替代目标服务器上的服务注册、重启、TLS、账户隔离和媒体任务验收。

## 8. 常见错误

- 找不到配置：先复制示例并填写本机绝对路径；不要直接使用示例工具路径。
- SSH 失败：用执行菜单的管理员账户检查 SSH key、仓库授权与已核实的主机指纹，不切 HTTPS 或关闭主机校验。
- Windows 服务 1069／拒绝登录：检查固定运行账户密码和“作为服务登录”权限；不要临时改成 LocalSystem。
- 权限不足：核对运行账户对 API 配置目录和业务数据的修改权限、对发布版本和工具的读取权限。
- 端口占用／身份不符：先识别原实例；脚本不接管由开发入口、其他目录或其他账户启动的服务。
- 已安装工具与配置工具不一致：服务二进制按首次副本校验，工具升级需要管理员单独安排，不在一次普通更新中静默替换。
- 域名健康检查超时：检查 DNS、证书、80/443 及服务器到自身域名的连通性；不要把本机 probe 成功当作公网部署成功。

按 [服务器上线清单](服务器部署.md#7-上线验收) 完成真实环境验证后，再开始真实资产迁移和生成业务。
