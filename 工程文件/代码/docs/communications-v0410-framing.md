# v0.4.10 连续物理帧、Turbo 与增量冗余

## 📦 自描述连续物理帧

在积木工坊选择“物理分包 · 自描述连续收发”。发送端使用 BPSK 比特载体接入自描述物理帧积木，再由物理帧积木选择实际载荷 MCS。四种 MCS 为 BPSK、QPSK、BPSK + 卷积 1/2、QPSK + 卷积 1/2，也可逐包轮换。

每包实际发送以下波形：

| 部分 | 内容 | 实际长度 |
| --- | --- | --- |
| 公开前导 | 固定种子 410 的 BPSK PN 序列 | 127 个符号 |
| 物理帧头 | 标记 `0x4f43`、版本、MCS、载荷比特数、包序号、业务比特偏移、业务总比特数 | 128 位 |
| 帧头保护 | CRC16/CCITT-FALSE、(7,5)₈ 卷积码及 2 位终止尾位、BPSK | 合计 292 个符号 |
| 载荷 | 业务比特、CRC16，再按 MCS 编码调制 | 根据实际解出的长度计算 |
| 包间隔 | 配置数量的零样本 | 0–2048 样本 |

帧头采用网络字节序 `>HBBHHII`，载荷支持末包的非整字节比特数。接收端以归一化前导相关捕获位置，从公开前导估计复增益与噪声，然后软译码保护帧头。接收载荷时使用实际解出的 MCS 和长度；CRC 通过的包按业务偏移写入重组缓冲，并标记覆盖区间。截断包、CRC 错误和间隔噪声之后继续搜索公开前导。

“连续录波 · 截断后重捕获”预设在发送样本 520 处移除 83 个样本，可观察首包 CRC 失败以及后续包恢复。连续流信道还支持前置噪声、AWGN、幅度和相位变化。

独立录波接口位于 `src/communication_framing_v0410.py`：

```python
wave, tx_details = encode_stream(bits, {"packet_bytes": 32, "mcs": 4, "gap": 32})
bits, rx_details, state = receive_stream(recorded_iq, {"threshold": .62})
# 任意长度的流式输入：每次传回 state，最后一块 final=True。
bits, rx_details, state = receive_stream(chunk, state=state, final=False)
```

录波接收配置只需捕获阈值。`total_bits`、`payload_bits`、`mcs`、包序号和偏移均来自波形帧头。`received_base64` 保存按偏移排序的成功载荷，`reassembled_base64` 保存含零填充缺口的完整业务布局；`coverage` 给出有效比特区间，`complete_payload` 表示覆盖完整。UI 展示实际包位置、头部与载荷 CRC、接收位数，并导出观测 JSON。

## 🌀 Turbo 迭代译码

“Turbo 并行级联编码”由两个 8 状态递归系统卷积编码器组成，反馈与前馈多项式采用 `(13,15)₈`，第二路输入经过公开种子确定的随机交织。每个编码器独立以 3 个尾输入回到零状态。每个信息块长度 K 可选 32、64、128、256、512，传输长度为 `3K + 12`：K 组系统位／第一校验位／第二校验位，加两路各 6 位尾段。末码字补零，配对译码后按原始业务长度裁剪。

“Turbo BCJR 迭代译码”提供 Log-MAP 与 Max-log-MAP，迭代轮数 1–12。LLR 约定为 `log P(0)/P(1)`。BCJR 对零初态和零终态计算前向、后向状态度量；Log-MAP 用稳定的 log-sum-exp 合并路径，Max-log 使用最大值。每一轮交换：

`外信息 = 后验 LLR − 信道系统位 LLR − 先验 LLR`

外信息经交织或逆交织后作为另一译码器的先验。内部用 ±60 限制外信息幅度。图表显示首码字前 64 位的先验、外信息、后验，以及硬判变化数和平均后验幅度；JSON 另保存各码字的逐轮统计。

实现依据可对照 [MathWorks 的并行级联 Turbo 编码与 APP 迭代说明](https://www.mathworks.com/help/comm/ug/parallel-concatenated-convolutional-coding-turbo-codes.html)。本实验采用公开随机交织与显式尾段布局，便于逐位检查编码、软信息交换和终止状态。

## 🔁 IR-HARQ 与公平资源对照

在“教学实验 → 协议与速率”选择 `IR-HARQ · 增量冗余`。参考 PHY 使用真实分包、CRC16、(7,5)₈ 卷积母码、PSK 调制、AWGN、软信息和 Viterbi；当前积木 PHY 保留工程的调制、信道与接收处理，使用卷积母码、配对打孔和 PSK/QAM 软接收，接入软 Viterbi。

每轮按公开 RV 索引选择母码位置。2/3 预算以 `[1,1,1,0]` 为基础，3/4 预算以 `[1,1,1,0,0,1]` 为基础，RV 改变循环位移；短末组调整到与 RV0 完全相同的编码位数。接收端把实际解调 LLR 写回对应母码位置，未观测位置初值为零，已观测位置累加，再运行软 Viterbi 和 CRC 检查。CRC 成功进入 ACK，反馈丢失触发超时重传并由接收端抑制重复交付。

“⚖️ 同预算 IR / Chase 对照”使用同一个源工程、分包、调制方式、每轮预算与随机种子。IR 改变 RV，Chase 重复 RV0；双方对应发送轮的编码位数和调制符号数一致，按实际停止轮数汇总发送样本、发送能量、重传次数和有效吞吐。QAM 的实际样本能量由每轮发送星座点计算并保留。

后端接口：

```python
result = protocol(program, {
    "phy": "program", "mode": "ir_harq", "budget_rate": 2,
    "packet_bytes": 16, "packets": 8, "max_retries": 4,
})
paired = compare_ir_chase(program, {"phy": "program", "budget_rate": 2})
```

`budget_rate=2/3` 分别表示每轮名义 2/3 或 3/4 编码预算。既有参考 ARQ/Chase 保留完整母码的 `budget_rate=1`。事件包含 `rv`、`mother_indices`、`mother_coverage`、完整 `llr_buffer`、发送编码位数和实际能量；图表逐轮显示前 256 个母码 LLR，导出 JSON 保留完整缓冲。

算法资料：[IEEE 802.16 工作组卷积码增量冗余提案](https://www.ieee802.org/16/tge/contrib/C80216e-04_246r3.pdf)给出通过循环改变打孔并在比特度量层合并的结构；[MathWorks HARQ 建模说明](https://www.mathworks.com/help/lte/ug/dl-sch-harq-modeling.html)说明 CRC 驱动重传、Chase 合并和不同冗余版本的接收流程。

## ✅ 核心验证与日志

```powershell
.venv/Scripts/python.exe scripts/test_communications_framing_v0410.py
.venv/Scripts/python.exe scripts/test_communications_turbo_v0410.py
.venv/Scripts/python.exe scripts/test_communications_harq_v0410.py
```

日志位于 `logs/communications-v0410/`：`framing-tests.log`、`turbo-tests.log`、`harq-tests.log`。测试覆盖四种载荷 MCS、任意录波分块、未知复增益、截断与损坏帧头后重捕获、原始 I/Q 字节回放、BCJR 对穷举后验的数值一致性、Turbo 多轮纠错、RV 母码覆盖、真实工程重传和同预算实际资源对照。
