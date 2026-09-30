# 代码执行与日志阅读

以下命令均在包含 `server.py` 的“代码”目录执行，先激活 Python 3.12 虚拟环境。

## 安装与验证

```bash
python -m pip install -r requirements-repro.txt
python -m pip check
python scripts/verify_reproduction.py
python scripts/test_regressions.py
```

验证脚本不调用外部模型，自动启动临时本地 HTTP 服务并关闭，输出测试结果到终端和 `logs/verification/latest.log`，每次覆盖。Python 3.10/3.11 如需安装可用 `requirements.txt`，本次未在这两个版本运行测试。

`test_regressions.py` 验证异常输入等边界行为，使用临时文件和本地 HTTP 服务，不调用外部模型；日志覆盖写入 `logs/regression/latest.log`。

## 运行入口

| 功能 | 命令或步骤 |
| --- | --- |
| Web 服务 | `python server.py --host 127.0.0.1 --port 8000` |
| Windows 配置启动 | `./scripts/start_server.ps1 -HostName 127.0.0.1 -Port 8000` |
| Linux/macOS 配置启动 | `bash scripts/start_server.sh` |
| 固定演示与报告 | `python run_demo.py` |
| 历史批处理入口 | `start_agent.bat`，端口为 **8001**，不加载配置文件，仅继承终端环境变量 |
| 仿真分析 | 页面输入采集请求，固定“随机种子 42”，然后选择预处理及分析，或开启 Agent 模式 |
| 文件分析 | 页面上传单列 CSV/TXT；双列时第一列时间（秒）、第二列采样值。无时间列需填写采样率 |
| 麦克风 | 在 localhost 或 HTTPS 页面授权麦克风，采集后提交；默认可输出 WAV，MP3 需 FFmpeg |
| 容器/systemd | 见 `../DEPLOY.md`；systemd 模板中虚拟环境路径须与实际安装一致 |

直接运行 `server.py` 不自动加载 `.env` 或 `config/server.env`，只读取已有进程环境。需要配置文件时使用启动脚本。脚本的 `python` 来自 PATH，先激活虚拟环境；Windows 如受执行策略限制，也可直接使用 `.venv/Scripts/python.exe` 启动服务器。

## 配置参数

复制 `config/server.env.example` 为 `config/server.env` 并填写。Shell 配置值有空格时需正确引用，建议 URL、模型名和密钥均不含空格；不要把说明文字填成实际值。

| 参数 | 含义及默认值 |
| --- | --- |
| `RS_AGENT_HOST` | 脚本监听地址，默认 `0.0.0.0`；本机推荐 `127.0.0.1` |
| `RS_AGENT_PORT` | 脚本监听端口，默认 8000 |
| `RS_AGENT_LLM_BASE_URL` | 兼容模型 API 根地址，客户端追加 `/chat/completions` |
| `RS_AGENT_LLM_MODEL` | 供应商支持的模型名 |
| `RS_AGENT_LLM_API_KEY` | 使用者自己的密钥；仅保存于被忽略的私有配置 |
| `RS_AGENT_LLM_TIMEOUT` | 模型请求超时秒数，默认 45 |
| `RS_AGENT_LOG_FILE` | 启动脚本日志路径，默认 `logs/server/server.log` |
| `RS_AGENT_LLM_ENABLED` | 可选；`0/false/off/no` 禁用模型，否则自动检查三项配置 |

模型地址、密钥、模型名为空时会尝试 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`。需要强制离线时设置 `RS_AGENT_LLM_ENABLED=0`。Docker 使用 `.env.example` 复制出的 `.env`，其中四个 LLM 参数由 Compose 传入容器。Compose 端口目前固定为 8000。

PowerShell 脚本参数 `-ConfigPath` 指定配置文件（默认 `config/server.env`），`-HostName`、`-Port` 覆盖监听设置；Bash 使用 `CONFIG_PATH` 环境变量更换配置文件。直接运行服务的 `--host` 和 `--port` 默认是 `0.0.0.0`、8000。

## 结果与日志

演示结果在 `outputs/`：`analysis_result.json` 为指标、决策和轨迹；`signal_samples.csv` 为完整样本；`demo.html` 为可视化；`design_report.md` 为报告。麦克风音频在 `outputs/audio/`，上传文件在 `uploads/`。这些运行数据均不提交 Git。

启动脚本日志在 `logs/server/server.log`，每次启动覆盖；直接运行命令查看终端输出，HTTP 访问日志在代码中被关闭。systemd 使用 `journalctl -u random-signal-agent.service`；Docker 使用 `docker compose logs`。验证日志在 `logs/verification/latest.log`，结尾 `OK` 表示通过，`FAIL/ERROR` 后的回溯指出失败原因。

健康检查访问 `/api/health`。`status=ok` 说明服务可响应；`llm.configured=true` 只说明配置齐全，不说明外部服务实际可用。
