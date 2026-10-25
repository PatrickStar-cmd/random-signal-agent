# 随机信号智能体

本项目面向“随机信号”与“通信原理”课程，通过 Web 工作区完成 💬 对话式信号分析与 🧩 积木式通信实验。支持本地计算、固定种子复现和可选模型辅助对话。

## 📡 通信原理实验室（v0.4.8）

六类积木提供 **193 个可添加模块 + 固定信宿、90 个示例**。拖入模块、选中编辑参数，先 **🔨 Build**，再 **▶️ Run**。

| 模块 | 包含的技术 |
| --- | --- |
| 🎲 信源 | 随机/自定义比特、UTF-8 文本、正弦、方波、高斯信号；新增 PRBS7/9/15 m 序列与相关观察。音频、图像、文件、离散概率信源与 SigMF / 原始 I/Q 录波。 |
| 🔀 发转换器 | 均匀/压扩 PCM、DPCM、增量调制；重复码、Hamming、卷积码、LDPC、CRC、扰码与交织；十种线路编码。Huffman、ADPCM、BCH、RS、分包；DSSS、SIMO 训练、Alamouti 与 MIMO 空间复用。 |
| 📡 调制器 | BPSK/QPSK/16QAM、OOK/2ASK、2FSK、DBPSK/DQPSK、MSK/GMSK；AM/DSB-SC/SSB/VSB/FM/PM、PAM；实/复基带成形、前导与导频、OFDM/IFFT/CP。 |
| 🌊 信道 | 白噪声、带限、衰减、相移、丢失、交流耦合、ISI、定时/时钟漂移；新增频偏、相位噪声、未知帧延迟、复多径、Rayleigh/Rician 衰落、独立时变路径与 Markov 突发噪声。扩频码片多径、多天线固定/块 Rayleigh 信道与独立接收噪声；移动相关 MIMO、频率选择性 MIMO 与 OFDMA 独立用户信道。 |
| 🎛️ 解调器 | 各制式配对解调与 PSK/QAM 软解调；匹配滤波、符号/载波/帧同步，ZF/MMSE/DFE、实/复 LMS/NLMS/RLS、CMA、导频 LS、OFDM/FFT/频域均衡；新增 AGC、自动 N0、重采样、T/2 均衡、OFDM 频偏与导频跟踪。 |
| 🔄 收转换器 | 线路译码、解交织、解扰、CRC 校验、重复码/Hamming 纠错、硬/软 Viterbi、LDPC 迭代，以及 PCM/压扩/DPCM/增量重构。Huffman/ADPCM/BCH/RS 译码、组包；码捕获、解扩、RAKE、SC/MRC、Alamouti、MIMO ZF/MMSE、ZF-SIC/MMSE-SIC、周期导频跟踪、MIMO-OFDM、OFDMA 分用户恢复与 FHSS 解跳。 |
| 📺 信宿 | 显示接收比特、文本与模拟波形，支持叠加原始信源、标记错误位和浏览完整接收序列。音频播放、图像重建与 PSNR、文件下载和 SHA256 核验。 |

- 🔁 **v0.4.8 闭环链路**：当前积木工程直接执行 ARQ、Chase HARQ 和 AMC；统计实际 ACK/NACK、重传、软合并、空口时长与吞吐。
- 🛰️ **v0.4.8 空间通信**：ZF-SIC/MMSE-SIC、动态相关 MIMO 与导频跟踪、MIMO-OFDM、独立用户 OFDMA、FHSS；观察天线波形、空间流星座、矩阵与逐层消除。
- 🧩 **v0.4.8 工程与教学**：带类型端口和公开参数的版本化子工程、教学任务编辑器、跨工程多种子队列、最低信噪比搜索；导入 SigMF/原始 I/Q，连接接收积木回放并导出录波。

🧩 沿用海洋风格积木工坊、拼接链路与参数面板；保留拖放排序、撤销重做、草稿恢复、工程快照、逐块调试、分支对照、参数扫描、连续多帧和 PDF 报告。

