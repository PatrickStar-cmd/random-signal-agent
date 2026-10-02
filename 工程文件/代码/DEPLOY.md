# 部署说明

本项目不包含任何固定公网 IP、云服务器账号、API Key 或私有路径。复现时请把下列占位信息替换为自己的环境。

v0.2.0 使用 Python 3.12–3.14 和 FastAPI/Uvicorn，已移除 `cgi`。按单进程部署，不要启动多个 Uvicorn worker：会话锁和任务队列属于同一个进程。本服务面向受控课程实验环境，已有输入及并发上限；公网访问仍需反向代理身份认证。

## 本地运行

下载 v0.2.0 Release 的 `random-signal-agent-v0.2.0-deploy.zip` 并解压后进入 `工程文件/代码`。发布包保留完整目录结构；`server.py` 位于该子目录，不在解压包根目录。

Windows（使用 Python 3.12）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-repro.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe server.py --host 127.0.0.1 --port 8000
```

Linux/macOS：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-repro.txt
.venv/bin/python -m pip check
.venv/bin/python server.py --host 127.0.0.1 --port 8000
```

访问：

```text
http://127.0.0.1:8000
```

## 外部模型 API

本项目使用 OpenAI 兼容的 `/chat/completions` 接口。复制并编辑配置文件：

```powershell
Copy-Item .\config\server.env.example .\config\server.env
notepad .\config\server.env
```

需要填写：

```text
RS_AGENT_LLM_BASE_URL=在此填写 API Base URL
RS_AGENT_LLM_MODEL=在此填写模型名
RS_AGENT_LLM_API_KEY=在此填写 API Key
```

不填写时，服务仍会启动，并使用本地规则工具链完成采集、预处理和分析。

## 云服务器运行

在自己的云服务器上安装 Python 3.12，上传代码目录后执行：

```bash
cd /path/to/random-signal-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-repro.txt
cp config/server.env.example config/server.env
nano config/server.env
bash scripts/start_server.sh
```

服务器上的完整应用可通过已有 HTTPS 反向代理访问，代理转发至 `127.0.0.1:8000`。代理需保留流式响应（关闭响应缓冲）并提供访问控制。浏览器麦克风需要 HTTPS 或 localhost。

## systemd 托管

复制模板：

```bash
sudo cp scripts/random-signal-agent.service.example /etc/systemd/system/random-signal-agent.service
sudo nano /etc/systemd/system/random-signal-agent.service
```

把模板中的 `YOUR_LINUX_USER` 和 `/path/to/random-signal-agent` 改成自己的 Linux 用户名和项目绝对路径，然后启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now random-signal-agent.service
sudo systemctl status random-signal-agent.service
```

查看日志：

```bash
journalctl -u random-signal-agent.service -n 100 --no-pager
```

## Docker 部署

在包含 `Dockerfile` 和 `docker-compose.yml` 的 `工程文件/代码` 目录执行。使用支持 `up --wait` 的 Docker Compose v2。

```bash
cp .env.example .env
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 120
docker compose ps
```

Windows PowerShell 的复制命令为 `Copy-Item .env.example .env`，其余 Docker 命令相同。

默认访问 <http://127.0.0.1:8000>。容器包含健康检查，启动完成后显示 `healthy`。无需填写外部模型配置即可完成本地分析。

`.env` 中的 `RS_AGENT_BIND_ADDRESS` 是宿主机绑定地址，默认 `127.0.0.1`；`RS_AGENT_PORT` 是宿主机端口，默认 8000，容器内始终使用 8000。`RS_AGENT_LLM_ENABLED=0` 强制使用本地工具链，`auto` 按模型配置决定。其余变量与外部模型设置一致。

上传文件和生成结果分别持久化到当前目录的 `uploads/`、`outputs/`。查看日志和停止服务：

```bash
docker compose logs --tail 100
docker compose down
```

如果需要直接从远端访问 8000 端口，将 `.env` 中 `RS_AGENT_BIND_ADDRESS` 改为 `0.0.0.0`，并限制防火墙访问来源。远端麦克风仍需通过 HTTPS 使用。

## 部署验收

在另一终端使用同一个 Python 环境执行：

```bash
python scripts/smoke_deployment.py --base-url http://127.0.0.1:8000
```

该检查创建独立测试会话，验证健康接口、页面资源、自动分析、SSE、CSV 上传及合成音频下载。运行参数位于 `config/deployment-check.json`，结果写入 `logs/deployment/latest.log`。`status=passed` 表示上述检查通过；真实麦克风授权和外部模型连接需在自己的环境中验证。

发布包的 SHA-256 校验文件为 `SHA256SUMS.txt`。Windows 可以执行：

```powershell
Get-FileHash .\random-signal-agent-v0.2.0-deploy.zip -Algorithm SHA256
```

Linux 执行 `sha256sum -c SHA256SUMS.txt`。发布包中的 `RELEASE.json` 记录版本和源码提交。

## 健康检查

```bash
curl http://127.0.0.1:8000/api/health
```

返回中的 `llm.configured` 只表示配置项齐全且已启用，不验证密钥有效性、联网或模型兼容性；即使为 `false`，本地规则工具链仍可运行。

## v0.2.0 数据和迁移

`data/experiments.sqlite3` 保存实验清单、完整状态元数据和任务结果，旁边的内容寻址 `.npz` 文件保存全量采样。Compose 将 `./data` 挂载到 `/app/data`；更新镜像或重启容器会保留这些文件。备份应在停止服务后复制整个 `data/`，还需 `uploads/` 与 `outputs/` 才能保留原上传文件及音频附件。不要只复制 SQLite 文件。

升级：停止旧进程，更新源码，在虚拟环境中安装 `requirements-repro.txt`，然后按原命令启动。v0.1.0 没有持久化会话，旧进程内尚未保存的数据无法自动迁移。已有静态演示 CSV 可以重新上传。

`RS_AGENT_DATA_DIR` 可指定数据目录，默认代码目录下的 `data/`。浏览器会话标识保存在 localStorage；清理浏览器站点数据会失去当前实验列表的入口，应先导出 ZIP。会话标识不是账号认证。

`config/workbench.json` 管理采样、请求大小、任务并发与候选搜索上限，字段说明见 `docs/exec.md`。默认普通请求 16 MiB、实验导入 64 MiB、200,000 点、2 个工作线程、最多 8 个待处理/运行任务。返回 429 时可用原 request_id 重试。服务中断中的任务不会自动重新执行；恢复到最近一次成功状态后再创建新请求。

实验 ZIP 含完整数据、参数、工具记录及报告。音频文件不打包；导入后可用其中的原始采样重新处理。跨算法版本的导入会被拒绝，防止静默改变解释；固定种子重算可能因不同 NumPy/平台产生细小数值差异，导入保存的采样则逐点一致。
