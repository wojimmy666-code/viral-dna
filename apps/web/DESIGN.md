# ViralDNA UI System 1.0

ViralDNA 是面向长时间桌面创作与分析工作的产品界面。用户通常在室内常规光线下持续阅读报告、编辑提示词并操作生成任务，因此界面采用安静的浅色工作台、克制的紫色交互强调和高可读性的紧凑排版。

本文件是 Web 端的设计契约。新页面和新组件必须遵守这里的规则；页面样式只能决定业务布局，不能自行创建新的字号、文字灰度、按钮或状态视觉。

适用边界：本文件下述“全系统”“Web 端”“业务页面”规则均指账户工作台及其业务界面。公开官网 `/` 使用独立的 [首页设计契约](src/landing/DESIGN.md) 与邻近 sidecar；其深色影像、大标题和 `--home-*` 令牌仅限 `src/landing/`，不改变本文件的工作台规范。

## Typography / 排版

全系统只使用系统无衬线字体与以下四档字号：

| 角色 | 令牌 | 尺寸 | 字重 | 用途 |
| --- | --- | --- | --- | --- |
| Page | `--type-page-size` | 20px | 600 | 页面唯一主标题 |
| Heading | `--type-heading-size` / `--type-subheading-size` | 16px | 600 | 区块、面板、弹窗标题 |
| Body / Label | `--type-body-size` / `--type-label-size` | 14px | 400 / 600 | 正文、输入、按钮、字段标签、提示词 |
| Caption | `--type-caption-size` | 12px | 400 / 600 | 时间、模型、状态和辅助信息 |

- 普通字重只能使用 `--type-weight-regular` 与 `--type-weight-semibold`。
- 中文标题与 UI 文本使用正常字距，不使用大写眉题或宽字距标签。
- 标题行高使用 `--type-leading-tight`，控件使用 `--type-leading-ui`，正文与编辑器使用 `--type-leading-copy` / `--type-leading-editor`。
- 长正文建议限制在 65–75ch；提示词编辑器按业务要求占满可用宽度并正常换行。
- 移动端输入框保持 16px，防止移动浏览器自动缩放。

## Color / 颜色

普通文字只有两个层级：

- `--text-primary`：标题、字段值、关键数据。
- `--text-secondary`：正文说明、标签、元信息。

`--text-disabled` 只表示不可操作状态。深色媒体界面使用 `--text-on-dark` 与 `--text-on-dark-muted`。

紫色 `--accent` 只用于：

- 主操作；
- 当前选中或活动状态；
- 键盘焦点；
- 可点击链接；
- `@` 素材引用。

成功、警告、错误、信息必须使用 `--status-*-text/bg/border`。不能使用颜色作为唯一状态线索，必须同时提供图标或文字。

普通结构使用 `--surface-*` 与 `--border-*`。页面不得通过新增近似灰色或大量浅色卡片制造层级。

## Spacing and geometry / 空间与形状

- 间距只使用 `--space-1/2/3/4/6/8`，对应 4/8/12/16/24/32px。
- 默认控件高 `--control-height`（40px），紧凑控件 36px，突出控件 44px。
- 控件使用 `--radius-control`，普通面板使用 `--radius-panel`，弹层使用 `--radius-overlay`。
- 胶囊圆角只用于状态标签或真正的 pill 控件。
- 普通面板依靠边框和空间分组；不同时叠加边框与大面积柔和阴影。
- z-index 必须使用 `--z-dropdown/sticky/modal-backdrop/modal/toast/tooltip`。

## Shared components / 共享组件

新页面优先使用 `src/ui/system`：

- `PageShell`：页面字体、颜色和最小宽度基线。
- `PageHeader`：唯一页面标题、说明与页面级操作。
- `SurfacePanel`：需要真实边界的内容面板。
- `SectionHeader`：区块标题与操作。
- `StatusBadge`：neutral / active / info / success / warning / danger。
- `InlineMessage`：行内信息、成功、警告和错误反馈。

设置页继续使用 `src/ui/settings`，其底层已复用 `PageShell` 和 `SurfacePanel`。按钮统一使用现有 `primary-button`、`secondary-button`、`text-button` 角色，不为单个页面重新发明按钮。

## Page patterns / 页面模式

### 账户与工作台顶栏

