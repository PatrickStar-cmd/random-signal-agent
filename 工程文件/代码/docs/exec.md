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

### 模块框线与精简文案

启动服务后刷新浏览器，依次查看六个导航分区。外层面板及内部功能卡片采用 2 px 框线；在“模板与实验 → PDF 分析报告”生成预览后，展开“数据说明”查看参考与分析条件。模型配置中，保存方式和连接测试计费信息位于“记住配置”下方。

2026-10-10 本地验收使用独立服务数据，实际完成生成、保存、对比、诊断和报告下载。临时脚本与桌面/手机截图位于 `debug/ui-frames/`；`logs/ui-frames/browser.log` 记录分区、屏幕宽度、操作结果和脚本错误列表，`server.log`、`server-error.log` 记录测试服务输出，每次覆盖。

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

启动后进入“模板与实验”，选择模板和目标、设置采样率/时长/基频/幅值/噪声/种子/AR 系数/脉冲概率，运行比较。命名并“保存为新快照”产生独立实验；“打开”恢复选中实验，“复制”保留原件并生成副本。每次成功操作还会自动保存当前会话。ZIP 可移到另一个浏览器或兼容算法版本的服务导入，CSV 保留每个采样点。HTML 无需后端即可打开。

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


## v0.2.6 诊断操作与配置

生成或导入信号后，打开“信号诊断实验室”，选择来源、窗长、重叠和相对首点的开始/结束秒数，点击诊断。至少 16 点，要求均匀采样。时频图拖动选区，证据卡片可定位波形并运行验证。采用仅更新处理结果；可在工作台保存为快照。主频变化不自动滤除。

“载入故障演示”生成 200 Hz / 8 秒示例并替换当前信号，需要保留时先保存快照。在故障注入区配置最多 8 个事件；强度为脉冲/正弦幅值、漂移终值或削顶阈值，归零不使用强度；频率用于窄带与主频变化。重新注入以挑战基线开始，不叠加前次注入。盲测只隐藏应用输出的真值/参考，不会抹除你自己设定参数的记忆。揭晓重新检查全段原始观测，显示评分。

`config/diagnostics.json`：version=1.0 为诊断契约；window=128 默认窗长；overlap=0.75 默认重叠比例；max_faults=8 注入配置上限；max_events=64 检测卡片上限；plot_frames=240 / plot_bins=128 为时频显示最大时间/频率格数；impulse_sigma=8 二阶差分 MAD 阈值倍率；minimum_event_samples=4 归零最少样本；spectral_ratio=8 为相对基线功率倍率；spectral_fraction=0.18 为该频点占帧功率下限。诊断脚本无额外生产依赖，SciPy 只用于独立验证。

运行 `python scripts/test_diagnostics.py`；日志覆盖写入 `logs/diagnostics/latest.log`。发布干净安装验证自动运行。

API：`POST /api/diagnostics/{analyze,inject,demo,reveal,verify,adopt}`，共同参数 session_id、request_id、respond_async；analyze 的 options 为 source(observed/processed)、window(32–2048 的 2 次幂)、overlap(0–0.75)、start/end 相对秒数；inject 的 faults 为 {kind,start,end,strength,frequency} 列表及 seed、blind；demo 接收 blind；verify 接收证据卡片 event_id 和诊断 token；adopt/reveal 不需额外参数。`GET /api/diagnostics/view?session_id=...&format=json|html` 重建图像或下载独立报告。重试须复用原请求 ID/参数；修改信号后重新诊断再验证。

盲测未揭晓时完整 ZIP/CSV/HTML/JSON 导出和快照对比会返回 400；诊断 HTML 不含内部基线与真值。揭晓后恢复参考指标与导出。内部持久化保留真值用于评分，这是一种课程盲测功能，不是对服务器文件访问者的保密机制。旧快照缺少新字段时使用空诊断状态；升级前停止服务并备份整个 data/，降级需恢复升级前备份。


## 模型 API 配置（v0.3.0）

点击顶部“模型与设置”，展开“模型 API 配置”，选服务、输入 Key、读取模型列表后点击“测试并应用”。具体操作、配置文件各字段、API 与保存行为见 [模型配置指南](model-api-setup.md)。运行 `python scripts/test_model_settings.py`；结果覆盖写入 `logs/model-settings/latest.log`。配置保存于独立的 data/model-settings.sqlite3，实验导出不含 Key。停止服务并备份整个 data/ 会同时备份记住的 Key，按部署数据权限保存。

