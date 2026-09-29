# Random Signal Agent · 随机信号智能体

UESTC 随机信号课程智能体项目。

提供 Web 对话界面、随机信号仿真、CSV/TXT 上传、麦克风数据分析、预处理对比、时频域和随机过程分析。不配置外部模型也可运行本地规则工具链。

## 从零复现

推荐 **Python 3.12**。当前后端依赖 `cgi`，支持的版本范围为 Python 3.10–3.12，不能直接使用 Python 3.13+。

```bash
git clone https://github.com/PatrickStar-cmd/random-signal-agent.git
cd random-signal-agent
cd "T组智能体工程文件/代码"
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

- [代码与配置](T组智能体工程文件/代码/README.md)
- [完整运行、参数与日志说明](T组智能体工程文件/代码/docs/exec.md)
- [检查结论与功能实现情况](T组智能体工程文件/代码/docs/review.md)
- [算法原理](T组智能体工程文件/代码/docs/principle.md)
- [部署说明](T组智能体工程文件/代码/DEPLOY.md)
- [原始 PDF 配置教程](T组智能体工程文件/配置文档/随机信号智能体配置教程.pdf)

2026-09-29 在 Windows、CPython 3.12.10、NumPy 2.5.3 独立环境完成 5 组集成检查。核心本地流程可复现；外部模型调用及真实浏览器麦克风效果已由项目作者验证；Linux/macOS、Docker、systemd 未在本次检查中实测。外部模型需自备兼容接口、模型名与密钥，`llm.configured` 仅检查配置齐全。MP3 导出可选依赖 FFmpeg，缺省仍可生成 WAV。

PDF 保留原版；其中 Python “3.10 或更高”应修正为 3.10–3.12，systemd 应使用项目虚拟环境解释器，具体以当前文档和模板为准。项目没有运行必需的私有数据集或模型权重；信号由代码生成或由使用者提供。当前服务用于课程实验，公网部署需要另行配置身份认证和资源限制。
