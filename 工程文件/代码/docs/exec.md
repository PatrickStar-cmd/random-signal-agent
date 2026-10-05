# 代码执行与日志阅读

以下命令均在包含 `server.py` 的“代码”目录执行，先激活 Python 3.12–3.14 虚拟环境。

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

配置值可使用匹配的外层单引号或双引号，Windows 脚本去掉外层引号后保留值内部的空格、等号及 `$`，不执行变量展开。Bash 启动脚本按 Shell 规则读取配置；跨平台保留包含 `$` 的字面值时使用单引号。例如 `RS_AGENT_PORT="8123"` 和 `RS_AGENT_LLM_MODEL='demo model'` 都能由 Windows 脚本读取。

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

模型地址、密钥、模型名为空时会尝试 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`。需要强制离线时设置 `RS_AGENT_LLM_ENABLED=0`。Docker 使用 `.env.example` 复制出的 `.env`，LLM 参数由 Compose 传入容器。`RS_AGENT_BIND_ADDRESS` 控制宿主绑定地址，默认 `127.0.0.1`；`RS_AGENT_PORT` 控制宿主端口，默认 8000，容器端口固定为 8000。

PowerShell 脚本参数 `-ConfigPath` 指定配置文件（默认 `config/server.env`），`-HostName`、`-Port` 覆盖监听设置；Bash 使用 `CONFIG_PATH` 环境变量更换配置文件。直接运行服务的 `--host` 和 `--port` 默认是 `0.0.0.0`、8000。

## 结果与日志

### 发布包与部署检查

提交所有修改后执行 `python scripts/build_release.py`。默认打包 HEAD，`--ref` 可指定版本或提交，`--output-dir` 可指定输出目录；默认产物在 `outputs/release/`，日志覆盖写入 `logs/release/build.log`。

`config/release.json` 的 `version` 为数字版本号（0.2.0），`name` 为产物前缀（random-signal-agent），`runtime_path` 为包内代码目录（工程文件/代码），`python` 为推荐 Python 版本（3.12）。ZIP 保留完整仓库结构，附加 `RELEASE.json` 记录源码提交。

执行 `python scripts/verify_release.py --archive outputs/release/random-signal-agent-v0.2.0-deploy.zip`，从包中新建干净环境，安装依赖并检查实际启动；Windows 用 PowerShell 启动脚本，Linux 用 Bash。检查完成清理临时目录，报告写入 `outputs/release/verification-<系统>.json`，日志位于 `logs/release/latest.log` 与 `server.log`。Linux 跳过仅适用于 Windows 的启动配置回归用例。

运行中的服务使用 `python scripts/smoke_deployment.py --base-url http://127.0.0.1:8000` 验收，会创建独立测试会话和少量合成上传/音频数据。检查参数位于 `config/deployment-check.json`：`startup_timeout` 是服务就绪等待秒数（60），`request_timeout` 是单次请求超时秒数（60），`sample_rate` 为测试采样率（200 Hz），`duration` 为仿真时长（2 秒），`frequency` 为目标主频（8 Hz），`seed` 为随机种子（42）。日志覆盖写入 `logs/deployment/latest.log`。

部署 CI 对 Windows、Linux 解压包和 Linux Docker Compose 执行上述检查。Docker 启动时等待容器健康检查，并验证真实 HTTP 接口与锁定依赖；运行日志可从 Actions 工件下载。

### 静态演示生成

在代码目录执行 `python scripts/build_showcase.py`。脚本调用现有采集、预处理、分析和决策工具链，生成仓库根目录 `docs/index.html`、`docs/data/sample.csv`、`reference.csv` 和 `result.json`；这些公开固定样本作为展示材料提交 Git。日志覆盖写入 `logs/showcase/latest.log`。

`config/showcase.json` 配置参数：

