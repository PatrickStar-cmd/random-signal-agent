# Changelog

## Unreleased

- AI-generated dimensional whale/starfish artwork, transparent WebP delivery (~143 KiB), richer ocean/lilac/pink gradients and restrained decorative emoji. Mobile artwork sits below the copy; preview and README screenshots stay in sync.

- Cute ocean UI: blue/lilac surfaces, original whale illustration, six persistent workspace views, responsive layout and accessible navigation.
- Chart colors match the light theme, wrapped legends reserve space, diagnostic trial plots survive view changes, and completed tasks correctly show completion. Updated preview and bilingual README screenshots.

- Per-session model API setup with provider presets, dynamic model lists, text connection tests, immediate application and optional restart persistence.
- Keys are separate from experiment snapshots/task history; browser storage contains no keys. Local mode, configuration removal, compatible token parameters and safe error reporting.

新增模型 API 配置向导与可爱海洋界面，待后续版本发布。

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
