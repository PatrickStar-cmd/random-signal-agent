# v0.4.5 · 真实收发链路与实验分析更新 🌊

150 个可添加模块、固定信宿、64 个示例、7 项实验任务。海洋配色、六类积木、Build/Run、工程 schema 1/2、组合模块、分支、单步、续跑和多帧状态继续可用。无需新增生产依赖。

## 开始实验 🧭

启动服务后打开通信实验室，展开「🌊 真实收发链路 · 测量仪表与实验任务」。选择任务 → 载入任务链路 → 运行任务对照。任务对照会构建当前链路，运行当前参数和各变体，并生成 BER、EVM、PAPR、净速率和频谱效率表及叠加曲线。选择「测量位置」查看具体积木的输入/输出，切换仪表观察功率谱或 CCDF。

七项任务：调制阶数、I/Q 校正、功放回退、ADC 位数/量程/AGC、OFDM 削峰、窄带干扰、打孔码率。可以先修改链路参数，再运行对照；所有变体沿用当前种子，各方案噪声按当前 Es/N0 或发送采样 SNR 定义。跨码率的同信息比特 Eb/N0 比较继续使用通用扫描。每个任务变体执行一帧；更多统计使用多帧运行或参数扫描。

## 新增积木 🧱

| 积木 | 参数与使用位置 |
| --- | --- |
| 8PSK / 64QAM / 256QAM | 每种都有映射、硬解调、Max-log LLR 软解调；单位平均星座能量和 Gray 标记。软输出连接软 Viterbi 或 LDPC。接入公共前导、RRC、OFDM、导频估计、均衡、噪声估计和判决引导载波环。 |
| I/Q 幅相不平衡 | Q/I 增益误差默认 2 dB，范围 −12–12；正交误差默认 10°，范围 −60–60。 |
| I/Q 训练校正 | 位于帧同步后；用公共复数前导估计直接项和镜像项，求逆校正。训练星座需覆盖两条正交轴。 |
| 直流偏置 | I 默认 0.2、Q 默认 −0.1，范围 ±4。 |
| 直流消除 | 默认整帧减均值；也可选一阶 IIR DC blocker，极点默认 0.995，范围 0.8–0.9999，跨帧保持状态。 |
| 功放非线性 | Rapp / Saleh；输入回退默认 3 dB（0–30）；幅度尺度默认 1（0.1–8）；Rapp 平滑因子默认 2（1–10）；Saleh 相位渐近值默认 30°（0–90）。放在发送成形或 OFDM 后、信道前。 |
| ADC 量化与饱和 | I/Q 每路默认 8 位（2–16），量程默认 ±2（0.05–16）；显示超量程样本数。可放在接收 AGC 后、匹配滤波或重采样前。 |
| OFDM 削峰滤波 | 每符号 4 倍插值后削峰、保留有效子载波、重建 CP；门限默认 5 dB（0–15），迭代默认 2 次（1–8）。 |
| 窄带单音干扰 | 频率默认 200 Hz，参数范围 ±100000 Hz 且须落在当前 Nyquist 范围；幅度默认 0.8（0–8）。多帧保持干扰相位。 |
| 复基带陷波 | 频率默认 200 Hz；极点半径默认 0.98（0.5–0.999）；跨帧保持滤波状态。 |
| 卷积码打孔 / 解打孔 | 紧接 (7,5)₈ 卷积编码；2/3 周期 1110，3/4 周期 111001；软解调后解打孔，在缺失位置填 LLR=0，再软 Viterbi。实际码率包含尾位和末周期长度。 |

OFDM 新增有效子载波数（默认 0，表示全部非直流；自定义须为 4 至 NFFT−1）和导频间隔（默认 4，范围 2–16）。至少保留两个导频和一个数据载波。默认参数兼容旧配置与 Build 令牌。FFT 点数、CP 继续使用原参数。

## 测量与解释 🔬

