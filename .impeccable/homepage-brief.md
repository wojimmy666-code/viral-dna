# 对外官网首页

- Scope: `/` 公开官网，与现有账户保护下的工作台分离；不部署、不推送。
- Mode: Persuade。面向初次了解 ViralDNA 的内容创作者与企业团队，让用户理解从参考视频或 Skill 到分镜、视频及剪辑导出的创作流程。
- Visual authority: 用户附图明确批准 `.impeccable/mocks/cinematic-negative-space.png`（第 2 张，1536 × 1024）。保留原有播放标志，仅扩展官网的品牌展示规范，不改工作台视觉系统。
- Approved story: 电影式首屏、两个创作入口、演示流程、精选创作方法、企业共享与收尾入口。
- Proof boundary: 当前影像为 AI 设计示意，页面和播放器均明确标记，不读取或匿名暴露任何账户私有资产，不称其为真实生成案例。没有真实公开案例、联系方式或政策信息时不得伪造；发布清单可后续替换影像。
- Behavior: 导航锚点、作品切换、暂停、演示弹窗、移动菜单、登录后返回站内目标均可用；不因官网访问调用模型、创建项目或获得编辑租约。

## Direction contract

THESIS: 用电影式作品展示引出可控的分镜创作流程，首屏保持左侧明确的阅读与操作、右侧完整产品影像和右下角三段样片选择。

OWN-WORLD: 深炭灰和白字、现有紫色品牌标志与主操作；以成片的暖色侧光承担画面色彩。官网专属大标题与宽留白，不扩散到浅色工作台。

STORY: 用户先看见示意影像并知道这是什么产品，再了解原视频和 Skill 两种入口，查看步骤演示与团队共享说明，最后通过现有登录进入创作。

FIRST VIEWPORT: 1536 × 1024 参考画幅；顶部导航约 72px，左侧两行标题和副文案、主次操作，右侧大幅影像，缩略图组在媒体右下，底部露出双入口。主画面和所有文字位置按批准图测量。移动端独立重排，核心操作保持可见。

FORM: 用户指定的电影级创作片场 / 片场留白构图；种子 9201c755，user-pinned 优先于随机分配。Approved comp: `.impeccable/mocks/cinematic-negative-space.png`。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Verification constraint

内置浏览器当前因本机运行环境过旧不能启动。用户已明确允许使用独立本地无头浏览器，仅验收本项目并保存截图；使用临时配置，不读取个人浏览器资料、不修改全局环境。不把构建通过当作视觉验收。

2026-09-13：独立 HeadlessChrome 152 使用新建临时配置验收，未访问个人浏览器资料。辅助脚本为 `apps/web/tests/helpers/local-browser.mjs`。登录返回目标已接入现有账户页面；官网浏览器测试 6 项、账户浏览器测试 14 项通过。真实生产构建使用本地合成登录响应验收，不代表真实账户/API 联调已完成。

主视觉规格例外：内置 imagegen 两次原生输出均为 1672 × 941，小于流程要求的 2304 × 1287，未放大。候选为 `.impeccable/build/hero-scene-native-candidate.png`，提示词为 `.impeccable/build/prompts/hero-scene.txt`。用户对“先使用这张原生图片完成本地版本，之后再换高清素材”的明确答复为“允许”。因此仅豁免主视觉 1.5 倍像素要求，不降低布局、交互、安全和验收要求，不部署或推送。

## Verification fallback

布局已按测量值实现。字体自动排名缺少可用渲染器且按拉丁字形选出了不支持本稿中文字形的候选，因此使用 Google Fonts 官方 Noto Sans SC 的本地子集，以实际字高对照校验。已保留该工具的原始排名，没有伪造自动测量结论。

首屏像素工具的整体得分已超过 72%（第二次完整对照为 80%），但把重新生成的岩石纹理 E5/C7/D8/E8 判定为额外界面墨迹，并把 6px 滚动条偏移和合法的 Phosphor 暂停图标差异作为控件门禁失败。已查看对应区域对照，修正真实导航定位和按钮偏移；保留工具原始失败状态，不再强制覆盖或把它称为通过。按照技能不能干净应用时的降级规则，后续以同尺寸对照、真实浏览器交互、设计 QA 与独立 finish reviewer 完成验收，明确记录机械门禁未全部闭合。

最终截图用真实“产品特写”控件选择首张并暂停轮播，避免截图耗时超过 7 秒后切到下一张；右下角因此显示播放图标，这是记录明确的验收状态，不是改写参考稿或页面。最终同尺寸报告为 81%，仍保留区域纹理差异及未闭合门禁。手机使用系统“减少动态效果”状态，菜单/演示截图保留实际键盘焦点。

## Independent finish review

`.impeccable/review/finish-review.md` 返回 `disposition: ship`，范围为用户批准的本地版本。独立打开原始稿、13 张指定截图和 15 个配对局部后，没有必须返工的视觉或产品边界问题；结论不代表 CLI 全门禁通过、真实账户后端已联调或获得部署授权。首页设计规范由独立 documenter 在 `apps/web/src/landing/` 归档，保留既有工作台系统。
