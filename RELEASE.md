# v0.3.4 · Installation and deployment

Download `random-signal-agent-v0.3.4-deploy.zip` from the [v0.3.4 release](https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.3.4) and extract it; the archive contains source, Web assets, configuration, documentation and example data. Use **Python 3.12–3.14** or **Docker**. The [previous v0.1.0 release](https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.1.0) remains available and requires Python 3.12.

Open a terminal in `random-signal-agent/工程文件/代码` (or `random-signal-agent-v0.3.4/工程文件/代码` in a deployment archive).

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

On Windows, use `Copy-Item .env.example .env` for the first command. Experiments, uploads and outputs are stored in the mounted `data/`, `uploads/` and `outputs/` folders and survive container restarts. Run one backend process; session locks are local to that process.

Open <http://127.0.0.1:8000>. No model API key is required for simulation, preprocessing, and analysis. For external models or server hosting, see [deployment configuration](工程文件/代码/DEPLOY.md).

## Verify a running service

From another terminal with the same Python environment:

```bash
python scripts/smoke_deployment.py --base-url http://127.0.0.1:8000
```

The check covers health, Web assets, Agent mode, streaming responses, CSV upload, and synthetic audio download. Browser microphone access requires localhost or HTTPS. GitHub Pages hosts the experiment preview; the complete application runs with the Python backend.

`SHA256SUMS.txt` verifies the deployment ZIP; `RELEASE.json` inside it records the version and source commit. The package contains no virtual environment, API keys, uploaded files, or local logs.

## 中文说明

下载 v0.3.4 部署包并解压，进入 `工程文件/代码` 后按上方命令启动。支持 Python 3.12–3.14，依赖版本在 `requirements-repro.txt` 固定。也可使用 Docker Compose；默认地址为 <http://127.0.0.1:8000>。实验可导出 ZIP，升级前停止服务并备份整个 `data/` 目录。

完整应用包含对话、分析、上传及音频处理，不需要外部模型密钥即可使用本地工具链。服务器部署、模型配置与日志查看见[部署说明](工程文件/代码/DEPLOY.md)。

## Upgrading from v0.2.0 / v0.2.1 / v0.2.5 / v0.2.6 / v0.3.0

Stop the old service and back up the entire `data/` directory, then copy it into the new deployment at the same relative location (or keep `RS_AGENT_DATA_DIR` pointing to it). Keep `uploads/` and `outputs/` to retain file and audio attachments. Restart using the same host and browser profile so its session ID is preserved. v0.2.0/v0.2.1/v0.2.5/v0.2.6 snapshots and experiment ZIPs remain readable: schema 1 and algorithm 0.2.0 are unchanged. No database reset is needed.

Upgrades from v0.2.0/v0.2.1 add an operation-label column to the task database (introduced in v0.2.5). Existing results remain intact. To roll back to an older application, restore the pre-upgrade data backup rather than reusing the migrated database. Run only one backend process against a data directory.

The new import wizard accepts UTF-8 CSV/TXT and validates selected columns before changing the workspace. Task cancellation is cooperative; an external request or native calculation must reach a checkpoint before it stops. Storage cleanup requires a preview and confirmation and only removes unreferenced NPZ files; it does not delete task history, uploads or audio.

## Diagnostic laboratory (introduced in v0.2.6)

Load the fault demo in the diagnostic laboratory to inspect time-frequency evidence. Locate an event or drag a time range, run a processing trial, and inspect before/after metrics. True error is available only with a clean reference. Adopt a trial and save it as a snapshot. Blind mode hides truth and reference error until reveal; full experiment export and snapshot comparisons are blocked until then, while the diagnostic report remains available.

在“信号诊断实验室”载入故障演示，查看时频图与证据卡片。点击“定位波形”或拖动时频图选择区间，运行验证实验查看前后变化；只有存在干净参考时显示真实误差。采用结果后可保存快照。盲测在揭晓前隐藏真值和参考误差，禁止完整实验导出与快照对比；独立诊断报告可导出。

Back up the entire `data/` directory before upgrading. Schema 1 and preprocessing algorithm 0.2.0 remain readable; diagnostic configuration has its own version 1.0. No additional production dependencies are required.

## Model API setup and ocean UI (introduced in v0.3.0)

Open **模型与设置 → 模型 API 配置**. Choose OpenAI, DeepSeek or a custom Chat Completions-compatible endpoint, enter your own key, load/select a model and choose **测试并应用**. Configuration takes effect for the current browser session without restarting. You can return to local mode or clear the configuration at any time. No external model is needed for the built-in signal tools.

Keys are held in server memory by default. Opting into **记住配置** stores the key in plaintext in `data/model-settings.sqlite3`; protect this file and any data backups. Browser storage, task history and experiment ZIPs do not contain keys. An existing `.env` configuration remains the service default. See the [model setup guide](工程文件/代码/docs/model-api-setup.md) for endpoint and parameter compatibility.

