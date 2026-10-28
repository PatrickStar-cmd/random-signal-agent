<div align="center">

# 🌊 Random Signal Agent · 谛听

[![Release](https://img.shields.io/github/v/release/PatrickStar-cmd/random-signal-agent?style=flat-square)](https://github.com/PatrickStar-cmd/random-signal-agent/releases/latest)
[![Python 3.12–3.14](https://img.shields.io/badge/Python-3.12%E2%80%933.14-3776AB?style=flat-square&logo=python&logoColor=white)](RELEASE.md)
[![Deployment checks](https://github.com/PatrickStar-cmd/random-signal-agent/actions/workflows/validate-deployment.yml/badge.svg?branch=main)](https://github.com/PatrickStar-cmd/random-signal-agent/actions/workflows/validate-deployment.yml)
[![MIT License](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)

</div>

<details name="readme-language">
<summary><strong>简体中文</strong></summary>

<div align="justify">

**💬 对话分析随机信号，🧩 积木搭建通信链路。**

谛听将随机信号与通信原理实验放进同一个海洋风格工作区：生成带噪信号、比较滤波方法、分析时频特征，也能用积木连接编码、调制、信道与接收模块，观察完整收发过程。

🎓 面向 **UESTC 随机信号与通信原理课程**，支持本地计算、固定种子复现，以及可选的模型辅助对话。

[🌐 实验预览](https://patrickstar-cmd.github.io/random-signal-agent/) · [📦 下载 v0.4.10](https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.4.10) · [📘 安装指南](RELEASE.md)

## 🧭 快速导航

| 开始使用 | 了解项目 |
| --- | --- |
| [✨ 核心功能](#zh-features) | [🏗️ 工作流程](#zh-workflow) |
| [📡 通信实验室](#zh-communications) | [📘 通信指南](工程文件/代码/docs/communications-lab.md) |
| [🎬 界面展示](#zh-interface) | [⚙️ 配置说明](#zh-configuration) |
| [🚀 快速开始](#zh-quick-start) | [📊 实验结果](#zh-results) |
| [🧪 第一个实验](#zh-first-experiment) | [🔧 常见问题](#zh-troubleshooting) |
| [📚 项目文档](#zh-documentation) | [🤝 参与改进](#zh-contributing) |

<a id="zh-features"></a>

## ✨ 核心功能

| 功能 | 可以完成的实验 |
| --- | --- |
| 🐳 可爱海洋界面 | 海蓝/薰衣草紫渐变、AI 立体鲸鱼插画，桌面/平板/手机自适应。 |
| 📡 通信实验室（v0.4.10） | 230 个可添加积木、121 个示例；自主接收、连续录波、约束选参、教师评阅、两路汇合与 OFDM 通感。 |
| 🔑 模型 API 配置 | 在页面选择服务与模型、填写 Key、测试并应用；可按会话记住配置。已包含在 v0.4.10 部署包中。 |
| 📄 PDF 分析报告（v0.4.10） | 填写标题、作者与目的，预览后导出中文简版或标准版，包含矢量图表、真实指标和复现信息。 |
| 🩺 信号诊断实验室 | STFT 时频图联动异常区间，六类可复现故障注入、盲测揭晓评分，以及保留原始观测的验证实验。 |
| 💾 实验工作台 | 用模板创建实验，保存、恢复、复制、搜索、重命名或删除快照；服务重启后继续工作。 |
| 📥 数据导入向导 | 预览 CSV/TXT，自选时间列与信号列，转换时间单位并定位错误行。 |
| 🔍 跨实验对比 | 叠加 2–4 个快照的波形与频谱，比较参数和指标，导出独立 HTML 报告。 |
| ⏳ 任务与存储 | 查看排队、在安全检查点取消任务、释放空闲会话，预览后清理无引用采样文件。 |
| 📦 数据与报告 | 导出完整采样 CSV、HTML 报告、参数清单和可重新导入的 ZIP。 |
| 🧮 可解释比较 | 按抑噪、保留波形或保留瞬态评分，查看评分分项、参数与耗时。 |
| 🎲 可复现仿真 | 设置采样率、时长、主频、噪声和随机种子，生成同一组样本。 |
| 🧹 六种预处理方法 | 比较鲁棒滑动平均、中值、指数平滑、FFT 低通、混合增强与卡尔曼滤波。 |
| 📈 时频域分析 | 查看统计指标、FFT 峰值、相关性与频谱特征。 |
| 🔬 随机过程分析 | 分析 AR 模型、Welch 功率谱与残差。 |
| 🤖 Agent 模式 | 自动比较方法与参数，查看工具调用轨迹和控制建议。 |
| 🎙️ 多种输入 | 分析仿真信号、CSV/TXT 样本或浏览器麦克风音频，下载处理后的音频。 |

<a id="zh-communications"></a>

## 📡 通信原理实验室 · 用积木搭建收发链路

拖入积木、编辑参数，点击 **🔨 Build** 检查链路，再用 **▶️ Run** 观察传输结果。六类积木覆盖发送、信道与接收环节，提供 **230 个可添加积木 + 固定信宿、121 个实验示例**。

**🎲 信源 → 🔀 发转换器 → 📡 调制器 → 🌊 信道 → 🎛️ 解调器 → 🔄 收转换器 → 📺 信宿**

| 模块 | 包含的技术 |
| --- | --- |
| 🎲 信源 | 随机/自定义比特、UTF-8 文本、正弦、方波、高斯信号；新增 PRBS7/9/15 m 序列与相关观察。音频、图像、文件、离散概率信源与 SigMF / 原始 I/Q 录波。 |
| 🔀 发转换器 | 均匀/压扩 PCM、DPCM、增量调制；重复码、Hamming、卷积码、Turbo、LDPC、CRC、扰码与交织；十种线路编码。Huffman、ADPCM、BCH、RS、自描述物理分包；DSSS、SIMO 训练、Alamouti 与 MIMO 空间复用。 |
| 📡 调制器 | BPSK/QPSK/16QAM、OOK/2ASK、2FSK、DBPSK/DQPSK、MSK/GMSK；AM/DSB-SC/SSB/VSB/FM/PM、PAM；实/复基带成形、前导与导频、OFDM/IFFT/CP。 |
| 🌊 信道 | 白噪声、带限、衰减、相移、丢失、交流耦合、ISI、定时/时钟漂移；新增频偏、相位噪声、未知帧延迟、复多径、Rayleigh/Rician 衰落、独立时变路径与 Markov 突发噪声。扩频码片多径、多天线固定/块 Rayleigh 信道与独立接收噪声；移动相关 MIMO、频率选择性 MIMO、OFDMA 独立用户信道；3GPP TDL-A/B/C、连续流截断与单目标延迟/多普勒。 |
| 🎛️ 解调器 | 各制式配对解调与 PSK/QAM 软解调；匹配滤波、符号/载波/帧同步，ZF/MMSE/DFE、MLSE 序列均衡、实/复 LMS/NLMS/RLS、CMA、导频 LS、OFDM/FFT/频域均衡；新增 AGC、自动 N0、重采样、T/2 均衡、OFDM 频偏与导频跟踪。 |
| 🔄 收转换器 | 线路译码、解交织、解扰、CRC 校验、重复码/Hamming 纠错、硬/软 Viterbi、Turbo BCJR、LDPC 迭代，以及 PCM/压扩/DPCM/增量重构。Huffman/ADPCM/BCH/RS 译码、组包；码捕获、解扩、RAKE、SC/MRC、Alamouti、MIMO ZF/MMSE、ZF-SIC/MMSE-SIC、周期导频跟踪、MIMO-OFDM、OFDMA 分用户恢复与 FHSS 解跳；MUSIC 测角、自动 MVDR、连续帧重组和 OFDM 测距测速。 |
| 📺 信宿 | 显示接收比特、文本与模拟波形，支持叠加原始信源、标记错误位和浏览完整接收序列。音频播放、图像重建与 PSNR、文件下载和 SHA256 核验。 |

- 🆕 **v0.4.10 自主接收**：MLSE 序列均衡、MUSIC 测角与自动 MVDR、3GPP TDL-A/B/C；自描述保护帧头与连续多包捕获，录波直接恢复长度、MCS 和业务偏移。
- 🔁 **v0.4.10 编码与闭环**：Turbo Log-MAP / Max-log BCJR 迭代译码、卷积母码 IR-HARQ、同预算 Chase 对照；查看逐轮外信息、RV 索引、母码覆盖与实际发送资源。
- 🔬 **v0.4.10 实验与教学**：本次算法步骤回放、测量诊断与逐块耗时、两参数约束 / Pareto 选参、教师批量评阅、帧级事件与恢复时间。
- 🔱 **v0.4.10 汇合与通感**：共享信道的两路复符号 / LLR 加权或选择汇合；单目标 OFDM 通感同时恢复通信比特并测距测速。分析按主题子页组织，沿用海洋配色、工程保存和导出。
- 🔍 **v0.4.9 先进接收与空间处理**：LMMSE、Kalman、按流软检测、Polar SC/CRC-SCL、阵列角度信道、MRT/SVD 预编码与 MVDR 空间零陷。
- 🌊 **v0.4.9 波形与射频**：DFT-s-OFDM/SC-FDMA、记忆功放与回环训练 DPD、Schmidl–Cox/Zadoff–Chu 突发同步与采样时钟恢复。
- 🧰 **v0.4.9 调试与教学**：条件断点、批量/二维/目标搜索检查点续跑、统计图与记录复跑、学生分阶段作业包、空间视图联动和可编排 PDF 报告。
- 🔁 **v0.4.8 闭环链路**：当前积木工程直接执行 ARQ、Chase HARQ 和 AMC；统计实际 ACK/NACK、重传、软合并、空口时长与吞吐。
- 🛰️ **v0.4.8 空间通信**：ZF-SIC/MMSE-SIC、动态相关 MIMO 与导频跟踪、MIMO-OFDM、独立用户 OFDMA、FHSS；观察天线波形、空间流星座、矩阵与逐层消除。
- 🧩 **v0.4.8 工程与教学**：带类型端口和公开参数的版本化子工程、教学任务编辑器、跨工程多种子队列、最低信噪比搜索；导入 SigMF/原始 I/Q，连接接收积木回放并导出录波。
- 🎙️ **v0.4.7 业务传输**：音频、图像、文件和概率信源；Huffman、IMA ADPCM、BCH、RS、分包/组包；播放接收音频、重建图片、核对文件 SHA256。
- 📡 **v0.4.7 扩频与多天线**：DSSS、码捕获、相关解扩、RAKE、SIMO SC/MRC、Alamouti 2×1、2×2 MIMO ZF/MMSE；观察相关峰、路径和训练估计矩阵。
- 🎓 **v0.4.7 教学实验**：工程变量与公式、二维参数热图、Huffman/Viterbi/LDPC/星座过程、9 项挑战、参数与结果差异、Python/JSON/SVG 导出；ARQ/HARQ 和五档 AMC 反馈实验。
- 🧭 **v0.4.6 界面与布局**：紧凑工具栏、可搜索实验库、参数/信宿切换、统一分析标签页、大图模式和窄屏参数抽屉；任务结果标注所属实验、时间与参数。
- 🆕 **v0.4.5 射频与分析**：8PSK/64QAM/256QAM、I/Q 失真与校正、直流消除、Rapp/Saleh 功放、ADC、OFDM 削峰、窄带干扰/陷波、打孔卷积码；Welch/CCDF/ACLR、逐子载波 EVM、资源栅格、自动对齐和 7 项实验任务。
- 🧰 **积木编程体验**：中文/英文搜索、收藏最近；自动补齐接收链路、连接类型/长度/群时延提示；真实单步、多图游标联动、命名工程与快照、框选组合复用、共享样本分支、通用参数扫描/停止/续跑、跨帧状态与中文 PDF。
- 🧩 **搭建与编辑**：海洋风格积木工坊、紧凑拼接链路、独立参数面板；拖放/排序、撤销重做、草稿恢复及工程 JSON 导入导出。
- 📈 **观察与保存**：中间处理波形、前导相关、OFDM 资源网格、眼图、同步和均衡收敛；BER/SER/FER 多种子扫描、Eb/N₀ 标定、95% 区间与多曲线比较，完整 JSON/CSV 导出。

![🐬 v0.4.7：业务传输与教学实验，沿用海洋风格](docs/images/communications-v047-learning.png)

![🧩 通信实验室：积木工坊、收发链路、信宿观察与参数面板](docs/images/communications-studio.png)

![🛰️ v0.4.8：空间通信、逐层检测与海洋工作区](docs/images/communications-v048-spatial.png)

![🌊 v0.4.10：自主接收与实验分析增强](docs/images/communications-v0410.png)

📘 [v0.4.10 自主接收与实验分析指南](工程文件/代码/docs/communications-v0410.md)

📘 [v0.4.9 先进收发与实验调试指南](工程文件/代码/docs/communications-v049.md) · [v0.4.8 闭环与空间通信指南](工程文件/代码/docs/communications-v048.md)

📘 [v0.4.7 业务与教学指南](工程文件/代码/docs/communications-v047.md)

📘 [v0.4.5 射频与测量指南](工程文件/代码/docs/communications-v045.md)

![🌊 v0.4.5 射频实验仪表](docs/images/communications-v045-analysis.png)


🆕 [v0.4.4 算法与实验说明](工程文件/代码/docs/communications-v044.md)

![🌊 v0.4.4 工程与逐块调试](docs/images/communications-v044-studio.png)

📚 [通信指南](工程文件/代码/docs/communications-lab.md) · [模拟调制](工程文件/代码/docs/analog-modulation.md) · [线路码与信道](工程文件/代码/docs/baseband-coding.md) · [同步与均衡](工程文件/代码/docs/receiver-recovery.md)

<a id="zh-interface"></a>

## 🎬 界面展示

v0.3.4 的海洋界面使用青蓝、薰衣草紫与珊瑚粉渐变，外层 4 px、内层 2 px 框线；中文优先使用华文中宋，英文与数字使用 Times New Roman。日期时间放大加粗，Agent 方法比较按结论、推荐指标与后续操作分段。六个功能分区切换时保留当前输入与实验状态。

以下截图来自 v0.3.4，部署包已包含本次视觉更新。字体使用访问者电脑上的本地字体，缺少时自动回退。

![v0.3.4 海洋工作区：Agent 分析、波形与频谱](docs/images/ocean-ui-v034.png)

<details>
<summary><strong>查看模板、诊断与 API 配置</strong></summary>

**模板与实验**：比较六种方法，保存命名快照，导入或导出完整实验包。

![v0.3.4 模板与实验](docs/images/workbench-v034.png)

**诊断实验室**：时频图与波形联动，定位异常区间并验证处理效果。

![v0.3.4 诊断实验室：时频图与联动波形](docs/images/diagnostics-v034.png)

**模型与设置**：选择服务商、模型与保存方式，在页面完成连接配置。

![v0.3.4 模型 API 配置表单](docs/images/model-api-v034.png)

</details>

<details>
<summary><strong>观看海洋界面操作演示（v0.3.0）</strong></summary>

Agent 采集与分析 → 保存实验快照 → 查看故障诊断 → 打开模型配置。演示使用本地信号工具链。

![v0.3.0 海洋界面操作演示](docs/images/ocean-demo-v030.gif)

</details>

## 📄 导出 PDF 分析报告

完成采集或载入实验后，打开 **模板与实验 → PDF 分析报告**，填写标题、作者、分析目的与量纲，选择简版或标准版。点击 **预览摘要与章节**，核对内容后点击 **下载 PDF**。

标准版包含波形、指标、频谱、Welch 功率谱、自相关、已有的方法比较与诊断，以及结论和复现参数。简版保留概览、关键指标、波形和频谱。说明由实际数据生成，无需模型 Key；无干净参考时不计算真实 SNR/RMSE，盲测须先揭晓。

![v0.3.1 报告预览与下载](docs/images/pdf-report-v031.png)

[查看示例 PDF](docs/report-example.pdf) · [报告使用说明](工程文件/代码/docs/pdf-report.md)

**v0.3.2 新增**：在“报告数据”选择处理历史，勾选最近 50 次以内的结果，也可补充已保存实验。按时间排序后导出统一封面、汇总表、可跳转目录和分组图表；总计最多 50 组，历史重启后保留。升级前未保存的结果无法补回。

<a id="zh-quick-start"></a>

## 🚀 快速开始

使用 **Python 3.12–3.14** 或 **Docker Compose v2**。v0.4.10 使用 FastAPI 后端；部署检查覆盖 Windows、Linux 的 Python 3.12–3.14 和 Linux Docker。

### 1. 获取项目

下载并解压 v0.4.10 的[部署 ZIP](https://github.com/PatrickStar-cmd/random-signal-agent/releases/download/v0.4.10/random-signal-agent-v0.4.10-deploy.zip)，在解压目录中的 `工程文件/代码` 打开终端。

也可以克隆仓库：

```bash
git clone https://github.com/PatrickStar-cmd/random-signal-agent.git
cd "random-signal-agent/工程文件/代码"
```

### 2. 安装并启动

**Windows PowerShell**：使用 Python 3.12–3.14。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-repro.txt
.\.venv\Scripts\python.exe server.py --host 127.0.0.1 --port 8000
```

**Linux / macOS**：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-repro.txt
.venv/bin/python server.py --host 127.0.0.1 --port 8000
```

<details>
<summary><strong>使用 Docker 启动</strong></summary>

在同一个 `工程文件/代码` 目录执行：

```bash
cp .env.example .env
docker compose up -d --build --wait --wait-timeout 120
```

Windows 将第一条命令替换为 `Copy-Item .env.example .env`。上传文件和生成结果保存在本地目录中；使用 `docker compose logs --tail 100` 查看日志，使用 `docker compose down` 停止服务。

</details>

### 3. 打开应用

访问 **<http://127.0.0.1:8000>**。无需配置外部模型，即可使用仿真、滤波和分析功能。

[在线预览](https://patrickstar-cmd.github.io/random-signal-agent/) 包含已保存的实验结果与界面截图；交互实验需要运行 Python 后端。

<a id="zh-first-experiment"></a>

## 🧪 第一个实验

1. 打开 **信号工作区**。可先开启 **Agent 模式**，自动比较六种预处理方法，再输入：

   > 采集一段 8 秒、采样率 200Hz、主频 8Hz 的正弦信号加高斯噪声，随机种子 42

2. 查看中间的波形、频谱与统计指标。使用命令式交互时，可继续输入：

   > 使用滑动平均预处理并分析时域和频域特征

3. 切换到 **模板与实验**，填写名称并点击“保存为新快照”；也可导出完整实验 ZIP，恢复全部采样、结果及工具记录。当前实验每次成功操作后自动保存。运行或恢复后默认比较当前数据；选择其他模板可生成新信号。
4. 使用自己的数据时，打开 **导入数据**，上传 UTF-8 CSV/TXT，选择时间列、信号列和时间单位，没有时间列则填写采样率。确认导入后进入模板与实验，比较方法并保存结果。
5. 在 **对比与报告** 选择 2–4 个快照，查看叠加曲线与指标，下载 HTML 报告。只有输入、参考信号、目标和评分版本一致时才直接比较评分。

想尝试异常定位时，先保存当前实验，再到 **诊断实验室** 点击“载入故障演示”。查看时频图与证据卡片，定位或选择区间后验证处理效果；采用结果后可保存快照。盲测在揭晓前隐藏真值和参考误差，限制完整实验导出与快照对比；独立诊断报告仍可导出。

外部模型是可选功能，入口为 **模型与设置 → 模型 API 配置**，操作见下方配置说明。

保持相同参数和随机种子，可重复生成同一组仿真样本。导入向导支持多列文件中的单个信号；工作区的“快速上传”按单列采样值或前两列“时间（秒）、采样值”读取，格式见[实验说明](docs/README.md)。

<a id="zh-workflow"></a>

## 🏗️ 工作流程

```mermaid
flowchart TD
    UI["Web 对话 / Agent 模式"] --> Agent["对话解析与工具调度"]
    Model["可选模型 API"] -.-> Agent
    Agent --> Input["仿真 / CSV / 麦克风输入"]
    Input --> Filter["预处理与方法比较"]
    Filter --> Analysis["时域 / 频域 / 随机过程分析"]
    Analysis --> Results["曲线、指标、工具轨迹与建议"]
```

| 组件 | 职责 |
| --- | --- |
| `web/chat.html` + `server.py` | Web 界面、上传、HTTP 接口与流式响应。 |
| `src/dialogue_agent.py` | 解析任务并调度信号工具。 |
| `src/acquisition.py` | 接收仿真信号、上传样本与音频。 |
| `src/preprocessing.py` | 信号滤波与候选方法比较。 |
| `src/analysis.py` + `src/advanced_analysis.py` | 提取时域、频域和随机过程特征。 |
| `src/llm_client.py` | 连接可选的 Chat Completions 兼容服务。 |

以上组件路径均相对于 `工程文件/代码`。

<a id="zh-configuration"></a>

## ⚙️ 配置说明

默认使用本地工具链。接入外部模型时，打开 **模型与设置 → 模型 API 配置**：

1. 选择 OpenAI、DeepSeek 或自定义 Chat Completions 兼容服务，输入该服务的 Key。
2. 点击“读取模型列表”并选择模型，或手动填写准确模型 ID。
3. 点击“测试并应用”，当前浏览器会话立即生效，无需重启。可随时切回本地工具链或移除配置。

默认只在服务内存保存；勾选“记住配置”后，Key 明文保存在 `data/model-settings.sqlite3`。浏览器存储、实验 ZIP 和任务记录不含 Key。接口兼容性、保存优先级与高级参数见[模型配置指南](工程文件/代码/docs/model-api-setup.md)。

<details>
<summary><strong>服务器默认配置与启动脚本</strong></summary>

管理员也可将 `config/server.env.example` 复制为 `config/server.env`，设置整个服务的默认地址、模型与 Key。会话配置优先于这些默认值。

| 配置项 | 用途 |
| --- | --- |
| `RS_AGENT_HOST` / `RS_AGENT_PORT` | 服务绑定地址与端口；仅本地使用时设置为 `127.0.0.1`。 |
| `RS_AGENT_LLM_BASE_URL` | 模型 API Base URL，例如 `https://your-provider.example.com/v1`。 |
| `RS_AGENT_LLM_MODEL` | 服务商提供的模型名称。 |
| `RS_AGENT_LLM_API_KEY` | 自己的模型 API Key。 |
| `RS_AGENT_LLM_TIMEOUT` | 模型请求超时秒数，默认 `45`。 |
| `RS_AGENT_LOG_FILE` | 启动脚本的日志路径，默认 `logs/server/server.log`。 |

激活虚拟环境后，Windows 使用 `scripts/start_server.ps1`，Linux/macOS 使用 `bash scripts/start_server.sh`，即可加载该配置文件。直接运行 `server.py` 不会加载 `config/server.env`。

Docker Compose 读取代码目录下的 `.env`。Docker 参数、HTTPS 部署与服务管理见[部署说明](工程文件/代码/DEPLOY.md)。

</details>

<a id="zh-results"></a>

## 📊 可复现实验示例

已保存的展示实验采用随机过程与混合噪声：采样率 **200 Hz**，时长 **8 秒**，共 **1600 点**，主频 **8 Hz**，随机种子 **42**。预处理使用 7 点窗口的鲁棒滑动平均。

| 指标 | 结果 |
| --- | ---: |
| 检测主频 | 8.000 Hz |
| 原始 SNR | 2.859 dB |
| 处理后 SNR | 4.781 dB |
| SNR 提升 | 1.922 dB |

以上数值对应这组已保存的实验，其他信号或滤波参数会得到不同结果。

[CSV 样例](docs/data/sample.csv) · [分析结果](docs/data/result.json) · [实验配置](工程文件/代码/config/showcase.json) · [复现步骤](docs/README.md)

<details>
<summary><strong>检查部署是否正常</strong></summary>

保持应用运行，在另一终端进入 `工程文件/代码`，使用相同的 Python 环境执行：

```powershell
# Windows
.\.venv\Scripts\python.exe scripts/smoke_deployment.py --base-url http://127.0.0.1:8000
```

```bash
# Linux / macOS
.venv/bin/python scripts/smoke_deployment.py --base-url http://127.0.0.1:8000
```

检查覆盖应用版本、海洋页面资源、模型配置接口、Agent 模式、流式响应、导入导出、诊断与 PDF 下载，结果写入 `logs/deployment/latest.log`。Release 附件还包含 `SHA256SUMS.txt` 和 `verification.json`。

</details>

<a id="zh-troubleshooting"></a>

## 🔧 常见问题

| 问题 | 处理方式 |
| --- | --- |
| 为什么在线预览不能运行新实验？ | GitHub Pages 提供已保存的展示内容。运行本地后端或使用 Docker 部署，即可交互实验。 |
| 必须配置 API Key 吗？ | 本地信号工具无需密钥；模型辅助对话属于可选功能。 |
| 支持哪些 Python 版本？ | v0.4.10 支持 Python 3.12、3.13、3.14。 |
| Windows 无法激活虚拟环境怎么办？ | 快速开始命令直接调用 `.venv\Scripts\python.exe`，无需激活。 |
| 麦克风无法使用怎么办？ | 通过 localhost 或 HTTPS 访问应用，并在浏览器中允许麦克风权限。 |
| 为什么上传信号没有 SNR 数值？ | 基于参考信号的 SNR 需要干净信号；上传样本与麦克风音频不包含该参考。 |
| 8000 端口被占用怎么办？ | 启动时改用 `--port 8001`，访问 `http://127.0.0.1:8001`，并同步修改部署检查的 URL。 |

<a id="zh-documentation"></a>

## 📚 项目文档

| 文档 | 内容 |
| --- | --- |
| [PDF 报告](工程文件/代码/docs/pdf-report.md) | 标题、预览、章节、数据依据与导出。 |
| [模型配置指南](工程文件/代码/docs/model-api-setup.md) | 页面选模、Key 保存方式与兼容设置。 |
| [界面说明](工程文件/代码/docs/ui-design.md) | 分区导航、响应式布局与操作入口。 |
| [通信实验室](工程文件/代码/docs/communications-lab.md) | 积木链路、Build/Run、指标、导出与复基带模型。 |
| [安装与发布说明](RELEASE.md) | 部署 ZIP、各系统启动命令与校验方式。 |
| [实验说明](docs/README.md) | 展示数据、参数、文件格式与复现步骤。 |
| [代码概览](工程文件/代码/README.md) | 模块结构与模型配置。 |
| [运行与配置](工程文件/代码/docs/exec.md) | 执行命令、配置参数与日志。 |
| [功能与验证](工程文件/代码/docs/review.md) | 实现情况、验证记录与当前限制。 |
| [算法原理](工程文件/代码/docs/principle.md) | 信号处理与分析方法。 |
| [部署说明](工程文件/代码/DEPLOY.md) | Docker、HTTPS、systemd 与健康检查。 |
| [更新日志](CHANGELOG.md) | 版本变更。 |

<a id="zh-contributing"></a>

## 🤝 参与改进

欢迎通过 Issue 或 Pull Request 提交问题修复、信号处理方法、实验样例和文档改进。报告问题时请提供 Python 版本、输入参数、复现步骤及相关日志；改进算法时请附上可复现信号与处理前后的对比。

[提交问题](https://github.com/PatrickStar-cmd/random-signal-agent/issues) · [查看 Pull Requests](https://github.com/PatrickStar-cmd/random-signal-agent/pulls)

## 📄 许可证

本项目采用 [MIT License](LICENSE)。使用、修改与分发时请保留许可证和版权声明；第三方依赖及素材遵循其各自许可。

</div>

</details>

<details name="readme-language" open>
<summary><strong>English</strong></summary>

<div align="left">

**💬 Analyze random signals through conversation. 🧩 Build communication pipelines with blocks.**

Diting brings Random Signals and Communication Principles experiments into one ocean-themed workspace. Generate noisy signals, compare filters and inspect time-frequency features, or connect coding, modulation, channel and receiver blocks to explore an end-to-end transmission.

🎓 Built for **UESTC Random Signals and Communication Principles coursework**, with local computation, seeded reproduction and optional model-assisted dialogue.

[🌐 Experiment preview](https://patrickstar-cmd.github.io/random-signal-agent/) · [📦 Download v0.4.10](https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.4.10) · [📘 Installation guide](RELEASE.md)

## 🧭 Explore

| Get started | Learn more |
| --- | --- |
| [✨ Features](#en-features) | [🏗️ How it works](#en-workflow) |
| [📡 Communication lab](#en-communications) | [📘 Lab guide](工程文件/代码/docs/communications-lab.md) |
| [🎬 Interface](#en-interface) | [⚙️ Configuration](#en-configuration) |
| [🚀 Quick start](#en-quick-start) | [📊 Example results](#en-results) |
| [🧪 First experiment](#en-first-experiment) | [🔧 Troubleshooting](#en-troubleshooting) |
| [📚 Documentation](#en-documentation) | [🤝 Contributing](#en-contributing) |

<a id="en-features"></a>

## ✨ Features

| Capability | What you can do |
| --- | --- |
| 🐳 Ocean UI | Layered ocean/lilac gradients and AI-generated 3D whale art for desktop, tablet and mobile. |
| 📡 Communication lab (v0.4.10) | 230 addable blocks and 121 presets: autonomous reception, continuous recordings, constrained design, classroom review, two-path merging and OFDM sensing. |
| 🔑 Model API setup | Choose a provider/model, enter a key and test/apply in the UI; optional per-session persistence. |
| 📄 PDF analysis reports (v0.4.10) | Preview and export Chinese brief/standard reports with vector plots, measured metrics, optional diagnosis and reproduction details. |
| 🩺 Diagnostic laboratory | Linked STFT and event timeline, six seeded fault types, blind challenge evaluation, and reversible evidence-based processing trials. |
| 💾 Experiment workbench | Create from templates, save, reopen, duplicate, search, rename or delete snapshots, and resume after a restart. |
| 📥 Data import wizard | Preview CSV/TXT, select time and signal columns, convert time units and locate invalid rows. |
| 🔍 Snapshot comparison | Overlay 2–4 saved results, compare parameters and metrics, and download a standalone HTML report. |
| ⏳ Tasks and storage | Inspect the queue, cancel work at safe checkpoints, unload idle sessions and clean unreferenced sample files after preview. |
| 📦 Data and reports | Export full-resolution CSV, standalone HTML reports, manifests and portable experiment ZIPs. |
| 🧮 Explainable comparison | Choose denoising, waveform or transient preservation; inspect score terms, parameters and timings. |
| 🎲 Reproducible simulation | Set sample rate, duration, frequency, noise, and random seed. |
| 🧹 Six preprocessing methods | Compare robust moving average, median, exponential smoothing, FFT low-pass, hybrid, and Kalman filtering. |
| 📈 Time and frequency analysis | Inspect statistics, FFT peaks, correlations, and spectral features. |
| 🔬 Random-process analysis | Explore AR models, Welch power spectra, and residuals. |
| 🤖 Agent mode | Compare methods and parameters automatically, inspect tool traces, and review recommendations. |
| 🎙️ Multiple inputs | Analyze simulated signals, CSV/TXT samples, or browser microphone audio; download processed audio. |

<a id="en-communications"></a>

## 📡 Communication-principles lab · Build a transmitter and receiver with blocks

Drag in blocks, edit their parameters, click **🔨 Build** to check the pipeline, then **▶️ Run** to inspect the transmission. Six block categories provide **230 addable blocks + a fixed sink and 121 presets**.

**🎲 Sources → 🔀 Transmit converters → 📡 Modulators → 🌊 Channels → 🎛️ Demodulators → 🔄 Receive converters → 📺 Sink**

| Module | Included techniques |
| --- | --- |
| 🎲 Sources | Random/custom bits, UTF-8 text, sine, square and Gaussian sources; PRBS7/9/15 m-sequences and correlation views. Audio, image, file and probabilistic byte sources. |
| 🔀 Transmit converters | Uniform/companded PCM, DPCM and delta modulation; repetition, Hamming, convolutional and LDPC coding, CRC, scrambling, interleaving and ten line codes. Huffman, ADPCM, BCH, RS, packetization, DSSS, SIMO training, Alamouti and MIMO spatial multiplexing. |
| 📡 Modulators | BPSK/QPSK/16QAM, OOK/2ASK, 2FSK, DBPSK/DQPSK, MSK/GMSK; AM/DSB-SC/SSB/VSB/FM/PM, PAM; real/complex pulse shaping, preambles, pilots and OFDM/IFFT/CP. |
| 🌊 Channels | AWGN, band limits, attenuation, phase shifts, erasures, AC coupling, ISI and clock/timing offsets; carrier offset, phase noise, unknown frame delay, complex multipath, Rayleigh/Rician fading, independent time-varying paths and Markov burst noise. Chip multipath, fixed/block-Rayleigh antenna matrices and independent receiver noise. |
| 🎛️ Demodulators | Paired demodulation and PSK/QAM LLRs; matched filtering, symbol/carrier/frame recovery, ZF/MMSE/DFE, real/complex LMS/NLMS/RLS, CMA, pilot LS and OFDM/FFT/frequency-domain equalization; AGC, estimated N0, rational resampling, T/2 FSE and OFDM CFO/pilot tracking. |
| 🔄 Receive converters | Line decoding, deinterleaving, descrambling, CRC checks, repetition/Hamming correction, hard/soft Viterbi, iterative LDPC and PCM/companding/DPCM/delta reconstruction. Huffman/ADPCM/BCH/RS decoding, reassembly, code acquisition, despreading, RAKE, SC/MRC, Alamouti and MIMO ZF/MMSE. |
| 📺 Sink | Received bits, text and analog waveforms, with source overlays, bit-error markers and full-sequence browsing. Audio playback, image reconstruction/PSNR and downloadable files with SHA256 comparison. |

- 🆕 **v0.4.10 autonomous reception:** MLSE, MUSIC-guided MVDR and 3GPP TDL-A/B/C; protected self-describing headers recover packet lengths, MCS and payload offsets directly from continuous I/Q recordings.
- 🔁 **v0.4.10 coding and feedback:** Turbo Log-MAP / Max-log BCJR, convolutional IR-HARQ and equal-budget Chase comparisons, with actual extrinsic messages, RV indices, mother-code coverage and resource counts.
- 🔬 **v0.4.10 experiments and teaching:** actual-run algorithm replay, measurement diagnostics and block timing, constrained two-parameter Pareto design, teacher batch review and frame-level event/recovery scenarios.
- 🔱 **v0.4.10 merging and sensing:** two receive paths share channel samples and merge symbols or LLRs; single-target OFDM sensing estimates range and velocity alongside communication decoding. Themed analysis pages retain the ocean design and project workflow.
- 🔍 **v0.4.9 advanced receivers:** LMMSE, Kalman, per-stream soft MIMO, Polar SC/CRC-SCL, angular array channels, MRT/SVD precoding and MVDR beamforming.
- 🌊 **v0.4.9 waveform and RF:** DFT-s-OFDM/SC-FDMA, memory polynomial PA and measured-loopback DPD, Schmidl–Cox/Zadoff–Chu burst synchronization and sampling-clock recovery.
- 🧰 **v0.4.9 experiments:** conditional breakpoints, durable batch/grid/search checkpoints, statistical plots and trial replay, staged student submissions, linked spatial views and configurable PDF reports.
- 🔁 **v0.4.8 closed-loop links:** run ARQ, Chase HARQ and AMC through your current block pipeline, measuring ACK/NACK, retries, soft combining, airtime and goodput.
- 🛰️ **v0.4.8 spatial communication:** ZF-SIC/MMSE-SIC, dynamic correlated MIMO and pilot tracking, MIMO-OFDM, independent-user OFDMA and FHSS; inspect antenna samples, stream constellations, channel matrices and SIC layers.
- 🧩 **v0.4.8 projects and teaching:** versioned subprojects with typed ports and public parameters, an assignment editor, multi-project seeded batches and minimum-SNR search; import SigMF/raw I/Q into receiver blocks and export recordings.
- 🎙️ **v0.4.7 business payloads:** audio, images, files and probabilistic sources; Huffman, IMA ADPCM, BCH, RS and packet assembly; playback, image reconstruction and SHA256 verification.
- 📡 **v0.4.7 spread spectrum and antennas:** DSSS, code acquisition, despreading, RAKE, SIMO SC/MRC, Alamouti 2×1 and 2×2 MIMO ZF/MMSE with correlation, path and pilot-estimation views.
- 🎓 **v0.4.7 teaching experiments:** shared formulas, 2D sweeps, algorithm traces, nine challenges, experiment differences and Python/JSON/SVG export; ARQ/HARQ and five-profile AMC feedback experiments.
- 🧭 **v0.4.6 layout and interaction:** compact controls, searchable experiments, parameter/receiver tabs, unified analysis, enlarged charts and mobile parameter drawers; explicit task, timestamp and parameter provenance.
- 🆕 **v0.4.5 RF and analysis:** 8PSK/64QAM/256QAM, I/Q/DC correction, Rapp/Saleh PA, ADC, OFDM clipping, tone interference/notch filtering and punctured convolutional coding; Welch/CCDF/ACLR, carrier EVM, resource grids, automatic alignment and seven guided comparisons.
- 🧰 **Block programming experience:** search/favorites, typed connections and receiver completion, real stepping, linked scopes, named projects and snapshots, reusable composite blocks, shared-channel branches, resumable generic sweeps, stateful frames and Chinese PDF reports.
- 🧩 **Build and edit:** an ocean-themed palette, compact connected blocks and a parameter inspector; drag/drop, reordering, undo/redo, draft recovery and project JSON import/export.
- 📈 **Inspect and save:** processing-stage waveforms, preamble correlation, OFDM grids, eyes and recovery traces; seeded BER/SER/FER sweeps, Eb/N₀ calibration, 95% intervals, curve comparisons and full JSON/CSV export.

![🧩 Communication lab: palette, pipeline, sink and parameter inspector](docs/images/communications-studio.png)

![🌊 v0.4.10 autonomous reception and experiment analysis](docs/images/communications-v0410.png)

📘 [v0.4.10 guide](工程文件/代码/docs/communications-v0410.md)

📘 [v0.4.9 advanced transceivers and debugging guide](工程文件/代码/docs/communications-v049.md) · [v0.4.8 closed-loop and spatial communication guide](工程文件/代码/docs/communications-v048.md)

📘 [v0.4.7 business and teaching guide](工程文件/代码/docs/communications-v047.md)

📘 [v0.4.5 RF and measurement guide](工程文件/代码/docs/communications-v045.md)

![🌊 v0.4.5 RF instruments](docs/images/communications-v045-analysis.png)


🆕 [v0.4.4 algorithms and experiments](工程文件/代码/docs/communications-v044.md)

![🌊 v0.4.4 ocean block studio](docs/images/communications-v044-studio.png)

📚 [Lab guide](工程文件/代码/docs/communications-lab.md) · [Analog modulation](工程文件/代码/docs/analog-modulation.md) · [Line codes and channels](工程文件/代码/docs/baseband-coding.md) · [Timing and equalization](工程文件/代码/docs/receiver-recovery.md)

<a id="en-interface"></a>

## 🎬 Interface

v0.3.4 uses cyan, lavender and coral-pink gradients, 4 px outer borders and 2 px inner borders. Chinese text uses STZhongsong when installed; Latin text and numbers use Times New Roman. A larger, bold clock sits above the local-computing badge. Agent method comparisons separate conclusions, recommended metrics and next steps. Switching between the six views preserves inputs and experiment state.

These captures show v0.3.4, including the visual update shipped in its deployment ZIP. Fonts are loaded from the visitor’s computer, with serif fallbacks when unavailable.

![v0.3.4 ocean workspace: Agent analysis, waveform and spectrum](docs/images/ocean-ui-v034.png)

<details>
<summary><strong>Explore templates, diagnostics and API setup</strong></summary>

**Templates and experiments**: compare six methods, save named snapshots and import/export full experiment packages.

![v0.3.4 templates and experiments](docs/images/workbench-v034.png)

**Diagnostic laboratory**: inspect linked time-frequency and waveform plots, locate events and verify processing trials.

![v0.3.4 diagnostic laboratory with linked plots](docs/images/diagnostics-v034.png)

**Models and settings**: choose your provider, model and persistence options in the browser.

![v0.3.4 model API setup form](docs/images/model-api-v034.png)

</details>

<details>
<summary><strong>Watch the ocean walkthrough (v0.3.0)</strong></summary>

Agent acquisition and analysis → save a snapshot → inspect fault diagnostics → open model settings. The walkthrough uses the local signal tools.

![v0.3.0 ocean interface walkthrough](docs/images/ocean-demo-v030.gif)

</details>

## 📄 Export a PDF analysis report

After collecting or restoring an experiment, open **模板与实验 → PDF 分析报告 (Templates & Experiments → PDF report)**. Set the title, author, purpose, units and brief/standard edition. Select **预览摘要与章节** to review the summary, then **下载 PDF** to download.

Reports currently use Chinese. Standard reports include waveform metrics, FFT, Welch PSD, autocorrelation, existing method comparisons/diagnostics and reproduction details; brief reports focus on the overview, key metrics, waveform and FFT. Narrative statements use the measured data and require no model key. True SNR/RMSE need a clean reference, and blind experiments must be revealed first.

![v0.3.1 PDF preview and download](docs/images/pdf-report-v031.png)

[Example PDF](docs/report-example.pdf) · [Report guide (Chinese)](工程文件/代码/docs/pdf-report.md)

**New in v0.3.2:** Select up to 50 recent processing results, optionally include saved snapshots, and arrange them chronologically. Export one PDF with a shared cover, summary, clickable contents and plots for every group. History survives server restarts; older unsaved results cannot be recovered.

<a id="en-quick-start"></a>

## 🚀 Quick start

Use **Python 3.12–3.14** or **Docker Compose v2**. v0.4.10 uses FastAPI; deployment checks cover Python 3.12–3.14 on Windows and Linux, plus Docker on Linux.

### 1. Get the project

Download the v0.4.10 [deployment ZIP](https://github.com/PatrickStar-cmd/random-signal-agent/releases/download/v0.4.10/random-signal-agent-v0.4.10-deploy.zip) and extract it, then open a terminal in `工程文件/代码` inside the extracted folder.

Or clone the repository:

```bash
git clone https://github.com/PatrickStar-cmd/random-signal-agent.git
cd "random-signal-agent/工程文件/代码"
```

### 2. Install and start

**Windows PowerShell** — use Python 3.12–3.14:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-repro.txt
.\.venv\Scripts\python.exe server.py --host 127.0.0.1 --port 8000
```

**Linux / macOS**

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-repro.txt
.venv/bin/python server.py --host 127.0.0.1 --port 8000
```

<details>
<summary><strong>Run with Docker instead</strong></summary>

From the same `工程文件/代码` directory:

```bash
cp .env.example .env
docker compose up -d --build --wait --wait-timeout 120
```

On Windows, replace the first command with `Copy-Item .env.example .env`. Uploads and generated outputs persist in local folders. Use `docker compose logs --tail 100` to inspect the service and `docker compose down` to stop it.

</details>

### 3. Open the application

Visit **<http://127.0.0.1:8000>**. Simulation, filtering, and analysis are available without configuring an external model.

The [online preview](https://patrickstar-cmd.github.io/random-signal-agent/) shows the saved experiment and interface captures. Interactive experiments run with the Python backend.

<a id="en-first-experiment"></a>

## 🧪 Your first experiment

1. Open **信号工作区 (Workspace)**. Enable **Agent mode** to compare six preprocessing methods automatically, then enter this command. The local command parser supports Chinese:

   > 采集一段 8 秒、采样率 200Hz、主频 8Hz 的正弦信号加高斯噪声，随机种子 42

   This creates an 8-second sine signal with Gaussian noise at 200 Hz, with an 8 Hz target frequency and seed 42.

2. Inspect the waveform, spectrum and statistics. In command mode, continue with:

   > 使用滑动平均预处理并分析时域和频域特征

   This applies a moving average and analyzes time/frequency features.

3. Open **模板与实验 (Templates)**, enter a name and save a snapshot. Export an experiment ZIP to restore full samples, results and tool records later. Successful operations automatically save the current experiment. After running or restoring, comparisons reuse current data; select another template to generate a new signal.
4. For your own data, open **导入数据 (Import)** and upload UTF-8 CSV/TXT. Select the time/signal columns and time unit, or enter a sample rate when no time column exists. Confirm the preview, then compare and save results in Templates.
5. Open **对比与报告 (Comparison)**, select 2–4 snapshots and inspect overlays and metrics or download an HTML report. Scores are directly comparable only when inputs, references, goals and scoring versions match.

For anomaly detection, save your current experiment before loading the fault demo in **诊断实验室 (Diagnostics)**. Inspect evidence, select an interval and verify a processing trial. Adopt a result and save it as a snapshot. Blind mode hides truth and reference error until reveal and restricts full experiment export and comparisons; the diagnostic report remains available.

External models are optional. Open **模型与设置 → 模型 API 配置 (Settings → Model API)**; see Configuration below.

Keep the same parameters and seed to reproduce simulated samples. The import wizard selects one signal from multicolumn data. Quick upload reads a single value column or the first two columns as time in seconds and values; see the [data guide](docs/README.en.md).

<a id="en-workflow"></a>

## 🏗️ How it works

```mermaid
flowchart TD
    UI["Web chat / Agent mode"] --> Agent["Dialogue and tool routing"]
    Model["Optional model API"] -.-> Agent
    Agent --> Input["Simulation / CSV / microphone"]
    Input --> Filter["Preprocessing and method comparison"]
    Filter --> Analysis["Time / frequency / random-process analysis"]
    Analysis --> Results["Plots, metrics, tool traces, and recommendations"]
```

| Component | Responsibility |
| --- | --- |
| `web/chat.html` + `server.py` | Web interface, uploads, HTTP endpoints, and streamed responses. |
| `src/dialogue_agent.py` | Interpret tasks and coordinate the signal tools. |
| `src/acquisition.py` | Acquire simulated signals, uploaded samples, and audio. |
| `src/preprocessing.py` | Filter signals and compare candidate methods. |
| `src/analysis.py` + `src/advanced_analysis.py` | Calculate time, frequency, and random-process features. |
| `src/llm_client.py` | Connect to an optional Chat Completions-compatible service. |

All component paths are relative to `工程文件/代码`.

<a id="en-configuration"></a>

## ⚙️ Configuration

The local toolchain is the default. To connect an external model, open **模型与设置 → 模型 API 配置 (Settings → Model API)**:

1. Choose OpenAI, DeepSeek or a custom Chat Completions-compatible provider and enter its key.
2. Load the model list and select a model, or enter the exact model ID manually.
3. Choose **测试并应用 (Test and apply)**. The current browser session updates immediately without restarting; you can switch back to local tools or remove the configuration.

Keys stay in server memory by default. Opting into restart persistence stores them in plaintext in `data/model-settings.sqlite3`. Browser storage, experiment ZIPs and task history contain no keys. See the [model setup guide](工程文件/代码/docs/model-api-setup.md) for compatibility, persistence and advanced parameters.

<details>
<summary><strong>Server defaults and startup scripts</strong></summary>

Administrators can copy `config/server.env.example` to `config/server.env` to set service-wide defaults. Per-session configuration takes precedence.

| Setting | Purpose |
| --- | --- |
| `RS_AGENT_HOST` / `RS_AGENT_PORT` | Server bind address and port; use `127.0.0.1` for local access. |
| `RS_AGENT_LLM_BASE_URL` | Model API base URL, such as `https://your-provider.example.com/v1`. |
| `RS_AGENT_LLM_MODEL` | Model identifier accepted by your provider. |
| `RS_AGENT_LLM_API_KEY` | Your provider's API key. |
| `RS_AGENT_LLM_TIMEOUT` | Model request timeout in seconds; default: `45`. |
| `RS_AGENT_LOG_FILE` | Startup-script log path; default: `logs/server/server.log`. |

After activating the virtual environment, use `scripts/start_server.ps1` on Windows or `bash scripts/start_server.sh` on Linux/macOS to load this file. Directly running `server.py` does not load `config/server.env`.

Docker Compose reads `.env` in the code directory. See the [deployment guide](工程文件/代码/DEPLOY.md) for Docker settings, HTTPS hosting, and service management.

</details>

<a id="en-results"></a>

## 📊 Reproducible example

The saved showcase uses a random process with mixed noise: **200 Hz**, **8 seconds**, **1,600 samples**, an **8 Hz** target frequency, and **seed 42**. A robust moving average uses a 7-sample window.

| Metric | Result |
| --- | ---: |
| Detected dominant frequency | 8.000 Hz |
| Original SNR | 2.859 dB |
| Processed SNR | 4.781 dB |
| SNR improvement | 1.922 dB |

Results depend on the input signal and filter parameters.

[Sample CSV](docs/data/sample.csv) · [Analysis results](docs/data/result.json) · [Experiment configuration](工程文件/代码/config/showcase.json) · [Reproduction guide](docs/README.en.md)

<details>
<summary><strong>Check your deployment</strong></summary>

With the application running, open another terminal in `工程文件/代码` and use the same Python environment:

```powershell
# Windows
.\.venv\Scripts\python.exe scripts/smoke_deployment.py --base-url http://127.0.0.1:8000
```

```bash
# Linux / macOS
.venv/bin/python scripts/smoke_deployment.py --base-url http://127.0.0.1:8000
```

The check covers the application version, ocean assets, model settings API, Agent mode, streaming, import/export, diagnostics and PDF download. Its result is written to `logs/deployment/latest.log`. Release assets also include `SHA256SUMS.txt` and `verification.json`.

</details>

<a id="en-troubleshooting"></a>

## 🔧 Troubleshooting

| Question | Answer |
| --- | --- |
| Why does the online preview not run new experiments? | GitHub Pages serves the saved showcase. Start the backend locally or deploy it with Docker for interactive use. |
| Do I need an API key? | The local signal tools do not require one. Model-assisted dialogue is optional. |
| Which Python versions work? | v0.4.10 supports Python 3.12, 3.13 and 3.14. |
| Why can I not activate the virtual environment on Windows? | The quick-start commands call `.venv\Scripts\python.exe` directly and do not require activation. |
| Why is the microphone unavailable? | Open the app on localhost or HTTPS and allow microphone access in the browser. |
| Why does my uploaded signal have no SNR value? | Reference-based SNR requires a clean signal. Uploaded samples and microphone audio do not provide that reference. |
| What if port 8000 is occupied? | Start with `--port 8001`, then open `http://127.0.0.1:8001`; update the smoke-check URL too. |

<a id="en-documentation"></a>

## 📚 Documentation

| Guide | Contents |
| --- | --- |
| [PDF report guide](工程文件/代码/docs/pdf-report.md) | Report options, preview, sections and measured evidence (Chinese). |
| [Model API setup](工程文件/代码/docs/model-api-setup.md) | Browser configuration, key persistence and compatibility. |
| [UI guide](工程文件/代码/docs/ui-design.md) | Six-view navigation, responsive layout and controls. |
| [Installation & release](RELEASE.md) | Deployment ZIP, platform commands, and checksums. |
| [Experiment guide](docs/README.en.md) | Saved data, parameters, file formats, and reproduction. |
| [Code overview](工程文件/代码/README.md) | Modules and model configuration. |
| [Communication lab](工程文件/代码/docs/communications-lab.md) | Block pipelines, Build/Run, metrics, exports and baseband model (Chinese). |
| [Running & configuration](工程文件/代码/docs/exec.md) | Commands, settings, and logs. |
| [Features & validation](工程文件/代码/docs/review.md) | Implemented capabilities, checks, and current limits. |
| [Algorithm principles](工程文件/代码/docs/principle.md) | Signal-processing methods and analysis. |
| [Deployment](工程文件/代码/DEPLOY.md) | Docker, HTTPS, systemd, and health checks. |
| [Changelog](CHANGELOG.md) | Release history. |

The code and algorithm guides are in Chinese.

<a id="en-contributing"></a>

## 🤝 Contributing

Issues and pull requests are welcome for bug fixes, signal-processing methods, experiment examples, and documentation. For a bug report, include your Python version, input parameters, steps to reproduce, and relevant logs. For an algorithm change, include a reproducible signal and a before/after comparison.

[Open an issue](https://github.com/PatrickStar-cmd/random-signal-agent/issues) · [View pull requests](https://github.com/PatrickStar-cmd/random-signal-agent/pulls)

## 📄 License

Licensed under the [MIT License](LICENSE). Retain the license and copyright notice when using, modifying, or distributing the project. Third-party dependencies and assets retain their respective licenses.

</div>

</details>
