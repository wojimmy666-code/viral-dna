# ViralDNA OSS 私有桶与签名 URL 实施说明

## 目标

当视频模型只接受公网 HTTPS 媒体地址时，ViralDNA 将工作区内的深度视频或参考视频临时上传到阿里云 OSS 私有 Bucket，并只向模型签发短期只读 URL。

本方案不公开 Bucket，不把 AccessKey 返回浏览器，也不改变本地工作区作为当前主存储的定位。上传对象属于当前账户和工作区；未来可在相同 `StorageLocation / StorageObject / ObjectReplica` 接口上扩展账户云同步。

## 数据流

```text
本地工作区文件
  -> StorageObject（内容寻址，SHA-256 去重）
  -> ObjectReplica（provider_staging）
  -> OSS 私有对象
  -> MediaAccessLease（用途、到期时间、清理时间）
  -> 短期签名 GET URL
  -> Seedance / MiniMax / Wan 等 Provider
```

生成完成或租约到期后，清理任务仅在没有活动租约引用该副本时删除 OSS 对象。Bucket 生命周期规则负责异常情况下的最终兜底。

## 阿里云侧配置

### 1. 创建私有 Bucket

- 地域：上海业务建议 `华东 2（上海）`，Endpoint 为 `oss-cn-shanghai`。
- 读写权限：`私有`。
- 版本控制：媒体暂存桶通常关闭，避免删除后仍产生历史版本费用。
- 服务端加密：推荐开启 OSS 托管密钥或 KMS。
- CORS：后端直传、模型服务通过签名 URL 拉取时不需要给浏览器开放 CORS。
- 生命周期：为前缀 `viraldna/staging/` 配置 2–3 天后删除，作为应用清理失败时的安全兜底。

### 2. 创建最小权限 RAM 策略

将 `YOUR_BUCKET` 替换成实际 Bucket 名称：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "oss:PutObject",
        "oss:GetObject",
        "oss:DeleteObject"
      ],
      "Resource": [
        "acs:oss:*:*:YOUR_BUCKET/viraldna/staging/*"
      ]
    }
  ]
}
```

生产环境优先把策略绑定到 ECS 实例 RAM 角色，不在服务器磁盘或 `.env` 中保存长期 AccessKey。本地开发可使用独立的 RAM 用户 AccessKey，ViralDNA 通过 Windows DPAPI 加密保存。

官方参考：

- [ECS 实例 RAM 角色](https://help.aliyun.com/en/ecs/user-guide/attach-an-instance-ram-role-to-an-ecs-instance)
- [OSS 签名 URL](https://help.aliyun.com/en/oss/developer-reference/ddd-signatures-to-urls)
- [OSS Python SDK](https://help.aliyun.com/en/oss/developer-reference/python-sdk-v1/)

## ViralDNA GUI 配置

进入“模型与设置 -> 对象存储媒体暂存”：

1. 暂存方式选择“阿里云 OSS 私有桶”。
2. 填写地域 `oss-cn-shanghai` 和私有 Bucket 名称。
3. ECS 部署选择“ECS RAM 角色”；本地开发选择“AccessKey”。
4. ECS 与 OSS 同地域时，上传 Endpoint 可填 `https://oss-cn-shanghai-internal.aliyuncs.com`；公网签名 Endpoint 使用 `https://oss-cn-shanghai.aliyuncs.com`。
5. 签名 URL 默认 8 小时。当前 V1 签名最长 9 小时，GUI 限制为 900–32400 秒。
6. 点击“测试连接”。系统会先保存本区草稿，再依次验证私有上传、对象 HEAD、签名 URL 公网读取和删除。

测试对象位于 `.viraldna-probes/`，测试结束后立即删除。

## 运行时行为

- 相同文件按 SHA-256 复用同一暂存副本，不重复上传。
- 每次模型调用生成新的 `MediaAccessLease` 和短期 URL；URL 不持久化为资产主地址。
- 深度视频请求在进入模型 Provider 前自动暂存，不要求用户手工上传。
- 签名 URL 会先做 `Range: bytes=0-0` 公网读取探测，探测失败时不提交付费模型任务。
- 清理任务每 15 分钟检查一次；URL 到期并超过清理宽限期、且没有活动租约时删除 OSS 对象。
- Bucket 生命周期策略仍必须配置，防止进程长期离线造成孤儿对象。

## ECS 与 OSS 的网络建议

- ECS 到同地域 OSS 上传使用内网 Endpoint，不占公网带宽且延迟更低。
- 模型 Provider 通常位于阿里云账户外，因此签名 URL 必须使用公网 Endpoint。
- 网站/API 放在 ECS、媒体放在 OSS 是推荐分工：ECS 负责计算与权限，OSS 负责大文件吞吐和容量。

## 故障排查

| 错误 | 检查项 |
| --- | --- |
| 无法读取 ECS RAM 角色 | 实例是否绑定角色；角色名和元数据服务是否可访问 |
| `403 AccessDenied` | RAM 策略的 Bucket、前缀和 Put/Get/Delete 权限 |
| 签名 URL 无法读取 | 公网 Endpoint 是否误填为 `-internal`；服务器时钟是否同步 |
| 上传成功但模型拉取超时 | URL 有效期是否覆盖排队时间；Provider 是否能访问 OSS 公网域名 |
| 暂存文件未删除 | 是否仍有活动租约；应用清理任务是否运行；Bucket 生命周期是否生效 |

## 安全边界

- Bucket 永远保持私有，禁止改成公共读。
- 前端只接收已脱敏的 AccessKey 提示，不返回 Secret。
- 生产使用 ECS RAM 角色和最小权限前缀策略。
- 日志不得记录完整签名 URL、AccessKey、SecurityToken。
- 签名 URL 只提供 GET，上传和删除由后端凭证完成。

