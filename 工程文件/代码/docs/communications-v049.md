# 🌊 v0.4.9 先进收发算法与实验调试增强

本版新增 24 个积木、19 个预设，总计 **217 个可添加积木、固定信宿和 109 个预设**。新算法、调试、教学与报告接入既有海洋工作区，沿用六类积木、参数面板、结果标签、工程快照和数据导出。

## 🧭 推荐体验顺序

| 顺序 | 示例或入口 | 观察内容 |
| --- | --- | --- |
| 1 | 接收估计 · LMMSE / MIMO；Kalman 因果跟踪 | 导频估计、时变复信道、协方差与检测结果 |
| 2 | 软检测 · MIMO / LDPC；MIMO-OFDM / 软 Viterbi | 按流增益校准、有效噪声、LLR 与纠错 |
| 3 | 工程工具 · 调试 | 指定积木断点、RMS 与低可靠度 LLR 条件、触发数值 |
| 4 | 新波形 · DFT-s-OFDM；SC-FDMA | 连续／交织子载波、频域均衡、IDFT 解扩、PAPR |
| 5 | 射频 · 回环训练与数字预失真 | 训练输入输出、拟合系数、记忆功放、幅相失真与频谱 |
| 6 | 同步 · Schmidl–Cox；Zadoff–Chu | 前导捕获、频偏、采样时钟估计和重采样；支持 I/Q 回放 |
| 7 | 现代编码 · Polar SC；Polar CRC-SCL | 冻结位构造、列表译码、CRC 与译码耗时 |
| 8 | 阵列 · MVDR；预编码 · MRT / SVD | 目标和干扰方向、方向图、空间零陷、导频测量 CSI |
| 9 | 教学实验 · 批量、任务、续跑 | 统计区间、实测分布、同种子差值、记录复跑、阶段提交 |
| 10 | 工程工具 · 实验报告 | 勾选实测素材、填写图注与结论、预览并导出 PDF |

## 🧱 新积木

- 🔍 接收：LMMSE 信道估计检测、Kalman 复信道跟踪、MIMO 软输出检测。
- 🌊 波形：DFT 扩展、SC-FDMA 子载波映射与 IFFT、FFT 均衡与解映射、IDFT 解扩。
- 🔧 射频：功放回环训练采集、DPD 逆模型系数估计、数字预失真器、记忆多项式功放。
- ⏱️ 同步：OFDM 突发同步前导、突发延迟与采样频偏、突发捕获与采样时钟恢复。
- 🛡️ 编码：Polar 编码、Polar SC / CRC-SCL 译码。
- 🧭 阵列：均匀线阵训练帧、MRT 发射波束成形、SVD 双流预编码、阵列角度多径信道、定向空间干扰、常规波束合并、MVDR 自适应零陷、预编码双流接收。

每个积木都通过实际 Build / Run 执行，提供相应类型端口、参数校验、观察点、保存和导出。自动补齐接收链路与配对参数联动支持新模块。

## 🔬 算法与数据

LMMSE 使用公开导频的 LS 残差估计噪声，再结合先验协方差估计信道；Kalman 逐时隙预测、在导频到达时更新。MIMO 软检测按各流响应校准 MMSE 输出，将残余流间干扰与滤波噪声合成为各符号的有效方差，传给软解调和实际 HARQ 合并。

SC-FDMA 在 QAM 符号与 OFDM 调制间加入单位能量 DFT，在接收均衡后执行 IDFT。独立 OFDM 对照预设使用相同分配载波，便于比较 PAPR 与频谱。记忆功放采用奇数阶多项式与延迟支路；公开训练经过回环功放后，使用最小二乘拟合逆模型系数，应用到后续发送波形。

突发同步利用首尾公开重复标记：前端相关捕获帧头与频偏，首尾位置间隔用于估计采样频偏，联合拟合后重采样恢复 OFDM 波形。SigMF 导入自动恢复前导、有效长度、SC-FDMA 资源映射与待执行 IDFT；原始录波可在信源参数中填写相应格式。Polar 提供 N=64/128/256、K/N=1/4、1/2、3/4，K 包含每码字 CRC-16，选择 K>16 的组合；SC 和 CRC-SCL 共用 BEC 可靠度构造。SCL 列表宽度为 2/4/8/16。

阵列信道由路径增益、到达角、离开角、阵元间距生成空间响应。MRT / SVD 通过反向公开训练测量 CSI 后形成预编码权重，接收通过正向训练估计有效信道。MVDR 使用训练残差的干扰噪声协方差形成空间零陷。

## 🧰 实验、教学与报告

- 批量、二维扫描和目标搜索保存检查点及已完成记录；停止、刷新、重启后按任务续跑。任务记录保存在当前会话的任务目录。
- 调试可运行到指定积木，或按输出 RMS、低可靠度 LLR 占比等条件暂停；显示触发位置和实测值。
- 批量结果展示 BER 区间、吞吐／时延分布和同种子差值，支持载入某次记录的工程、实际种子并复跑。
- 学生模式按阶段保存独立工程和验收结果，记录尝试与提示使用，支持导入／导出本地作业包。
- 空间观察在资源单元、用户队列、矩阵、星座和 SIC 过程间保留所选位置。
- 报告支持批量统计、二维热图、目标搜索、闭环协议、空间矩阵、OFDMA 资源／队列及阶段成果。图注和结论随工程保存；浏览器预览和 PDF 使用同一数值素材。

## 🧪 运行与验证

在 `工程文件/代码` 目录执行：

```powershell
.venv/Scripts/python.exe -m unittest discover -s scripts -p "test_*.py"
node scripts/verify_communications_ui.js
.venv/Scripts/python.exe scripts/benchmark_algorithms.py
.venv/Scripts/python.exe scripts/build_release.py
.venv/Scripts/python.exe scripts/verify_release.py
```

测试包含新预设端到端执行、自动补齐接收、按流 LLR 与真实 HARQ、I/Q 突发回放、Polar 纠错、DPD 与同步数值检查、断点与检查点续跑、学生阶段保存、报告内容与 API。日志位于 `logs/communications-v049/`、`logs/release/`，调试截图与 PDF 位于 `debug/v049/`。

## 📚 详细实现与来源

- [接收与阵列算法](communications-v049-receiver.md)
- [波形、射频、同步与 Polar](communications-v049-waveform.md)
- [实验调试与教学](communications-v049-experiments.md)
- [Sionna OFDM MIMO 信道估计与检测](https://nvlabs.github.io/sionna/v2.1.0/phy/tutorials/notebooks/OFDM_MIMO_Detection.html)
- [SC-FDMA 与 OFDM](https://www.mathworks.com/help/comm/ug/scfdma-vs-ofdm.html)
- [数字预失真](https://www.mathworks.com/help/comm/ref/dpd.html)
- [Polar 编码](https://www.mathworks.com/help/5g/gs/polar-coding.html)
- [OFDM 同步](https://www.mathworks.com/help/comm/ug/ofdm-synchronization.html)
- [MVDR 波束成形](https://www.mathworks.com/help/phased/ref/phased.mvdrbeamformer-system-object.html)

升级时保留 `data/`、`uploads/`、`outputs/`，更新源码并重启服务或重建 Docker，再刷新浏览器。生产依赖沿用现有版本。