| 参数 | 含义与当前值 |
| --- | --- |
| `sample_rate` | 每秒采样数，200 Hz |
| `duration` | 采集时间，8 秒 |
| `base_frequency` | 参考主频，8 Hz |
| `amplitude` | 参考信号幅值，1.2 |
| `noise_std` | 高斯噪声标准差，0.55 |
| `ar_coefficient` | 有色噪声的 AR 系数，0.86 |
| `impulse_probability` | 每个样本产生脉冲的概率，0.012 |
| `seed` | 随机种子，42 |

未覆盖的 `SignalConfig` 默认字段为 `signal_model=random_process`、`waveform=random_process`、`noise_model=mixed`。预处理比较使用各方法默认参数，窗口 7 点、异常阈值 3σ；完整参数记录于结果 JSON。Web Agent 自动搜索参数，所以不能直接与固定参数比较等同。

GitHub Pages 从 `main` 分支 `/docs` 发布；生成结果后提交该目录更新。具体步骤见仓库根目录 [docs/README.md](../../../docs/README.md)。

演示结果在 `outputs/`：`analysis_result.json` 为指标、决策和轨迹；`signal_samples.csv` 为完整样本；`demo.html` 为可视化；`design_report.md` 为报告。麦克风音频在 `outputs/audio/`，上传文件在 `uploads/`。这些运行数据均不提交 Git。

启动脚本日志在 `logs/server/server.log`，每次启动覆盖；直接运行命令查看终端输出，HTTP 访问日志在代码中被关闭。systemd 使用 `journalctl -u random-signal-agent.service`；Docker 使用 `docker compose logs`。验证日志在 `logs/verification/latest.log`，结尾 `OK` 表示通过，`FAIL/ERROR` 后的回溯指出失败原因。

健康检查访问 `/api/health`。`status=ok` 说明服务可响应；`llm.configured=true` 只说明配置齐全，不说明外部服务实际可用。

## v0.2.0 工作台与验证

启动后在页面顶部选择模板和目标、设置采样率/时长/基频/幅值/噪声/种子/AR 系数/脉冲概率，运行比较。命名并“保存为新快照”产生独立实验；“打开”恢复选中实验，“复制”保留原件并生成副本。每次成功操作还会自动保存当前会话。ZIP 可移到另一个浏览器或兼容算法版本的服务导入，CSV 保留每个采样点。HTML 无需后端即可打开。

```bash
python -m pip install -r requirements-test.txt
python scripts/test_regressions.py
python scripts/verify_reproduction.py
python scripts/test_workbench.py
python scripts/test_studio.py
python scripts/benchmark_algorithms.py
```

日志分别位于 `logs/regression/latest.log`、`logs/verification/latest.log`、`logs/workbench/latest.log`、`logs/benchmark/latest.log`，每次覆盖。基准详细数据在 `outputs/benchmark/baseline.csv`，汇总在 `summary.json`。SciPy 仅用于数值验证，实际服务不依赖它。

`config/workbench.json` 字段：`max_samples` 为每条信号的最大点数；`request_bytes` 为普通 JSON/上传请求最大实际字节数；`experiment_package_bytes` 为实验导入大小及解压总量上限；`workers` 为工作线程数；`task_capacity` 为运行与排队任务合计上限；`session_capacity` 为单次服务进程允许载入的会话数；`candidates_per_method` 为单方法搜索候选上限；`candidate_sample_budget` 为候选数与信号点数的乘积预算（至少保留一组）。修改后重启。采样数上限不是运行时长保证。

`config/benchmark.json` 中 `waveforms` 指定信号类别，`sample_rates` 指定采样率，`noise_levels` 指定高斯噪声标准差，`seeds` 为随机种子列表，`duration` 为每例时长。基准使用固定默认滤波参数，避免把参数搜索收益误当作算法普遍优劣。

新增 API：`POST /api/experiment/run`；`GET /api/experiments`；`POST /api/experiments/{save,open,duplicate,import}`；`GET /api/experiments/export?format=zip|csv|html|json`；`GET /api/tasks/{id}` 与 `/events`。请求包含 `session_id` 和唯一 `request_id`，重试必须原样复用；同 ID 不同参数返回 409。`respond_async:true` 返回 task_id，后续读取实际进度。聊天普通/SSE 路由共享同一幂等任务。API 字段详情可直接参考 `server.py` 与前端 `web/workbench.js`。