## 可爱海洋界面（v0.3.0）

启动命令不变。默认进入“信号工作区”，其余操作位于六个顶栏入口；模型配置、任务队列与清理位于“模型与设置”。示例按钮只填写指令。界面说明与验证日志位置见 [ui-design.md](ui-design.md)。

## 海洋插画与背景增强（v0.3.0）

启动方式不变，素材随 web/ 本地静态资源提供，不需要生图服务或新运行依赖。替换素材文件为 web/ocean-whale.webp；静态预览的相同副本由 scripts/build_showcase.py 维护。生成提示词、编码参数和 logs/ocean-artwork/ 日志见 [visual-assets.md](visual-assets.md)。

## v0.3.0 部署包验证

先提交源码，再运行 `python scripts/build_release.py` 和 `python scripts/verify_release.py`。后者解压 ZIP、创建独立虚拟环境、安装固定依赖，运行回归、数值基准、模型配置和诊断验收，并通过真实启动脚本检查 HTTP 服务。模型测试使用本地模拟服务，不调用真实付费 API。

部署冒烟新增校验应用版本与 `config/release.json` 一致、海洋图片及模型配置脚本实际交付内容匹配解压文件、模型配置接口返回预设服务且不返回 Key。单独运行 `python scripts/smoke_deployment.py --base-url http://127.0.0.1:8000` 时须使用与该源码版本相同的服务。

产物位于 `outputs/release/`：部署 ZIP、`SHA256SUMS.txt`、`verification-windows.json` 或 `verification-linux.json`；构建和验收日志分别覆盖写入 `logs/release/build.log`、`latest.log`、`server.log`。临时解压及环境在 `debug/release/` 中，验证完成自动移除临时环境。CI 覆盖 Windows/Linux 的 Python 3.12–3.14 和 Linux Docker 重启持久化。

## README 图片与演示

启动应用后，在信号工作区开启 Agent 模式，采集 8 秒、200 Hz、8 Hz、种子 42 的正弦加高斯噪声，保存快照；随后载入诊断故障演示并打开模型设置。首页媒体由该流程实际截图与录制，API 表单截图未输入 Key。`docs/images/ocean-ui.png`、`workbench-v030.png`、`diagnostics-v030.png`、`model-api-v030.png` 和 `ocean-demo-v030.gif` 均相对于仓库根目录。

此次独立录制数据、帧与调试脚本在 `debug/readme-v030/`；界面、GIF 和 GitHub 渲染检查覆盖写入 `logs/readme-v030/browser.log`、`media.log`、`render.log`，独立服务日志在同目录 `server.log`。无需增加生产依赖或配置外部模型。静态展示数据的固定实验参数未改变，页面截图的正弦实验与展示数据的随机过程实验分别说明。

## PDF 分析报告（v0.3.1）

启动方式不变，依赖已固定在 requirements-repro.txt（ReportLab 5.0.1、Pillow 12.3.0、charset-normalizer 3.5.2）；测试依赖 pypdf 6.12.2。运行 `python scripts/test_pdf_report.py`，14 项验收结果覆盖写入 logs/pdf-report/latest.log。页面操作和 HTTP 接口见 [pdf-report.md](pdf-report.md)。

config/report.json 全部字段：version=2.0 为当前报告版式契约；plot_points=780 为每图采样显示上限；max_title=120、max_author=80、max_purpose=1200 为输入字符上限；max_pages=24 为单实验输出页数上限；collection_max_pages=1208 为合并报告总页数上限；history_limit=50 为每会话保留的处理组数及报告选择上限；render_workers=2 为同时渲染上限；font 为随包交付的 TrueType 中文字体路径。量纲限制 20 字符，edition 仅 brief/standard。不修改实验 schema 1 或算法 0.2.0。历史扩展的页面选择上限为 50，修改此配置时应同时调整页面提示/选择控制。

