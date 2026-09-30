# Random Signal Agent · Diting

<div align="justify">

[简体中文](README.md) · **English**

**A signal analysis agent for the Random Signals course at UESTC**

Diting brings signal simulation, filter comparison, time and frequency analysis, and random-process analysis into a conversational Web interface. It also supports CSV/TXT files and microphone audio.

The local toolchain runs without an external model. A Chat Completions-compatible model service can be connected for additional capabilities.

[Live demo](https://patrickstar-cmd.github.io/random-signal-agent/) · [Experiment data](docs/README.en.md) · [MIT License](LICENSE)

## Features

![Diting Web interface](docs/images/web-ui.png)

- **Experiments through conversation**: set the sample rate, duration, target frequency, and random seed to generate reproducible signals.
- **Automatic filter comparison**: robust moving average, median filtering, exponential smoothing, FFT low-pass filtering, hybrid filtering, and Kalman filtering, with curves and parameter comparisons.
- **Signal and random-process analysis**: time-domain statistics, FFT, correlation, AR models, Welch power spectra, and residual analysis.
- **Multiple inputs**: simulated signals, CSV/TXT files, and browser microphone audio, with analysis metrics and control recommendations.

Enable Agent mode and enter an acquisition command to compare preprocessing methods and view the results.

![Agent mode walkthrough](docs/images/web-demo.gif)

## Example experiment

Seed 42, a sample rate of 200 Hz, an 8-second duration, an 8 Hz target frequency, and 1,600 samples. The input combines a random process with mixed noise; preprocessing uses a robust moving average with a 7-sample window.

| Metric | Result |
| --- | ---: |
| Detected dominant frequency | 8.000 Hz |
| Original SNR | 2.859 dB |
| Processed SNR | 4.781 dB |
| SNR improvement | 1.922 dB |

[Sample CSV](docs/data/sample.csv) · [Analysis results](docs/data/result.json) · [Experiment configuration](工程文件/代码/config/showcase.json)

See the [experiment guide](docs/README.en.md) for parameters, file formats, and reproduction steps.

## Getting started

Requirements: **Python 3.10–3.12**, preferably 3.12. The backend uses `cgi` and does not currently support Python 3.13 or later.

```bash
git clone https://github.com/PatrickStar-cmd/random-signal-agent.git
cd random-signal-agent
cd "工程文件/代码"
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-repro.txt
python server.py --host 127.0.0.1 --port 8000
```

Linux/macOS (use Python 3.12, or create the environment with `python3.12`):

```bash
source .venv/bin/activate
python -m pip install -r requirements-repro.txt
python server.py --host 127.0.0.1 --port 8000
```

### Start an experiment

Open <http://127.0.0.1:8000> and enter this example command in Chinese:

> 采集一段 8 秒、采样率 200Hz、主频 8Hz 的正弦信号加高斯噪声，随机种子 42

This generates an 8-second sine signal with Gaussian noise at a sample rate of 200 Hz and a target frequency of 8 Hz, using seed 42.

Then enter “使用滑动平均预处理并分析时域和频域特征” to apply moving-average preprocessing and analyze time and frequency features, or enable Agent mode to compare methods automatically. The same parameters and seed reproduce the same samples.

## Documentation (Chinese)

- [Code and configuration](工程文件/代码/README.md)
- [Running and configuring the project](工程文件/代码/docs/exec.md)
- [Features and validation records](工程文件/代码/docs/review.md)
- [Algorithm principles](工程文件/代码/docs/principle.md)
- [Deployment](工程文件/代码/DEPLOY.md)
- [Original PDF setup guide](工程文件/配置文档/随机信号智能体配置教程.pdf)

## License

This project is licensed under the [MIT License](LICENSE). Retain the license and copyright notice when using, modifying, or distributing it. Third-party dependencies and assets retain their respective licenses.

</div>