- 登录后使用单一 56px 顶栏，`--account-header-height` 同步通知抽屉与侧栏偏移；不堆叠账户条和第二行工具栏。
- DOM 与视觉顺序均为紫色播放标识与 ViralDNA、侧栏折叠入口、账户名称／类型、页面原有搜索、通知、用户名菜单。品牌固定在最左上角，侧栏不重复显示品牌及“视频逆向拆解系统”副标题，菜单导航上移。账户类型使用 Caption／次级文字；账户名和用户长名省略，保留完整 title，不缩小正文。
- 主要操作目标 44px，组间距沿用 16px／窄屏 8px，白色表面与一条底部分隔线；无全局问号帮助按钮。
- 820px 及以下，品牌只保留图标，账户图标和类型让位于名称与操作；600px 及以下，账户名称和类型移到账户菜单中。原有搜索改为点击图标打开浮出输入框，Escape 关闭并归还焦点，不生成常驻第二行。导航开关在桌面折叠侧栏，在窄屏打开抽屉，抽屉内保留关闭按钮。专注页面继续不显示搜索。
- 账户菜单独立于工作台控件；成员、存储、只读及独立设置页面无工作台控件时也保留品牌和账户入口，但不显示无效的侧栏开关。品牌整体为“返回工作台”链接，普通账户回 `/projects`、admin 回 `/admin/accounts`，不跳官网或退出登录；保持原标识外观，点击区域至少 44px，键盘焦点清晰。跳转须等待统一草稿保存，失败时在品牌下方短提示并保留原页；等待中防重复点击，取消过期跳转。存储页仍保留“返回资产库”。公开官网和独立登录表面不应用此顶栏。

### 分析报告

- 结论优先，证据和推断过程渐进展开。
- 章节标题 16px，正文 14px，证据元信息 12px。
- 普通摘要、编号和依据标签使用中性色，不使用装饰性紫色。
- 减少嵌套卡片；同一报告区块优先使用分隔线、列表和留白。

### 设置

- 页面标题 20px，设置组标题 16px。
- 字段标签 14px/600，值 14px/400，帮助文字 12px。
- 所有输入、选择、开关必须提供 default、hover、focus、disabled、error 状态。
- 设置组使用分割线组织；只保留一个页面级主保存操作。

### 提示词与生成工作台

- 提示词与高亮镜像层统一为 14px、1.55 行高和 10px 12px 内边距。
- `@` 引用与正文同字号，只用紫色和 600 字重区分。
- 图片和视频提示词必须复用相同文本角色。

## Responsive / 响应式

- 1440px：完整桌面布局。
- 1280px：保持主要双栏，不允许内容横向溢出。
- 1024px：受限工作区按容器宽度降为单栏。
- 768px：侧栏或设置导航切换为横向/折叠结构。
- 390px：操作换行，主按钮可占满一行；不能通过缩小正文塞入内容。
- 响应式调整布局结构，不使用流式字体缩放。

## Accessibility and motion / 可访问性与动效

- 普通正文和占位符对比度至少 4.5:1。
- 所有交互可键盘访问并显示统一焦点环。
- 触控目标至少 44×44px；桌面紧凑控件必须保留足够点击区域。
- 状态变化使用 150–200ms 的 ease-out 过渡，不使用无意义的入场动画。
- 所有非必要动效必须提供 `prefers-reduced-motion` 关闭方案。

## Engineering rules / 工程约束

- CSS 中的 `font-size` 和 `font-weight` 必须引用系统令牌；只有图形隐藏可以使用 `font-size: 0`。
- 普通 `color` 属性必须引用语义令牌；强制颜色模式的 `CanvasText` / `HighlightText` 是例外。
- 禁止新增 `--production-*` 等页面私有排版或文字颜色变量。
- 禁止新增 500、700、800 等普通 UI 字重、数值字距和 `text-transform: uppercase`。
- 业务页面不得使用旧兼容变量 `--purple/--ink/--muted/--line/--panel/--canvas`。
- 修改 UI 后必须运行 `npm run check:design`、`npm run test:web` 和 `npm run build:web`。

## Pull request checklist / 新增页面检查

- [ ] 使用共享页面与反馈组件。
- [ ] 只使用四档字号、两档字重和两级普通文字色。
- [ ] 主操作、选中和状态色含义一致。
- [ ] 加载、空、错误、禁用和处理中状态完整。
- [ ] 1440/1280/1024/768/390px 无关键文字截断和横向溢出。
- [ ] 键盘、焦点、对比度和 reduced-motion 已验证。
- [ ] 设计检查、测试和生产构建通过。