发布命令仍为 `python scripts/build_release.py`、`python scripts/verify_release.py`，在已提交干净源码上执行。新验证涵盖字体/许可证打包、14 项 PDF 验收和服务实际 PDF 下载；全部套件共 104 项，另有 540 个数值基准案例。源码、页面与 release.json 版本均为 0.3.1。

报告生成、逐页 PNG 和浏览器下载验证脚本/产物保存在 debug/pdf-report/，浏览器结果在 logs/pdf-report/browser.log，独立服务在 logs/pdf-report/server.log。README v0.3.1 四张截图已从运行界面重录，PDF 示例为真实 Agent 的 8 秒、200 Hz、8 Hz、种子 42 正弦加高斯噪声实验。旧 GIF 标明 v0.3.0，静态固定展示实验保持原参数。

## v0.3.2 历史结果合并 PDF

启动方式和生产依赖不变。历史写入 data/experiments.sqlite3 的独立 report_history 表，完整数组使用原 NPZ 格式；首次启动自动创建新表。升级前停止服务并备份整个 data/。当前单实验入口保持兼容，v0.3.2 部署 ZIP 包含本次扩展，应用/页面/release.json 版本统一 0.3.2。

在“模板与实验 → 生成 PDF 分析报告”选择历史模式，勾选最多 50 组处理结果，可补充手动快照并选择时间顺序，再预览、下载。操作与 HTTP selection 参数见 [报告指南](pdf-report.md)。最近记录按浏览器会话保存；未留存的旧处理结果不能自动补回。

运行 `python scripts/test_report_history.py`，15 项验收覆盖留存/重启、重复请求、回滚、会话隔离、盲测、清理、全组图表和 PDF 导航，日志覆盖写入 logs/report-history/latest.log。结合原有套件共 119 项；verify_release.py 已加入此验收，部署冒烟与重启检查增加 history/缩略图/选择 PDF。

验收自动创建 debug/report-history/ 及说明文件，可在部署 ZIP 的全新环境运行，不依赖已有调试目录。提交源码后运行 `python scripts/build_release.py`、`python scripts/verify_release.py`；产物与覆盖日志位置保持原发布约定。

本次独立浏览器测试结果在 logs/report-history/browser.log，390 像素手机和桌面选择、50 组下载、快照补充及淘汰提示均通过。最大输入测试在 logs/report-history/maximum-input.json：50 组、每组 200000 点，事实整理约 4.3 秒、排版约 2.9 秒，实际耗时随机器和诊断内容变化。debug/report-history/ 存放独立测试数据、脚本、截图与逐页 PDF 渲染。未调用外部模型。

## v0.3.3 界面维护版本

启动命令与依赖保持一致，刷新页面加载 2 px 框线与精简文案。应用、页面和 config/release.json 版本均为 0.3.3。发行包通过 scripts/build_release.py 从已提交源码生成，scripts/verify_release.py 在新虚拟环境安装、执行全部验收并真实启动；日志覆盖 logs/release/latest.log 与 server.log，产物位于 outputs/release/。

## v0.3.4 海洋渐变界面

启动命令不变，运行 `scripts/start_server.ps1` 或 `bash scripts/start_server.sh` 后刷新页面。中文优先华文中宋，英文和数字使用 Times New Roman；字体依赖访问者电脑，缺少时自动回退。通过工作区对话“比较所有预处理方法”查看推荐指标，展开“查看全部方法与参数”查看完整结果。右上时间每秒刷新。

本次独立验证说明、脚本与截图位于 `debug/ocean-visual/`；最新浏览器结果为 `logs/ocean-visual/browser.log`，服务输出为同目录 `server.log` 和 `server-error.log`。生产服务运行方式、配置参数和日志位置均保持原有约定。


v0.3.4 发行：运行 `python scripts/build_release.py` 从已提交源码生成部署 ZIP 与 SHA256SUMS.txt，运行 `python scripts/verify_release.py` 在新虚拟环境验收。日志覆盖写入 `logs/release/`，附件生成至 `outputs/release/`。升级时保留 data/，重启后刷新浏览器。

## 通信实验室（v0.4.0）

在 `工程文件/代码` 按现有步骤安装 `requirements-repro.txt`，运行 `scripts/start_server.ps1`（Windows）或 `bash scripts/start_server.sh`，打开 `http://127.0.0.1:8000/#communicationsPanel`。无需新增依赖或模型 Key。选择示例或拖动积木，Build 后再 Run；具体操作与 HTTP 接口见 [通信指南](communications-lab.md)。修改配置后重启服务。