使用 `python scripts/smoke_deployment.py` 验证真实运行服务；服务重启后再执行 `python scripts/smoke_deployment.py --check-persistence` 验证当前实验及命名快照保留。成功日志保存会话及校验摘要，供第二步读取。

## v0.2.1 快照管理与升级

在实验列表前的搜索框按名称筛选。选择实验，在名称框输入新名称，点击“按上方名称重命名”。“删除快照”会先确认；取消无修改，确认后当前工作区及其他快照保留。复制名称支持中间点等字符；名称需 1–120 字符且不能为 Autosave。

`POST /api/experiments/rename` 接收 `{session_id, request_id, id, name}`；`POST /api/experiments/delete` 接收 `{session_id, request_id, id}`。它们遵循原幂等与会话限制。重试只需保持业务参数不变，可以改变 `respond_async`；旧版保存的任务摘要也可重放。

运行或恢复后模板切换为“当前信号”，只修改目标可重新评分；若要编辑生成参数，先选择正弦、脉冲或 AR 模板。打开空聊天历史的实验会清除上一实验聊天。

升级保留整个 data/（SQLite 和 NPZ），不要清空数据库；详细步骤见 DEPLOY.md。`python scripts/build_release.py` 后直接执行 `python scripts/verify_release.py` 即按 config/release.json 自动选取部署包；也可用 --archive 指定路径。验证仍覆盖写入 logs/release/latest.log。

## v0.2.5 导入、对比、任务与清理

1. 打开“数据导入向导”，选择 UTF-8 CSV/TXT。预览前 20 行，选择时间列和信号列，指定时间单位；无时间列则按采样率生成时间。分隔符支持逗号、分号、制表符、空格。自动识别可手动覆盖。最多 200,000 行、64 列（普通请求总大小上限仍为 16 MiB）。
2. 点击“预览并校验”。最多展示 20 处错误及总数；错误显示原文件行号和从 1 开始的列号。修正缺失值、重复/倒序/不均匀时间后重新预览；不自动丢行或插值。通过后确认导入，原始文件摘要及列映射随实验保存。
3. 在“处理与保存”运行比较，分别保存方案。在“跨实验对比与报告”勾选 2–4 个快照，查看各快照当前处理结果的波形、频谱、指标及参数，下载 HTML。原始未处理快照也可查看，但不显示评分排名。
4. 展开“任务与排队”查看状态并取消。正在执行时等待安全检查点，外部请求等返回或超时；保存阶段与短的元数据写入操作无法取消。取消后的请求 ID 保留终态；重新运行要使用新的请求 ID。
5. 展开存储管理，查看全服务 NPZ/数据库占用和无引用数组，确认后清理。预览变化时需重新预览；清理不删除引用中的文件、任务历史、上传及音频。

新增配置 idle_session_seconds=900，表示无活动请求/任务的会话在空闲 15 分钟后可从内存释放；维护周期最多 60 秒。session_capacity 表示同时保留在内存的会话数，到达上限时优先释放空闲旧会话。数据仍在 data/，后续访问可恢复。

新增 API：POST /api/data/preview 与 /api/data/import 接受 multipart file、session_id、options(JSON)，导入还需预览 token 和可选 request_id；options 的 signal_column/time_column 从 0 开始，time_column=null 表示手填采样率，time_unit 为 s/ms/us/ns，delimiter 为 auto/comma/semicolon/tab/space，header 为 auto/yes/no。POST /api/experiments/compare 接受 session_id、ids(2–4 个)、format(json/html)。GET /api/tasks?session_id=... 列出最近 50 项；POST /api/tasks/{id}/cancel 接受 session_id。GET /api/storage 预览全服务清理范围；POST /api/storage/cleanup 接受 token 和 confirm=true。

执行 python scripts/test_studio.py；日志 logs/studio/latest.log 覆盖写入，OK 表示通过。部署包干净安装验证会自动运行此脚本。现有回归、集成、工作台与基准命令保持可用。