- **Welch 功率谱**：完整内部数组，Hann 窗，最多 1024 点，50% 重叠，额外覆盖末尾窗口；双边功率密度，单位为归一化功率/Hz。累积积分的 0.5%–99.5% 频率范围给出 99% 占用带宽。
- **PAPR / CCDF**：PAPR=10 log10(max|x|²/mean|x|²)。CCDF 是整帧离散采样瞬时功率超过门限的比例；0–15 dB 共 61 点。OFDM 削峰内部用 4 倍插值；测量显示实际输出采样波形的 PAPR。多帧运行提供逐帧峰均比和 EVM。
- **ACLR**：主信道和左右邻道分别对 Welch 密度积分，显示 10 log10(Pmain/Padj)。中心、主带宽、邻道间隔及邻道带宽可在界面配置；频段必须位于采样带宽内且互不重叠。结果不是特定无线标准的合规判定。
- **EVM**：沿用接收符号相对发送符号的归一化 RMS 误差；增加每 128 符号的分段曲线、多帧曲线和逐数据子载波聚合 EVM。统计只在评价阶段读取发送负载，接收校正只读取公共训练。
- **净速率**：信息比特数 / 完整发送帧时间，包含编码、前导、导频、CP、终止和填充开销。频谱效率用净速率 / 发送 99% 占用带宽计算。它表示发送有效信息速率，不是扣除误帧或重传后的吞吐量。模拟调制只显示波形测量。
- **OFDM 栅格**：金色训练、紫蓝数据、绿色导频、灰色保护、淡紫直流；最多展示前 16 个符号。另有逐子载波信道幅度与 EVM 曲线。
- **A/B 自动对齐**：先按采样率插值到 A 的时间网格，再在当前窗口内搜索最多 ±256 点（不超过窗口 1/3）的去均值归一化复互相关峰。显示估计延迟及相关值；叠加图显示 A-I/B-I，差值保留 I/Q。周期信号可有多峰；此功能只调整观察视图。
- **理论 BER**：无编码、无额外失真的单一 AWGN 符号链路支持 BPSK/QPSK 精确理论曲线；8PSK/方形 QAM 使用 Gray 最近邻中高 SNR 近似，界面标注适用口径。其余链路展示实测统计。原 BER/SER/FER 置信区间继续保留。

测量位置保留前 8 个新增射频处理阶段的完整帧统计。原始观察点分页仍可查看所有积木。工程 JSON 保存仪表频段、任务结果和多帧记录；「导出测量 JSON」带测量数组、指标、设置与对照链路。扫描 JSON/CSV 增加 EVM/PAPR/净速率/频谱效率；PDF 增加效率摘要与射频任务对照。

## 算法说明 🧮

设 x=I+jQ，I/Q 失真为 y=I+jg(Q cosφ+I sinφ)，g=10^(gain_dB/20)。等价写成 y=a x+b x*，用前导的 [x,x*] 两列复数最小二乘估计 a,b，再以 x̂=(a* y−b y*)/(|a|²−|b|²) 校正。

令 r=|x|·10^(−IBO/20)/A。Rapp 输出幅度为 A r/(1+r^(2p))^(1/(2p))，保持相位；归一化 Saleh 幅度为 A r/(1+r²)，附加相位 φmax·r²/(1+r²)。两者是无记忆复包络器件模型。量化器在 ±A 的 2^B 个等距电平上四舍五入，超量程饱和。

复陷波 H(z)=(1−e^(jω0)z⁻¹)/(1−ρe^(jω0)z⁻¹)，ω0=2πf0/Fs。ρ<1 保证稳定，越接近 1 陷波越窄。直流 IIR 为 y[n]=x[n]−x[n−1]+ρy[n−1]。

参考：[射频组件建模](https://www.mathworks.com/help/comm/rf-component-modeling.html)、[调制精度测量](https://www.mathworks.com/help/comm/ug/measure-modulation-accuracy.html)、[ACPR 与 CCDF](https://www.mathworks.com/help/comm/gs/acpr-and-ccdf-measurements-with-matlab-system-objects.html)。

## 启动、接口与验证 🧪

沿用 `config/communications.json` 的全局范围与运行资源限制，`config/release.json` 记录版本。积木可配置参数由 `/api/communications/catalog` 返回，默认值/范围见上表；无需模型 API Key。Windows 用 `scripts/start_server.ps1`，Linux 用 `bash scripts/start_server.sh`。

新增后台任务类型 `rf-task`：向 `/api/communications/job-start` 传入 `kind: "rf-task"`，payload 含当前 program、Build token 和 task_id（order/iq/pa/adc/clip/notch/rate）；状态与取消复用原接口，并检查会话所有权。catalog 增加 tasks；运行结果增加 analysis 和效率指标。旧工程继续导入；新字段随 schema 2 保存。

```powershell
.venv/Scripts/python.exe scripts/test_communications_rf.py
node scripts/test_communications_alignment.js
.venv/Scripts/python.exe -m unittest discover -s scripts -p "test_*.py"
.venv/Scripts/python.exe scripts/verify_reproduction.py
.venv/Scripts/python.exe scripts/benchmark_algorithms.py
.venv/Scripts/python.exe scripts/run_communication_sweep.py --preset rf_qam64 --values 10,15,20,25 --frames 10
```

新增 Python 套件 16 项：星座 Gray 邻接/能量、硬软映射、编码/OFDM/RRC 组合、I/Q 校正、ADC、功放、陷波、OFDM 资源与跟踪、削峰 CP、打孔尾长、错误连接、Welch 对照 SciPy、效率与 EVM、理论曲线、64 示例、任务所有权与保存、多帧滤波状态。Node 检查正负时延、复数、常量信号和不同采样率。生产启动无需 Node。

日志：`logs/communications-rf/latest.log`、`alignment.log`；全量结果与浏览器验收放 `logs/communications-v045/`；临时调试在 `debug/v045/`。发布包使用 `scripts/build_release.py` 和 `scripts/verify_release.py`，验证日志在 `logs/release/`。
