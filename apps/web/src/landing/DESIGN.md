---
name: ViralDNA Public Homepage
description: 公开官网的电影式片场留白；规范仅覆盖 landing 表面。
colors:
  primary: "#5b4df5"
  primary-hover: "#7165ff"
  ground: "#100f12"
  text: "#f7f7f6"
  muted: "#bcbcc2"
  panel: "#1c1b20"
  line: "#36353b"
typography:
  display:
    fontFamily: '"ViralDNA Display", "Microsoft YaHei", "PingFang SC", sans-serif'
    fontSize: "clamp(48px, 5.46875vw, 96px)"
    fontWeight: 800
    lineHeight: 1.18
    letterSpacing: normal
  section:
    fontFamily: '"ViralDNA Display", "Microsoft YaHei", "PingFang SC", sans-serif'
    fontSize: "clamp(32px, 3.125vw, 48px)"
    fontWeight: 600
    lineHeight: 1.35
  headline:
    fontFamily: '"ViralDNA Display", "Microsoft YaHei", "PingFang SC", sans-serif'
    fontSize: "clamp(28px, 2.34375vw, 40px)"
    fontWeight: 600
    lineHeight: 1.35
  title:
    fontFamily: '"Microsoft YaHei UI", "PingFang SC", system-ui, sans-serif'
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: '"Microsoft YaHei UI", "PingFang SC", system-ui, sans-serif'
    fontSize: "clamp(16px, 1.3672vw, 21px)"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: '"Microsoft YaHei UI", "PingFang SC", system-ui, sans-serif'
    fontSize: "16px"
    fontWeight: 600
  caption:
    fontFamily: '"Microsoft YaHei UI", "PingFang SC", system-ui, sans-serif'
    fontSize: "14px"
    fontWeight: 400
rounded:
  label: "4px"
  compact: "8px"
  thumbnail: "10px"
  surface: "12px"
  dialog: "16px"
  circle: "50%"
spacing:
  small: "8px"
  compact: "12px"
  standard: "16px"
  content: "24px"
  panel: "28px"
  wide: "32px"
  page-gutter: "clamp(24px, 4.8177vw, 96px)"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.text}"
    rounded: "{rounded.surface}"
    padding: "14px 32px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: transparent
    textColor: "{colors.text}"
    rounded: "{rounded.surface}"
    padding: "14px 32px"
  button-secondary-hover:
    backgroundColor: "{colors.panel}"
  navigation:
    textColor: "{colors.muted}"
    padding: "10px 0"
  scene-choice:
    backgroundColor: transparent
    textColor: "{colors.text}"
    typography: "{typography.label}"
    rounded: "{rounded.compact}"
    padding: "10px 16px"
  scene-choice-selected:
    backgroundColor: "{colors.panel}"
  collaboration-card:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.surface}"
---

# Design System: ViralDNA Public Homepage

## Overview

**Creative North Star: "电影级创作片场 / 片场留白"**

暖金侧光、玻璃、金属和岩石影像为官网建立片场气氛。深炭背景托住宽厚白字，既有紫色标志与主操作保持品牌识别，界面结构以留白和细线组织。

本契约从 [HomePage.jsx](HomePage.jsx) 与 [home.css](home.css) 提取，仅适用于公开 `/`。工作台继续遵守 [Web 工作台设计契约](../../DESIGN.md)。首页构图与交付状态见[方向契约](../../../../.impeccable/homepage-brief.md)，产品事实见 [PRODUCT.md](../../../../PRODUCT.md)；它们不扩大本文件的视觉作用域。

**Key Characteristics:**

- 影像承担材质与暖色，紫色承担品牌与交互。
- 本地中文展示字体、两行首屏标题、宽松区块间距。
- 手机独立重排，示意标识与核心操作清楚可达。

## Colors

### Primary

品牌紫用于主按钮、选中边框、焦点及方向图标；亮紫用于悬停与强调反馈。沿用现有播放标志，不创造另一套官网标识。

### Neutral

炭黑地面、浅色文字、辅助灰字、抬高一层的面板及细线组成主要界面。暖金来自影像，不是额外的界面状态色；创作方法区使用源码中的轻微底色变化。

邻近 sidecar 的八阶 OKLCH 色带仅用于面板预览，由实际色值推导；页面的规范色值仍以 frontmatter 为准。组件片段独立解析局部令牌，不依赖工作台样式。

**The Image Color Rule.** 暖色和材质由实际影像承担，界面强调沿用品牌紫。

## Typography

展示字体为本地 Noto Sans SC 的 600/800 字重子集，以 `ViralDNA Display` 注册；字体文件位于 `public/home/fonts/`，使用 swap。一级与二级标题使用它，正文和三级标题沿用 frontmatter 中的中文系统字体栈。显示子集随标题字符变化补齐，不能默认覆盖全部汉字。

