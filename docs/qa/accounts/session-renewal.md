# 登录续期与原地恢复验收

实施日期：2026-09-20。业务规则见 [独立账户与企业协作](../../features/accounts/account-system-implementation.md)。

## 范围与边界

- 个人和企业成员使用 12 小时滑动窗口、7 天最长会话；admin 使用 2 小时滑动窗口、24 小时最长会话。
- 续期复用当前登录令牌，每 5 分钟最多延长一次，Cookie 同步更新，不创建新用户或新会话。登录身份变化、退出、改密、停用仍独立生效。
- 只接受当前窗口的真实输入、点击、滚动与拖拽活动；后台请求、编辑锁和模拟 DOM 事件不续期。标签页广播不包含凭据或内容，并通过服务器核实；Web Locks 不可用时仍有服务器节流。
- 网络失败保留内容并退避重试状态检查；真实登录失效暂停业务请求。重新登录在原页完成，后端要求原用户 ID；成功后重新申请编辑锁，冲突只读，不自动重放生成、保存或消费请求。
- 草稿保护是当前页面内存保护，不是跨刷新持久化；退出/刷新前仍可复制或下载已挂载提示词。
- 使用原认证表结构，不迁移真实账户数据；本轮自动化测试使用临时数据库、虚拟时钟和临时浏览器，不调用真实模型。

## 自动化覆盖

后端 `test_account_session_lifetime.py` 覆盖双会话的滑动/最长期限、只读不续期、已过期/注销/改密/停用拒绝复活、并发续期、编辑锁最长时限、Cookie 标志、来源/CSRF/跨标签页身份校验和原用户重新登录。原账户仓库、输入规则与租户隔离测试共同回归。

前端 `session-activity.test.mjs`、`account-client.test.mjs` 覆盖持续输入、拖拽/滚动、闲置/后台/伪事件、前后端独立、断网退避、唤醒过期、跨标签页核验、撤销与迟到响应、监听清理、暂停期间业务请求拦截。

`account-browser.test.mjs` 在隔离 Chromium 中检查 1280px/390px 原地登录、错误密码/错误用户、键盘关闭与焦点、等待验证期间不卸载编辑器、保留同一个输入 DOM 及文本、占用冲突保持只读、重新取得编辑权后继续编辑、不重放失败的业务请求；同场回归既有登录、账户管理、顶栏和存储页面。

## 复现命令

```powershell
.\.venv\Scripts\python.exe -m pytest services/api/tests/test_account_session_lifetime.py services/api/tests/test_accounts_repository.py services/api/tests/test_account_input_rules.py services/api/tests/test_account_isolation_http.py -q
npm --workspace apps/web run test:sessions
npm --workspace apps/web run test:accounts-browser
npm run check:design
npm run test:web
npm run build:web
npm run check:docs
```

## 本地结果

- 本地 API 已重启加载新代码，源码新鲜度检查通过；`127.0.0.1:4174/login` 返回 200，前台/后台续期端点及前端代理在未登录时均返回预期的 401。未改动正式服务器，未用真实用户密码进行验收。
- 账户后端回归 98 项通过（包含真实隔离应用启动及迁移回归）；前端预检查 85 项、主回归 331 项通过；隔离浏览器 20 项通过；设计检查 8 项及生产构建通过。构建保留已有的大包体积提示。
- 桌面 1280px 与手机 390px 的重新登录、错误恢复和占用冲突截图在本地 `.tmp/session-review/`，不作为生产账户数据提交。
- 当前环境无可连接的 Browser 插件，使用项目隔离 headless Chromium 测试。Windows 环境部分原生 Esc 注入未送达，测试明确记录并回退验证 DOM 键盘与原生 dialog 的 cancel 处理；不是对真实用户浏览器/正式服务器的完整验收。

## 升级后人工检查

1. 旧页面先保存或复制未提交内容，再刷新加载新版本；已失效的登录重新登录一次。
2. 持续编辑时在网络面板观察 `/auth/refresh`：约每 5 分钟一次，Cookie 与返回的到期时间同时更新。
3. 页面后台闲置、只轮询生成进度不应持续发送续期；返回前台先检查登录状态。
4. 超时后原页点击「重新登录」，验证失败、关闭窗口不丢内容；成功且项目空闲后才能继续提交。
5. 另一成员占用项目时，保留原文本并提示占用，不能强行覆盖；原版本冲突检查继续生效。
