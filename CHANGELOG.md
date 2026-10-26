# Changelog

## Unreleased

## v0.4.9 · 先进收发算法与实验调试增强 · 2026-10-26

- 🔍 新增 LMMSE 信道估计、Kalman 复信道跟踪、按流有效噪声 MIMO 软检测，接入 LDPC、软 Viterbi 与实际 HARQ。
- 🌊 新增 DFT-s-OFDM / SC-FDMA 的 DFT 扩展、连续/交织映射、FFT 均衡与 IDFT 解扩；新增记忆多项式功放、回环训练、逆模型拟合和数字预失真。
- ⏱️ 新增 Schmidl–Cox / Zadoff–Chu 突发同步、帧延迟与采样频偏信道、频偏和采样时钟恢复，支持 I/Q 录波回放。
- 🛡️ 新增 Polar 编码、SC / CRC 辅助 SCL 译码，开放码长、码率、冻结位构造参数和列表宽度。
- 🧭 新增均匀线阵、角度多径、定向干扰、MRT / SVD 预编码、常规 / MVDR 合并，展示导频 CSI、方向图与有效噪声。
- 🧰 新增条件断点、指定积木断点、批量/二维/目标搜索检查点续跑、统计图、同种子差值和单条记录复跑。
- 🎓 新增学生模式、阶段独立提交、尝试与提示记录、作业包；空间观察联动资源/用户/队列/矩阵/星座/SIC，报告支持素材选择、图注与结论。
- 🌊 保留海洋风格和原有功能；新增 24 个积木、19 个预设，总计 217 个可添加积木、固定信宿与 109 个预设。

## v0.4.8 · 闭环链路与空间通信增强 · 2026-10-25

- 🔁 自建物理链路接入 ARQ、Chase HARQ 与 AMC，实际执行调制、信道、同步、检测及译码，展示软合并、反馈延迟、重传和空口吞吐。
- 🧩 新增版本化子工程：类型端口、公开参数、多实例独立状态、展开编辑、更新版本和 JSON 分享。
- 🛰️ 新增 ZF-SIC/MMSE-SIC、动态空间相关 MIMO、周期导频跟踪、MIMO-OFDM、独立用户 OFDMA 与 FHSS，共 14 个无线积木与 11 个预设。
- 📡 新增 I/Q 录波信源与回放预设，支持 SigMF、cf32/cf64/ci16 原始复采样、当前观测导出及接收积木回放。
- 📊 新增天线波形、空间流星座、信道幅相矩阵、条件数、SIC 逐层残差、Alamouti 时隙、OFDMA 资源与队列、FHSS 时频图。
- 🎓 新增教学任务编辑器、开放参数与分阶段验收、实验包分享、跨工程多种子批量队列和最低信噪比目标搜索。
- 🌊 保留海洋风格、原有功能及工程格式，新增模块沿用统一控件、分析标签和窄屏布局；共 193 个可添加积木、固定信宿与 90 个预设。

## v0.4.7 · 业务传输与教学实验增强 · 2026-10-23

- 🎙️ 新增音频、图像、文件和离散概率信源；信宿播放音频、重建图像、下载文件，显示 RMSE / SNR / PSNR 与 SHA256。
- 🗜️ 新增 Huffman、IMA ADPCM、BCH (15,7)、RS (255,223) 编译码及分包 / 组包，连接真实收发链路与业务字节。
- 📡 新增 DSSS、码捕获、相关解扩、RAKE、SIMO SC/MRC、Alamouti 2×1、2×2 MIMO ZF/MMSE；公共训练估计接收参数，完整保留多天线数组。
- 🧮 新增工程变量与参数公式、二维扫描与网格点恢复、算法逐步演示、9 项教学挑战、工程 / 结果差异、可运行 Python 与 JSON / SVG 输出。
- 📦 新增 ARQ / Chase HARQ 包级反馈和五档 AMC 实验，观察 ACK/NACK、超时、软合并、反馈延迟、切换滞回及 goodput。
- 🌊 保留海洋风格、原有算法和工程体验；共 178 个可添加积木、固定信宿与 78 个示例。升级时保留 data/、uploads/、outputs/，更新源码并重启服务或重建 Docker，刷新浏览器。

## v0.4.6 · 界面布局与交互优化更新 · 2026-10-18

