# Experiment data

<div align="left">

[简体中文](README.md) · **English**

[Live demo](https://patrickstar-cmd.github.io/random-signal-agent/) · [Project home](../README.en.md)

This experiment compares six preprocessing methods on a random process with mixed noise, using the same input samples and fixed parameters.

## Reproduce the experiment

With Python 3.12, run the following commands from `工程文件/代码`:

```bash
python -m pip install -r requirements-repro.txt
python scripts/build_showcase.py
```

The experiment uses a random process with mixed noise, containing **1,600 samples**. Its configuration is in [`config/showcase.json`](../工程文件/代码/config/showcase.json) and matches `run_demo.py`.

| Parameter | Value |
| --- | ---: |
| Sample rate | 200 Hz |
| Duration | 8 seconds |
| Target frequency | 8 Hz |
| Amplitude | 1.2 |
| Noise standard deviation | 0.55 |
| AR coefficient | 0.86 |
| Impulse probability | 0.012 |
| Random seed | 42 |

With a 7-sample robust moving average, the detected dominant frequency is **8 Hz**. SNR improves from **2.859 dB** to **4.781 dB**, a gain of **1.922 dB**.

Filter performance depends on the signal and parameters. Dependency versions and platforms may affect the last digits of floating-point results.

## Data files

| File | Contents |
| --- | --- |
| [`sample.csv`](data/sample.csv) | Two columns: time and observed values. Suitable for upload to the local Web interface. |
| [`reference.csv`](data/reference.csv) | Four columns: time, clean reference, observations, and processed values. For offline comparison, rather than direct upload as observations. |
| [`result.json`](data/result.json) | Generation environment, configuration, analysis metrics, execution trace, and results for all six filters. |

SNR is calculated against the clean simulation signal. `sample.csv` contains only observations, so true SNR is not calculated after upload.

Web Agent mode searches preprocessing parameters automatically and may produce different results from this fixed-parameter experiment.

The screenshots and walkthrough on the project home page use a **sine signal with Gaussian noise**. This experiment uses a **random process with mixed noise**.

Run log: `工程文件/代码/logs/showcase/latest.log`.

</div>
