# 随机信号智能体

本项目是面向“随机信号”课程的可复现智能体系统。系统通过 Web 对话界面接收任务，调用本地信号采集、预处理、时域分析、频域分析、随机过程分析和结果解释工具，完成随机信号处理实验。

## 通信原理仿真实验室（v0.4.1）

打开“通信实验室”拖拽信源、编码、调制、信道与接收积木，先 Build 再 Run，右侧展示信宿输出、误码率和星座。空白工程默认固定信宿与电视雪花屏。支持数字、模拟 + PCM 和文字示例、工程 JSON 与完整信宿 CSV 导出，无需模型 Key。v0.4.1 部署 ZIP 已包含此功能。

v0.4.1「传输环节模块补充」增加 AM/DSB-SC/SSB/VSB/FM/PM、十对线路编译码、PAM/成形与基带信道、自动符号同步、固定/自适应线性及 DFE，合计 29 个示例。观察波形、频谱、眼图、时钟与均衡收敛。使用与接口见 [通信指南](docs/communications-lab.md)，参数和原理见 [模拟调制](docs/analog-modulation.md)、[线路码与信道](docs/baseband-coding.md)、[同步与均衡](docs/receiver-recovery.md)。

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
