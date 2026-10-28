# v0.4.10 接收算法与标准信道

本轮新增 5 个积木、7 个预设。算法观测位于「空间」分析区的「🐬 序列检测、自动测向与标准信道」面板，可导出当前算法的完整 JSON。

## 🧵 MLSE 序列检测

链路：`BPSK/QPSK → MLSE 公共训练帧 → 复多径/噪声 → MLSE 序列均衡 → 硬解调`。

- `tx_mlse_frame` 添加 32/64/128/256 个公开伪随机训练符号和两个公开终止符号。
- `rx_mlse` 用训练观测解最小二乘 `y = Xh + n`，估计 2 或 3 个复 FIR 抽头；训练残差按自由度计算噪声方差。
- Viterbi 状态由最近 `L−1` 个符号构成，状态数为 `M^(L−1)`。分支度量为 `|y[k] − Σh[l]x[k−l]|²`，初态由前导末尾确定，终态由公开尾符号确定。
- 全帧回溯输出最大似然判决符号。面板展示前 64 步的状态度量、前驱、最终幸存路径、估计抽头和实际分支距离计算次数。

预设：`mlse_bpsk`、`mlse_qpsk`。可比较 2/3 抽头的检测运算量，或与现有 DFE 比较强 ISI 下的 BER。

数值实现对应 [MathWorks MLSE/Viterbi 与公开前后导说明](https://www.mathworks.com/help/comm/ref/mlseeq.html)。接收函数 `mlse_decode(received, public, taps)` 的公开参数只包含训练序列、尾符号、长度与调制星座。

## 📐 MUSIC 测角与自动 MVDR

链路：`均匀线阵训练帧 → 阵列角度信道 → 方向干扰 → MUSIC → MUSIC 引导 MVDR`。

- 接收阵列样本形成协方差，特征分解后选取噪声子空间；扫描 `P(θ) = 1 / ||Eₙᴴa(θ)||²`。
- 可选前后向平均、重叠子阵空间平滑，展示信号源数与有效子阵孔径。
- 在候选角谱峰处构造阵列响应，用公开导频估计的空间增益解各峰系数，选取目标峰。
- `rx_music_mvdr` 使用该估计角度，复用公开训练残差协方差与 MVDR 权重计算；输出增益校准后的符号和接收有效噪声方差，可接软解调。

预设 `music_mvdr` 展示目标和更强干扰的分离；`music_smoothing` 展示两个相干目标路径与独立干扰的平滑测角。面板提供角谱、导频目标标记、特征值、自动波束方向图与抑制量。

算法依据：[MUSIC 与空间平滑](https://www.mathworks.com/help/phased/ref/phased.musicestimator-system-object.html)。估角输入为接收样本、公开导频和阵元间距；真实传播角度用于环境生成和测试对照。

## 🌊 TDL-A / TDL-B / TDL-C

`tdl_channel` 使用 [3GPP TR 38.901 V18.0.0](https://www.etsi.org/deliver/etsi_tr/138900_138999/138901/18.00.00_60/tr_138901v180000p.pdf) 第 7.7.2 节表 7.7.2-1/2/3（文档第 74–75 页）的完整 A/B/C 功率时延谱，共 23/23/24 条路径。

- 时延按第 7.7.3 节缩放：`τ = τ_normalized × DS`，输入 DS 单位为 ns。路径线性功率归一化为总和 1。
- 每条路径采用独立 32 散射波、均匀到达角的 Jakes 衰落；零多普勒采用静态复高斯系数。
- 每条物理分数时延采用 17 点 Kaiser 窗 sinc FIR。公共实现延迟为 8 个采样点，保留各路径物理时延；帧末追加最大 FIR 尾长的零保护区，完整释放接收波形。
- 相位时间轴和 FIR 输入历史由运行上下文跨帧保存。`tdl_process` 提供逐段等长处理，`run_stage` 负责添加帧末保护区，保护区进入编译计数和运行时长。
- 面板展示标准 PDP、归一化路径功率、本帧实测路径增益功率、实际 RMS 时延扩展和连续采样编号下的逐路径复增益。

预设 `tdl_a`、`tdl_b`、`tdl_c` 连接 OFDM 与梳状导频跟踪；RRC 和 SC-FDMA 也已完成数值接入验收。可改变 CP、DS、多普勒和导频参数观察 BER 与信道变化。

## 验收与接线

`scripts/test_communications_receiver_v0410.py` 包含 9 项核心验收：

1. BPSK/QPSK、2/3 抽头 MLSE 与短帧穷举最大似然结果及距离一致。
2. 公开训练恢复未知复 FIR，发送端诊断字段变化保持接收结果一致。
3. MUSIC 从实际样本估角，公开导频选目标，自动 MVDR 恢复数据。
4. 空间平滑分离相干多径与独立干扰。
5. 标准 PDP 数值、RMS 缩放和分数延迟频率响应。
6. 分段 TDL 与整段滤波一致，时间相位和历史连续。
7. Jakes 平均增益功率与 `J₀(2πf_Dτ)` 自相关对照。
8. 七个预设端到端 Build/Run 与配对构建约束。
9. RRC/SC-FDMA 的 TDL 编译计数、实际采样长度与接收恢复。

`scripts/test_communications_receiver_v0410_ui.js` 验证逐步路径、估角/波束图、TDL 轨迹、原始 JSON 导出与界面清空生命周期。日志位于 `logs/communications-v0410/receiver-tests.log` 和 `receiver-ui-tests.log`。

扩展遵循 `register / presets / build_stage / run_stage`；结果位于 `advanced.wireless`。组件 `createCommunicationReceiverV0410(core, ctx)` 提供 `render / onResult / buttons / invalidate / replaceProgram`，挂接 `cmPane-spatial`。

## 📻 自描述帧的独立 I/Q 回放

I/Q 信源的 `mode=3` 对应「自描述连续物理帧」，自动接收链路为 `I/Q 录波 → 连续物理帧捕获与业务重组 → BPSK 比特载体解调 → 信宿`。实际载荷可以逐包采用 BPSK、QPSK 及卷积编码；其 MCS、长度、序号和业务偏移均从接收帧头恢复。

自描述波形观察点导出的 SigMF 保存公共格式编号、比特载体格式、采样率和中心频率。接收后再导出则保存已恢复的普通 BPSK 符号。Build 标记动态长度，Run 使用实际帧头更新每级点数。`received_bits` 统计 CRC 通过的覆盖位数，`reassembled_bits` 表示包含缺口占位的业务总长度；覆盖区间和逐包状态位于 `advanced.recovery.self_frame`。

`scripts/test_communications_iq_v0410.py` 验收 6 项：真实观察点 SigMF 往返、2053 位变长混合 MCS 与噪声间隔、录波首尾截断后的连续重捕获、接收前后二次导出、纯噪声空结果、自动补齐接收链路。原 I/Q 13 项及 v0.4.9 波形录波 6 项回归通过。日志为 `logs/communications-v0410/iq-tests.log`、`iq-legacy-tests.log` 和 `iq-v049-tests.log`。
