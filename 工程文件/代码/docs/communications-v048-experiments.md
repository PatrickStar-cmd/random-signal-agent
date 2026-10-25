# v0.4.8 教学任务与实验编排

在通信实验室「教学实验」中打开「教学任务与实验编排」，可创建可分享的课堂实验、统一比较多个工程，并搜索达到目标误码率的参数。

## 教学任务编辑器

1. 先搭建可运行链路，再选择「用当前链路创建任务」。
2. 填写标题、目标和任务类型。参数探索适合比较不同设置；故障修复适合保存频偏、噪声或均衡参数欠佳的初始工程。
3. 勾选学生可以调整的参数。其余参数及积木结构由验收器与初始工程逐项比较。
4. 每个阶段填写名称、提示、权重和验收目标。例如 `ber <= 0.01`、`evm_percent <= 15`、`net_bit_rate >= 1000`；业务指标可使用 `sink.media.metrics.identical == true`。
5. 填写验收种子。保存任务或导出实验包后，其他工程可直接导入。
6. 载入初始链路并调整开放参数，点击「多种子验收当前链路」。后端在每个验收种子上重新运行真实链路，逐项记录测量值。每个阶段的全部种子均达到目标后解锁下一阶段，按已完成阶段权重计算得分。

教学包使用 `assignment_schema: 1`，包含 `title`、`objective`、`kind`（`experiment` / `repair`）、`initial_program`、`editable`、`stages` 与 `seeds`。参数路径为全局参数名称，或 `blocks.<积木ID>.<参数名>`；阶段包含 `name`、`hint`、`weight` 和 `goals`。目标字段为 `metric`、`operator`（`<=`、`>=`、`==`）与 `value`。

任务库、当前编辑任务和验收记录一起保存在工程文档的 `experiments` 字段中。编辑任务或修改当前链路会更新验收状态，历史队列及搜索保留各自的源工程用于复现。

## 跨工程批量实验

队列支持加入当前工程、工程库中选定的版本快照，以及导入的工程 JSON。每次加入时复制工程参数，后续编辑当前链路保持队列方案独立。最多包含 12 个工程、32 个种子，每种子最多 32 帧，总执行次数上限为 256。

所有工程使用相同的种子序列。每种子第 `frame` 帧的实际种子为 `(seed + frame) % 4294967295`，从零计帧；种子范围之间保持独立，重复试验种子会提示调整。每次试验独立初始化算法状态。

- **物理链路模式**：执行完整工程，记录比特计数、BER、EVM、净比特率及实际计算耗时。帧发送时长等于信息比特数除以链路净比特率。
- **自建链路 ARQ 模式**：将各工程交给闭环协议控制器，记录实际交付吞吐率、交付延迟和重传计数。界面开放包数及重传上限。
- **统计汇总**：BER 使用错误比特总数除以比特总数，并保存 Wilson 95% 区间；吞吐、时延、EVM 等保存平均值、最小最大值及第 95 百分位数；计算耗时单独记录。
- **停止与导出**：停止任务后保留已完成试验；JSON 保存源工程、种子和逐次指标，CSV 导出汇总表。

## 最低信噪比目标搜索

选择信道的 `snr_db` 或 `esn0_db` 参数，设置起点、终点、步长、目标 BER 和随机种子。搜索按升序完整测量网格中的所有信噪比点。每点使用相同种子序列，累计真实错误比特与总比特，选择测量 BER 达到目标的最低网格点。

结果保存每点的运行次数、比特数、错误比特、BER、95% 区间及完整工程，支持一键载入合格参数点。所选值对应本次扫描范围和步长；表格同时展示全部点，便于检查测量波动。最多 41 个参数点、256 次实际运行。

## 接口与验证

后端模块：`src/communication_experiments.py`。

- `validate_assignment(task)`：校验并规范教学包。
- `classroom(task, program, settings, progress, cancel)`：实际运行并验收课堂任务。
- `batch(programs, settings, progress, cancel)`：跨工程队列，支持 `mode: link | protocol`。
- `target_search(program, settings, progress, cancel)`：最低信噪比网格搜索。

前端模块：`web/communication-experiments.js` / `.css`，复用现有 `cm-learning` 海洋面板、工程存储和后台任务进度。

```powershell
.venv/Scripts/python.exe scripts/test_communications_experiments.py
node --check web/communication-experiments.js
node scripts/test_communications_experiments_ui.js
```

核心验证覆盖教学包往返、真实修复验收、阶段解锁与评分、固定参数校验、多工程计数与直接运行一致、取消保留结果、协议吞吐时延、最低合格点选择及搜索边界。
