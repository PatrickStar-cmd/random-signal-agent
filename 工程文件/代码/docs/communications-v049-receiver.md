# v0.4.9 接收估计、软检测与阵列实验

本组新增 11 个积木与 10 个实验预设，覆盖 LMMSE、Kalman、按流有效噪声、MRT/SVD 预编码、均匀线阵和 MVDR 空间零陷。

## 🔍 公开导频信道估计

`rx_mimo_lmmse` 可接静态 MIMO、周期正交导频 MIMO 和 MIMO-OFDM。`rx_mimo_kalman` 接周期正交导频 MIMO。`rx_mimo_soft` 提供 LS、LMMSE、Kalman 三种估计选项。

设公共训练矩阵为 P，接收训练为 Y，采用 Y = P Hᵀ + N。LS 以最小二乘求 H；导频残差估计复噪声方差，分母使用剩余自由度。LMMSE 在每根接收天线上应用发送维相关先验 R：

`Ĥᵀ = (PᴴP + σ²R⁻¹)⁻¹PᴴY`

先验矩阵元素为 `R[i,j] = prior_power × correlation^|i-j|`。用户可改变先验功率和相关系数，观察导频噪声、估计收缩与检测性能。

Kalman 使用复 AR(1) 状态模型 `h[t+1] = ρ h[t] + u[t]`，逐时隙预测状态与协方差，在公共导频时隙更新。数据时隙使用当时已有的估计；首组导频残差初始化噪声方差。空间观察提供协方差迹、导频位置、估计矩阵与矩阵条件数。

接收函数的输入包含公开导频、接收样本、帧布局和长度。模拟信道真值用于信道观察图，接收计算由公开测量驱动。

## 🫧 逐流软信息

空间复用维持总发送功率归一化，令 `A = Ĥ / √Nt`，使用 MMSE 权重 `W = (AᴴA + σ²I)⁻¹Aᴴ`。检测后的响应矩阵为 B = WA。

每条流先除以 `B[k,k]` 校准平均增益，再使用以下有效噪声计算软信息：

`σ²eff[k] = (σ²Σr|W[k,r]|² + Σj≠k|B[k,j]|²) / |B[k,k]|²`

其中第一项是滤波后的噪声，第二项是残余空间流干扰。有效方差逐符号传给现有 PSK/QAM 软解调，LLR 正值偏向比特 0。LDPC、软 Viterbi 和闭环实验使用相同软信息。

三个新 MIMO 接收积木均输出有效方差；MIMO 软输出积木突出展示该实验主题。空间观察中的「每流有效噪声与 LLR」可比较各流可靠性。

## 🧭 均匀线阵与预编码

阵列响应为 `a[n,θ] = exp(j 2π d n sinθ)`，其中 d 为以波长计的阵元间距。每条路径形成 `g a_rx(θ) a_tx(φ)ᴴ`，各路径相加得到收发矩阵。参数包括收发天线数、间距、到达角、离开角、复增益和接收噪声。

- `tx_array`：单流公共训练与数据，供接收阵列合并实验。
- `tx_mrt`：反向正交公共导频测量信道，以估计信道共轭设置单位范数发送权重，使用一根接收天线。
- `tx_svd`：对反向导频测得的矩阵作 SVD，选取两个右奇异向量发送双流。
- `array_channel`：按角度生成真实阵列传播与噪声。
- `array_interference`：从指定方向叠加随机 QPSK 干扰，阵元间保持对应的空间相位。

MRT/SVD 的反向探测时隙计入帧时长。前向训练经过实际预编码器，接收侧据此估计有效信道。发送数据总功率保持归一化；SVD 双流由 `rx_array_svd` 作增益校准 MMSE 检测。

## 🎯 常规合并与 MVDR

`rx_array_conventional` 使用目标方向矢量作常规合并。`rx_array_mvdr` 从接收公共训练残差估计干扰噪声协方差 Rn，以

`w = Rn⁻¹a / (aᴴRn⁻¹a)`

形成目标方向单位响应和自适应空间零陷。对角加载参数按平均阵元残差功率缩放。两种合并都使用公共导频校准最终复增益。

「波束方向图与零陷」展示 −90° 至 +90° 的归一化方向响应，以及训练残差的合并前后功率与抑制量。发送 MRT/SVD 同样提供方向图。

## 🧪 预设与操作

| 预设 | 主要实验 |
|---|---|
| receiver_lmmse | 静态 MIMO 的 LMMSE 估计 |
| receiver_kalman | 移动 MIMO 的因果跟踪 |
| receiver_soft_ldpc | MIMO 有效噪声与 LDPC |
| receiver_soft_viterbi | MIMO-OFDM 与软 Viterbi |
| receiver_ofdm_lmmse | 逐子载波 LMMSE 估计 |
| receiver_kalman_soft | Kalman 跟踪、逐流 LLR 与 LDPC |
| array_conventional | 常规合并面对方向干扰 |
| array_mvdr | MVDR 空间零陷 |
| array_mrt | 反向公共导频与 MRT |
| array_svd | 角度多径与 SVD 双流 |

运行后打开「空间观察」，选择接收或阵列积木。改变视图查看矩阵、跟踪、波束或有效噪声。星座图中的样本可点选，下方联动卡列出对应空间流、有效噪声、信道矩阵和 SIC 记录；按钮保持所选位置切换视图。OFDMA 资源格可点选到具体时隙和子载波，联动查看用户、功率、调度前队列、吞吐和时延。

建议对照：LMMSE 与 LS 的低 SNR 导频；Kalman 与线性插值的移动场景；双流可靠性差异与软译码；常规合并与 MVDR；单路发送与 MRT；不同角度分离下的 SVD 双流。

## ✅ 数值验证

执行 ` .venv/Scripts/python.exe -m unittest discover -s scripts -p test_communications_receiver_v049.py -v `。

测试覆盖 200 次随机信道下的 LMMSE 估计误差、Kalman 因果性、四万组双流符号的有效噪声校准、静态和 OFDM 软检测、反向导频矩阵恢复、预编码发送能量、MVDR 干扰抑制、10 个预设端到端运行以及积木组合约束。

参考：[LMMSE / Kalman 时变 OFDM 研究](https://arxiv.org/abs/1205.3394)、[MathWorks MVDR 波束形成](https://www.mathworks.com/help/phased/ref/phased.mvdrbeamformer-system-object.html)。