- 🧭 合并工程工具栏，新增可搜索与按主题筛选的实验库，集中工程、调试和实验参数入口。
- 🎛️ 桌面优先显示选中积木参数，信宿观察可切换；窄屏提供四个工作区入口和底部参数抽屉。
- 📊 统一结果总览、信号观察、射频测量和性能对照，支持收起、大图和集中数据导出。
- 🧾 修正旧工程任务选择恢复，结果注明任务、时间、种子及参数，切换待运行任务时保留明确归属。
- 🧱 批量选择独立开启，次要按钮随选中、悬停和聚焦显示；保留海洋风格、全部模块和旧工程功能。
- 升级时保留 data/、uploads/、outputs/，更新源码并重启服务或重建 Docker，再刷新浏览器；无新增生产依赖。

## v0.4.5 · 真实收发链路与实验分析更新 · 2026-10-18

- 新增 20 个积木：8PSK/64QAM/256QAM 硬软调制解调、I/Q 失真与训练校正、DC 偏置/消除、Rapp/Saleh 功放、ADC、OFDM 削峰、窄带干扰/陷波及卷积码打孔/解打孔。
- OFDM 开放有效子载波数与导频间隔，新增资源栅格、逐子载波信道/EVM；完整帧 Welch、CCDF、PAPR、99% 占用带宽与可配置 ACLR。
- 新增 A/B 互相关时延对齐、净信息速率与频谱效率、AWGN 高阶调制理论近似、7 项任务对照；扫描与 JSON/CSV/PDF 同步支持新指标。
- 保留海洋视觉、现有功能与 schema 1/2 工程；150 个可添加模块、64 个示例。增加物理/数学独立检验，旧套件与 540 组算法基准继续验证。
- 升级：保留 data/、uploads/、outputs/，替换源码并重启服务或重建 Docker，再刷新浏览器；无新增生产依赖。

## v0.4.2 · 积木编程视图更新 · 2026-10-12

- 采用统一海洋配色、4 px 外框、六类表情积木工坊和 3 px 未选中积木边框；Build / Run 增加表情。
- 编程区使用紧凑拼接积木、参数摘要和选中高亮，完整参数移到独立面板；符号同步、均衡和高级参数分组展开。
- 保留全部模块与 29 个示例、拖放/排序、撤销重做、Build/Run、草稿恢复、工程 JSON 和完整 CSV/结果 JSON；保留波形、频谱、眼图、时钟及收敛分析。
- 参数变化使旧 Build 失效，未选中或折叠的非法参数自动定位；工程替换确认支持键盘取消，去除页面中的防御性描述。
- 更新真实截图、双语文档、静态预览和部署 ZIP。依赖、通信工程 schema 1、已有数据与数值算法保持兼容。

Upgrade from v0.4.1 by retaining data/, replacing source and restarting the service or rebuilding Docker, then refreshing the browser. No new runtime dependencies or migration are needed.

## v0.4.1 · 传输环节模块补充 · 2026-10-12

补充第三、四章传输环节：细分发/收转换器与调制/解调器，新增模拟调制、线路编译码、实基带信道、符号同步和固定/自适应均衡。提供 29 个示例、波形/频谱/眼图/时钟/收敛观测，保留旧工程与实验数据兼容性。由 v0.4.0 升级时保留 data/、替换源码并重启服务或重建 Docker，再刷新页面；无新增生产依赖。

- Add nonlinear clock acquisition, early/late and Gardner PI timing loops, sample clock drift, fixed-response DFE and public-preamble-trained linear/DFE equalizers with LMS/NLMS/RLS and optional decision-directed tracking. Include actual preamble transmission/overhead, clock/convergence plots, seven presets and 12 numerical cases; all 22 previous preset results and Build tokens remain identical. Document coarse-frame assumptions and feedback error propagation.
- Add ten course line-code encoder/decoder pairs (NRZ/RZ polarities, differential, AMI, Manchester, Miller, CMI and HDB3/HDBn), sampled real baseband and 2–256-PAM transmission, six pulse shapes, real sample-SNR and band-limited AWGN, low-pass/band-pass/AC-coupled/FIR ISI/timing channels, matched/low-pass receivers and finite ZF/regularized MMSE equalization. Include eye diagrams, 12 presets and 13 numerical/API cases with independent course vectors; retain all ten previous preset results.
- Add the course's six analog modulation/demodulation pairs: AM, DSB-SC, SSB, VSB, FM and PM; include AM envelope/coherent detection, SSB Hilbert/filter implementations and selectable sidebands, complementary VSB filtering, full angle modulation and a narrowband FM preset. Add analog sample-SNR noise, waveform/spectrum views, recovery metrics and 10 numerical acceptance cases while preserving existing digital results.
- Split the communication block palette into sources, transmit converters, modulators, channels, demodulators and receive converters; distinguish each category by color and show the full processing order. Existing project JSON, drafts and simulation behavior remain compatible.

