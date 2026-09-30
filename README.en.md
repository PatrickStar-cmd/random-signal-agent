# Random Signal Agent · Diting

<div align="left">

[简体中文](README.md) · **English**

**Signal simulation, filtering, and analysis**

Diting is a conversational signal analysis tool built for the Random Signals course at UESTC. Work with simulated signals, CSV/TXT files, or microphone audio in a single Web interface.

The local toolchain runs without an external model. You can also connect a Chat Completions-compatible model service.

[Live demo](https://patrickstar-cmd.github.io/random-signal-agent/) · [Experiment data](docs/README.en.md) · [MIT License](LICENSE)

## Features

- **Reproducible simulation**: choose the sample rate, duration, target frequency, and random seed.
- **Six preprocessing methods**: robust moving average, median, exponential smoothing, FFT low-pass, hybrid, and Kalman filtering.
- **Signal analysis**: time-domain statistics, FFT, correlation, AR models, Welch power spectra, and residual analysis.
- **Agent mode**: compare preprocessing methods and parameters automatically, then view analysis metrics and control recommendations.

## Interface

![Diting Web interface](docs/images/web-ui.png)

<details>
<summary>Agent mode walkthrough</summary>

Enable Agent mode and enter an acquisition command to compare preprocessing methods and view the results.

![Agent mode walkthrough](docs/images/web-demo.gif)

</details>

## Example experiment

A random process with mixed noise, sampled at **200 Hz** for **8 seconds**: **1,600 samples**, an **8 Hz** target frequency, and **seed 42**.

Preprocessing uses a robust moving average with a 7-sample window.

| Metric | Result |
| --- | ---: |
| Detected dominant frequency | 8.000 Hz |
| Original SNR | 2.859 dB |
| Processed SNR | 4.781 dB |
| SNR improvement | 1.922 dB |

[Sample CSV](docs/data/sample.csv) · [Analysis results](docs/data/result.json) · [Experiment configuration](工程文件/代码/config/showcase.json)

See the [experiment guide](docs/README.en.md) for parameters, file formats, and reproduction steps.

## Getting started

Use **Python 3.12** (supported: 3.10–3.12). The backend depends on `cgi`, which is unavailable in Python 3.13 and later.

```bash
git clone https://github.com/PatrickStar-cmd/random-signal-agent.git
cd random-signal-agent
cd "工程文件/代码"
python -m venv .venv
```

**Windows PowerShell**

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-repro.txt
python server.py --host 127.0.0.1 --port 8000
```

**Linux / macOS**

Use Python 3.12, or create the environment above with `python3.12`.

```bash
source .venv/bin/activate
python -m pip install -r requirements-repro.txt
python server.py --host 127.0.0.1 --port 8000
```

### Start an experiment

Open <http://127.0.0.1:8000> and enter this example command in Chinese:

> 采集一段 8 秒、采样率 200Hz、主频 8Hz 的正弦信号加高斯噪声，随机种子 42

The command generates an 8-second sine signal with Gaussian noise at 200 Hz, with an 8 Hz target frequency and seed 42.

For moving-average preprocessing and time/frequency analysis, enter:

> 使用滑动平均预处理并分析时域和频域特征

Alternatively, enable **Agent mode** to compare methods automatically. The same parameters and seed reproduce the same samples.

## Documentation (Chinese)

- [Code and configuration](工程文件/代码/README.md)
- [Running and configuring the project](工程文件/代码/docs/exec.md)
- [Features and validation records](工程文件/代码/docs/review.md)
- [Algorithm principles](工程文件/代码/docs/principle.md)
- [Deployment](工程文件/代码/DEPLOY.md)
- [Original PDF setup guide](工程文件/配置文档/随机信号智能体配置教程.pdf)

## License

Licensed under the [MIT License](LICENSE). Retain the license and copyright notice when using, modifying, or distributing the project.

Third-party dependencies and assets retain their respective licenses.

</div>
