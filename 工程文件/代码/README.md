# 随机信号智能体

本项目是面向“随机信号”课程的可复现智能体系统。系统通过 Web 对话界面接收任务，调用本地信号采集、预处理、时域分析、频域分析、随机过程分析和结果解释工具，完成随机信号处理实验。

## 功能概览

- 仿真随机信号采集：支持指定采样率、时长、主频、噪声强度和随机种子。
- 文件上传分析：支持单列采样值或“时间,采样值”双列 CSV/TXT。
- 麦克风网关：浏览器端采集音频后上传至后端做降噪和特征分析。
- 预处理工具链：滑动平均、中值滤波、鲁棒异常点抑制、去均值等。
- 时频域分析：均值、方差、RMS、自相关、功率谱、主频、谱带宽、谱熵等。
- Agent 模式：自动比较预处理方法并输出工具调用轨迹、风险等级和控制建议。
- 外部模型增强：可接入任意 OpenAI 兼容 Chat Completions API；不配置 API 时仍可使用本地规则工具链。

## 快速运行

1. 安装 Python 3.10–3.12，推荐 3.12。当前后端使用 `cgi`，不支持 Python 3.13 及以上版本。

2. 安装依赖：

```powershell
pip install -r requirements.txt
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

v0.3.2 可在“模板与实验 → PDF 分析报告”生成当前实验或最近 50 次处理结果的中文报告。选择处理历史与已保存实验，排序并预览后下载；统一封面、汇总表、可跳转目录与逐组矢量图表，完整采样计算指标，详见 [使用说明](docs/pdf-report.md)。