## v0.4.0 · 通信原理积木编程 · 2026-10-12

- Add a Scratch-inspired communication lab with an editable block pipeline and a fixed sink, separate Build/Run steps, and default TV snow until a simulation completes.
- Combine analog/digital sources, PCM, repetition/Hamming/convolutional coding and interleaving; BPSK/QPSK/16-QAM; AWGN, attenuation, phase rotation and symbol erasures; paired hard-decision receivers.
- Show full-frame BER, effective coding rate, EVM and analog RMSE; inspect sink windows, decision-input constellations and pre-compensation channel I/Q. Preserve reproducible seeds, draft recovery, undo/redo, portable project JSON and full sink CSV/result JSON.
- Validate pipeline types, pairing, bounds and compiled configuration; limit simultaneous runs and release capacity on failure. Add 14 numerical/API cases and deployment coverage, with desktop/mobile browser checks.
- Ship bilingual documentation, actual screenshots, static preview and a verified deployment ZIP. Keep existing signal experiments, report history, dependencies, experiment schema 1 and algorithm 0.2.0 compatible.

新增通信原理积木实验室，随 v0.4.0 部署包交付。由 v0.3.4 升级时保留 data/，替换源码并重启服务或重建 Docker，再刷新浏览器。


## v0.3.4 · 2026-10-10

- Add cyan, lavender and coral-pink gradients, local SVG waves and subtle bubbles throughout the ocean interface.
- Use 4 px outer frames and 2 px inner cards across all six views and the static showcase.
- Use STZhongsong for Chinese text and Times New Roman for Latin text and numbers, including Canvas labels, with local serif fallbacks.
- Enlarge and bold the live clock; place the local-computing badge below it.
- Structure complete Agent method comparisons into conclusions, recommendations, measured metrics and next steps. Preserve every method and parameter in expandable details, historical measurements, Markdown fallback and HTML escaping.
- Refresh bilingual documentation, screenshots, deployment assets and release checks. Runtime dependencies, experiment schema 1 and algorithm 0.2.0 remain unchanged.

丰富海洋渐变、加粗分层框线、调整中英文字体与时钟，改善 Agent 回复排版。由 v0.3.3 升级时保留 data/，替换源码并重启服务，再刷新页面。


## v0.3.3 · 2026-10-10

- Use consistent 2 px blue-lilac borders across all six views, including chart frames, report selections, diagnosis cards, API settings, tasks and storage.
- Shorten repeated and defensive UI explanations. Keep result-specific reference/score information, validation errors, deletion confirmations and API persistence/billing details at their relevant controls.
- Collapse PDF preview data notes by default; preserve the full report and recent-50-result export workflow.
- Refresh bilingual README screenshots and GitHub Pages styles/copy. Keep the static-preview generator aligned with current wording and release links.
- Existing runtime dependencies, experiment schema 1 and algorithm 0.2.0 stay unchanged.

加粗模块框线、精简界面说明，报告数据说明按需展开；同步截图与静态演示。由 v0.3.2 升级时保留 data/，替换源码并重启服务，刷新浏览器。


## v0.3.2 · 2026-10-09

- Select 1–50 recent processing results, with waveform thumbnails, chronological ordering and saved snapshot supplements, for one Chinese PDF report.
- Retain immutable per-session processing evidence across restarts; commit autosave, history retention and task completion together. Retries, ordinary questions, failed/cancelled tasks and snapshot opening do not create duplicate processing records.
- Shared cover and summary, clickable contents/bookmarks, independent full-sample metrics/vector plots and continuous page numbers. Preserve blind-test restrictions and reject deleted/evicted selections; storage cleanup protects all referenced history arrays.
- Fix simulation source labels and include actual simulation parameters/seeds. Add 15 acceptance cases, browser checks and deployment/restart coverage.
- Initialize acceptance output directories in fresh installations so deployment verification does not depend on local debug files.

新增最近 50 次处理结果选择与多组合并 PDF，已包含在 v0.3.2 部署包中。升级前停止服务并备份 data/，已有快照可继续选择，升级前未保存的处理结果无法补回。

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
