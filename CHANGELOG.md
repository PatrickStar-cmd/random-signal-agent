# Changelog

## v0.3.1 · 2026-10-08

- Single-experiment Chinese PDF reports: title, author, purpose and units; preview the measured summary/sections, then download a brief or standard edition.
- A4 ocean cover, embedded searchable Chinese font, vector waveform/FFT/Welch PSD/autocorrelation plots, available method comparisons and diagnostics, full-sample metrics and reproduction hashes/parameters.
- Evidence-based wording for absent references, degraded processing, constant/short/nonuniform data; blind experiments require reveal. Reports exclude model keys, chat history and server paths.
- Frozen-state calculation and content tokens reject stale previews; bounded concurrent rendering and page/input limits. Fix diagnostic heatmap layout and retain actual filter parameters.
- 14 PDF acceptance tests plus desktop/mobile download checks and page-by-page visual inspection. Fresh-package validation now covers font/license and live PDF download; pinned ReportLab/Pillow/charset-normalizer ship with an OFL Chinese font.
- Bilingual README, current screenshots, PDF example and static preview updated. Experiment schema 1 and algorithm 0.2.0 are unchanged.

新增无需模型 Key 的中文 PDF 报告，支持简版/标准版、预览与下载。升级 v0.3.0 后重新安装固定依赖；中文字体随包交付。旧实验继续可读，升级前停止服务并备份数据。

## v0.3.0 · 2026-10-06

- Model API setup in the browser: OpenAI, DeepSeek and custom Chat Completions-compatible providers, dynamic model lists, text connection tests and immediate per-session application without restarting. Optional restart persistence, local-mode switching and configuration removal.
- API keys stay out of browser storage, experiment snapshots, exports and task history. Endpoint changes never reuse a saved key automatically; compatible token parameters and redacted errors support different providers. Opt-in persistence stores keys in plaintext on the server.
- Cute ocean interface with six persistent views, blue/lilac/mint/pink gradients, rounded cards, keyboard and history navigation, desktop/tablet/mobile layouts and reduced-motion support.
- AI-generated 3D whale/starfish artwork delivered as a transparent 143 KiB WebP; preview, artwork documentation and bilingual README stay in sync. All assets ship locally in the deployment package.
- Fix wrapped chart legends, preserve diagnostic trial plots across view changes and show completed tasks correctly. Example prompts fill the input for review before sending.
- Release smoke checks now verify the application version, packaged ocean/model-settings assets and model configuration endpoint alongside existing experiment, diagnostic and restart checks. Schema 1 and algorithm 0.2.0 remain unchanged.

新增页面内模型 API 配置，统一发布海洋 UI、AI 鲸鱼插画与图表/任务提示修复。升级前停止服务并备份整个 `data/`；若启用“记住配置”，备份包含明文 Key，需妥善保护。本地工具链仍无需 Key。

## v0.2.6 · 2026-10-06

- Diagnostic laboratory with relative-time STFT/PSD, linked waveform and interval selection, explicit resolution, edge padding and bounded display grids.
- Six seeded fault types, editable intervals, blind truth protection and reveal-only typed interval precision/recall/F1. Detectors use observations only.
- Evidence cards with alternative interpretations; local notch, median, detrend and interpolation trials show interval energy/error and preserve raw observations. Stale trials cannot be adopted.
- Durable diagnostic tasks, chat diagnosis, snapshot/package round trips and standalone diagnostic HTML reports. Old schema 1 / algorithm 0.2.0 snapshots remain readable.
- 16 diagnostic acceptance tests, SciPy PSD reference checks, maximum-size input, browser flow and deployment/restart coverage.

新增“信号诊断实验室”：时频定位、故障盲测和可验证处理建议。检测为启发式特征提示；频带能量降低不等于真实信号恢复。升级前备份整个 data/。

## v0.2.5 · 2026-10-05

