disposition: ship

范围：当前获准的本地官网版本；QUALITY BAR 为用户选定的 `cinematic-negative-space.png`。没有独立启动浏览器或重跑测试、检测器。交互结果采用委派包提供的生产构建 fixture 测试证据，不代表真实账户/API 联调或部署验收。

## persistence

- pass：`PRODUCT.md`、六段首页契约、选稿记录、`state.json`、`spec.json`、两轮差异报告均存在。FORM 的 `9201c755` 与 state 的 direction 一致；comps、spec、plates 已 closed，无 forced 记录。
- fail（机械流程全闭合这一项）：hero 仍 open，历史 gate 为 0.7997 / `ok: false`，后续阶段仍 pending。最终同尺寸报告为 0.8078，并不使历史门禁自动通过。本次采用 brief 已记录的人工复核 fallback；下表给出实际画面的判断，不改写原始门禁结果。
- pass（证据有效性）：已打开原始 comp 及全部 13 张指定截图：hero-repro、desktop、desktop-1280、desktop-1600、mobile、mobile-first-viewport、mobile-menu、demo-desktop、demo-mobile、responsive-320、responsive-375、responsive-768、responsive-1024。全页从顶部开始、图片齐全；首屏和菜单/弹窗捕获的状态与文件用途一致，无缺失或空白捕获。手机弹窗存在可滚动内容，不是损坏截图。
- 新首页的最终 DESIGN.md 与 design.json 属于随后 documenter 的工作；旧工作台 DESIGN.md 未作为本首页视觉权威，也未扩展审计旧工作台。

## fidelity

原始构图的显著元素是：左上播放标志及字标、顶部四项导航和右上紫色入口、左侧两行粗黑体白字与双操作、右侧高大的琥珀瓶和金属瓶盖、暖光岩石环境、右下三幅带标签的样片与圆形播放控制，以及底部露出的双入口。

| 元素 | 判断 | 证据与裁决 |
| --- | --- | --- |
| 总体拓扑、阅读顺序与焦点 | match | 同尺寸 hero 保留左文右物、产品大尺度、右下样片、底部双入口；没有用整张 UI 截图替代页面。 |
| TYPE | match | 主标题仍是宽厚、低笔画反差、明确方形结构的中文黑体，两行关系保持；paired headline 的字墨范围为 543×177 对 534×180，未换成另一种文字性格。代码为本地字体资源，不是系统 display face。 |
| MATERIAL | match | 玻璃通透、金属拉丝、湿岩反光和光雾均由可见栅格素材承担。主图的岩纹和局部高光不同，但没有变成 CSS 假材质，也没有把图藏在遮罩后。用户已明确允许该原生素材完成本地版本。 |
| GROUND | match | 片外底色抽样：comp 在 (30,880) 为 RGB 15,16,20，build 为 16,15,18；(300,880) 为 16,17,21 对 16,15,18。差值很小，仍是同一深炭灰范围，未形成可见的另一套冷暖底色。主图暗部更黑、岩石亮部更明显，是重生照片的差异。 |
| 品牌 | adaptation | 使用既有 favicon 播放标志，保留紫色与 ViralDNA 字标；依据 brief 明确保留原品牌的要求。 |
| 四项导航 | match | 项目、顺序和顶部层级齐全；最终 navigation paired crop 的轻微字形/基线差异未改变结构。 |
| 顶部入口 | match | 紫底、白字、圆角、右上位置和实际登录目标保留。 |
| 副文案 | match | 参考视频/Skill、分镜、图像、视频和剪辑的产品说明完整，双行节奏与 comp 接近。 |
| 首屏双操作 | match | 紫色主操作与黑底细描边次操作、箭头/播放识别均在，按钮层级和相邻关系保留。 |
| 示意标签 scene-label | match | 报告判 contradicted，但 paired crop 两边均有“视觉示意 · 非真实案例”；右侧差异包含更亮岩纹、真实文字渲染与裁切边界，未出现语义矛盾或内容缺失。 |
| 产品特写 thumb-close | adaptation | 最终 report 的 missing 不成立：paired crop 清楚显示琥珀瓶、岩台、暖光及紫色选中边框。按 brief 的 AI 示意素材边界重生照片，结构和用途保留。 |
| 场景演绎 thumb-scene | adaptation | 峡谷、远景产品与暖光关系保持；纹理差异属于已记录的重生示意素材。 |
| 运镜节奏 thumb-motion | adaptation | 倾斜金属瓶盖近景与材质焦点保持。历史 missing 不是当前状态；最终 paired crop 中素材完整。 |
| 三项样片文字 | match | 三个名称、顺序和各自图像的对应关系完整、可读。 |
| 播放/暂停控制 | adaptation | 本次使用真实控件选第一张并暂停，因而显示播放图标；依据 brief 的捕获状态。手机禁用自动播放且保留手动切图，依据减少动态效果要求。 |
| 底部双入口 | match | 参考视频与 Skill 两入口并列、垂直分隔关系保留；手机堆叠符合 FIRST VIEWPORT 的独立重排要求。 |
| 后续流程、方法、协作与收尾 | adaptation | 为 brief 已批准的 STORY 延展，完整桌面/手机截图均可见；没有新增客户成绩、统计数字或收费承诺。 |
| 手机、菜单与演示 | adaptation | 320–768 宽度把图片、正文和操作分开排列，主操作可达；1024 恢复左右结构。菜单和弹窗保持同一色系、清晰焦点及可读内容，依据响应式与键盘访问要求。 |

