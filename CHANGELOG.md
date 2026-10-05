# Changelog

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