- CSV/TXT import wizard with preview, selectable time/signal columns, time-unit conversion, source provenance, and row/column diagnostics. Invalid rows are never silently discarded by the wizard.
- Read-only comparison of 2–4 saved results with shared-axis waveform/spectrum plots, full-sample metrics, parameters and portable HTML reports. Scores are only compared for matching inputs, references, goals and scoring versions.
- Task history, queue state and cooperative cancellation with current-state rollback. Fair per-session dispatch prevents blocked sessions from occupying all workers.
- Automatic idle-session eviction and reload, storage usage, and confirmed cleanup of unreferenced sample arrays with preview revalidation and save/load locking.
- Three-step navigation, collapsible management panels, compact numeric inputs and improved mobile spacing.
- Existing experiment schema and algorithm version remain unchanged. Task database migration preserves results; downgrades require restoring a pre-upgrade backup.

新增数据导入向导、跨实验对比、任务取消和存储管理。旧快照和 ZIP 可继续使用；升级前备份整个 data/。

## v0.2.1 · 2026-10-05

- Search saved experiments by name; rename or delete a selected snapshot with deletion confirmation. Current data and other snapshots remain intact.
- Preserve complete names containing ` · `, validate duplicate/rename names consistently, and clear stale chat when restoring an empty history.
- Reuse the current signal after running/restoring; generation parameters are disabled in comparison-only mode to prevent accidental regeneration.
- Keep progress streaming after the 256-event replay buffer wraps and drain final tool events before completion.
- Allow retries to switch synchronous/asynchronous transport without duplicate execution; preserve v0.2.0 task replay and protect the internal operation identifier.
- Separate application and algorithm versions: existing v0.2.0 snapshots, autosaves and ZIPs remain readable without resetting the database.
- Release verification selects its archive from configuration instead of a hard-coded version.

新增快照搜索、重命名和删除，修复名称截断、旧聊天残留、比较时误生成信号及长任务进度中断。应用版本更新为 0.2.1，保存格式仍为 schema 1 / algorithm 0.2.0；升级前备份整个 data/。

## v0.2.0 · 2026-10-02

- Persistent experiment workbench with named snapshots, duplication, automatic recovery, and portable ZIP import/export.
- Full-resolution CSV, standalone HTML reports and versioned parameter/data manifests with SHA-256 validation.
- Sine, impulsive-noise and AR(1) templates, a parameter panel and three comparison goals.
- Method-neutral score breakdowns, search timings and explicit no-reference diagnostics; removed the hybrid-only score bonus.
- FastAPI/Uvicorn replaces the legacy `cgi` server. Bounded tasks, durable request IDs, per-session serialization and actual execution progress prevent duplicate retry work.
- Extrema-preserving plotting, split frontend assets, input/resource limits and bounded parameter searches.
- Windows/Linux Python 3.12–3.14 clean-install matrix, Docker restart persistence checks and 540 fixed-seed numerical benchmark cases.

实验从一次性对话升级为可保存、可恢复、可导出的工作台。保存格式为 schema 1 / algorithm 0.2.0；旧版尚无持久化实验格式。

## v0.1.0 · 2026-09-30

First public release of Diting, the Random Signal Agent for the UESTC Random Signals course.

- Conversational Web interface with simulated signals, CSV/TXT upload, and microphone audio processing.
- Six preprocessing methods, automatic parameter comparison, time/frequency features, AR models, Welch spectra, and residual analysis.
- Fixed-seed experiment data and a static online preview.
- English and Chinese README, screenshots, walkthrough, and MIT License.
- Input validation fixes for malformed requests, invalid samples, CSV time axes, and encoded file paths; corrected spectrum and shared-axis rendering.
- Python 3.12 deployment package with pinned NumPy, checksums, clean-install checks, and Docker Compose health checks.

首个公开版本，包含完整信号分析工具链、双语说明与部署材料。支持本地 Python 服务和 Docker Compose；GitHub Pages 提供实验预览。
