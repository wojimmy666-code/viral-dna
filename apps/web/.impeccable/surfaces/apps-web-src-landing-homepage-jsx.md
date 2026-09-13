---
version: 1
slug: "apps-web-src-landing-homepage-jsx"
primary_target: "apps/web/src/landing/HomePage.jsx"
related_targets:
  - "apps/web/src/landing/HomeFilm.jsx"
  - "apps/web/src/landing/home-media.js"
---

# 对外官网首页

## 当前媒体更新 · 2026-09-13

用户已提供「视频节点 1 .mp4」「视频节点 2.mp4」「视频节点 3.mp4」并明确要求应用到首页。现按原帧顺序无损拼接为 15.125 秒、720p、24fps 的静音影片，替换先前静态轮播及静态演示；版式与产品事实保持不变。缩略图来自实际视频首帧，播放/暂停与分镜跳转均操作真实影片。来源见 `public/home/video/provenance.json`，本次本地验收见根 `.impeccable/review/homepage-video/acceptance.md`。以下原生图片例外与旧 finish review 保留为历史记录，不代表新视频为4K或已部署。

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

2026-09-13：独立 HeadlessChrome 152 使用临时配置完成截图和交互验收；官网浏览器 6 项、账户浏览器 14 项通过。生产构建使用合成登录响应，不代表真实账户/API 联调完成。完整现行证据与限制以根 `.impeccable/homepage-brief.md` 为准。

主视觉采用用户明确允许的原生 1672×941 素材完成本地版本，未放大；仅豁免主视觉 1.5 倍像素要求，不扩大部署或推送权限。

## Verification fallback

字体使用官方 Noto Sans SC 本地子集并人工对照字高，保留原始工具排名。最终同尺寸像素报告为 81%，机械 hero gate 仍未全部闭合；保留原始失败状态，不声称 CLI 全门禁通过。按根 brief 已记录的 fallback，以同尺寸对照、真实浏览器交互、设计 QA 与独立 finish review 完成本地验收。截图通过真实控件选首张并暂停；手机采用系统减少动态效果状态。

## Independent finish review

根 `.impeccable/review/finish-review.md` 返回 `disposition: ship`，仅覆盖用户批准的本地版本；原始稿、13 张截图及 15 个配对局部没有必须返工的视觉或产品边界问题。机械门禁未闭合、原生素材例外和真实账户后端未联调仍须保留。首页设计规范与 schemaVersion 2 sidecar 归档在 `apps/web/src/landing/`，既有工作台规则继续保留。