The package includes the six-view ocean interface, transparent AI-generated whale artwork, responsive charts and all local styles/scripts. GitHub Pages is a static preview; API configuration and interactive experiments require the Python backend.

打开“模型与设置 → 模型 API 配置”，选择服务、输入自己的 Key、读取模型列表并“测试并应用”，无需重启。默认只在服务内存保存；勾选“记住配置”后会将 Key 明文写入 `data/model-settings.sqlite3`，需保护该文件及数据备份。可随时切回本地模式或清除配置。v0.3.4 部署包已包含海洋界面及所有图片资源；GitHub Pages 仍为静态预览。

## PDF analysis reports (v0.3.4)

In **模板与实验 → PDF 分析报告**, enter report details, choose brief/standard, preview the summary, then download. Reports currently use Chinese and include measured results, vector plots and reproduction information; existing comparison and diagnosis sections appear when available. No model key is required. Blind experiments must be revealed first; true SNR/RMSE need a clean reference.

Reinstall requirements-repro.txt when upgrading from v0.3.0: ReportLab, Pillow and charset-normalizer are new pinned runtime dependencies. The package includes an OFL-licensed Chinese font (about 10 MiB) for offline PDF generation, plus its license. No browser, external converter or system Chinese font is needed. Existing data and algorithm versions remain unchanged. See the [report guide](工程文件/代码/docs/pdf-report.md) and [example](docs/report-example.pdf).

完成采集/恢复实验后，打开“模板与实验 → PDF 分析报告”，填写信息，预览再下载。升级 v0.3.0 时重新安装固定依赖；中文字体及许可证已随包交付，无需系统字体或外部转换器。报告不包含 Key、聊天或服务器路径，旧实验数据可继续读取。

## Multi-result PDF reports (introduced in v0.3.2)

Choose **报告数据 → 选择处理历史 / 已保存实验** in the PDF report panel. Select 1–50 groups in total, including saved snapshots if needed; choose the time order, preview and download. Each group retains its own full-sample metrics and vector plots. A shared cover, summary, clickable contents, PDF bookmarks and continuous page numbers keep long reports navigable.

Successful processing tasks retain the latest 50 final results per browser session across server restarts. Retries do not duplicate a task; ordinary questions, opening snapshots, failed or cancelled tasks do not add results. Older unsaved results from before this upgrade cannot be recovered. Blind records created before reveal remain locked; reveal the current experiment to create an exportable result.

Stop the service and back up the entire `data/` directory before upgrading. The existing `experiments.sqlite3` gains a `report_history` table automatically; experiment schema 1 and algorithm 0.2.0 stay unchanged. Confirmed storage cleanup protects arrays referenced by both history and saved snapshots. Reinstall the pinned requirements or rebuild Docker after replacing the source.

在 PDF 报告中选择“处理历史 / 已保存实验”，勾选最近 50 次以内的结果，可补充手动快照，合计最多 50 组。选择顺序并预览后下载；统一封面、汇总、可跳转目录与逐组图表，历史重启后保留。升级前未保存的数据无法补回；先停止服务并备份整个 data/，新历史表会自动创建。

## Clearer modules and concise UI (introduced in v0.3.3)

All six views use 2 px blue-lilac borders for panels, charts and result cards. Instructions focus on actions and results; PDF preview data notes expand on demand. The ocean artwork, gradient background, signal algorithms and recent-50-result PDF workflow remain available. Screenshots and the GitHub Pages preview reflect this UI.

From v0.3.2, replace the source and restart the service, or rebuild Docker. Keep the existing data directory and browser session, then refresh the page to load the new styles. Runtime dependencies, experiment schema 1 and algorithm 0.2.0 are unchanged.

v0.3.3 加粗六个分区的模块框线，精简重复解释及防御性文案，PDF 预览中的数据说明按需展开。由 v0.3.2 升级时保留数据目录，替换源码并重启服务（或重建 Docker），刷新浏览器即可；依赖与数据格式保持一致。

## Richer ocean interface (v0.3.4)

Cyan, lavender and coral-pink gradients, local SVG waves, 4 px outer frames and 2 px inner cards give the six views stronger visual structure. Chinese text uses STZhongsong when installed; Latin text and numbers use Times New Roman. Charts follow the same font stack. Fonts are read from the visitor’s computer and fall back to available serif fonts; commercial fonts are not bundled.

The clock is larger and bold, with the local-computing badge below it. Agent method comparisons separate conclusions, recommendations, metrics and next steps; all method results remain available in expandable details. Historical replies retain their original values.

From v0.3.3, stop the service, back up and retain data/, replace the source, restart or rebuild Docker, and refresh the browser. Production dependencies, experiment schema 1 and algorithm 0.2.0 are unchanged.

v0.3.4 提供更丰富的海洋渐变、双层框线、华文中宋与 Times New Roman 字体、加粗时钟及更清晰的 Agent 回复。由 v0.3.3 升级时保留 data/，替换源码并重启服务或重建 Docker，再刷新浏览器。
