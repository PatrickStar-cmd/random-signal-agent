# 部署说明

本项目不包含任何固定公网 IP、云服务器账号、API Key 或私有路径。复现时请把下列占位信息替换为自己的环境。

使用 Python 3.10–3.12（推荐 3.12）；当前代码依赖 `cgi`，不支持 Python 3.13+。本服务面向课程实验，未实现身份认证和资源配额，公网部署应由反向代理提供访问控制。

## 本地运行

```powershell
pip install -r requirements.txt
python .\server.py --host 127.0.0.1 --port 8000
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
pip install -r requirements.txt
cp config/server.env.example config/server.env
nano config/server.env
bash scripts/start_server.sh
```

在云平台安全组和服务器防火墙中开放 TCP 8000 端口后访问：

```text
http://你的服务器公网IP:8000
```

建议正式演示时配置域名和 HTTPS。浏览器麦克风权限通常要求 HTTPS 或 localhost。

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

```bash
cp .env.example .env
nano .env
docker compose up -d --build
```

访问：

```text
http://你的服务器公网IP:8000
```

## 健康检查

```bash
curl http://127.0.0.1:8000/api/health
```

返回中的 `llm.configured` 只表示配置项齐全且已启用，不验证密钥有效性、联网或模型兼容性；即使为 `false`，本地规则工具链仍可运行。
