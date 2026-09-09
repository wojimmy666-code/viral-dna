# 现行功能说明

这里是当前使用规则的入口。初始化、部署、备份和同步操作统一阅读 [部署流程](../deployment/README.md)。未连接并确认真实服务器前，不能把本地保存称作云端已保存。

先读 [创作流程与生成规则](创作流程与生成规则.md)，了解两条创作入口、采用门槛、提示词及资产绑定。

## 账户、协作与长期存储

- [account-storage-and-sync](accounts/account-storage-and-sync.md)
- [account-system-implementation](accounts/account-system-implementation.md)

## 提示词与资产引用

- [资产感知创作与缩略图引用验收](prompts/资产感知创作与缩略图引用验收.md)
- [项目全局与局部提示词验收](prompts/项目全局与局部提示词验收.md)

## 生成性能与运行机制

- [ImageGen本机性能优化](generation/ImageGen本机性能优化.md)

## 相关资料

- 平台凭据由 admin 维护，用户设置只管理偏好；当前不支持用户自行配置 Provider 密钥。
- 平台 Cookie 连接见 [平台连接记录](../qa/platform/Phase1_平台连接与本机Cookie凭证执行验收.md)，凭据恢复限制见 [备份恢复](../deployment/升级备份与恢复.md)。
- Skill 封面、批量生图、工作台细项见 [验收索引](../qa/README.md)，不要用旧截图推断当前界面。