`config/communications.json` 的全部字段：

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| schema | 1 | 通信工程 JSON 格式版本，独立于既有实验快照 schema。 |
| max_blocks | 32 | 单工程积木数上限，包含信源和固定信宿。 |
| max_bits | 65536 | 任一级中间数组的长度上限，Build 在分配前检查；单位随级别为位或符号/样本。 |
| max_source_bits | 8192 | 合并数字信源的最大比特数，也用于单随机/自定义比特信源范围。 |
| max_samples | 1024 | 单个模拟信源及信宿的样本数上限。 |
| plot_points | 256 | 信宿每次可视窗口和信道 I/Q 显示点数上限；信宿滑块可浏览其余数据。 |
| scatter_points | 1000 | 星座图最多显示的前部符号数。 |
| concurrent_runs | 2 | 同时运行许可数，超出返回 429，失败也释放许可。 |
| defaults.seed | 42 | 默认种子；合法整数范围 0–4294967294。 |
| defaults.sample_rate | 256 | 模拟信源采样率 Hz，范围 16–48000。 |
| defaults.sample_count | 256 | 模拟信源样本数，32 至 max_samples。 |
| defaults.symbol_rate | 1000 | 复符号分支的符号率 / 实基带分支的电平码元率 Baud；后者 fs=Rs×sps；范围 1–100000。 |

配置上限为正整数，`max_blocks` 应足够容纳完整链路，`plot_points`/`scatter_points` 不超过资源预算；`defaults` 须处于上述范围。调整资源上限时同时评估内存和响应时间。积木自身参数由 `src/communications.py` 定义，通过 catalog 接口供表单与自动化读取。

执行 `python scripts/test_communications.py`，当前 49 项验收结果覆盖写入 `logs/communications/latest.log`。`scripts/verify_release.py` 已接入该套件并校验通信脚本、样式、模拟算法、baseband、receiver_recovery 模块和配置文件打包；发行在已提交的干净源码构建并验证。

本次独立浏览器验证脚本和截图位于 `debug/communications/`，目的见同目录 `note.md`；日志覆盖到 `logs/communications/browser.log`，隔离服务输出为 `server.log` / `server-error.log`。浏览器验证使用真实本地后端，桌面和手机截图没有输入模型 Key。部署冒烟 `python scripts/smoke_deployment.py --base-url http://127.0.0.1:8000` 新增通信 catalog/build/run 与静态资源交付检查，输出为 `logs/deployment/latest.log`，测试会创建独立测试会话。

自动化界面入口：`[data-view-link="communications"]`、`#cmProgram`、`[data-cm-kind]`、`#cmBuild`、`#cmRun`；可通过浏览器输入/拖拽操作和页面截图验证。只计算时使用指南所列 HTTP 接口。工程草稿保存在访问者浏览器 `rs_communication_draft_v1`，结果不写入已有实验数据库。

积木箱分类按钮按信号处理顺序排列：信源、发转换器、调制器、信道、解调器、收转换器。先在发转换器选择 PCM/编码/交织，再在调制器选择 BPSK/QPSK/16-QAM；接收侧先选择对应解调器，再按相反顺序添加收转换器。数字信源无需编码时可直接进入调制器。catalog 的 category 标识分别为 `source`、`tx_converter`、`modulator`、`channel`、`demodulator`、`rx_converter`；固定信宿仍为 `sink`。该分类调整无需修改配置或迁移旧工程。

2026-10-12 分类细分验收继续使用 `python scripts/test_communications.py`（14 项）；旧版本对照日志为 `logs/communications-categories/compatibility.log`，浏览器分类、320/390/1440 px 布局、数字示例 Build/Run 和草稿刷新检查记录为 `logs/communications-categories/browser.log`。本轮临时脚本及截图位于 `debug/communications-categories/`，说明见 `note.md`；不需要运行该调试服务来使用正式功能。

文档检查结果为 `logs/communications/docs.log`：README/指南本地链接、GitHub Markdown 的默认英文与中文切换、新截图加载和静态预览桌面/手机宽度均已检查。

