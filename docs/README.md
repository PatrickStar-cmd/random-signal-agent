# Experiment data · 实验数据

<details name="readme-language">
<summary><strong>简体中文</strong></summary>

<div align="justify">

[在线演示](https://patrickstar-cmd.github.io/random-signal-agent/) · [项目首页](../README.md)

本实验比较六种预处理方法对随机过程与混合噪声的处理效果，使用相同的输入样本和固定参数。

## 复现实验

在 Python 3.12 环境下，进入 `工程文件/代码`：

```bash
python -m pip install -r requirements-repro.txt
python scripts/build_showcase.py
```

配置在 [`config/showcase.json`](../工程文件/代码/config/showcase.json)，与 `run_demo.py` 的默认实验一致：200 Hz、8 秒、8 Hz 主频、幅值 1.2、噪声标准差 0.55、AR 系数 0.86、脉冲概率 0.012、种子 42；信号为随机过程，噪声为混合噪声。共 1600 点。

鲁棒滑动平均采用 7 点窗口，检测主频为 8 Hz；原始 SNR 约 2.859 dB，处理后约 4.781 dB，提升约 1.922 dB。不同方法的效果随信号和参数而变化；依赖版本和平台可能影响浮点数末位。

## 数据文件

| 文件 | 用途 |
| --- | --- |
| [`sample.csv`](data/sample.csv) | 两列：时间、观测值。可直接上传到本地 Web 界面。 |
| [`reference.csv`](data/reference.csv) | 四列：时间、干净参考、观测值、处理结果。用于离线核对，不能作为观测值直接上传。 |
| [`result.json`](data/result.json) | 生成环境、完整配置、分析指标、执行轨迹及六种滤波结果。 |

SNR 以仿真干净信号为参考。`sample.csv` 仅包含观测值，上传后不计算真实 SNR。Web Agent 会自动搜索预处理参数，与本实验的固定参数结果可能不同。

首页的界面截图和操作演示使用**正弦信号 + 高斯噪声**，本实验使用**随机过程 + 混合噪声**。

运行日志：`工程文件/代码/logs/showcase/latest.log`。

</div>

</details>

<details name="readme-language" open>
<summary><strong>English</strong></summary>

<div align="justify">

[Live demo](https://patrickstar-cmd.github.io/random-signal-agent/) · [Project home](../README.en.md)

This experiment compares six preprocessing methods on a random process with mixed noise, using the same input samples and fixed parameters.

## Reproduce the experiment

With Python 3.12, run the following commands from `工程文件/代码`:

```bash
python -m pip install -r requirements-repro.txt
python scripts/build_showcase.py
```

The configuration is in [`config/showcase.json`](../工程文件/代码/config/showcase.json) and matches the default experiment in `run_demo.py`: a sample rate of 200 Hz, an 8-second duration, an 8 Hz target frequency, amplitude 1.2, noise standard deviation 0.55, AR coefficient 0.86, impulse probability 0.012, and seed 42. The signal is a random process with mixed noise, containing 1,600 samples.

With a 7-sample robust moving average, the detected dominant frequency is 8 Hz. The original SNR is approximately 2.859 dB, the processed SNR is 4.781 dB, and the improvement is 1.922 dB. Filter performance depends on the signal and parameters; dependency versions and platforms may affect the last digits of floating-point results.

## Data files

| File | Contents |
| --- | --- |
| [`sample.csv`](data/sample.csv) | Two columns: time and observed values. Suitable for upload to the local Web interface. |
| [`reference.csv`](data/reference.csv) | Four columns: time, clean reference, observations, and processed values. For offline comparison, rather than direct upload as observations. |
| [`result.json`](data/result.json) | Generation environment, configuration, analysis metrics, execution trace, and results for all six filters. |

SNR is calculated against the clean simulation signal. `sample.csv` contains only observations, so true SNR is not calculated after upload. Web Agent mode automatically searches preprocessing parameters and may produce different results from this fixed-parameter experiment.

The screenshots and walkthrough on the project home page use a **sine signal with Gaussian noise**. This experiment uses a **random process with mixed noise**.

Run log: `工程文件/代码/logs/showcase/latest.log`.

</div>

</details>
