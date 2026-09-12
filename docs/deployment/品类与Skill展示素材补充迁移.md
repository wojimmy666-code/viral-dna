# 品类与 Skill 展示素材补充迁移

适用：测试端账号和工作区已迁入正式端，但品类库、Skill 封面/展示视频或模型密钥尚未补齐。正式端可以已有新项目、新成员或修改过手机号。本工具不重做整库迁移，不要求正式端为空。

## 迁移范围

| 内容 | 补充方式 | 正式端已有不同内容时 |
| --- | --- | --- |
| 账号品类库 | 从账户目录登记文件旁的 `category-profiles.json`，按账户 ID、档案 ID 合并 | 保留正式端，列出冲突；同账户同名不同 ID 也不强行新增 |
| Skill 封面和展示视频 | 只合并 `platform-skills.json` 的 `presentation`，连同引用到的 `platform-skill-media` 文件 | 不覆盖已编辑或主动清空的展示；相同内容可重复执行 |
| 模型 API key | 单独加密，解密后只补正式端配置中缺失或为空的白名单项 | 不替换不同密钥，列出冲突 |

旧版 [整账户迁移](测试服务器整体迁入空正式服务器.md)没有包含独立存储的品类库，也刻意排除了平台级 Skill 展示与模型配置。更新 Git 不会同步这些运行数据。这里用增量补充工具处理，**不要再用整库 import 覆盖已经使用中的正式端**。

目前密钥白名单是 `DASHSCOPE_API_KEY`、`ARK_API_KEY`、`MINIMAX_API_KEY`、`GEMINI_API_KEY`，仅复制来源指定配置文件中非空的项目。不复制模型 ID、验证时间、代理、本机可执行文件路径、域名、身份库路径、认证开关、OSS 或其他配置。环境变量单独注入的密钥不在包中。

Skill 展示是平台共享配置，不是每个账号各一套。不会导入或发布 Skill 定义版本；正式端缺少相应 Skill ID 时报告冲突，应先确认两端 Skill 已安装。通知库、Cookie、OSS/同步 DPAPI 凭据和本机 Codex 登录不包含在本包内，需要在正式端单独设置。

## 推荐：使用准备好的独立菜单包

包内自带少量 Python 标准库脚本，不依赖 API 虚拟环境、不联网、不编译前端，也不需要先更新 Git。正式端使用已准备的 Python 和 Node：

```text
C:\Projects\ViralDNA\.server\tools\python\python.exe
C:\Projects\ViralDNA\.server\tools\node\node.exe
C:\Projects\ViralDNA\.server\config\api.env
```