📚 [v0.4.8 闭环与空间通信指南](docs/communications-v048.md) · [通信指南](docs/communications-lab.md) · [业务与教学](docs/communications-v047.md) · [射频与测量](docs/communications-v045.md)

## 功能概览

- 仿真随机信号采集：支持指定采样率、时长、主频、噪声强度和随机种子。
- 文件上传分析：支持单列采样值或“时间,采样值”双列 CSV/TXT。
- 麦克风网关：浏览器端采集音频后上传至后端做降噪和特征分析。
- 预处理工具链：滑动平均、中值滤波、鲁棒异常点抑制、去均值等。
- 时频域分析：均值、方差、RMS、自相关、功率谱、主频、谱带宽、谱熵等。
- Agent 模式：自动比较预处理方法并输出工具调用轨迹、风险等级和控制建议。
- 外部模型增强：可接入任意 OpenAI 兼容 Chat Completions API；不配置 API 时仍可使用本地规则工具链。

## 快速运行

1. 安装 Python 3.12–3.14。后端使用 FastAPI；完整安装步骤见仓库根目录 [README](../../README.md)。

2. 安装依赖：

```powershell
pip install -r requirements-repro.txt
```

3. 本地启动：

```powershell
python .\server.py --host 127.0.0.1 --port 8000
```

4. 浏览器访问：

```text
http://127.0.0.1:8000
```

## 配置外部 API

复制配置模板：

```powershell
Copy-Item .\config\server.env.example .\config\server.env
```

编辑 `config/server.env`，填写自己的 OpenAI 兼容 API 信息：

```text
RS_AGENT_LLM_BASE_URL=在此填写外部模型 API Base URL，例如 https://your-provider.example.com/v1
RS_AGENT_LLM_MODEL=在此填写模型名称
RS_AGENT_LLM_API_KEY=在此填写 API Key
```

然后用脚本启动：

```powershell
.\scripts\start_server.ps1
```

Linux/macOS：

```bash
cp config/server.env.example config/server.env
vim config/server.env
bash scripts/start_server.sh
```

## 项目结构

```text
.
  server.py                         # HTTP/SSE 后端入口
  web/chat.html                     # 智能体控制台前端
  src/
    dialogue_agent.py               # 对话智能体和工具调度核心
    llm_client.py                   # OpenAI 兼容 API 客户端
    acquisition.py                  # 仿真、文件、实时/麦克风采集
    preprocessing.py                # 预处理算法
    analysis.py                     # 基础时频域分析
    advanced_analysis.py            # 随机过程扩展分析
    signal_processing.py            # 信号生成与处理函数
  config/server.env.example         # 环境变量模板
  scripts/start_server.ps1          # Windows 启动脚本
  scripts/start_server.sh           # Linux/macOS 启动脚本
  scripts/random-signal-agent.service.example
  DEPLOY.md                         # 部署说明
```

复现检查及限制见 [docs/review.md](docs/review.md)，完整运行步骤和配置说明见 [docs/exec.md](docs/exec.md)，算法原理见 [docs/principle.md](docs/principle.md)。

原配置教程见 `../配置文档/随机信号智能体配置教程.pdf`。PDF 中的 Python 版本和 systemd 解释器路径以当前 Markdown 文档及脚本为准。

## PDF 报告

v0.3.3 可在“模板与实验 → PDF 分析报告”生成当前实验或最近 50 次处理结果的中文报告。选择处理历史与已保存实验，排序并预览后下载；统一封面、汇总表、可跳转目录与逐组矢量图表，完整采样计算指标，详见 [使用说明](docs/pdf-report.md)。

🆕 [v0.4.4 工程、单步调试、组合积木、共享分支与扫描续跑](docs/communications-v044.md)。新增中间波形、相关峰、OFDM 网格与 BER/SER/FER 多曲线比较。
