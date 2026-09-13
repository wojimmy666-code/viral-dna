---
version: 1
slug: "apps-web-src-landing-logindialog-jsx"
primary_target: "apps/web/src/landing/LoginDialog.jsx"
related_targets:
  - "apps/web/src/landing/PublicLoginForm.jsx"
  - "apps/web/src/landing/HomePage.jsx"
  - "apps/web/src/landing/login.css"
  - "apps/web/src/main.jsx"
  - "apps/web/src/accounts/login-service.js"
---

# 官网登录浮层

Mode: Operate。用户已确认在既有首页上浮现前端登录，成功后才进入工作台。沿用已批准的首页影像、品牌与组件语言；本次是窄范围扩展，不产生新的视觉世界或重新选择首页构图。

## Direction contract

THESIS: 让登录成为从官网进入创作的连续一步，官网实例与当前位置保持不变。

OWN-WORLD: 继承官网深炭面板、白字、细灰边框、紫色主操作和既有播放标识。以功能性压暗与轻模糊区分前景表单和背景首页，不扩散到浅色工作台。

STORY: 点击创作入口，在原页面上输入手机号与密码；错误原位修正，成功进入已选择的站内目标，关闭继续浏览。

FIRST VIEWPORT: 桌面居中最大 440px 宽、16px 圆角，内边距 28px 32px 32px；32px 既有标识、18px／600 品牌和 44px 关闭控件，24px／600 标题，手机号与密码纵向排列。标签 14px／500、输入 16px／400 且高 48px，提交 16px／600、最小高 48px（实际约 48.39px）；说明 13px／400、连接及错误文字 14px／400。全部继承中文系统 UI 字体，不用展示字子集。480px 及以下内边距 20px 24px 24px，两侧至少 16px；高度受 visualViewport 约束，可内部滚动，顶部品牌与关闭栏 sticky。

FORM: 用户明确确认的首页登录浮层，继承既有 homepage direction（9201c755）；本次窄范围用户指定交互直接实现，无新的 concept-seed 或素材生成。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Boundaries and acceptance

- `/` 与 `/login?returnTo=…` 复用同一首页实例；所有创作入口打开登录浮层并保留站内白名单目标。普通 `/` 不预读账户接口，仅浮层打开后按需加载表单、读取 auth/status，再按状态读取 session；直达、刷新、关闭、浏览器前后退均有效。
- 只复用真实认证 API、既有手机号/密码规则和站内跳转白名单，不创建账户、不绕过权限、不代填真实凭据。
- 打开暂停视频并关闭菜单／演示，关闭恢复原播放意图、滚动位置与焦点；支持关闭按钮、Esc、遮罩关闭和 Tab 圈定。可见视口 resize／scroll 时更新布局，短视口仍能滚动至提交并关闭；实体手机软键盘未实测。
- API 不可用不卸载首页；连接错误与凭据错误分开显示并可恢复。状态检查与提交均使用 AbortController 和 15 秒超时，提交防重；关闭卸载表单、清除密码并忽略迟到结果。
- 后台登录入口移至官网页脚；初始化、激活和工作台内会话失效处理保留独立原流程。
- 使用项目既有隔离浏览器及合成账户验证；真实本地 API 仅匿名读取状态，不提交真实账户密码。未授权提交、推送或正式部署。

## Implemented visual contract

规范与 schemaVersion 2 sidecar 位于 `apps/web/src/landing/DESIGN.md` 及其 `.impeccable/design.json`。深炭面板沿用已有 panel、ground、line 与 text；输入和提交为 8px 圆角，44px 密码眼睛控件内嵌 2px，使用 6px 圆角。输入焦点外偏移 2px，其余交互保留 5px；均为 2px 亮紫轮廓。

默认主操作沿用 `#5b4df5`，仅登录 hover 使用 `#6355f6`，白字 `#f7f7f6` 的对比度为 4.7083:1；原首页 hover `#7165ff` 保留。错误为 `#ffc0c4` 并配明确文案。18px 品牌、13px 说明、6px 内嵌圆角和错误色均是本次评审接受的实际值。

遮罩为 `rgb(8 7 10 / 58%)`、模糊 5px；入场 180ms，减少动态效果下无入场动画。打开期间根画布临时取 `--home-ground`、`color-scheme: dark`、`scrollbar-gutter: stable` 并锁背景滚动，关闭逐项恢复；不改变独立账户页或工作台主题。

## Completion evidence · 2026-09-13

[独立完成评审](../../../../.impeccable/review/homepage-login/finish-review.md) 为 `disposition: ship`，只对根画布露白与登录 hover 对比度两项修复判为 resolved。最终运行结果与证据范围以主代理的[本地验收](../../../../.impeccable/review/homepage-login/acceptance.md)为准：build 通过、前端 pretest 75/75 与主套件 313/313、官网浏览器 16/16 且退出码 0、原账户浏览器 14/14。文档合并未重跑这些测试。

截图覆盖桌面、390×844、320×568、768×900、390×360，以及凭据错误、服务错误与 hover；文件清单和相对链接见验收记录。390×360 是短视口 fixture，不是实体手机键盘测试。真实 5175 本地预览只验证匿名打开与关闭（auth/status 200、session 401），未提交真实密码；成功登录与错误分支使用合成响应。旧首页素材例外和 hero gate 历史继续保留，本次未新增栅格素材。
