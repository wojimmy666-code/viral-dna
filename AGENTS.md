# ViralDNA Repository Instructions

## GitHub transport

- 与 GitHub 交互时始终使用 SSH，包括 clone、fetch、pull、push、submodule 和远程地址配置。
- 本仓库的 `origin` 必须保持为 `git@github.com:wojimmy666-code/viral-dna.git`。
- 不要将 GitHub 远程地址改回 HTTPS。
- `git commit` 在本地完成；凡需连接 GitHub 的后续操作，统一通过 SSH 认证。
- 不要自动执行 `git push`。只有用户明确下达推送指令后，才允许向 GitHub 推送。

## Branch policy

- 默认仅使用 `main` 分支进行开发和本地提交。
- 除非用户明确要求创建或使用新分支，否则不要创建、切换、推送新的功能分支，也不要自动创建 PR 分支或 Git worktree。
- 用户未指定分支时，后续改动和提交均保留在 `main`；是否推送仍遵循上面的显式授权规则。

## 人工确认文件交付规则

- 凡交付给用户人工查看、对比、确认或验收的本地文件（包括图片、视频、截图和文档），必须逐项提供完整绝对路径，包含盘符、全部目录、文件名和扩展名。
- Windows 路径使用可直接复制的原生形式（例如 `D:\Projects\ViralDna\output\imagegen\example.png`），在正文或 `text` 代码块中完整展示。可同时提供点击链接或预览，但不能只给短链接标签、文件名、相对路径，或让用户自行拼接目录与文件名。
- 多个候选文件必须分别列出各自的完整路径，并明确对应的候选名称或用途。
- 交付前验证文件实际存在且非空。需要保留供人工确认的生成文件应保存到工作区内稳定的位置，不仅依赖生成工具缓存或临时目录；已有文件不得无授权覆盖。
- 文件尚未生成、保存失败或不可访问时，应如实说明，不能把计划路径当作已完成文件交付。
