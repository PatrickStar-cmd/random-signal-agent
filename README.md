# Random Signal Agent · 随机信号智能体

**UESTC 随机信号课程智能体项目**

提供 Web 对话界面、随机信号仿真、CSV/TXT 上传、麦克风数据分析、预处理对比、时频域和随机过程分析。不配置外部模型也可运行本地规则工具链。

[在线静态演示](https://patrickstar-cmd.github.io/random-signal-agent/) · [固定种子实验与数据](docs/README.md) · [MIT 许可证](LICENSE)

## 看看它能做什么

![实际运行的随机信号智能体 Web 界面](docs/images/web-ui.png)

- **自然语言实验**：指定采样率、时长、主频与随机种子，生成可复现的仿真信号。
- **自动比较预处理**：鲁棒滑动平均、中值、指数平滑、FFT 低通、混合增强和卡尔曼滤波，展示曲线与参数比较。
- **时频与随机过程分析**：时域统计、FFT、相关性、AR 模型、Welch 功率谱与残差分析。
- **多种输入**：仿真、CSV/TXT 文件、浏览器麦克风；可查看分析指标和控制建议。

下面的操作 GIF 演示：开启 Agent 模式 → 输入固定种子的正弦信号与高斯噪声指令 → 自动比较方法 → 展开分析指标。

![真实界面的操作过程](docs/images/web-demo.gif)

GitHub Pages 提供固定样本的静态结果；对话、上传和麦克风功能请按下方步骤本地运行。

## 一个可核对的实验

固定种子 42，采样率 200 Hz，时长 8 秒，主频 8 Hz，共 1600 点。使用随机过程与混合噪声，采用 7 点窗口的鲁棒滑动平均。

| 指标 | 结果 |
| --- | ---: |
| 检测主频 | 8.000 Hz |
| 原始 SNR | 2.859 dB |
| 处理后 SNR | 4.781 dB |
| SNR 提升 | 1.922 dB |

[下载可上传的 CSV 样例](docs/data/sample.csv) · [完整结果 JSON](docs/data/result.json) · [实验配置](工程文件/代码/config/showcase.json)

进入 `工程文件/代码` 后执行 `python scripts/build_showcase.py` 可重新生成结果。真实 SNR 依赖仿真干净参考，上传的观测数据没有参考时不计算；固定参数实验与 Web Agent 自动调参是不同流程，详情见[复现说明](docs/README.md)。

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
### **操作示例**（基础仿真实验室功能，还有其他功能可以参见教程）：

浏览器打开 <http://127.0.0.1:8000>。可以直接在Agent对话栏输入：

> 采集一段 8 秒、采样率 200Hz、主频 8Hz 的正弦信号加高斯噪声，随机种子 42

然后输入“使用滑动平均预处理并分析时域和频域特征”，或开启 Agent 模式自动比较预处理方法。复现同一随机样本时必须固定随机种子。

## 文件与验证范围

- [代码与配置](工程文件/代码/README.md)
- [完整运行、参数与日志说明](工程文件/代码/docs/exec.md)
- [检查结论与功能实现情况](工程文件/代码/docs/review.md)
- [算法原理](工程文件/代码/docs/principle.md)
- [部署说明](工程文件/代码/DEPLOY.md)
- [原始 PDF 配置教程](工程文件/配置文档/随机信号智能体配置教程.pdf)

## 许可证

本项目采用 [MIT License](LICENSE)。使用、修改与分发时请保留许可证和版权声明；第三方依赖及素材遵循其各自许可。