1. 将 `*.vdna-supplement-kit.zip` 复制到正式端，解压到 `C:\Projects\ViralDNA\.server\migration\`。保留包内完整目录，不要在 ZIP 中直接运行脚本。可以使用 Windows 自带解压；包内采用普通 ZIP/Deflate，打包后会校验 CRC 和逐文件 SHA-256。
2. 把另外提供的 `*.vdna-unlock` 解锁文件保持原名，单独复制到 `C:\Projects\ViralDNA\.server\migration-secrets\`。不要放入解压目录、IIS 站点物理目录或 Git。复制完成后核对 ZIP 的 SHA-256 与提供方记录一致，解锁文件内容不要截图或发到聊天。
3. 暂停 **ViralDNA** 的 IIS 站点入口，运行 `.server\setup\05-run.bat` 选择 **4**，停止本项目服务。不要 `iisreset`，不要停止其他站点或服务。等待正在生成的任务结束后再停服。
4. 双击解压目录内 `migrate.bat`，按 **1** 预览。核对目标配置、账户 ID、品类数、Skill 展示和密钥名称。预览不改业务文件；菜单会另外保存不含密钥值的操作报告。
5. 无冲突时按 **2**，输入 `IMPORT` 执行。预览后文件变化会阻止导入，必须重新按 **1**。若有冲突，默认完全不导入；核对后可按 **5** 切换为“保留正式端”，重新按 **1** 后只补不冲突项，仍不会覆盖冲突项。
6. 出现 `imported: true` 后，运行 `.server\setup\05-run.bat` 选 **3** 启动本项目服务，再恢复 ViralDNA 站点入口。无需重新初始化账户或重建前端。

不希望复制密钥时，菜单按 **6** 明确跳过，再重新预览。解锁文件丢失/不匹配、媒体缺失、目录联接/符号链接、账户 ID 不匹配或 Skill 媒体未处理完成都会拒绝相应操作，不会猜测账户归属。

## 验收

- 用正式端当前手机号和密码登录，确认新旧项目仍在；工具从不写入身份数据库、账户目录登记或账户工作区。
- 对应账号的品类库出现补齐的档案，其他账号的档案不受影响。
- Skill 列表和详情能显示封面并播放展示视频；定义版本与发布状态保持正式端原值。
- 后台模型设置显示预期服务商已配置密钥，再分别验证服务商配置。**配置已迁移不等于已验证密钥有效、余额充足或网络可达**；本工具不会发起模型调用。
- 重复预览应显示无需新增，或仅列出此前选择保留的正式端冲突。

## 备份与中断恢复

实际导入要求人工确认停服，并与 API 共用排他锁。写入前保存旧文件和恢复日志，逐个校验后原子替换；异常自动回退。中断标记使用现有 API 也认识的 `.installation-migration.json`，避免断电后启动半完成的数据。

默认备份位于 `C:\Projects\ViralDNA\.server\data\supplement-migrations\<操作ID>\`；报告在 `.server\migration-reports\`。旧 `api.env` 的备份同样加密，不能当明文配置直接覆盖回去。

发生断电或 Ctrl+C：保持停服，重新运行菜单，按 **3** 预览故障恢复，再按 **4** 输入 `RECOVER`。只恢复未完成的本次补充操作；新加文件会移入该操作的 `rolled-back-files`，不直接删除。如果恢复时发现人工新修改，会暂停保护这些文件，请提供报告进一步检查。**不要删除迁移标记、备份或解锁文件来绕过检查**。

密钥使用 AES-256-GCM，随机 256 位解锁密钥、随机 12 字节 nonce 和 16 字节认证标签。解密认证通过后才释放明文；算法接口依据 [Node.js Crypto 文档](https://nodejs.org/docs/latest-v20.x/api/crypto.html)。解锁文件与普通包分开存放，Windows 创建时限制为当前用户与 SYSTEM 可读写；不需要新建 Windows 账户。长期保留解锁文件的受控备份，不能丢失。

## 维护者：重新生成补充包

入口：[build-supplement-package.py](../../scripts/maintenance/build-supplement-package.py)。先预览，确认路径和数量后加 `--apply`。输出路径必须是新目录，禁止覆盖旧包；真实包和解锁文件已被 Git 忽略。

```powershell
$supplementPython = 'C:\Users\HUAWEI\AppData\Local\Programs\Python\Python312\python.exe'
$supplementTool = 'D:\Projects\ViralDna\scripts\maintenance\build-supplement-package.py'
$supplementArgs = @(
  '--env-file', 'D:\Projects\ViralDna\.env.local',
  '--output', 'D:\Projects\ViralDna\.server\migration\copy.vdna-supplement-kit',
  '--include-model-keys',
  '--unlock-file', 'D:\Projects\ViralDna\.server\migration-secrets\copy.vdna-unlock',
  '--node', 'D:\ViralDNA\tools\node\node.exe'
)
& $supplementPython $supplementTool @supplementArgs
# 核对预览后执行下一行；已经生成过的输出路径需改成新名称。
& $supplementPython $supplementTool @supplementArgs --apply
```

导出只读取来源文件，前后检查配置与媒体哈希是否稳定；如来源正在修改封面或品类，停止这些编辑后用新包名重试。不会停止测试端服务。来源配置必须指向实际使用的账户目录，不能拿另一台机器的环境文件代替。

高级命令入口为 [transfer-supplement.py](../../scripts/maintenance/transfer-supplement.py)：`export`、`verify`、`import`、`recover`，默认只预览；实际 import 需 `--apply --confirm-api-stopped --manifest-sha256 ... --plan-sha256 ...`。`--keep-target-conflicts` 只允许保留正式端冲突项，绝不表示强制覆盖。正式端要求 `accounts.sqlite3`、`account-catalog.json` 和 `accounts` 同在专用数据目录，`api.env` 位于数据目录之外。

这里是补齐缺项和离线恢复工具，不是持续双向同步；以后两端同时编辑的同一档案仍需人工决定，不会自动选最新时间覆盖。
