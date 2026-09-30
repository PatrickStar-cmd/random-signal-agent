# v0.1.0 · Installation and deployment

Download `random-signal-agent-v0.1.0-deploy.zip` from the [v0.1.0 release](https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.1.0) and extract it. The package includes source code, Web assets, configuration templates, documentation, and experiment data. It requires **Python 3.12** or **Docker**; it is not a standalone executable.

Open a terminal in `random-signal-agent-v0.1.0/工程文件/代码`.

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

On Windows, use `Copy-Item .env.example .env` for the first command. Uploads and outputs are stored in local folders and survive container restarts.

Open <http://127.0.0.1:8000>. No model API key is required for simulation, preprocessing, and analysis. For external models or server hosting, see [deployment configuration](工程文件/代码/DEPLOY.md).

## Verify a running service

From another terminal with the same Python environment:

```bash
python scripts/smoke_deployment.py --base-url http://127.0.0.1:8000
```

The check covers health, Web assets, Agent mode, streaming responses, CSV upload, and synthetic audio download. Browser microphone access requires localhost or HTTPS. GitHub Pages hosts the experiment preview; the complete application runs with the Python backend.

`SHA256SUMS.txt` verifies the deployment ZIP; `RELEASE.json` inside it records the version and source commit. The package contains no virtual environment, API keys, uploaded files, or local logs.

## 中文说明

下载部署 ZIP，解压后进入 `工程文件/代码`，按上方对应系统命令安装并启动。推荐 Python 3.12，依赖锁定为 NumPy 2.5.3。也可使用 Docker Compose；默认地址为 <http://127.0.0.1:8000>。

完整应用包含对话、分析、上传及音频处理，不需要外部模型密钥即可使用本地工具链。服务器部署、模型配置与日志查看见[部署说明](工程文件/代码/DEPLOY.md)。