Display 对应首屏两行标题，section 对应流程、方法、协作与收尾，headline 对应双入口，title 对应内容小标题；body、label、caption 分别承担阅读、控件与示意说明。普通正文常规字重，按钮与标题半粗，首屏标题使用展示粗重。中文使用正常字距。

**The Two-Line Rule.** 首屏保留“看懂好视频，／把创意做成片。”两行关系；手机调整字号和结构，不挤压正文来维持桌面布局。

## Layout

桌面首屏为左文右影，媒体占满容器；高度随视口宽度变化（55.859375vw，上限 1100px），正文左沿使用 page-gutter。缩略图停靠媒体右下，双入口随后并列。普通区块上下留白（112px），流程为左步骤右画面，创作方法三列，企业说明与协作卡并列。

断点按实际源码分工：1150px 以下缩紧导航、按钮及区块，首屏最小高度为 660px；820px 以下菜单折叠、正文与图片上下排列，双入口、流程、方法与协作均为单列，页面左右留白 24px；480px 以下再调整首屏图片高度、裁切与按钮间距。1800px 以上仅微调首屏正文位置与行宽。

820px 以下 display 使用 `clamp(38px, 6.65vw, 54px)`、body 为 17px、section 为 32px；480px 以下 display 使用 `clamp(32px, 8.55vw, 41px)`。主按钮高度依次为桌面至少 62px、中屏至少 54px；手机导航与轮播按钮至少 44px。手机图片按 66% / 68% 水平位置裁切，正文处于独立深色底面。

## Elevation & Depth

玻璃、金属、岩石与暖光的深度由栅格素材提供。界面面板使用色阶、细边框和留白，没有通用卡片投影；影像上的示意文字有柔和黑色文字阴影。演示弹窗使用深色原生遮罩，其精确值及文字阴影保存在 sidecar 的 extensions。

## Shapes

按钮、媒体舞台和协作卡共用柔和矩形，缩略图略紧凑，演示弹窗略宽松；小型真实性标签使用小圆角。轮播、菜单和关闭控件采用圆形。真实样片允许 cover 裁切；这不改变工作台素材预览完整显示的规则。

## Components

- 主按钮是紫底白字，次按钮透明底配中性边框；悬停改变背景或边框（160ms ease-out）。键盘焦点为亮紫轮廓（2px，外偏移 5px）。文字链接悬停加下划线。导航手机展开后保持相同色系，Escape 关闭并恢复菜单按钮焦点。
- 三段样片使用实际视频首帧缩略图、名称与 pressed 状态；选中边框外置。用户提供的三段视频无损拼成一支 15.125 秒、720p 静音影片，以真实播放时间驱动「光线唤醒 / 材质特写 / 英雄定格」的选中态，点击缩略图跳转对应分镜。不再用定时器切图或 CSS 推近模拟运镜。
- 解码帧准备好前显示匹配封面，准备好后以 180ms 透明度过渡显示视频。首屏媒体离开视口、标签页隐藏、菜单或演示打开时暂停；减少动态效果与节省流量默认不设置视频地址，允许用户显式播放，播放按钮不禁用。视频失败保留封面与创作入口，并提供重试。实际播放与用户的播放意图分别记录，临时暂停后不覆盖用户决定。
- 五步流程使用单选 tablist、文字步骤与当前方向图标；支持方向键、Home、End 和 roving focus。画面旁保留“创作示意”及非实际项目数据说明。
- 演示采用原生 dialog，支持关闭按钮、Escape 和遮罩关闭，锁定背景滚动并在关闭后恢复原焦点。16:9 原生视频控制完整显示影片，分镜按钮可跳转；标记为「静音分镜短片」，不冒充真实客户案例，不调用模型。演示播放时首屏暂停，减少重复解码。
- 方法卡使用影像、标题与简短说明；协作卡通过细分隔线组织示意成员和状态。后者是静态展示，不能渲染为实际编辑锁或账户数据。首页没有输入框，不在此契约新增表单模式。

## Do's and Don'ts

### Do:

- **Do** 将官网令牌限制在 landing 表面，保留浅色工作台的原有规范。
- **Do** 保留示意影像、分镜短片和协作状态的真实性说明，视频与封面使用同一公开来源。
- **Do** 维护手机可达操作、键盘焦点及减少动态效果下的手动切换。

### Don't:

- **Don't** 把 AI 示意素材描述为真实客户案例或真实账户记录；只有实际接入的视频才可描述为可播放短片。
- **Don't** 用装饰性渐变或 CSS 假材质替代已批准的摄影质感影像。
- **Don't** 将本地获准的原生分辨率例外当作未来素材质量标准；审批与机械门禁状态留在方向契约和验收记录中。