已读取两个 report、最终 15 个区域的 paired crops 和 heatmap。E5/C7/D8/E8 的额外细节落在照片岩石/光影上，未发现对应的额外导航、标签或界面结构；不能据此要求删除真实照片纹理。

## ceiling

reached（用户选定构图与获准原生分辨率的本地范围）。影像的尺度、玻璃/金属/岩石深度、粗标题与暖光承担了该方向的表现力；没有需要另加的新装饰或另一套视觉世界。

- THESIS / OWN-WORLD：左侧阅读操作、右侧影像及紫色品牌均成立，工作台通过独立私有入口加载。
- STORY：从示意画面进入双入口、五步流程、方法与团队共享，再进入登录，顺序完整。
- FIRST VIEWPORT：桌面记忆点仍是暖光瓶体、两行白字和紫色主入口；手机第一屏提供产品说明和两项主操作。
- FORM：用户指定的片场留白构图保持，seed 有 state corroboration。
- Truth / Floor：示意图、静态分镜及协作成员均明确为示例；四个 spec 栅格区域均被 SceneImage 引用且实际可见，PNG/WebP 共八个素材的 provenance 由委派包声明已校验。首页文件没有账户数据请求、创建项目或生成模型调用；登录返回地址有站内白名单。未见装饰性 eyebrow、假统计、渐变文字、伪摄影 SVG 或无意义编号；步骤编号具有流程含义，示意标签是内容真实性说明。detector.json 为 []。
- 行为验证范围：代码具有真实切图、暂停、减少动态效果、菜单 Escape、原生 dialog 及焦点恢复、流程键盘切换。提供的测试结果为工作台 312、首页/登录目标 6、账户浏览器 14、官网浏览器 6 项通过；这里只接受其合成 fixture 范围，不据此扩大为真实登录验证。FINISH 的文档交接仍需随后完成。

## material_fixes

无必须返工的视觉或产品边界问题。机械 hero gate 的未闭合状态、原生素材例外和真实后端未联调范围必须随本地交付保留；本 disposition 不表示 CLI 全门禁完成，也不授权部署。

## keep

保留左文右影的首屏构图、暖金摄影材质、现有紫色品牌、清楚的示意标识、手机可达操作，以及公开官网与账户工作台的边界。
