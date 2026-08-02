# ViralDNA Phase 1 Batch 2.5：链接采集层执行与验收

> 开始日期：2026-08-02
> 完成日期：2026-08-02
> 状态：小红书与抖音真实链路均已完成验收
> 目标：把抖音、小红书公开视频链接转换为可由现有 FFmpeg 媒体证据管线处理的本地源视频

## 1. 交付范围

本批实现：

- 识别并校验抖音、小红书、短链接及 RedNote 域名。
- 使用 `yt-dlp` 解析平台页面、短链重定向和真实媒体地址。
- 将公开源视频下载到受控的本地存储目录。
- 将下载结果接入现有 ffprobe、代理转码、音频提取、分镜、关键帧和 Contact Sheet 流程。
- 持久化平台视频 ID、作者、解析后链接、真实标题和采集时间。
- 对登录验证、失效、私密、超时、格式不支持、时长超限和大小超限返回明确错误码。
- 前端展示链接采集进度、真实媒体报告和失败原因，不再默认生成链接模拟报告。

本批仍不实现：

- 账号主页、账号历史视频或粉丝数据分析。
- 绕过验证码、平台登录、风控或付费/私密内容权限。
- ASR、OCR、VLM、爆点 LLM、最终 Seedance Prompt 和元素替换语义。
- 视频生成模型调用。

## 2. 真实处理链路

```text
用户公开链接
  → HTTP/HTTPS 与域名白名单校验
  → 平台识别（Douyin / Xiaohongshu）
  → yt-dlp 页面与短链解析
  → 时长、大小、单视频限制
  → storage/links/{video_id}/source.*
  → ingestion.json
  → ffprobe / SHA-256
  → H.264/AAC 代理与 WAV
  → scene score 分镜
  → 关键帧 / Contact Sheet / manifest
  → media_evidence 报告
```

链接采集失败时任务进入 `failed`，不会回退到模拟报告，也不会用其他视频代替。

## 3. 安全边界

### 输入限制

- 只接受 `http`、`https`。
- 禁止 URL 用户名和密码。
- 禁止 IP 地址来源及非 80/443 端口。
- 主机名必须精确匹配白名单域名或其子域名，避免 `xiaohongshu.com.evil.example` 一类伪装。
- 解析后的页面仍必须属于原平台，否则返回 `link_redirect_blocked`。

### 下载限制

- 默认最大 500 MB。
- 默认最长 5 分钟。
- 禁止播放列表，只处理单个视频。
- 默认网络超时 20 秒、重试 2 次。
- 输出模板固定在 `storage/links/{video_id}`，并校验最终文件仍位于该目录。
- 不自动读取 Chrome 或其他浏览器 Cookie。

若公开页面确实需要登录，用户可以主动导出 Netscape Cookie 文件并设置 `VIRAL_DNA_YTDLP_COOKIE_FILE`。应用不会把 Cookie 内容写入日志、数据库或报告。

## 4. 环境变量

```dotenv
VIRAL_DNA_LINK_MAX_BYTES=524288000
VIRAL_DNA_LINK_SOCKET_TIMEOUT=20
VIRAL_DNA_LINK_RETRIES=2
VIRAL_DNA_YTDLP_COOKIE_FILE=
VIRAL_DNA_YTDLP_PROXY=
```

未配置 Cookie 和代理时，采集器只访问无需登录即可读取的公开内容。

## 5. 主要错误码

| 错误码 | 含义 | 是否建议重试 |
|---|---|---:|
| `link_invalid` | 链接格式无效 | 否 |
| `link_platform_unsupported` | 不是支持的平台 | 否 |
| `link_redirect_blocked` | 跳转到其他平台或非白名单站点 | 否 |
| `link_auth_required` | 平台要求登录或人机验证 | 是 |
| `link_unavailable` | 视频失效、删除、私密或不存在 | 否 |
| `link_download_timeout` | 平台连接超时 | 是 |
| `link_download_failed` | 采集器未取得公开视频 | 是 |
| `link_size_exceeded` | 超过 500 MB 默认限制 | 否 |
| `link_duration_exceeded` | 超过 5 分钟默认限制 | 否 |
| `link_download_missing` | 解析成功但没有生成媒体文件 | 是 |

## 6. 自动化验收

- 平台域名、短链接、伪装域名、IP、用户信息和异常端口测试通过。
- 假下载器测试覆盖本地文件、`ingestion.json`、标题、作者、平台 ID 和解析后 URL。
- 登录验证错误翻译测试通过。
- 链接 → 下载文件 → FFmpeg → 报告的端到端测试通过。
- API 全量测试：22 项通过。
- Ruff 格式和静态检查通过。
- Vite 生产构建通过。
- Sites Worker：4 项通过。

## 7. 小红书真实样本验收

验收样本：小红书公开视频笔记“AI直出的产品宣传片(36s)”。

| 项目 | 结果 |
|---|---|
| 平台解析 | 成功，识别为小红书 |
| 平台视频 ID | `6a68dead000000001f01db1b` |
| 标题回填 | `AI直出的产品宣传片(36s)` |
| 下载文件 | 4,394,099 字节 MP4 |
| 视频信息 | 36.167 秒、1280×720、30 FPS、H.264/AAC |
| 真实分镜 | 2 个 |
| 关键帧 | 每个镜头均生成并可由前端访问 |
| 报告模式 | `media_evidence`，非模拟 |
| 完整任务耗时 | 约 23 秒 |

首次真实运行还捕获并修复了 `yt-dlp max_downloads` 在完成单条下载后抛出终止异常的问题。移除冗余选项后，同一链接重新运行成功。

## 8. 抖音真实样本验收

验收样本：抖音公开视频“胡楚靓AI工作台火了，我用一段提示词改掉了AI味”。

| 项目 | 结果 |
|---|---|
| 平台解析 | 成功，识别为抖音 |
| 平台视频 ID | `7667239828002185546` |
| 登录处理 | 用户主动导出 Netscape Cookie 文件，本地显式配置 |
| 下载文件 | 3,151,481 字节 MP4 |
| 视频信息 | 55.8 秒、1280×720、HEVC/AAC |
| 真实分镜 | 9 个 |
| 关键帧 | 每个镜头均生成并可由前端访问 |
| 报告模式 | `media_evidence`，非模拟 |
| 完整任务耗时 | 约 15 秒 |
| 在线播放 | 支持 HTTP Range，实测返回 `206 Partial Content` |
| 下载 | 返回完整附件 |

Cookie 文件只通过被 Git 忽略的 `.env.local` 保存路径。采集清单、数据库、报告、日志和 Git 差异均未保存 Cookie 内容或本机路径。

## 9. 已知边界与下一步

- 平台页面结构和反爬策略可能变化，`yt-dlp` 需要定期升级并保留回归样本。
- 小红书与抖音真实样本均已通过；平台页面结构或风控变化后仍需重新执行回归。
- 需要登录或验证码的内容不会自动绕过，产品会提示改用公开链接、显式 Cookie 文件或本地上传。
- 任务仍在 API 进程内执行，服务重启时正在下载或分析的任务不会自动恢复。
- 下一批进入 ASR、OCR 和 VLM 语义层，再生成主体、服装、场景、爆点及 Seedance 复刻/替换提示词。
