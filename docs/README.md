# 固定种子实验与 GitHub Pages

[在线静态演示](https://patrickstar-cmd.github.io/random-signal-agent/) · [返回项目首页](../README.md)

这个目录是 GitHub Pages 的发布源，`index.html` 由已有 Python 工具链计算生成，不需要服务端，也不调用外部模型。

## 复现实验

在 Python 3.12 环境下，进入 `工程文件/代码`：

```bash
python -m pip install -r requirements-repro.txt
python scripts/build_showcase.py
```

配置在 [`config/showcase.json`](../工程文件/代码/config/showcase.json)，与 `run_demo.py` 的默认实验一致：200 Hz、8 秒、8 Hz 主频、幅值 1.2、噪声标准差 0.55、AR 系数 0.86、脉冲概率 0.012、种子 42；信号为随机过程，噪声为混合噪声。共 1600 点。

固定默认参数下，鲁棒滑动平均采用 7 点窗口，主频检测为 8 Hz；原始 SNR 约 2.859 dB，处理后约 4.781 dB，提升约 1.922 dB。六种方法的结果均来自同一输入，不保证每种滤波都改善 SNR。浮点数末位可能随依赖和平台不同而略有变化。

## 数据文件

| 文件 | 用途 |
| --- | --- |
| [`sample.csv`](data/sample.csv) | 两列：时间、观测值。可直接上传到本地 Web 界面。 |
| [`reference.csv`](data/reference.csv) | 四列：时间、干净参考、观测值、处理结果。用于离线核对，不能作为观测值直接上传。 |
| [`result.json`](data/result.json) | 生成环境、完整配置、分析指标、执行轨迹及六种滤波结果。 |

SNR 计算使用仿真时已知的干净参考。上传 `sample.csv` 后服务端只有观测值，因此不会显示真实 SNR；不能把这误认为生成失败。Web Agent 会搜索预处理参数，结果也可能不同于这里固定参数的离线实验。

首页截图及操作 GIF 来自实际运行的 Web 界面，示例指令使用**正弦信号 + 高斯噪声**；它与这里的**随机过程 + 混合噪声**实验是两个示例。

## 发布与更新

GitHub 仓库 Settings → Pages → Deploy from a branch → `main` / `/docs`。更新配置后重新执行生成脚本，提交生成文件即可触发静态站点更新。执行日志覆盖写入 `工程文件/代码/logs/showcase/latest.log`。

对话、上传分析、麦克风等交互功能需要本地 Python 后端，GitHub Pages 仅展示这次实验的计算结果。
