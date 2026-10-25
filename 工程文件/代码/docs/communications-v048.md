# 🛰️ v0.4.8 闭环链路与空间通信增强

通信实验室现有 **193 个可添加积木、固定信宿与 90 个预设**。本次增加 15 个积木、12 个预设，并将闭环协议、工程复用、空间观察和教学编排连接到同一条实际收发链路。新增面板沿用海洋配色、加粗框线、圆角控件、分析标签、大图和窄屏布局。

## 🧭 推荐体验顺序

| 顺序 | 操作 | 可观察的结果 |
| --- | --- | --- |
| 1 | 搭建链路，在「教学实验 → 闭环收发协议」选择当前积木链路 | ARQ / Chase HARQ 的 ACK、重传、软合并、实际空口时长与吞吐；AMC 的接收反馈和档位切换 |
| 2 | 勾选相邻接收积木，在「空间与子工程 → 子工程」封装 | 类型端口、公开参数、独立实例、展开编辑、版本保存和 JSON 分享 |
| 3 | 运行「多天线 · 排序 MMSE-SIC」 | 两路空间流星座、信道矩阵、检测顺序和逐层抵消残差 |
| 4 | 运行动态 MIMO、MIMO-OFDM、OFDMA、FHSS 示例 | H(t) 跟踪、逐子载波检测、用户资源/吞吐/队列、跳频同步与时频图 |
| 5 | 在「空间与子工程 → I/Q 录波」导入文件 | SigMF 或原始复采样通过同步、均衡、解调积木回放；完整观察点导出 |
| 6 | 在「教学实验 → 教学任务与实验编排」创建任务 | 开放参数、分阶段目标、提示、验收种子及可分享实验包 |
| 7 | 加入多个工程，运行批量队列和最低信噪比搜索 | 配对种子比较、实际错误计数、统计区间、可恢复的合格参数点与 JSON/CSV |

## 🧩 新积木

| 分类 | 积木 |
| --- | --- |
| 信源 | I/Q 录波信源 |
| 多天线检测 | 2×2 MIMO ZF-SIC、MMSE-SIC |
| 动态多天线 | MIMO 周期正交导频、移动与空间相关 MIMO、MIMO 导频跟踪检测 |
| 宽带多天线 | 2×2 MIMO-OFDM 组帧、频率选择性 MIMO 多径、MIMO-OFDM 矩阵估计检测 |
| 多用户 | OFDMA 多用户资源调度、独立用户信道、分用户恢复 |
| 跳频 | FHSS 跳频发射、跳频码与帧同步、解跳与积分 |

各无线模块接入 Build 类型检查、自动补齐接收、实际 Run、中间观察、工程保存和连续帧。I/Q 录波按采样格式生成对应接收链路，显示实际接收统计。

## 📘 详细指南

- [闭环协议、AMC 与版本化子工程](communications-v048-closedloop.md)：实际物理链路调用、软合并、反馈时序、参数映射、API 和验收。
- [多天线、移动信道与多用户无线](communications-v048-wireless.md)：14 个无线积木、11 个预设、公式、单位、图表数据和算法来源。
- [I/Q 录波与接收回放](communications-v048-iq.md)：SigMF、原始格式、接收配置、实际采样率、完整录波导出。
- [教学任务与实验编排](communications-v048-experiments.md)：实验包、逐种子验收、批量统计、停止与目标搜索。

## 🔌 接口与工程保存

所有接口沿用会话标识与 `/api/communications/` 前缀。新增同步动作包括 `subproject-create`、`subproject-validate`、`subproject-insert`、`subproject-update`、`classroom-validate`、`iq-import`、`iq-export`。闭环沿用 `job-start` 的 `protocol/amc` 类型；教学与队列新增 `classroom/batch/target-search` 类型，复用任务状态、进度与停止接口。

原有 schema 1 数值链路继续使用；schema 2 工程文档增加 `subprojects` 和 `experiments` 元数据。子工程实例展开为独立 ID 的普通积木，连续帧状态随实例区分。任务包、源工程、随机种子和测量结果一起保存，便于再次运行。

## ✅ 验证与部署

在 `工程文件/代码` 目录执行：

```powershell
.venv/Scripts/python.exe -m unittest discover -s scripts -p "test_*.py"
node scripts/verify_communications_ui.js
.venv/Scripts/python.exe scripts/benchmark_algorithms.py
.venv/Scripts/python.exe scripts/verify_reproduction.py
```

专项测试文件为 `test_communications_closedloop.py`、`test_communications_spatial.py`、`test_communications_iq.py`、`test_communications_experiments.py`、`test_communications_v048_integration.py`，以及前端 `test_communications_spatial_ui.js`、`test_communications_experiments_ui.js`。它们覆盖实际算法、交互状态、HTTP、后台任务、会话归属和工程往返。

日志位于 `logs/communications-v048/`，发布环境验证位于 `logs/release/`，调试材料及最近文档备份位于 `debug/v048/`。升级时保留 `data/`、`uploads/` 和 `outputs/`，更新源码后重启服务或重建 Docker，并刷新浏览器。部署包通过 `build_release.py` 从提交生成，由 `verify_release.py` 解包到全新环境验证；ZIP、SHA256SUMS.txt 和 verification.json 随 GitHub Release 一起发布。
