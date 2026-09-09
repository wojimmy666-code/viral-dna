# 设计规范与参考

唯一 Web 设计契约是 [apps/web/DESIGN.md](../../apps/web/DESIGN.md)，实际令牌位于 [styles.css](../../apps/web/src/styles.css)，共享组件位于 `apps/web/src/ui/system/`。本目录不再维护第二套字号、颜色或组件规范。

## 参考资料

- [最初 UI 风格参考](UI模板.png)：历史视觉方向，不代表当前信息架构或产品能力。
- [分析记录方案 B 参考图](analysis-records-option-b-reference.png)。
- [实现与视觉验收](../../design-qa.md)、[验收截图索引](../qa/README.md)。

## 修改界面后的检查清单

- 使用设计契约的字号、字重、文字层级、语义状态和共享组件，不在业务 CSS 中另建近似令牌。
- 提示词正文可读，移动端输入字号符合规范；长文本、引用、错误及禁用状态均可用。
- 检查 1440、1280、1024、768、390px；通过布局重排适配，不缩小文字强塞内容。
- 检查 125%、150%、200% 缩放，主要操作可达且不产生整页横向溢出。
- 检查键盘焦点、弹层关闭、窄屏、长名称和媒体完整显示；截图与报告一起记录验证范围。

```powershell
npm run check:design
npm run test:web
npm run build:web
```

任何规范例外都必须在设计契约中说明原因和作用范围，不能仅靠页面末尾覆盖样式处理。