### 六种直接模拟调制

本轮源码新增 AM、DSB-SC、SSB、VSB、FM、PM，不需要安装新增依赖或修改配置。按现有启动脚本重启服务并刷新浏览器，从“实验示例”选择四个“线性”或三个“非线性”示例，Build 后 Run。模拟信源直接进入模拟调制器，不经过 PCM；全部模拟时钟使用 sample_rate，symbol_rate 仅用于数字符号。AM 检波方式、SSB 方法/上下边带、VSB 残留宽度、FM/PM 灵敏度和低通参数详见 [模拟指南](analog-modulation.md)。

`src/analog_modulation.py` 实现模拟算法，`src/communications.py` 定义积木、默认参数、示例及链路编译，无需额外启动进程。使用原 catalog/build/run 接口；新结果含 transport=analog、模拟指标和 analog 图表信息，旧数字结果结构保持一致。下载 CSV 为完整还原样本，结果 JSON 保留全帧频谱与完整信宿数组。

部署冒烟 `python scripts/smoke_deployment.py --base-url http://127.0.0.1:8000` 同时检查六种新增示例；日志仍为 `logs/deployment/latest.log`。本轮隔离浏览器验收日志为 `logs/communications-analog/browser.log`，测试服务日志为同目录 server.log/server-error.log，临时脚本、PDF 提取和页面截图归入 `debug/communications-analog/`（目的见 note.md）。生产运行不依赖该调试目录。

### 第四章线路编码与基带信道

重启现有源码服务并刷新页面，从“实验示例”选择十种“线路码”或两个“基带”示例，Build、Run 后查看波形/频谱/眼图。全部新增参数的含义、合法范围与默认值见 [基带指南](baseband-coding.md)，表单和 catalog 来自相同定义；配置文件及启动脚本不变，无新增依赖。`src/baseband.py` 由原 communications API 自动调用，无需独立启动。

`max_bits` 同时限制线路展开、发送零保护区和接收滤波尾部的采样总量。增加 sps 或长脉冲跨度前应减少信源位数；Rs 是实际电平码元率，fs=Rs×sps，滤波截止须小于 fs/2。原 `sample_rate` 只控制模拟信源及 PCM 输出的时间轴。实基带结果新增 `transport=baseband`、电平 RMSE/违例、baseband 波形/频谱/眼图/均衡系数；旧分支结果未改动。

本轮 `python scripts/test_communications.py` 37 项、`python scripts/test_regressions.py` 25 项、`python scripts/verify_reproduction.py` 5 项通过。部署冒烟还逐个检查 12 个新示例的真实 HTTP Build/Run、眼图和结果。数值日志为 `logs/communications/latest.log`，十个旧示例逐字段对照为 `logs/communications-coding/compatibility.log`，浏览器与隔离服务输出为 `logs/communications-coding/browser.log`、`server.log`、`server-error.log`；调试脚本、PDF 提取/渲染、独立服务数据和截图在 `debug/communications-coding/`。以上功能已纳入 v0.4.1 发布 ZIP。

### 自动符号同步与自适应均衡（当前源码）

以上累积功能已纳入 v0.4.1「传输环节模块补充」。提交干净源码后运行 `python scripts/build_release.py`、`python scripts/verify_release.py`；产物为 `outputs/release/random-signal-agent-v0.4.1-deploy.zip`、`SHA256SUMS.txt` 和平台验证 JSON。完整验证包含 49 项通信验收及既有各套件、540 个基准、真实启动与 HTTP 全流程。发布前合并 GitHub 六组平台/Python 及 Docker 检查到 `verification.json`，随 Release 上传。日志覆盖 `logs/release/`，本次临时发布材料在 `debug/release-v041/`，干净解压环境由 `debug/release/` 管理并自动回收。

沿用现有启动脚本、环境配置及 API，重启源码服务并刷新页面。选择三个“同步”或四个“均衡”新示例，Build、Run；在基带/PAM 接收器中选择同步模式、均衡结构及 LMS/NLMS/RLS。自适应模式须在发送器配置足量“公共训练前导”；关闭“训练后按判决继续自适应”可冻结系数。全部新增参数、范围、默认值和实验步骤见 [同步与均衡指南](receiver-recovery.md)。`src/receiver_recovery.py` 由 `baseband.py` 调用，无需单独启动或新增依赖。

