# Random Signal Agent · 随机信号智能体

**UESTC 随机信号课程智能体项目**

提供 Web 对话界面、随机信号仿真、CSV/TXT 上传、麦克风数据分析、预处理对比、时频域和随机过程分析。不配置外部模型也可运行本地规则工具链。

## 从零复现

推荐 **Python 3.12**。当前后端依赖 `cgi`，支持的版本范围为 Python 3.10–3.12，不能直接使用 Python 3.13+。

```bash
git clone https://github.com/PatrickStar-cmd/random-signal-agent.git
cd random-signal-agent
cd "工程文件/代码"
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-repro.txt
python scripts/verify_reproduction.py
python server.py --host 127.0.0.1 --port 8000
```

Linux/macOS（确认 `python` 指向 Python 3.12，或创建环境时改用 `python3.12`）：

```bash
source .venv/bin/activate
python -m pip install -r requirements-repro.txt
python scripts/verify_reproduction.py
python server.py --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。输入：

> 采集一段 8 秒、采样率 200Hz、主频 8Hz 的正弦信号加高斯噪声，随机种子 42

然后输入“使用滑动平均预处理并分析时域和频域特征”，或开启 Agent 模式自动比较预处理方法。复现同一随机样本时必须固定随机种子。

## 文件与验证范围

- [代码与配置](工程文件/代码/README.md)
- [完整运行、参数与日志说明](工程文件/代码/docs/exec.md)
- [检查结论与功能实现情况](工程文件/代码/docs/review.md)
- [算法原理](工程文件/代码/docs/principle.md)
- [部署说明](工程文件/代码/DEPLOY.md)
- [原始 PDF 配置教程](工程文件/配置文档/随机信号智能体配置教程.pdf)

