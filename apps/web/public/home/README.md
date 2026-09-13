# 官网公开展示素材

这里的四张图片是按照用户选定设计稿，用内置 ImageGen 专门生成的视觉示意。没有使用任何账户的资产、项目、Skill 封面或生成历史。它们不是客户案例，也不代表模型服务的真实生成效果或速度。

## 素材清单

| 文件前缀 | 用途 |
| --- | --- |
| hero-scene | 首屏主视觉，产品特写 |
| thumb-close | 产品特写缩略图和创作方向展示 |
| thumb-scene | 场景演绎缩略图与流程演示 |
| thumb-motion | 材质近景与运镜节奏示意 |

PNG 为原生生成文件（带原始提示词元数据）；WebP 为同尺寸压缩版本，提示词保存在对应 `.webp.json`。网页优先使用 WebP，加载失败时回退 PNG，再失败则显示图片不可用状态。主视觉原生尺寸 1672 × 941；用户已明确同意先用于本地版本，没有放大补像素。字体来源与许可证见 [fonts/README.md](fonts/README.md)。品牌标志直接复用项目已有的 `favicon.svg`，未交给图像模型重绘。

## 更新展示

公开清单位于 `src/landing/HomePage.jsx` 的 `IMAGE_SOURCES`、`SAMPLES` 与创作方法列表。替换前确认公开使用授权，替换相应 PNG/WebP 和来源记录，并检查桌面及手机裁切。不要从账户 API 自动读取图片，不要把生成历史、模型授权或私有 Skill 配置加入该目录。

“观看演示”当前为有明确标记的静态分镜演示，不是假视频播放器。取得可公开的视频后，可再增加实际视频播放；不要把静态图切换称为真实生成案例。

## 本地验收

在项目根目录执行 `npm run build:web`。前端静态测试运行 `npm --workspace apps/web run test:homepage`；独立浏览器测试运行 `npm --workspace apps/web run test:homepage-browser`。

浏览器测试只使用临时回环 HTTP 服务、合成账号响应和新建浏览器配置，不连接真实 API、不创建项目或生成任务。`HOMEPAGE_SCREENSHOT_DIR` 可指定本项目内的截图目录。