当前通信 49 项、回归 25 项、复现 5 项通过，运行命令保持上文不变。启动服务后执行 `python scripts/smoke_deployment.py --base-url http://127.0.0.1:8000` 验证 HTTP 全流程，额外检查 7 个同步/均衡示例。日志覆盖写入 `logs/communications/latest.log` 与 `logs/deployment/latest.log`；本次算法观测、22 个旧示例对照、浏览器、文档和隔离服务日志位于 `logs/communications-recovery/`。临时课件页图、脚本及数据位于 `debug/communications-recovery/`，不参与部署；页面截图见指南。新默认字段规范化省略，原工程 schema 1 与 Build token 保持兼容。以上功能随 v0.4.1 发布 ZIP 交付。

### v0.4.2 积木编程区

沿用启动脚本和 config/communications.json，无新增参数或依赖。重启后刷新浏览器，选择通信实验室：点击链路积木，在右侧编辑参数；同步/均衡及高级参数可展开。先 🔨 Build 再 ▶️ Run，下方查看指标和分析图，工具栏导入/导出工程。原 schema 1 草稿和 JSON 可继续读取。

数值验证：`python scripts/test_communications.py`（49 项）；前端语法：`node --check web/communications.js`。本轮真实浏览器覆盖 29 个示例、完整导出、参数、拖放和九种屏宽；记录为 logs/communications-studio/browser.log、browser-presets.json、tests.log，隔离服务日志为同目录 server.log/server-error.log。调试目的与隔离数据位于 debug/communications-studio/，均不进入部署包。

发布仍执行 `python scripts/build_release.py` 和 `python scripts/verify_release.py`，从已提交源码产生 outputs/release/random-signal-agent-v0.4.2-deploy.zip、SHA256SUMS.txt 与平台验证 JSON。六组平台/Python 及 Docker CI 汇总到发布 verification.json；日志覆盖 logs/release/，临时发布材料在 debug/release-v042/。

### v0.4.3 积木功能更新

运行 `python scripts/test_communications.py` 和 `python scripts/test_communications_advanced.py`，日志分别覆盖 `logs/communications/latest.log` 与 `advanced.log`。使用 `python scripts/run_communication_sweep.py --preset soft_viterbi --mode ebn0 --stop 6 --frames 10` 生成 `outputs/communications/sweep.json` 和 CSV，日志覆盖 `logs/communications/sweep.log`。接口、配置字段和参数说明见 [v0.4.3 指南](communications-v043.md)。

页面中 Build 后运行预设，展开“批量性能实验”扫描并加入对比。浏览器验收与六档宽度记录位于 `logs/communications-v043/browser.json`，测试服务为隔离的 `debug/communications-v043/serve.py`，端口 8793；正式部署仍使用标准启动脚本。静态预览中的性能图来自真实浏览器。

部署继续执行 `python scripts/build_release.py` 和 `python scripts/verify_release.py`，新增模块与验收套件均加入解包检查；v0.4.3 ZIP、SHA256SUMS.txt 和最终平台验证记录随 Release 交付。


### v0.4.4 积木编程体验更新

执行 `python scripts/test_communications_experience.py`（24 项），日志覆盖 logs/communications/experience.log；旧套件和 540 组基准继续执行。启动脚本不变，打开 /#communicationsPanel。新增配置字段、工程库/续跑目录、后台任务 API 详见 [v0.4.4 指南](communications-v044.md)。logs/communications-v044/browser.json 记录 54 个示例与交互、响应式验收；debug/communications-v044/ 放隔离数据、报告渲染与临时材料。发布执行 build_release.py、verify_release.py，新增模块及套件纳入清洁解包验收，实际平台结果随 verification.json 交付。


## v0.4.5 启动与测试

沿用原启动脚本和通信配置，打开通信实验室的射频仪表面板。新增测试 scripts/test_communications_rf.py 和可选 Node 数值测试 scripts/test_communications_alignment.js；日志在 logs/communications-rf/。通用扫描 CLI 可直接选择 rf_qam64 等新示例。 参数、公式、接口、验证和日志位置详见 [v0.4.5 指南](communications-v045.md)。
