# v0.2.1 · Installation and deployment

Download `random-signal-agent-v0.2.1-deploy.zip` from the [v0.2.1 release](https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.2.1) and extract it; the archive contains source, Web assets, configuration, documentation and example data. Use **Python 3.12–3.14** or **Docker**. The [previous v0.1.0 release](https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.1.0) remains available and requires Python 3.12.

Open a terminal in `random-signal-agent/工程文件/代码` (or `random-signal-agent-v0.2.1/工程文件/代码` in a deployment archive).

## Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-repro.txt
.\.venv\Scripts\python.exe server.py --host 127.0.0.1 --port 8000
```

## Linux / macOS

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-repro.txt
.venv/bin/python server.py --host 127.0.0.1 --port 8000
```

## Docker Compose

```bash
cp .env.example .env
docker compose up -d --build --wait --wait-timeout 120
```

On Windows, use `Copy-Item .env.example .env` for the first command. Experiments, uploads and outputs are stored in the mounted `data/`, `uploads/` and `outputs/` folders and survive container restarts. Run one backend process; session locks are local to that process.

Open <http://127.0.0.1:8000>. No model API key is required for simulation, preprocessing, and analysis. For external models or server hosting, see [deployment configuration](工程文件/代码/DEPLOY.md).

## Verify a running service

From another terminal with the same Python environment:

```bash
python scripts/smoke_deployment.py --base-url http://127.0.0.1:8000
```

The check covers health, Web assets, Agent mode, streaming responses, CSV upload, and synthetic audio download. Browser microphone access requires localhost or HTTPS. GitHub Pages hosts the experiment preview; the complete application runs with the Python backend.

`SHA256SUMS.txt` verifies the deployment ZIP; `RELEASE.json` inside it records the version and source commit. The package contains no virtual environment, API keys, uploaded files, or local logs.

## 中文说明

下载 v0.2.1 部署包并解压，进入 `工程文件/代码` 后按上方命令启动。支持 Python 3.12–3.14，依赖版本在 `requirements-repro.txt` 固定。也可使用 Docker Compose；默认地址为 <http://127.0.0.1:8000>。实验可导出 ZIP，升级前停止服务并备份整个 `data/` 目录。

完整应用包含对话、分析、上传及音频处理，不需要外部模型密钥即可使用本地工具链。服务器部署、模型配置与日志查看见[部署说明](工程文件/代码/DEPLOY.md)。

## Upgrading from v0.2.0

Stop the old service and back up the entire `data/` directory, then copy it into the new deployment at the same relative location (or keep `RS_AGENT_DATA_DIR` pointing to it). Keep `uploads/` and `outputs/` to retain file and audio attachments. Restart using the same host and browser profile so its session ID is preserved. v0.2.0 snapshots and experiment ZIPs remain readable: schema 1 and algorithm 0.2.0 are unchanged. No database reset is needed.
