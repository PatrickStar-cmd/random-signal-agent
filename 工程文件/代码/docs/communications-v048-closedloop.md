# 🧩 v0.4.8 子工程与真实链路闭环实验

## 🪸 在界面中复用收发机

在通信实验室的「🛰️ 空间与子工程 → 🧩 子工程」中，勾选相邻积木，填写名称并选择公开参数，点击「封装勾选积木」。定义保存命名的输入、输出端口、信号类型、内部积木和版本。

选择定义后，在插入位置加入实例。每个实例的公开参数分别应用；「展开编辑」可直接修改内部积木，「保存实例为新版本」将当前实现保存到库中。导出的 JSON 定义可在其他通信工程中导入。工程快照同时保存定义库与各实例使用的具体版本。

运行链仍由普通积木组成。实例块标识由实例 ID 和定义内块 ID 的摘要组合生成；连续运行使用这些标识保存载波环、AGC、移动衰落等状态，因此相同定义的多个实例分别保留算法状态。升级一个实例时，其他实例继续使用各自的参数和版本。

I/Q 录波也可使用「补齐接收」：符号采样连接元数据指定的解调器；RRC 波形补齐匹配滤波与符号同步，已匹配录波直接进入符号同步；OFDM 录波补齐 OFDM 解调。标注公共帧头的录波自动加入帧同步，已有接收处理与参数继续保留。

## 📦 用当前积木链路发送真实数据包

在「🎓 业务与教学 → 闭环收发协议」中选择「当前积木链路」，再选择停等 ARQ、HARQ 或 AMC。数字业务信源包括随机比特、文字、图片和文件；I/Q 录波在接收回放面板运行。

当前数字业务先按字节分包，每包实际发送 16 位序号、16 位有效字节数、载荷和 CRC-16/CCITT-FALSE。协议控制器把这个完整比特帧写入信源位置，再调用现有 Build / Run。原工程的编码、RRC、OFDM、DSSS、FHSS、衰落、同步、均衡及多天线接收按积木顺序执行。结果保存 `source_program` 与最后一帧的 `actual_program`，并显示实际链路。

停等 ARQ 在成功捕获、CRC 与包头校验通过后发送 ACK，否则发送 NACK；反馈丢失时等待配置的超时后重传。接收端按序号抑制重复交付，时间线保留每次发送、接收、反馈和超时事件。

HARQ 在实际解调器处提取软信息。软解调直接提供原有 LLR，硬判决 PSK / QAM 接收机从实际恢复的符号计算 Max-log LLR。捕获成功的同一码字重传逐位相加，随后继续执行原工程的译码器和 CRC。捕获失败的发送记录为 NACK，已有的软信息留待后续重传继续使用。

「参考收发链路」继续提供统一的卷积码、PSK、AWGN、软 Viterbi 对照实验。

## 🎛️ AMC 的控制点、编码与反馈

选择工程中的 SNR / Es/N₀ 信道作为扫描控制点，设置起止信噪比、额外反馈延迟和滞回。

| 设置 | 实际行为 |
| --- | --- |
| 保留工程编码 | 保留编码器、译码器和所有传输处理，按接收反馈切换 BPSK、QPSK、16QAM、64QAM |
| 联动卷积码率 | 调整卷积码、打孔 / 解打孔与软 Viterbi，提供 1/2、3/4 码率配置 |
| SNR / Es/N₀ 控制点 | 修改所选信道的参数，其余信道配置继续参与实际传输 |
| OFDMA 用户信道 | 以用户 0 的 SNR 为扫描基准，保持各用户原有 SNR 差，采用保留工程编码模式 |
| 接收估计 | 有噪声估计积木时使用其测量值；其余链路使用恢复符号到最近星座点的残差功率 |
| 反馈时序 | 第 `i` 帧使用第 `i − delay − 1` 帧的有效接收估计；捕获成功后才形成可用反馈 |

OFDMA 包注入保留独立用户数量，将完整包按星座字分到各用户，并在末尾补齐完整星座字。接收后按公开的原包长度移除这些填充位，再执行 CRC 和载荷统计。每帧提供 `wire_padding_bits`；64QAM 的 16 字节载荷包使用 4 位对齐填充。

## 📊 指标与复现

`tx_duration_seconds` 根据实际发送样本数与采样率计算，包含前导、导频、RRC 保护段、OFDM CP 及无线帧结构。`channel_tail_seconds` 记录信道输出额外样本对应的时间；两者共同形成发送至接收的 `duration_seconds`。停等时延再累计反馈或超时等待。MIMO 的 `tx_energy` 汇总全部发送天线的实际样本能量。

`goodput_bps` 是成功交付的有效载荷比特数除以协议总时间。每包第一次成功到达计算交付时延；重复 ACK 丢失产生的再次发送继续计入占用时间。BER 对成功包比较实际交付内容，对最终失败包比较最后一次译码载荷。包交付率、CRC 与 BER 分别保存在结果中。

工程种子与包序号、发送次数共同派生实际链路和反馈的随机流。ARQ / HARQ 的同包同次发送使用配对种子。AMC 按工程种子与帧序号派生随机流。每条事件保留实际 Build token、执行的积木种类和 PHY 指标。

## 🔌 API

所有动作通过 `POST /api/communications/{action}` 调用，并沿用当前会话参数。

| action | 主要请求字段 | 返回 |
| --- | --- | --- |
| `subproject-create` | `program, block_ids, name, parameters` | 定义对象 |
| `subproject-validate` | `definition` | 规范定义 |
| `subproject-insert` | `program, definition, instance_id?, parameters?, index?` | `{program, instance}` |
| `subproject-update` | `program, definition, instance, parameters?` | `{program, instance}` |

公开参数格式示例：

```json
{"name":"snr","label":"噪声信噪比","default":18,"targets":["block-3:snr_db"]}
```

工程文档保存 `subprojects: {definitions: [...], instances: [...]}`。定义包含 `id/name/version/ports/blocks/parameters`；实例包含 `id/definition_id/version/parameters/members/block_map/ports`。

闭环运行使用已有后台任务 `job-start`，`kind` 为 `protocol` 或 `amc`，提供 `{program, token, settings}`。实际物理层设置 `settings.phy="program"`，参考物理层设置 `"reference"`。AMC 额外接收 `coding="preserve" | "convolutional"` 与 `noise_block_id`。结果沿用 `config/frames/events/metrics/complete`，并提供实际工程和每次发送的详细证据。

## ✅ 验证

在代码目录运行：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -m unittest scripts.test_communications_closedloop -v
```

专项测试覆盖实例参数、版本和独立状态，OFDM / DSSS / RAKE / MIMO / MIMO-OFDM / OFDMA / FHSS 实际包交付，软信息逐位合并，捕获失败重传，反馈丢失去重，AMC 位宽和 SNR 差，实际时延与多天线能量，以及任务取消。最近结果保存在 `logs/communications-v048/closedloop-core-tests.txt`；相关旧功能联测结果在 `closedloop-tests.txt`。
