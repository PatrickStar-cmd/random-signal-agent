# Changelog

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
