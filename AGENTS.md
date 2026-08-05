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
