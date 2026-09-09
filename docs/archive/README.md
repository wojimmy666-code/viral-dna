# 历史归档

保留原设计决策、旧数据契约和当时的验收结果。文档开头已标明历史属性；其中当前、未来、必须等措辞须结合原日期理解，不作为现行操作或部署依据。

替代入口：[账户与存储](../features/README.md)、[创作流程](../features/创作流程与生成规则.md)、[架构协议](../architecture/README.md)、[部署](../deployment/README.md)、[剩余规划](../roadmap/README.md)。

## Phase 1 阶段记录

- [Phase1_Batch2.5_链接采集层执行与验收](phase-1/Phase1_Batch2.5_链接采集层执行与验收.md)
- [Phase1_Batch2_真实媒体证据层执行计划](phase-1/Phase1_Batch2_真实媒体证据层执行计划.md)
- [Phase1_Batch3.1_证据时间线与Provider执行计划](phase-1/Phase1_Batch3.1_证据时间线与Provider执行计划.md)
- [Phase1_Batch3.2_本地语音与字幕识别执行验收](phase-1/Phase1_Batch3.2_本地语音与字幕识别执行验收.md)
- [Phase1_Batch3.3_VLM网关与模型计费执行计划](phase-1/Phase1_Batch3.3_VLM网关与模型计费执行计划.md)
- [Phase1_Batch3.4_工作区与分析记录执行计划](phase-1/Phase1_Batch3.4_工作区与分析记录执行计划.md)
- [Phase1_Batch3.5_混合分镜边界执行计划](phase-1/Phase1_Batch3.5_混合分镜边界执行计划.md)
- [Phase1_执行计划](phase-1/Phase1_执行计划.md)
- [Phase1_架构与接口设计](phase-1/Phase1_架构与接口设计.md)

## Phase 2 已替代计划与流程

- [Phase2_Batch4.4.4_4.4.5与4.2.4_人工验收](phase-2/Phase2_Batch4.4.4_4.4.5与4.2.4_人工验收.md)
- [Phase2_Batch4.4_账户工作区与混合资产库执行计划](phase-2/Phase2_Batch4.4_账户工作区与混合资产库执行计划.md)
- [Phase2_Batch4.5.1_视频生成基础架构执行验收](phase-2/Phase2_Batch4.5.1_视频生成基础架构执行验收.md)
- [Phase2_Batch4.5.3_视频体验与音轨衔接执行验收](phase-2/Phase2_Batch4.5.3_视频体验与音轨衔接执行验收.md)
- [Phase2_单视频生成工作流执行计划](phase-2/Phase2_单视频生成工作流执行计划.md)
- [Phase2_生成产物加入资产库与账户云同步预留_执行验收](phase-2/Phase2_生成产物加入资产库与账户云同步预留_执行验收.md)

## 旧账户边界设计

- [用户账户与平台管理后台拆分](accounts/用户账户与平台管理后台拆分.md)

## 2026-09-09 清理记录

用户确认后删除以下 4 个文件，均已有 Git 历史可恢复：

| 原文件 | 理由／替代入口 |
| --- | --- |
| 旧 `qa/implementation-report-1696x931.png` | 修复前中间截图，保留 [最终截图](../qa/screenshots/implementation-report-1696x931-final.png) |
| 原「原视频与替换资产驱动生成方案」目录的 `README.md` | 重复概览／跳转，正式方案见 [全场景深度控制](../architecture/generation/Phase2_全场景深度控制与资产重建_执行验收.md) |
| 同目录的 `index.html` | 无仓库内引用的静态概览，不是应用页面，内容由正式技术文档承载 |
| `ViralDNA_UI字体与响应式布局规范.md` | 入口和检查清单并入 [设计索引](../design/README.md)，唯一规范仍在 `apps/web/DESIGN.md` |

其余旧文件仅归档，没有因年代早而删除。恢复时从 Git 历史找到整理前版本，仅提取所需文件，不对整个工作区回退。目录整理没有修改业务代码、用户资产、部署配置或执行 GitHub 推送。
