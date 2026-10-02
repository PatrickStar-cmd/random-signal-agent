function createSessionId() {
      if (window.crypto?.randomUUID) {
        return window.crypto.randomUUID();
      }
      const randomPart = Math.random().toString(16).slice(2);
      const timePart = Date.now().toString(16);
      return `${timePart}-${randomPart}`;
    }

    const sessionId = localStorage.getItem("rs_agent_session") || createSessionId();
    localStorage.setItem("rs_agent_session", sessionId);
    const sessionLabel = document.getElementById("sessionLabel");
    sessionLabel.title = "当前本地日期时间";
    function formatCurrentTime() {
      const now = new Date();
      const pad = (value) => String(value).padStart(2, "0");
      return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    }
    function updateSessionClock() {
      sessionLabel.textContent = formatCurrentTime();
    }
    updateSessionClock();
    setInterval(updateSessionClock, 1000);

    const state = {
      messages: [],
      agentState: null,
      renderedState: null,
      selectedSeriesKey: "observed",
      dataSignature: "",
      openLibraryNode: localStorage.getItem("rs_agent_open_library_node") || "",
      toolLibrary: null,
      agentMode: localStorage.getItem("rs_agent_mode") === "1",
      agentProgress: null,
      metricsCollapsed: localStorage.getItem("rs_agent_metrics_collapsed") !== "0",
      insightsCollapsed: localStorage.getItem("rs_agent_insights_collapsed") !== "0",
      metricsHtml: "",
      insightsCount: 0,
      chartViews: {
        signalChart: null,
        spectrumChart: null
      }
    };
    const $ = (id) => document.getElementById(id);
    let sizingFrame = 0;
    let realtimeTimer = 0;
    let realtimePlayback = null;
    let stoppingRealtime = false;
    let microphoneCapture = null;
    const REALTIME_TICK_MS = 1200;
    const MIN_CHART_ZOOM = 1;
    const MAX_CHART_ZOOM = 20;
    const CHART_ZOOM_STEP = 1.35;
    const STREAM_TIMEOUT_MS = 18000;
    const FALLBACK_TIMEOUT_MS = 25000;
    const AGENT_TASK_TIMEOUT_MS = 180000;
    const COMPARISON_DEFAULT_HEIGHT = 178;
    const COMPARISON_MIN_HEIGHT = 130;

    const PREPROCESS_TOOL_LIBRARY = [
      {
        id: "robust_mean",
        label: "鲁棒滑动平均",
        params: [
          { key: "smoothing_window", label: "平滑窗口", min: 1, max: 31, step: 2, defaultValue: 7, note: "奇数窗口，越大越平滑。" },
          { key: "anomaly_threshold_sigma", label: "异常阈值 σ", min: 1.5, max: 6, step: 0.1, defaultValue: 3, note: "越小越容易判为异常点。" }
        ]
      },
      {
        id: "median",
        label: "中值滤波",
        params: [
          { key: "smoothing_window", label: "中值窗口", min: 1, max: 31, step: 2, defaultValue: 7, note: "奇数窗口，适合脉冲噪声。" },
          { key: "anomaly_threshold_sigma", label: "异常阈值 σ", min: 1.5, max: 6, step: 0.1, defaultValue: 3, note: "修复前的鲁棒异常检测阈值。" }
        ]
      },
      {
        id: "ema",
        label: "指数平滑",
        params: [
          { key: "ema_alpha", label: "平滑系数 alpha", min: 0.02, max: 0.95, step: 0.01, defaultValue: 0.22, note: "越小越平滑，越大越跟随原始信号。" },
          { key: "anomaly_threshold_sigma", label: "异常阈值 σ", min: 1.5, max: 6, step: 0.1, defaultValue: 3, note: "EMA 前的异常点修复阈值。" }
        ]
      },
      {
        id: "fft_lowpass",
        label: "FFT 低通",
        params: [
          { key: "lowpass_cutoff_hz", label: "截止频率 Hz", min: 1, max: 100, step: 1, defaultValue: 36, note: "应低于采样率的一半。" },
          { key: "anomaly_threshold_sigma", label: "异常阈值 σ", min: 1.5, max: 6, step: 0.1, defaultValue: 3, note: "低通前的脉冲修复阈值。" }
        ]
      },
      {
        id: "hybrid",
        label: "混合增强",
        params: [
          { key: "smoothing_window", label: "组合窗口", min: 3, max: 31, step: 2, defaultValue: 7, note: "同时影响中值与滑动平均阶段。" },
          { key: "anomaly_threshold_sigma", label: "异常阈值 σ", min: 1.5, max: 6, step: 0.1, defaultValue: 3, note: "复杂噪声下建议 2.5-3.5。" }
        ]
      },
      {
        id: "kalman",
        label: "卡尔曼滤波",
        params: [
          { key: "kalman_process_noise", label: "过程噪声 Q", min: 0.001, max: 1, step: 0.001, defaultValue: 0.02, note: "越大越相信状态会快速变化，跟踪更灵敏。" },
          { key: "kalman_measurement_noise", label: "测量噪声 R", min: 0.001, max: 3, step: 0.001, defaultValue: 0.25, note: "越大越不信任观测值，滤波更平滑。" },
          { key: "kalman_initial_error", label: "初始误差 P", min: 0.01, max: 20, step: 0.01, defaultValue: 1, note: "初始状态估计的不确定度。" },
          { key: "anomaly_threshold_sigma", label: "异常阈值 σ", min: 1.5, max: 6, step: 0.1, defaultValue: 3, note: "卡尔曼递推前先修复脉冲异常点。" }
        ]
      }
    ];

    const RANDOM_PROCESS_TOOL_LIBRARY = [
      {
        id: "ar_model",
        label: "AR 模型",
        params: [
          { key: "ar_order", label: "AR 阶数 p", min: 1, max: 32, step: 1, defaultValue: 8, note: "阶数越高可描述更长记忆，但过高会过拟合。" },
          { key: "prediction_horizon", label: "预测步长", min: 1, max: 128, step: 1, defaultValue: 24, note: "用于生成短期预测序列和残差诊断。" }
        ]
      },
      {
        id: "autocorrelation",
        label: "自相关分析",
        params: [
          { key: "max_autocorr_lag", label: "最大滞后 lag", min: 8, max: 256, step: 1, defaultValue: 48, note: "控制自相关函数估计的最大滞后长度。" }
        ]
      },
      {
        id: "power_spectrum",
        label: "功率谱估计",
        params: [
          { key: "psd_segment_length", label: "Welch 段长", min: 32, max: 1024, step: 1, defaultValue: 256, note: "段长越大频率分辨率越高，统计平滑越弱。" },
          { key: "psd_overlap", label: "重叠比例", min: 0, max: 0.9, step: 0.05, defaultValue: 0.5, note: "Welch 平均时相邻片段的重叠比例。" }
        ]
      },
      {
        id: "prediction_residual",
        label: "预测残差分析",
        params: [
          { key: "residual_lag", label: "残差相关 lag", min: 4, max: 128, step: 1, defaultValue: 24, note: "用于判断 AR 预测残差是否接近白噪声。" }
        ]
      }
    ];

    const ACQUISITION_CHANNEL_LIBRARY = [
      { id: "simulated_lab", label: "仿真实验室", status: "可用", note: "按对话参数生成常见信号与噪声组合。" },
      { id: "realtime_stream", label: "实时流式采集", status: "可用", note: "按时间片模拟在线采集过程。" },
      { id: "autonomous_sweep", label: "自主巡检采集", status: "可用", note: "智能体根据目标自动选择信号、噪声和采集策略。" },
      { id: "uploaded_file", label: "用户文件通道", status: "可用", note: "上传 CSV/TXT 后作为采集来源。" },
      { id: "sensor_gateway", label: "外部传感器网关", status: "可用", note: "支持浏览器电脑麦克风采集；远程硬件 API 仍为预留接口。" }
    ];

    function escapeHtml(text) {
      return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function safeOutputUrl(url) {
      const value = String(url || "");
      if (!value.startsWith("/outputs/")) return "";
      return value.replaceAll('"', "%22");
    }

    function renderMathExpression(raw) {
      let expr = String(raw || "").trim();
      expr = expr
        .replace(/&amp;/g, "&")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"');
      expr = expr
        .replace(/\\begin\{(?:aligned|align|equation|gathered|cases|matrix|pmatrix|bmatrix)\}/g, "")
        .replace(/\\end\{(?:aligned|align|equation|gathered|cases|matrix|pmatrix|bmatrix)\}/g, "")
        .replace(/\\\\/g, " ; ")
        .replace(/&\s*=/g, "=")
        .replace(/&/g, "");

      const normalizeScriptGlyphs = (source) => {
        const superscripts = {
          "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
          "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
          "⁺": "+", "⁻": "-", "⁽": "(", "⁾": ")", "ᵀ": "T", "ⁿ": "n"
        };
        const subscripts = {
          "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
          "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
          "₊": "+", "₋": "-", "₍": "(", "₎": ")", "ₖ": "k",
          "ₙ": "n", "ₘ": "m", "ₚ": "p", "ₛ": "s", "ₜ": "t", "ₓ": "x"
        };
        let output = "";
        let sup = "";
        let sub = "";
        const flush = () => {
          if (sup) {
            output += `^{${sup}}`;
            sup = "";
          }
          if (sub) {
            output += `_{${sub}}`;
            sub = "";
          }
        };
        for (const char of String(source || "")) {
          if (superscripts[char] !== undefined) {
            if (sub) flush();
            sup += superscripts[char];
          } else if (subscripts[char] !== undefined) {
            if (sup) flush();
            sub += subscripts[char];
          } else {
            flush();
            if (char === "−") {
              output += "-";
            } else if (char === "⊤") {
              output += "^{T}";
            } else {
              output += char;
            }
          }
        }
        flush();
        return output;
      };
      expr = normalizeScriptGlyphs(expr);

      const commandMap = {
        varepsilon: "ε",
        epsilon: "ε",
        phi: "φ",
        varphi: "φ",
        sum: "∑",
        tau: "τ",
        rho: "ρ",
        sigma: "σ",
        mu: "μ",
        omega: "ω",
        alpha: "α",
        beta: "β",
        gamma: "γ",
        lambda: "λ",
        eta: "η",
        theta: "θ",
        vartheta: "θ",
        nu: "ν",
        xi: "ξ",
        pi: "π",
        kappa: "κ",
        partial: "∂",
        nabla: "∇",
        Delta: "Δ",
        Gamma: "Γ",
        Lambda: "Λ",
        Theta: "Θ",
        Pi: "Π",
        Sigma: "Σ",
        Omega: "Ω",
        top: "T",
        intercal: "T",
        cdot: "·",
        dots: "…",
        cdots: "⋯",
        ldots: "…",
        times: "×",
        div: "÷",
        propto: "∝",
        int: "∫",
        prod: "∏",
        leq: "≤",
        geq: "≥",
        lt: "<",
        gt: ">",
        approx: "≈",
        neq: "≠",
        pm: "±",
        to: "→",
        rightarrow: "→",
        leftarrow: "←",
        infty: "∞",
        quad: " ",
        qquad: " ",
        Big: "",
        big: "",
        Bigg: "",
        bigg: ""
      };

      const skipSpaces = (source, index) => {
        let cursor = index;
        while (cursor < source.length && /\s/.test(source[cursor])) cursor += 1;
        return cursor;
      };
      const readGroup = (source, index) => {
        if (source[index] !== "{") return null;
        let depth = 1;
        let cursor = index + 1;
        while (cursor < source.length) {
          if (source[cursor] === "\\" && cursor + 1 < source.length) {
            cursor += 2;
            continue;
          }
          if (source[cursor] === "{") depth += 1;
          if (source[cursor] === "}") depth -= 1;
          if (depth === 0) {
            return { content: source.slice(index + 1, cursor), end: cursor + 1 };
          }
          cursor += 1;
        }
        return { content: source.slice(index + 1), end: source.length };
      };
      const readAtom = (source, index) => {
        let cursor = skipSpaces(source, index);
        const grouped = readGroup(source, cursor);
        if (grouped) return grouped;
        if (source[cursor] === "\\") {
          const command = source.slice(cursor).match(/^\\[A-Za-z]+/);
          if (command) return { content: command[0], end: cursor + command[0].length };
          if (cursor + 1 < source.length) return { content: source.slice(cursor, cursor + 2), end: cursor + 2 };
        }
        const signedNumber = source.slice(cursor).match(/^[+\-]\d+(?:\.\d+)?/);
        if (signedNumber) return { content: signedNumber[0], end: cursor + signedNumber[0].length };
        const plain = source.slice(cursor).match(/^[A-Za-z0-9]+(?:[|+\-=][A-Za-z0-9]+)*/);
        if (plain) {
          const token = plain[0];
          if (/^(xx|yy|xy|yx|rms|max|min|avg)$/i.test(token)) {
            return { content: token, end: cursor + token.length };
          }
          if (/^[A-Za-z0-9]{2,}$/.test(token) && !/[|+\-=]/.test(token)) {
            return { content: token[0], end: cursor + 1 };
          }
          return { content: token, end: cursor + token.length };
        }
        return { content: source[cursor] || "", end: Math.min(cursor + 1, source.length) };
      };
      const renderSegment = (source) => {
        let output = "";
        for (let index = 0; index < source.length; index += 1) {
          const char = source[index];
          if (char === "\\") {
            const command = source.slice(index).match(/^\\([A-Za-z]+)/);
            if (!command) {
              const next = source[index + 1] || "";
              if ("{}[]".includes(next)) {
                output += escapeHtml(next);
                index += 1;
              } else if (",;:!".includes(next)) {
                output += " ";
                index += 1;
              } else {
                output += escapeHtml(next || char);
                if (next) index += 1;
              }
              continue;
            }
            const name = command[1];
            index += command[0].length - 1;
            if (name === "left" || name === "right") continue;
            if (name === "frac") {
              const numerator = readAtom(source, index + 1);
              const denominator = readAtom(source, numerator.end);
              output += `<span class="math-frac"><span class="math-frac-num">${renderSegment(numerator.content)}</span><span class="math-frac-den">${renderSegment(denominator.content)}</span></span>`;
              index = denominator.end - 1;
              continue;
            }
            if (name === "hat" || name === "bar" || name === "vec" || name === "tilde" || name === "dot") {
              const atom = readAtom(source, index + 1);
              const accentClass = name === "tilde" || name === "dot" ? "hat" : name;
              output += `<span class="math-accent math-${accentClass}">${renderSegment(atom.content)}</span>`;
              index = atom.end - 1;
              continue;
            }
            if (name === "mathcal") {
              const atom = readAtom(source, index + 1);
              output += `<span class="math-cal">${renderSegment(atom.content)}</span>`;
              index = atom.end - 1;
              continue;
            }
            if (name === "operatorname") {
              const atom = readAtom(source, index + 1);
              output += escapeHtml(atom.content);
              index = atom.end - 1;
              continue;
            }
            if (name === "mathrm" || name === "mathbf" || name === "text") {
              const atom = readAtom(source, index + 1);
              output += renderSegment(atom.content);
              index = atom.end - 1;
              continue;
            }
            if (name === "sqrt") {
              const atom = readAtom(source, index + 1);
              output += `√(${renderSegment(atom.content)})`;
              index = atom.end - 1;
              continue;
            }
            output += escapeHtml(commandMap[name] !== undefined ? commandMap[name] : name);
            continue;
          }
          if (char === "_" || char === "^") {
            const atom = readAtom(source, index + 1);
            const tag = char === "_" ? "sub" : "sup";
            output += `<${tag}>${renderSegment(atom.content)}</${tag}>`;
            index = atom.end - 1;
            continue;
          }
          if (char === "{") {
            const grouped = readGroup(source, index);
            output += renderSegment(grouped.content);
            index = grouped.end - 1;
            continue;
          }
          if (char === "}") continue;
          output += escapeHtml(char);
        }
        return output.replace(/\s+/g, " ").trim();
      };

      return renderSegment(expr);
    }

    function renderMathInText(text) {
      let value = String(text || "");
      value = value.replace(/\\\[((?:.|\n)*?)\\\]/g, (_, expr) => `<span class="math-display">${renderMathExpression(expr)}</span>`);
      value = value.replace(/\\\(((?:.|\n)*?)\\\)/g, (_, expr) => `<span class="math-inline">${renderMathExpression(expr)}</span>`);
      value = value.replace(/\$\$((?:.|\n)*?)\$\$/g, (_, expr) => `<span class="math-display">${renderMathExpression(expr)}</span>`);
      value = value.replace(/(^|[^\\$])\$([^$\n]+)\$/g, (_, prefix, expr) => `${prefix}<span class="math-inline">${renderMathExpression(expr)}</span>`);
      return value;
    }

    function replaceOutsideMathSpans(value, transform) {
      const text = String(value || "");
      let output = "";
      let cursor = 0;
      while (cursor < text.length) {
        const start = text.indexOf('<span class="math-', cursor);
        if (start === -1) {
          output += transform(text.slice(cursor));
          break;
        }
        output += transform(text.slice(cursor, start));
        let depth = 0;
        let pos = start;
        while (pos < text.length) {
          const nextOpen = text.indexOf("<span", pos);
          const nextClose = text.indexOf("</span>", pos);
          if (nextOpen !== -1 && (nextOpen < nextClose || nextClose === -1)) {
            depth += 1;
            pos = nextOpen + 5;
            continue;
          }
          if (nextClose !== -1) {
            depth -= 1;
            pos = nextClose + 7;
            if (depth <= 0) break;
            continue;
          }
          pos = text.length;
          break;
        }
        output += text.slice(start, pos);
        cursor = pos;
      }
      return output;
    }

    function looksLikeBareMath(expr) {
      const value = String(expr || "").trim();
      if (!value) return false;
      return /\\(?:hat|bar|vec|tilde|dot|frac|mathcal|operatorname|sum|phi|varphi|epsilon|varepsilon|tau|sigma|mu|rho|omega|lambda|theta|eta|Delta|Gamma|Omega|top|intercal|left|right|begin|end)/.test(value)
        || /[A-Za-zΑ-Ωα-ω][A-Za-z0-9]*\s*(?:_|\^|=)/.test(value)
        || /(?:_|\^)\{/.test(value);
    }

    function renderBareLatexLine(line) {
      const value = String(line || "");
      if (!looksLikeBareMath(value)) return value;
      let start = -1;
      const match = value.match(/(?:\\(?:hat|bar|vec|frac|mathcal|operatorname|sum|phi|varphi|epsilon|varepsilon|tau|sigma|mu|rho|omega|Delta|top|intercal)|[A-Za-zΑ-Ωα-ω][A-Za-z0-9]*(?:_\{?|\^\{?|\s*=))/);
      if (match) start = match.index ?? -1;
      if (start < 0) return value;
      const before = value.slice(0, start);
      const rest = value.slice(start);
      const leading = rest.match(/^\s*/)?.[0] || "";
      const bodyStart = leading.length;
      const body = rest.slice(bodyStart);
      const punctuation = body.search(/[，。；]/);
      const chinese = body.search(/[\u4e00-\u9fff]/);
      const stops = [punctuation, chinese].filter(index => index > 0);
      const end = bodyStart + (stops.length ? Math.min(...stops) : body.length);
      const formula = rest.slice(bodyStart, end).trim();
      if (!looksLikeBareMath(formula)) return value;
      const className = formula.length > 56 || formula.includes("\\frac") ? "math-display" : "math-inline";
      return `${before}${leading}<span class="${className}">${renderMathExpression(formula)}</span>${rest.slice(end)}`;
    }

    function renderBareLatexInText(text) {
      return replaceOutsideMathSpans(text, chunk => chunk.split(/(\r?\n)/).map(renderBareLatexLine).join(""));
    }

    function renderLooseMathTokens(text) {
      const greek = {
        phi: "φ",
        varphi: "φ",
        epsilon: "ε",
        varepsilon: "ε",
        alpha: "α",
        beta: "β",
        gamma: "γ",
        sigma: "σ",
        omega: "ω",
        mu: "μ",
        rho: "ρ",
        tau: "τ"
      };
      let value = String(text || "");
      return replaceOutsideMathSpans(value, chunk => {
        let value = chunk;
      value = value.replace(/([Α-Ωα-ωϕϵ])_(?:\{([^{}<>\s]+)\}|([A-Za-z0-9+\-=]+))/g, (_, symbol, grouped, plain) => {
        return `<span class="math-inline">${symbol}<sub>${grouped || plain}</sub></span>`;
      });
      value = value.replace(/([Α-Ωα-ωϕϵ])\^(?:\{([^{}<>\s]+)\}|([A-Za-z0-9+\-=]+))/g, (_, symbol, grouped, plain) => {
        return `<span class="math-inline">${symbol}<sup>${grouped || plain}</sup></span>`;
      });
      value = value.replace(/\b(phi|varphi|epsilon|varepsilon|alpha|beta|gamma|sigma|omega|mu|rho|tau)_(?:\{([^{}<>\s]+)\}|([A-Za-z0-9+\-=|]+))/gi, (_, name, grouped, plain) => {
        const symbol = greek[String(name).toLowerCase()] || name;
        return `<span class="math-inline">${symbol}<sub>${grouped || plain}</sub></span>`;
      });
      value = value.replace(/\b([A-Zxyzuvw])_(?:\{([^{}<>\s]+)\}|([A-Za-z0-9+\-=|]+))/g, (_, name, grouped, plain) => {
        return `<span class="math-inline">${name}<sub>${grouped || plain}</sub></span>`;
      });
      value = value.replace(/\b([A-Zxyzuvw])\^(?:\{([^{}<>\s]+)\}|([A-Za-z0-9+\-=|]+))/g, (_, name, grouped, plain) => {
        return `<span class="math-inline">${name}<sup>${grouped || plain}</sup></span>`;
      });
      return value;
      });
    }

    function renderMarkdown(text) {
      let safe = escapeHtml(text);
      safe = renderMathInText(safe);
      safe = renderBareLatexInText(safe);
      safe = renderLooseMathTokens(safe);
      safe = safe.replace(/\*\*([^*\n][^*\n]*?)\*\*/g, "<strong>$1</strong>");
      const lines = safe.split(/\r?\n/);
      const html = [];
      let inList = false;
      let inOrderedList = false;
      let traceLines = null;
      let tableLines = [];
      const closeList = () => {
        if (inList) {
          html.push("</ul>");
          inList = false;
        }
        if (inOrderedList) {
          html.push("</ol>");
          inOrderedList = false;
        }
      };
      const flushTrace = () => {
        if (!traceLines) return;
        closeList();
        flushTable();
        const [title, ...steps] = traceLines;
        html.push('<div class="agent-trace">');
        if (title) html.push(`<b>${title}</b>`);
        steps.forEach(step => html.push(`<div>${step}</div>`));
        html.push("</div>");
        traceLines = null;
      };
      const isTableLine = (line) => /^\s*\|.*\|\s*$/.test(line);
      const isSeparatorLine = (line) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
      const flushTable = () => {
        if (!tableLines.length) return;
        const rows = tableLines
          .filter(line => !isSeparatorLine(line))
          .map(line => line.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim()));
        if (rows.length) {
          const [header, ...body] = rows;
          html.push("<table><thead><tr>");
          header.forEach(cell => html.push(`<th>${cell}</th>`));
          html.push("</tr></thead><tbody>");
          body.forEach(row => {
            html.push("<tr>");
            row.forEach(cell => html.push(`<td>${cell}</td>`));
            html.push("</tr>");
          });
          html.push("</tbody></table>");
        }
        tableLines = [];
      };
      for (const line of lines) {
        if (line.trim() === ":::agent-trace") {
          closeList();
          flushTable();
          traceLines = [];
          continue;
        }
        if (traceLines) {
          if (line.trim() === ":::") {
            flushTrace();
          } else if (line.trim()) {
            traceLines.push(line.trim());
          }
          continue;
        }
        if (!line.trim()) {
          if (inList) continue;
          flushTable();
          html.push('<div class="md-gap"></div>');
          continue;
        }
        if (isTableLine(line)) {
          closeList();
          tableLines.push(line);
          continue;
        }
        flushTable();
        const heading = line.match(/^\s*#{1,4}\s+(.+)$/);
        if (heading) {
          closeList();
          html.push(`<strong class="md-heading">${heading[1]}</strong>`);
          continue;
        }
        const unorderedMatch = line.match(/^\s*[-*]\s+(.+)$/);
        if (unorderedMatch) {
          if (inOrderedList) {
            html.push("</ol>");
            inOrderedList = false;
          }
          if (!inList) {
            html.push("<ul>");
            inList = true;
          }
          html.push(`<li>${unorderedMatch[1]}</li>`);
          continue;
        }
        const orderedMatch = line.match(/^\s*(\d+)[.)]\s+(.+)$/);
        if (orderedMatch) {
          if (inList) {
            html.push("</ul>");
            inList = false;
          }
          if (!inOrderedList) {
            html.push("<ol>");
            inOrderedList = true;
          }
          html.push(`<li value="${orderedMatch[1]}">${orderedMatch[2]}</li>`);
          continue;
        }
        closeList();
        html.push(`<div class="md-paragraph">${line}</div>`);
      }
      flushTrace();
      flushTable();
      closeList();
      return html.join("");
    }

    function defaultToolLibrary() {
      const preprocessMethods = {};
      PREPROCESS_TOOL_LIBRARY.forEach(method => {
        preprocessMethods[method.id] = {};
        method.params.forEach(param => {
          preprocessMethods[method.id][param.key] = param.defaultValue;
        });
      });
      const randomProcessAnalysis = {};
      RANDOM_PROCESS_TOOL_LIBRARY.forEach(method => {
        randomProcessAnalysis[method.id] = {};
        method.params.forEach(param => {
          randomProcessAnalysis[method.id][param.key] = param.defaultValue;
        });
      });
      return {
        preprocess_methods: preprocessMethods,
        random_process_analysis: randomProcessAnalysis
      };
    }

    function loadToolLibrary() {
      const defaults = defaultToolLibrary();
      try {
        const saved = JSON.parse(localStorage.getItem("rs_agent_tool_library") || "{}");
        PREPROCESS_TOOL_LIBRARY.forEach(method => {
          const savedParams = saved?.preprocess_methods?.[method.id] || {};
          method.params.forEach(param => {
            const value = Number(savedParams[param.key]);
            if (Number.isFinite(value)) {
              defaults.preprocess_methods[method.id][param.key] = value;
            }
          });
        });
        RANDOM_PROCESS_TOOL_LIBRARY.forEach(method => {
          const savedParams = saved?.random_process_analysis?.[method.id] || {};
          method.params.forEach(param => {
            const value = Number(savedParams[param.key]);
            if (Number.isFinite(value)) {
              defaults.random_process_analysis[method.id][param.key] = value;
            }
          });
        });
      } catch {
        return defaults;
      }
      return defaults;
    }

    function saveToolLibrary() {
      localStorage.setItem("rs_agent_tool_library", JSON.stringify(state.toolLibrary));
    }

    let pendingChatPayload = null;
    function chatPayload(message) {
      if (pendingChatPayload) return pendingChatPayload;
      return JSON.stringify({
        session_id: sessionId,
        request_id: createSessionId(),
        message,
        tool_library: state.toolLibrary,
        agent_mode: state.agentMode
      });
    }

    function renderAgentModeToggle() {
      const toggle = $("agentModeToggle");
      const label = $("agentModeLabel");
      if (!toggle || !label) return;
      toggle.classList.toggle("active", state.agentMode);
      toggle.setAttribute("aria-pressed", state.agentMode ? "true" : "false");
      label.textContent = state.agentMode ? "开启 · 自主处理" : "关闭 · 命令式交互";
    }

    function toggleAgentMode() {
      state.agentMode = !state.agentMode;
      localStorage.setItem("rs_agent_mode", state.agentMode ? "1" : "0");
      renderAgentModeToggle();
      addMessage(
        "assistant",
        state.agentMode
          ? "Agent 模式已开启。除麦克风采集外，采集/上传/停止实时采集后我会自动比较全部预处理方法，并输出最优处理方案和时频域表格。"
          : "Agent 模式已关闭。当前恢复命令式交互：采集或上传后不会自动预处理，只有你明确提出预处理/分析时才执行。"
      );
    }

    function agentProgressText(mode = "standard") {
      const realtimeStep = mode === "realtime"
        ? "1. 正在停止实时流式采集，并锁定当前完整采集窗口。"
        : "1. 正在读取采集/上传信号，并锁定当前样本窗口。";
      return [
        ":::agent-trace",
        "Agent 模式执行中",
        realtimeStep,
        "2. 正在调用全部预处理方法生成候选曲线。",
        "3. 正在比较 SNR、谱熵、谱带宽和异常点率等指标。",
        "4. 正在选择最优预处理方式和参数。",
        "5. 正在整理最优处理结果的时域/频域特征表格。",
        ":::"
      ].join("\n");
    }

    function agentProgressSteps(mode = "standard") {
      const firstStep = mode === "realtime"
        ? "停止实时采集并锁定最终信号窗口"
        : mode === "upload"
          ? "读取上传信号文件并建立样本窗口"
          : "读取采集任务并生成原始随机信号";
      return [
        { running: `${firstStep}中`, done: `${firstStep}完成` },
        { running: "查找各预处理方法的最优参数中", done: "查找各预处理方法的最优参数完成" },
        { running: "比较不同预处理方法的最优结果中", done: "比较不同预处理方法的最优结果完成" },
        { running: "整理最优结果的时域与频域分析表格中", done: "整理最优结果的时域与频域分析表格完成" }
      ];
    }

    function shouldShowAgentProgress(message, mode = "standard") {
      if (!state.agentMode) return false;
      if (mode === "upload" || mode === "realtime") return true;
      const text = String(message || "").toLowerCase();
      const keywords = [
        "采集", "重新采集", "生成", "模拟", "上传", "实时", "传感器", "停止",
        "sample", "acquire", "collect", "signal", "realtime"
      ];
      return keywords.some(word => text.includes(word));
    }

    function startAgentProgress(mode = "standard") {
      const steps = agentProgressSteps(mode);
      state.agentProgress = {
        steps,
        current: 0,
        shown: 1,
        status: "running",
        timers: []
      };
      renderAgentProgress();

    }

    function clearAgentProgressTimers() {
      if (!state.agentProgress?.timers) return;
      state.agentProgress.timers.forEach(timer => clearTimeout(timer));
      state.agentProgress.timers = [];
    }

    function receiveTaskProgress(event) {
      const panel = $("agentProgressPanel");
      if (!panel) return;
      panel.classList.add("active");
      $("agentProgressStatus").textContent = event.status === "queued" ? "排队中" : "执行中";
      const labels = {task: "任务", acquire_signal: "采集信号", compare_preprocess_methods: "比较方法",
        robust_mean: "鲁棒滑动平均", median: "中值滤波", ema: "指数平滑", fft_lowpass: "FFT 低通", hybrid: "混合增强", kalman: "卡尔曼滤波"};
      const label = labels[event.tool] || event.tool;
      $("agentProgressSteps").textContent = `${label}：${event.status === "success" ? "已完成" : event.status === "error" ? "失败" : event.status === "queued" ? "等待执行" : "执行中"}${event.duration_ms != null ? ` · ${event.duration_ms} ms` : ""}`;
    }

    function completeAgentProgress() {
      clearAgentProgressTimers();
      state.agentProgress = null;
      $("agentProgressStatus").textContent = "已完成";
      $("agentProgressSteps").textContent = "结果已返回并保存。";
    }

    function failAgentProgress() {
      clearAgentProgressTimers();
      state.agentProgress = null;
      $("agentProgressStatus").textContent = "执行异常";
      $("agentProgressSteps").textContent = "请查看错误信息；连接中断时可恢复原请求。";
    }

    function resetAgentProgress() {
      clearAgentProgressTimers();
      state.agentProgress = null;
      renderAgentProgress();
    }

    function renderAgentProgress() {
      const panel = $("agentProgressPanel");
      const stepsRoot = $("agentProgressSteps");
      const status = $("agentProgressStatus");
      const progress = state.agentProgress;
      if (!panel || !stepsRoot || !status) return;
      if (!progress) {
        panel.classList.remove("active");
        stepsRoot.innerHTML = "";
        status.textContent = "等待任务";
        return;
      }
      panel.classList.add("active");
      status.textContent = progress.status === "done"
        ? "已完成"
        : progress.status === "error"
          ? "执行异常"
          : "执行中";
      stepsRoot.innerHTML = progress.steps.slice(0, progress.shown).map((step, index) => {
        const done = progress.status === "done" || index < progress.current;
        const running = progress.status === "running" && index === progress.current;
        const className = done ? "done" : running ? "running" : "";
        const text = done ? step.done : running ? step.running : step.running.replace(/中$/, "等待中");
        return `
          <div class="agent-progress-step ${className}">
            <span class="agent-progress-dot" aria-hidden="true"></span>
            <span class="agent-progress-text">${escapeHtml(text)}</span>
          </div>
        `;
      }).join("");
    }

    state.toolLibrary = loadToolLibrary();

    function addMessage(role, text) {
      state.messages.push({ role, text });
      renderMessages();
      return state.messages.length - 1;
    }

    function updateMessage(index, text) {
      if (!state.messages[index]) return;
      state.messages[index].text = text;
      renderMessages();
    }

    function renderMessages() {
      $("messages").innerHTML = state.messages.map(item =>
        `<div class="message ${item.role}">${renderMarkdown(item.text)}</div>`
      ).join("");
      $("messages").scrollTop = $("messages").scrollHeight;
    }

    async function sendMessage(text) {
      const message = text || $("messageInput").value.trim();
      if (!message || $("sendButton").disabled) return;
      pendingChatPayload = null;
      pendingChatPayload = chatPayload(message);
      sessionStorage.setItem("rs_pending_chat", pendingChatPayload);
      $("messageInput").value = "";
      $("sendButton").disabled = true;
      addMessage("user", message);
      const useAgentProgress = shouldShowAgentProgress(message);
      if (useAgentProgress) startAgentProgress();
      const assistantIndex = addMessage("assistant", useAgentProgress ? "正在处理..." : "正在处理...");
      try {
        if (shouldStopRealtimeBeforeMessage(message)) {
          if (state.agentMode) {
            startAgentProgress("realtime");
          } else {
            updateMessage(assistantIndex, "已检测到后续处理指令，正在先停止实时采集...");
          }
          const stopped = await stopRealtimeAcquisition({ silent: true, messageIndex: assistantIndex });
          if (stopped && state.agentMode) return;
        }
        await sendStreamingMessage(message, assistantIndex);
      } catch (error) {
        await sendFallbackMessage(
          message,
          assistantIndex,
          error,
          useAgentProgress ? AGENT_TASK_TIMEOUT_MS : FALLBACK_TIMEOUT_MS
        );
      } finally {
        $("sendButton").disabled = false;
        $("messageInput").focus();
      }
    }

    function shouldStopRealtimeBeforeMessage(message) {
      if (!realtimePlayback || !state.renderedState?.realtime_playback) return false;
      const text = String(message || "").toLowerCase();
      const stopWords = ["停止", "结束", "stop", "暂停"];
      const nextStepWords = [
        "预处理", "去噪", "滤波", "分析", "时域", "频域", "频谱", "功率谱", "解释", "结果",
        "比较", "卡尔曼", "中值", "低通", "平滑", "ar", "fft", "preprocess", "analyze"
      ];
      return stopWords.some(word => text.includes(word)) || nextStepWords.some(word => text.includes(word));
    }

    async function stopRealtimeAcquisition(options = {}) {
      if (!realtimePlayback || stoppingRealtime) return false;
      stoppingRealtime = true;
      const keep = realtimePlayback.visibleSamples;
      const button = $("stopRealtimeButton");
      if (button) {
        button.disabled = true;
        button.textContent = "停止中...";
      }
      stopRealtimePlayback({ keepRendered: true });
      const useAgentProgress = state.agentMode && !options.silent;
      if (useAgentProgress) startAgentProgress("realtime");
      try {
        const response = await fetch("/api/realtime/stop", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            sample_count: keep,
            tool_library: state.toolLibrary,
            agent_mode: state.agentMode
          })
        });
        const payload = await response.json();
        if (payload.error) throw new Error(payload.error);
        if (options.messageIndex !== undefined) {
          completeAgentProgress();
          updateMessage(options.messageIndex, payload.reply || "已停止实时采集。");
        } else if (!options.silent) {
          const messageIndex = addMessage("assistant", state.agentMode ? "正在停止实时采集..." : "正在停止实时采集...");
          completeAgentProgress();
          updateMessage(messageIndex, payload.reply || "已停止实时采集。");
        }
        applyAgentState(payload.state, { skipRealtimePlayback: true });
        return true;
      } catch (error) {
        const detail = error?.message ? `：${error.message}` : "";
        if (useAgentProgress) failAgentProgress();
        if (!options.silent) addMessage("assistant", `停止实时采集失败${detail}`);
        return false;
      } finally {
        stoppingRealtime = false;
        updateRealtimeControls();
      }
    }

    async function sendFallbackMessage(message, assistantIndex, streamError, timeoutMs = FALLBACK_TIMEOUT_MS) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
      try {
        updateMessage(assistantIndex, "Agent 自动处理中，正在等待最优参数搜索和分析结果...");
        const response = await fetch("/api/chat", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: chatPayload(message),
          signal: controller.signal
        });
        const payload = await response.json();
        if (payload.error) {
          failAgentProgress();
          updateMessage(assistantIndex, `错误：${payload.error}`);
          return;
        }
        const prefix = streamError ? "流式通道不可用，已切换普通响应。\n" : "";
        completeAgentProgress();
        updateMessage(assistantIndex, prefix + payload.reply);
        applyAgentState(payload.state);
        sessionStorage.removeItem("rs_pending_chat");
      } catch (error) {
        const detail = error?.message ? `：${error.message}` : "";
        failAgentProgress();
        updateMessage(assistantIndex, `请求失败${detail}。任务可能仍在后台执行，可点击“恢复未完成请求”继续等待；不要重复提交新任务。`);
      } finally {
        clearTimeout(timeoutId);
      }
    }

    async function sendStreamingMessage(message, assistantIndex) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 300000);
      try {
        const response = await fetch("/api/chat/stream", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: chatPayload(message),
          signal: controller.signal
        });
        if (!response.ok || !response.body) {
          throw new Error(`HTTP ${response.status}`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let assistantText = "";
        let finalPayload = null;

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const blocks = buffer.split(/\r?\n\r?\n/);
          buffer = blocks.pop() || "";
          for (const block of blocks) {
            const data = block
              .split(/\r?\n/)
              .filter(item => item.startsWith("data:"))
              .map(item => item.slice(5).trim())
              .join("\n");
            if (!data || data === "[DONE]") continue;
            const event = JSON.parse(data);
            if (event.event === "progress") {
              receiveTaskProgress(event);
            } else if (event.event === "delta") {
              assistantText += event.delta || "";
              updateMessage(assistantIndex, assistantText);
            } else if (event.event === "done") {
              finalPayload = event;
            } else if (event.event === "tool_call") {
              if (event.state) applyAgentState(event.state);
            } else if (event.event === "error") {
              throw new Error(event.error || "stream error");
            }
          }
        }

        if (finalPayload) {
          completeAgentProgress();
          updateMessage(assistantIndex, finalPayload.reply || assistantText);
          applyAgentState(finalPayload.state);
          sessionStorage.removeItem("rs_pending_chat");
        } else {
          throw new Error("stream ended without final state");
        }
      } finally {
        clearTimeout(timeoutId);
      }
    }

    async function refreshAgentState() {
      const response = await fetch(`/api/state?session_id=${encodeURIComponent(sessionId)}&_=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) return false;
      const payload = await response.json();
      if (!payload.state) return false;
      applyAgentState(payload.state);
      return true;
    }

    async function uploadFile() {
      const file = $("fileInput").files[0];
      if (!file) {
        addMessage("assistant", "请先选择 CSV/TXT 信号文件。");
        return;
      }
      const form = new FormData();
      form.append("session_id", sessionId);
      form.append("request_id", createSessionId());
      form.append("sample_rate", $("sampleRate").value || "200");
      form.append("agent_mode", state.agentMode ? "1" : "0");
      form.append("tool_library", JSON.stringify(state.toolLibrary || {}));
      form.append("file", file);
      if (state.agentMode) startAgentProgress("upload");
      const assistantIndex = addMessage("assistant", state.agentMode ? "正在上传并自动处理信号..." : "正在上传信号...");
      try {
        const response = await fetch("/api/upload", { method: "POST", body: form });
        const payload = await response.json();
        if (payload.error) {
          failAgentProgress();
          if (assistantIndex >= 0) {
            updateMessage(assistantIndex, `上传失败：${payload.error}`);
          } else {
            addMessage("assistant", `上传失败：${payload.error}`);
          }
          return;
        }
        completeAgentProgress();
        if (assistantIndex >= 0) {
          updateMessage(assistantIndex, payload.reply);
        } else {
          addMessage("assistant", payload.reply);
        }
        applyAgentState(payload.state);
      } catch (error) {
        failAgentProgress();
        const detail = error?.message ? `：${error.message}` : "";
        if (assistantIndex >= 0) {
          updateMessage(assistantIndex, `上传失败${detail}`);
        } else {
          addMessage("assistant", `上传失败${detail}`);
        }
      }
    }

    function updateGatewayStatus(text) {
      const status = $("gatewayStatus");
      if (status) status.textContent = text;
    }

    async function toggleMicrophoneCapture() {
      if (microphoneCapture) {
        await stopMicrophoneCapture();
        return;
      }
      await startMicrophoneCapture();
    }

    async function startMicrophoneCapture() {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!window.isSecureContext) {
        addMessage("assistant", "当前页面是 HTTP 公网地址，Edge/Chrome 默认会屏蔽麦克风权限。如果坚持使用 HTTP，请用项目里的 open_cloud_http_microphone_edge.bat 启动 Edge 演示模式；正常部署仍建议 HTTPS。");
        updateGatewayStatus("外部传感器网关：HTTP 页面被浏览器屏蔽麦克风 API；可用 Edge HTTP 演示脚本临时放行。");
        return;
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        addMessage("assistant", "浏览器没有暴露麦克风授权接口。请确认地址是 HTTPS/localhost，并检查 Edge 的站点权限是否允许麦克风。");
        updateGatewayStatus("外部传感器网关：未检测到 getUserMedia，可能被站点权限或安全策略禁用。");
        return;
      }
      if (!AudioContextClass) {
        addMessage("assistant", "当前浏览器没有暴露 Web Audio 处理接口。请检查 Edge 是否为新版，或尝试 Chrome/Firefox。");
        updateGatewayStatus("外部传感器网关：未检测到 AudioContext。");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false
          }
        });
        const audioContext = new AudioContextClass();
        const source = audioContext.createMediaStreamSource(stream);
        const processor = audioContext.createScriptProcessor(4096, 1, 1);
        const samples = [];
        processor.onaudioprocess = event => {
          const input = event.inputBuffer.getChannelData(0);
          for (let i = 0; i < input.length; i += 1) samples.push(input[i]);
          const seconds = samples.length / Math.max(audioContext.sampleRate, 1);
          updateGatewayStatus(`外部传感器网关：电脑麦克风采集中，已接收 ${seconds.toFixed(1)} s / ${samples.length} 样本。`);
        };
        source.connect(processor);
        processor.connect(audioContext.destination);
        microphoneCapture = { stream, audioContext, source, processor, samples, startedAt: Date.now() };
        const button = $("microphoneButton");
        if (button) button.textContent = "停止麦克风";
        addMessage("assistant", "电脑麦克风采集已开始。请在本机发声或输入环境信号，完成后点击“停止麦克风”。");
        updateGatewayStatus("外部传感器网关：电脑麦克风采集中...");
      } catch (error) {
        const detail = error?.message ? `：${error.message}` : "";
        addMessage("assistant", `麦克风采集启动失败${detail}。如果当前是公网 HTTP 地址，请先配置 HTTPS 或在 localhost 下测试。`);
        updateGatewayStatus("外部传感器网关：麦克风未授权或当前页面不满足浏览器安全要求。");
      }
    }

    async function stopMicrophoneCapture() {
      if (!microphoneCapture) return;
      const capture = microphoneCapture;
      microphoneCapture = null;
      const button = $("microphoneButton");
      if (button) {
        button.disabled = true;
        button.textContent = "上传中...";
      }
      try {
        capture.processor.disconnect();
        capture.source.disconnect();
        capture.stream.getTracks().forEach(track => track.stop());
        await capture.audioContext.close();
      } catch {}
      const rawSampleRate = capture.audioContext.sampleRate || 44100;
      const maxAudioSamples = 240000;
      const sampleStep = Math.max(1, Math.ceil(capture.samples.length / maxAudioSamples));
      const sampleRate = rawSampleRate / sampleStep;
      const samples = downsampleMicrophoneSamples(capture.samples, sampleStep);
      if (samples.length < 16) {
        addMessage("assistant", "麦克风采集样本过少，请重新采集至少 1 秒左右。");
        updateGatewayStatus("外部传感器网关：麦克风采集样本过少。");
        if (button) {
          button.disabled = false;
          button.textContent = "麦克风采集";
        }
        return;
      }
      try {
        const response = await fetch("/api/microphone", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, sample_rate: sampleRate, pcm16: encodePcm16Base64(samples) })
        });
        const payload = await response.json();
        if (payload.error) throw new Error(payload.error);
        addMessage("assistant", payload.reply);
        applyAgentState(payload.state, { skipRealtimePlayback: true });
        updateGatewayStatus(`外部传感器网关：已载入电脑麦克风信号，${samples.length} 样本，采样率 ${sampleRate.toFixed(0)} Hz。`);
      } catch (error) {
        const detail = error?.message ? `：${error.message}` : "";
        addMessage("assistant", `麦克风信号上传失败${detail}`);
        updateGatewayStatus("外部传感器网关：麦克风信号上传失败。");
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = "麦克风采集";
        }
      }
    }

    function downsampleMicrophoneSamples(samples, step) {
      if (!samples.length) return [];
      const output = [];
      for (let i = 0; i < samples.length; i += step) {
        output.push(Number(samples[i]));
      }
      return output;
    }

    function encodePcm16Base64(samples) {
      const bytes = new Uint8Array(samples.length * 2);
      for (let i = 0; i < samples.length; i += 1) {
        const value = Math.max(-1, Math.min(1, Number(samples[i]) || 0));
        const intValue = value < 0 ? Math.round(value * 32768) : Math.round(value * 32767);
        bytes[i * 2] = intValue & 0xff;
        bytes[i * 2 + 1] = (intValue >> 8) & 0xff;
      }
      let binary = "";
      const chunkSize = 0x8000;
      for (let i = 0; i < bytes.length; i += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
      }
      return btoa(binary);
    }

    function applyAgentState(nextState, options = {}) {
      window.dispatchEvent(new CustomEvent("experiment-state", {detail: nextState}));
      if (!nextState) return;
      stopRealtimePlayback();
      state.agentState = nextState;
      state.renderedState = nextState;
      syncSelectedSeries();
      renderDashboard();
      if (!options.skipRealtimePlayback) maybeStartRealtimePlayback(nextState);
      updateRealtimeControls();
      requestAnimationFrame(() => {
        syncSelectedSeries();
        updateWorkspaceSizing();
        renderCharts(state.renderedState);
      });
    }

    function stopRealtimePlayback(options = {}) {
      if (realtimeTimer) {
        clearInterval(realtimeTimer);
        realtimeTimer = 0;
      }
      const keepRendered = Boolean(options.keepRendered);
      realtimePlayback = null;
      if (!keepRendered) updateRealtimeControls();
    }

    function updateRealtimeControls() {
      const button = $("stopRealtimeButton");
      if (!button) return;
      const active = Boolean(realtimePlayback && state.renderedState?.realtime_playback);
      button.hidden = !active;
      button.disabled = stoppingRealtime;
      button.textContent = stoppingRealtime ? "停止中..." : "停止采集";
    }

    function maybeStartRealtimePlayback(nextState) {
      const signal = nextState?.signal || {};
      const series = nextState?.series || {};
      const plan = nextState?.acquisition_plan || {};
      const source = String(signal.source || "");
      if (signal.acquisition_channel !== "realtime_stream" || !series.observed?.length) return;
      if (plan.realtime_stopped || source.includes("/stopped") || nextState.has_processed || nextState.preprocess_comparison) return;
      const sampleRate = Math.max(1, Number(signal.sample_rate || 1));
      const totalSamples = Math.max(1, Number(signal.sample_count || series.observed.length));
      const totalPoints = series.observed.length;
      const durationSeconds = Math.max(1, totalSamples / sampleRate);
      const chunkSamples = Math.max(1, Math.round(sampleRate));
      const chunkPoints = Math.max(4, Math.round(totalPoints / durationSeconds));
      if (totalSamples <= chunkSamples || totalPoints <= chunkPoints) return;
      const initialSamples = Math.min(chunkSamples, totalSamples);
      const initialPoints = Math.max(2, Math.round((initialSamples / totalSamples) * totalPoints));
      realtimePlayback = {
        fullState: nextState,
        chunkPoints,
        chunkSamples,
        visiblePoints: initialPoints,
        visibleSamples: initialSamples,
        totalSamples,
        totalPoints
      };
      updateRealtimeRenderedState();
      realtimeTimer = setInterval(() => {
        if (!realtimePlayback) return;
        realtimePlayback.visibleSamples = Math.min(
          realtimePlayback.visibleSamples + realtimePlayback.chunkSamples,
          realtimePlayback.totalSamples
        );
        realtimePlayback.visiblePoints = Math.min(
          Math.max(2, Math.round((realtimePlayback.visibleSamples / realtimePlayback.totalSamples) * realtimePlayback.totalPoints)),
          realtimePlayback.totalPoints
        );
        updateRealtimeRenderedState();
        if (realtimePlayback.visibleSamples >= realtimePlayback.totalSamples) {
          clearInterval(realtimeTimer);
          realtimeTimer = 0;
          updateRealtimeControls();
        }
      }, REALTIME_TICK_MS);
      updateRealtimeControls();
    }

    function updateRealtimeRenderedState() {
      if (!realtimePlayback) return;
      const visible = realtimePlayback.visiblePoints;
      const full = realtimePlayback.fullState;
      const series = full.series || {};
      const visibleSeries = { ...series };
      Object.entries(series).forEach(([key, value]) => {
        if (Array.isArray(value) && value.length === realtimePlayback.totalPoints) {
          visibleSeries[key] = value.slice(0, visible);
        }
      });
      visibleSeries.realtime_progress = {
        visible_points: visible,
        total_points: realtimePlayback.totalPoints,
        visible_samples: realtimePlayback.visibleSamples,
        total_samples: realtimePlayback.totalSamples,
        chunk_points: realtimePlayback.chunkPoints,
        chunk_samples: realtimePlayback.chunkSamples,
        chunk_index: Math.ceil(realtimePlayback.visibleSamples / realtimePlayback.chunkSamples),
        chunk_count: Math.ceil(realtimePlayback.totalSamples / realtimePlayback.chunkSamples),
        elapsed_seconds: realtimePlayback.visibleSamples / Math.max(Number(full.signal?.sample_rate || 1), 1),
        buffer_seconds: realtimePlayback.totalSamples / Math.max(Number(full.signal?.sample_rate || 1), 1),
        complete: realtimePlayback.visibleSamples >= realtimePlayback.totalSamples
      };
      const visibleAnalysis = buildRealtimeAnalysis(full, visibleSeries);
      if (visibleAnalysis) {
        visibleSeries.analysis = {
          ...(series.analysis || {}),
          observed: visibleAnalysis
        };
        visibleSeries.frequency = visibleAnalysis.frequency;
        visibleSeries.power = visibleAnalysis.power;
      }
      state.renderedState = {
        ...full,
        signal: {
          ...(full.signal || {}),
          sample_count: realtimePlayback.visibleSamples,
          planned_sample_count: realtimePlayback.totalSamples
        },
        series: visibleSeries,
        realtime_playback: visibleSeries.realtime_progress
      };
      syncSelectedSeries();
      renderDashboard();
      updateRealtimeControls();
    }

    function buildRealtimeAnalysis(full, visibleSeries) {
      const y = visibleSeries.observed || [];
      const sampleRate = Number(full?.signal?.sample_rate || 0);
      if (!y.length || !sampleRate) return null;
      const spectrum = estimateSpectrum(y, sampleRate);
      return {
        key: "observed",
        label: "原始观测",
        frequency: spectrum.frequency,
        power: spectrum.power,
        summary: {
          time_features: estimateTimeFeatures(y),
          frequency_features: spectrum.features,
          quality: {
            anomaly_rate: 0,
            detected_anomaly_count: 0,
            processed_snr_db: null,
            raw_snr_db: null,
            snr_improvement_db: null
          },
          insights: [
            { label: "实时采集", value: `${visibleSeries.realtime_progress?.visible_samples || y.length} 样本`, meaning: "时域与频域图谱按已接收片段动态刷新。" }
          ]
        }
      };
    }

    function estimateTimeFeatures(values) {
      const n = values.length || 1;
      const mean = values.reduce((sum, value) => sum + Number(value || 0), 0) / n;
      const centered = values.map(value => Number(value || 0) - mean);
      const variance = centered.reduce((sum, value) => sum + value * value, 0) / n;
      const rms = Math.sqrt(values.reduce((sum, value) => sum + Number(value || 0) ** 2, 0) / n);
      const peak = values.reduce((max, value) => Math.max(max, Math.abs(Number(value || 0))), 0);
      return {
        mean,
        variance,
        std: Math.sqrt(variance),
        rms,
        peak,
        peak_to_peak: Math.max(...values) - Math.min(...values),
        crest_factor: peak / Math.max(rms, 1e-12),
        lag1_autocorrelation: estimateLagCorrelation(values, 1)
      };
    }

    function estimateLagCorrelation(values, lag) {
      if (values.length <= lag + 1) return 0;
      const n = values.length;
      const mean = values.reduce((sum, value) => sum + Number(value || 0), 0) / n;
      let numerator = 0;
      let denominator = 0;
      for (let i = 0; i < n; i += 1) {
        const centered = Number(values[i] || 0) - mean;
        denominator += centered * centered;
        if (i + lag < n) numerator += centered * (Number(values[i + lag] || 0) - mean);
      }
      return denominator > 1e-12 ? numerator / denominator : 0;
    }

    function estimateSpectrum(values, sampleRate) {
      const n = values.length;
      const maxBins = 180;
      const step = Math.max(1, Math.ceil((Math.floor(n / 2) + 1) / maxBins));
      const mean = values.reduce((sum, value) => sum + Number(value || 0), 0) / Math.max(n, 1);
      const centered = values.map((value, index) => {
        const window = n > 1 ? 0.5 - 0.5 * Math.cos((2 * Math.PI * index) / (n - 1)) : 1;
        return (Number(value || 0) - mean) * window;
      });
      const frequency = [];
      const power = [];
      for (let k = 0; k <= Math.floor(n / 2); k += step) {
        let real = 0;
        let imag = 0;
        for (let t = 0; t < n; t += 1) {
          const angle = (2 * Math.PI * k * t) / n;
          real += centered[t] * Math.cos(angle);
          imag -= centered[t] * Math.sin(angle);
        }
        const p = real * real + imag * imag;
        frequency.push((k * sampleRate) / n);
        power.push(k === 0 ? 0 : p);
      }
      const totalPower = power.reduce((sum, value) => sum + value, 0);
      let dominantIndex = 0;
      power.forEach((value, index) => {
        if (value > power[dominantIndex]) dominantIndex = index;
      });
      const centroid = totalPower > 1e-12
        ? frequency.reduce((sum, value, index) => sum + value * power[index], 0) / totalPower
        : 0;
      const variance = totalPower > 1e-12
        ? frequency.reduce((sum, value, index) => sum + ((value - centroid) ** 2) * power[index], 0) / totalPower
        : 0;
      let entropy = 0;
      if (totalPower > 1e-12) {
        power.forEach(value => {
          const p = value / totalPower;
          if (p > 1e-12) entropy -= p * Math.log(p);
        });
        entropy /= Math.log(Math.max(power.length, 2));
      }
      return {
        frequency,
        power,
        features: {
          dominant_frequency_hz: frequency[dominantIndex] || 0,
          spectral_centroid_hz: centroid,
          mean_frequency_hz: centroid,
          rms_frequency_hz: Math.sqrt(Math.max(variance + centroid * centroid, 0)),
          frequency_variance_hz2: variance,
          frequency_std_hz: Math.sqrt(Math.max(variance, 0)),
          spectral_entropy: entropy,
          spectral_bandwidth_hz: Math.sqrt(Math.max(variance, 0))
        }
      };
    }

    function metric(label, value, note) {
      const displayValue = value == null ? "" : String(value);
      const displayNote = note == null ? "" : String(note);
      const longValue = displayValue.length > 14 || /[_/+]/.test(displayValue);
      return `<div class="metric"><span>${escapeHtml(label)}</span><strong class="${longValue ? "is-long" : ""}">${escapeHtml(displayValue)}</strong><small>${escapeHtml(displayNote)}</small></div>`;
    }

    function renderDashboard() {
      const current = state.renderedState || state.agentState;
      renderMetrics(current);
      renderMetricsModuleState();
      renderAudioResult(current);
      renderInsights(current);
      renderInsightsModuleState();
      renderPreprocessComparison(current);
      updateWorkspaceSizing();
      renderCharts(current);
      renderRisk(current);
      renderToolLibrary();
      renderActions(current);
    }

    function renderMetrics(current) {
      const metrics = [];
      if (current?.signal) {
        metrics.push(metric("样本数", current.signal.sample_count, current.signal.source));
        metrics.push(metric("采样率", `${Number(current.signal.sample_rate).toFixed(1)} Hz`, "采集配置"));
        if (current.signal.acquisition_channel_label) {
          metrics.push(metric("采集通道", current.signal.acquisition_channel_label, current.signal.acquisition_policy || current.signal.acquisition_channel));
        }
        if (current.realtime_playback) {
          const progress = current.realtime_playback;
          const ratio = progress.total_points ? progress.visible_points / progress.total_points : 0;
          const elapsed = Number(progress.elapsed_seconds || 0).toFixed(1);
          const status = progress.complete ? "缓冲已满，点击停止锁定数据" : `${Math.round(ratio * 100)}% 已接收`;
          metrics.push(metric(
            "实时采集",
            `第 ${progress.chunk_index} 片`,
            `${status}，已接收 ${progress.visible_samples || progress.visible_points} 样本 / ${elapsed} s`
          ));
        }
        if (current.signal.waveform || current.signal.noise_model) {
          metrics.push(metric("信号-噪声", `${current.signal.waveform || "-"} + ${current.signal.noise_model || "-"}`, current.signal.acquisition_goal || ""));
        }
      }
      const selected = selectedAnalysis(current);
      const summary = selected?.summary || current?.summary;
      if (summary) {
        const tf = summary.time_features;
        const ff = summary.frequency_features;
        const q = summary.quality;
        const advanced = summary.advanced_analysis || {};
        const ar = advanced.ar_model || {};
        const residual = advanced.prediction_residual || {};
        metrics.push(metric("当前曲线", selected?.label || "当前结果", state.selectedSeriesKey));
        metrics.push(metric("主频", `${ff.dominant_frequency_hz.toFixed(2)} Hz`, "FFT 峰值"));
        metrics.push(metric("谱熵", ff.spectral_entropy.toFixed(3), "频谱分散度"));
        metrics.push(metric("RMS", tf.rms.toFixed(3), "信号能量"));
        metrics.push(metric("AR 模型", `AR(${Number(ar.order || 0)})`, `残差方差 ${Number(ar.noise_variance || 0).toFixed(4)}`));
        metrics.push(metric("残差白化", Number(residual.whiteness_score || 0).toFixed(3), "越低越接近白噪声"));
        metrics.push(metric("异常点率", `${(q.anomaly_rate * 100).toFixed(2)}%`, "鲁棒检测"));
      }
      if (current?.decision) {
        metrics.push(metric("状态", current.decision.status, current.decision.filter_level));
      }
      state.metricsHtml = metrics.length ? metrics.join("") : metric("状态", "等待信号", "请开始对话或上传文件");
      $("metricsContent").innerHTML = state.metricsHtml;
      const hint = $("metricsModuleHint");
      if (hint) hint.textContent = metrics.length ? `采样配置、当前曲线与核心统计量 · ${metrics.length} 项` : "采样配置、当前曲线与核心统计量";
    }

    function renderMetricsModuleState() {
      const module = $("metricsModule");
      const icon = $("metricsToggleIcon");
      const toggle = $("metricsToggle");
      const metrics = $("metricsContent");
      if (!module || !icon || !toggle || !metrics) return;
      module.classList.toggle("collapsed", state.metricsCollapsed);
      module.classList.toggle("expanded", !state.metricsCollapsed);
      metrics.classList.toggle("open", !state.metricsCollapsed);
      metrics.hidden = false;
      metrics.style.display = state.metricsCollapsed ? "none" : "grid";
      metrics.innerHTML = state.metricsHtml || metrics.innerHTML;
      metrics.setAttribute("data-expanded", state.metricsCollapsed ? "0" : "1");
      icon.textContent = state.metricsCollapsed ? "+" : "-";
      toggle.setAttribute("aria-expanded", String(!state.metricsCollapsed));
    }

    function toggleMetricsModule() {
      state.metricsCollapsed = !state.metricsCollapsed;
      localStorage.setItem("rs_agent_metrics_collapsed", state.metricsCollapsed ? "1" : "0");
      renderDashboard();
      requestAnimationFrame(() => {
        updateWorkspaceSizing();
        renderCharts(state.renderedState || state.agentState);
      });
    }

    function renderAudioResult(current) {
      const box = $("audioResult");
      const audio = current?.audio_result;
      if (!audio?.denoised_url) {
        box.classList.remove("active");
        box.innerHTML = "";
        return;
      }
      const denoisedUrl = safeOutputUrl(audio.denoised_url);
      const originalUrl = safeOutputUrl(audio.original_url);
      const downloadUrl = safeOutputUrl(audio.download_url || audio.denoised_url);
      const duration = Number(audio.duration || 0);
      const sampleRate = Number(audio.sample_rate || 0);
      const reduction = audio.noise_reduction_db == null ? null : Number(audio.noise_reduction_db);
      const downloadFormat = String(audio.download_format || "wav").toUpperCase();
      box.classList.add("active");
      box.innerHTML = `
        <div class="audio-head">
          <div>
            <h2>麦克风噪声抵消输出</h2>
            <p>${escapeHtml(audio.method_label || "强噪声画像抵消")}：智能体已估计环境噪声画像，并执行语音保留型抵消与残留噪声门控。</p>
          </div>
          ${downloadUrl ? `<a class="audio-download" href="${downloadUrl}" download>下载 ${escapeHtml(downloadFormat)}</a>` : ""}
        </div>
        <div class="audio-grid">
          <div class="audio-card">
            <b>降噪后声音</b>
            <audio controls src="${denoisedUrl}"></audio>
          </div>
          <div class="audio-card">
            <b>原始麦克风声音</b>
            ${originalUrl ? `<audio controls src="${originalUrl}"></audio>` : `<small>暂无原始音频文件</small>`}
          </div>
        </div>
        <div class="audio-stats">
          <div class="audio-stat"><span>时长</span><strong>${duration ? duration.toFixed(2) : "-"} s</strong></div>
          <div class="audio-stat"><span>采样率</span><strong>${sampleRate ? sampleRate.toFixed(0) : "-"} Hz</strong></div>
          <div class="audio-stat"><span>估计降噪量</span><strong>${reduction == null || !Number.isFinite(reduction) ? "-" : reduction.toFixed(2)} dB</strong></div>
          <div class="audio-stat"><span>下载格式</span><strong>${escapeHtml(downloadFormat)}</strong></div>
        </div>
      `;
    }

    function renderInsights(current) {
      const insights = selectedAnalysis(current)?.summary?.insights || current?.summary?.insights || [];
      state.insightsCount = insights.length || 1;
      $("insights").innerHTML = insights.length
        ? insights.map(item => `<div class="insight"><b>${escapeHtml(item.label)}</b><span>${escapeHtml(item.value)}</span><small>${escapeHtml(item.meaning)}</small></div>`).join("")
        : `<div class="insight"><b>课程知识点</b><span>等待分析</span><small>完成分析后展示统计量、自相关、功率谱、谱熵和质量评估。</small></div>`;
      const hint = $("insightsModuleHint");
      if (hint) hint.textContent = insights.length
        ? `统计解释、自相关、功率谱与质量评估 · ${insights.length} 项`
        : "统计解释、自相关、功率谱与质量评估";
    }

    function renderInsightsModuleState() {
      const module = $("insightsModule");
      const icon = $("insightsToggleIcon");
      const toggle = $("insightsToggle");
      const insights = $("insights");
      if (!module || !icon || !toggle || !insights) return;
      module.classList.toggle("collapsed", state.insightsCollapsed);
      module.classList.toggle("expanded", !state.insightsCollapsed);
      insights.classList.toggle("open", !state.insightsCollapsed);
      insights.hidden = false;
      insights.style.display = state.insightsCollapsed ? "none" : "grid";
      insights.setAttribute("data-expanded", state.insightsCollapsed ? "0" : "1");
      icon.textContent = state.insightsCollapsed ? "+" : "-";
      toggle.setAttribute("aria-expanded", String(!state.insightsCollapsed));
    }

    function toggleInsightsModule() {
      state.insightsCollapsed = !state.insightsCollapsed;
      localStorage.setItem("rs_agent_insights_collapsed", state.insightsCollapsed ? "1" : "0");
      renderDashboard();
      requestAnimationFrame(() => {
        updateWorkspaceSizing();
        renderCharts(state.renderedState || state.agentState);
      });
    }

    function renderPreprocessComparison(current) {
      const box = $("preprocessComparison");
      const comparison = current?.preprocess_comparison;
      if (!comparison?.methods?.length) {
        box.classList.remove("active");
        box.innerHTML = "";
        return;
      }
      box.classList.add("active");
      box.innerHTML = `
        <div class="comparison-resize-handle" title="拖动调整方法评分区域高度" role="separator" aria-orientation="horizontal"></div>
      ` + comparison.methods.map(item => {
        const recommended = item.method === comparison.recommended;
        const selected = state.selectedSeriesKey === `processed_${item.method}`;
        const snr = item.processed_snr_db == null ? "未计算" : `${Number(item.processed_snr_db).toFixed(2)} dB`;
        return `
          <div class="method-card ${recommended ? "recommended" : ""} ${selected ? "selected" : ""}">
            <b>${escapeHtml(item.label)}${recommended ? " · 推荐" : ""}</b>
            <div class="score">Score ${Number(item.score || 0).toFixed(2)}</div>
            <small>SNR：${snr}</small>
            <small>谱熵：${Number(item.spectral_entropy || 0).toFixed(3)}</small>
            <small>主频：${Number(item.dominant_frequency_hz || 0).toFixed(2)} Hz</small>
            <small>异常点：${Number(item.detected_anomaly_count || 0)}</small>
          </div>
        `;
      }).join("");
    }

    function renderRisk(current) {
      const risk = current?.risk || { score: 0, level: "idle", reasons: ["等待分析结果"] };
      const score = Number(risk.score || 0);
      const color = risk.level === "high" ? "#dc2626" : (risk.level === "medium" ? "#d97706" : "#164c8c");
      $("riskGauge").style.background = `conic-gradient(${color} ${score * 3.6}deg, #2b394c 0deg)`;
      $("riskScore").textContent = score.toFixed(0);
      $("riskReasons").innerHTML = (risk.reasons || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
    }

    function renderActions(current) {
      const actions = current?.decision?.recommended_actions || [];
      $("actionList").innerHTML = actions.length
        ? actions.map(item => `<li>${escapeHtml(item)}</li>`).join("")
        : `<li>等待智能体生成建议</li>`;
    }

    function formatParamValue(value, param) {
      const number = Number(value);
      if (!Number.isFinite(number)) return param.defaultValue;
      const step = Number(param.step);
      if (Number.isInteger(step)) return String(Math.round(number));
      const decimals = Math.min(6, Math.max(0, String(param.step).split(".")[1]?.length || 2));
      return number.toFixed(decimals).replace(/0+$/, "").replace(/\.$/, "");
    }

    function clampParamValue(value, param) {
      let number = Number(value);
      if (!Number.isFinite(number)) number = Number(param.defaultValue);
      number = Math.max(Number(param.min), Math.min(Number(param.max), number));
      if (Number.isInteger(Number(param.step))) {
        number = Math.round(number);
        if (number % 2 === 0 && Number(param.step) === 2) {
          number += number < Number(param.max) ? 1 : -1;
        }
      }
      return Number(number.toFixed(4));
    }

    function renderToolLibrary() {
      const current = state.renderedState || state.agentState;
      $("toolLibrary").innerHTML = `
        <div class="library-title"><h2>工具库</h2></div>
        <div class="library-root-title">信号采集通道</div>
        ${ACQUISITION_CHANNEL_LIBRARY.map(channel => {
          const active = current?.signal?.acquisition_channel === channel.id;
          return `
            <div class="library-method ${active ? "open" : ""}">
              <div class="library-row static">
                <b>${escapeHtml(channel.label)}</b>
                <span>${escapeHtml(active ? "当前" : channel.status)}</span>
              </div>
              <div class="library-channel-note">${escapeHtml(channel.note)}</div>
            </div>
          `;
        }).join("")}
        <div class="library-root-title">信号处理工具库</div>
        <div class="library-sub-title">预处理</div>
        ${PREPROCESS_TOOL_LIBRARY.map(method => {
          const nodeKey = `preprocess:${method.id}`;
          const isOpen = state.openLibraryNode === nodeKey;
          const params = state.toolLibrary.preprocess_methods[method.id] || {};
          return `
            <div class="library-method ${isOpen ? "open" : ""}" data-category="preprocess" data-method="${method.id}">
              <button class="library-row" type="button" data-library-toggle="${nodeKey}">
                <b>${escapeHtml(method.label)}</b>
                <span>${isOpen ? "-" : "+"}</span>
              </button>
              <div class="library-params">
                ${method.params.map(param => {
                  const value = formatParamValue(params[param.key] ?? param.defaultValue, param);
                  return `
                    <div class="param-row">
                      <label for="param_${method.id}_${param.key}">${escapeHtml(param.label)}</label>
                      <input id="param_${method.id}_${param.key}" type="number"
                        min="${param.min}" max="${param.max}" step="${param.step}"
                        value="${value}" data-category="preprocess" data-method="${method.id}" data-param="${param.key}">
                      <input type="range" min="${param.min}" max="${param.max}" step="${param.step}"
                        value="${value}" data-category="preprocess" data-method="${method.id}" data-param="${param.key}">
                      <small>${escapeHtml(param.note)}</small>
                    </div>
                  `;
                }).join("")}
              </div>
            </div>
          `;
        }).join("")}
        <div class="library-root-title">随机过程分析</div>
        ${RANDOM_PROCESS_TOOL_LIBRARY.map(method => {
          const nodeKey = `random:${method.id}`;
          const isOpen = state.openLibraryNode === nodeKey;
          const params = state.toolLibrary.random_process_analysis[method.id] || {};
          return `
            <div class="library-method ${isOpen ? "open" : ""}" data-category="random" data-method="${method.id}">
              <button class="library-row" type="button" data-library-toggle="${nodeKey}">
                <b>${escapeHtml(method.label)}</b>
                <span>${isOpen ? "-" : "+"}</span>
              </button>
              <div class="library-params">
                ${method.params.map(param => {
                  const value = formatParamValue(params[param.key] ?? param.defaultValue, param);
                  return `
                    <div class="param-row">
                      <label for="param_${method.id}_${param.key}">${escapeHtml(param.label)}</label>
                      <input id="param_${method.id}_${param.key}" type="number"
                        min="${param.min}" max="${param.max}" step="${param.step}"
                        value="${value}" data-category="random" data-method="${method.id}" data-param="${param.key}">
                      <input type="range" min="${param.min}" max="${param.max}" step="${param.step}"
                        value="${value}" data-category="random" data-method="${method.id}" data-param="${param.key}">
                      <small>${escapeHtml(param.note)}</small>
                    </div>
                  `;
                }).join("")}
              </div>
            </div>
          `;
        }).join("")}
      `;
    }

    function initToolLibrary() {
      $("toolLibrary").addEventListener("click", event => {
        const toggle = event.target.closest("[data-library-toggle]");
        if (!toggle) return;
        const nodeKey = toggle.dataset.libraryToggle;
        state.openLibraryNode = state.openLibraryNode === nodeKey ? "" : nodeKey;
        localStorage.setItem("rs_agent_open_library_node", state.openLibraryNode);
        renderToolLibrary();
      });
      $("toolLibrary").addEventListener("input", event => {
        const input = event.target;
        if (!input.dataset?.category || !input.dataset?.method || !input.dataset?.param) return;
        const library = input.dataset.category === "random" ? RANDOM_PROCESS_TOOL_LIBRARY : PREPROCESS_TOOL_LIBRARY;
        const stateGroup = input.dataset.category === "random" ? "random_process_analysis" : "preprocess_methods";
        const method = library.find(item => item.id === input.dataset.method);
        const param = method?.params.find(item => item.key === input.dataset.param);
        if (!method || !param) return;
        const value = clampParamValue(input.value, param);
        state.toolLibrary[stateGroup][method.id][param.key] = value;
        saveToolLibrary();
        const paired = [...$("toolLibrary").querySelectorAll(`[data-category="${input.dataset.category}"][data-method="${method.id}"][data-param="${param.key}"]`)];
        paired.forEach(item => { if (item !== input) item.value = formatParamValue(value, param); });
      });
      $("toolLibrary").addEventListener("change", event => {
        const input = event.target;
        if (!input.dataset?.category || !input.dataset?.method || !input.dataset?.param) return;
        const library = input.dataset.category === "random" ? RANDOM_PROCESS_TOOL_LIBRARY : PREPROCESS_TOOL_LIBRARY;
        const method = library.find(item => item.id === input.dataset.method);
        const param = method?.params.find(item => item.key === input.dataset.param);
        if (!method || !param) return;
        input.value = formatParamValue(clampParamValue(input.value, param), param);
      });
    }

    function agentStateSignature(current) {
      const signal = current?.signal || {};
      const preprocess = current?.preprocess || {};
      const comparison = current?.preprocess_comparison || {};
      const audio = current?.audio_result || {};
      const observed = current?.series?.observed || [];
      const processed = current?.series?.processed || [];
      const firstObserved = observed.slice(0, 8).map(value => Number(value).toFixed(5)).join(",");
      const firstProcessed = processed.slice(0, 8).map(value => Number(value).toFixed(5)).join(",");
      return [
        signal.sample_count || 0,
        signal.sample_rate || 0,
        signal.source || "",
        preprocess.method || "",
        comparison.recommended || "",
        audio.denoised_url || "",
        audio.download_url || "",
        current?.has_summary ? "summary" : "no-summary",
        firstObserved,
        firstProcessed
      ].join("|");
    }

    function resetChartViews() {
      state.chartViews = {
        signalChart: null,
        spectrumChart: null
      };
      updateChartTools("signalChart");
      updateChartTools("spectrumChart");
    }

    function syncSelectedSeries() {
      const current = state.renderedState || state.agentState;
      const analysis = current?.series?.analysis || {};
      const fallback = current?.selected_series_key || "observed";
      const signature = agentStateSignature(current);
      if (signature && signature !== state.dataSignature) {
        state.dataSignature = signature;
        resetChartViews();
        state.selectedSeriesKey = analysis[fallback] ? fallback : (Object.keys(analysis)[0] || "observed");
        return;
      }
      if (!analysis[state.selectedSeriesKey]) {
        state.selectedSeriesKey = analysis[fallback] ? fallback : (Object.keys(analysis)[0] || "observed");
      }
    }

    function selectedAnalysis(current) {
      const analysis = current?.series?.analysis || {};
      return analysis[state.selectedSeriesKey] || analysis[current?.selected_series_key] || analysis.observed || null;
    }

    function selectSeries(key) {
      const analysis = (state.renderedState || state.agentState)?.series?.analysis || {};
      if (!analysis[key]) return;
      state.selectedSeriesKey = key;
      renderDashboard();
    }

    function renderCharts(current) {
      if (!current?.series) {
        clearChart($("signalChart"), "暂无信号");
        clearChart($("spectrumChart"), "暂无频谱");
        return;
      }
      if (!current.series.observed?.length) {
        clearChart($("signalChart"), "正在采集信号");
        clearChart($("spectrumChart"), "分析后显示功率谱");
        return;
      }
      const signalSeries = [
        { key: "observed", name: "原始观测", x: current.series.time || [], y: current.series.observed || [], color: "#6fb6ff" }
      ];
      if (current.series.comparison_series?.length) {
        const colors = ["#fb7185", "#60a5fa", "#fbbf24", "#a78bfa", "#22d3ee", "#f472b6", "#818cf8", "#34d399", "#c084fc", "#f8fafc"];
        current.series.comparison_series.forEach((item, index) => {
          signalSeries.push({
            key: item.key,
            name: item.label,
            x: current.series.time || [],
            y: current.series[item.key] || [],
            color: colors[index % colors.length]
          });
        });
      } else if (current.series.processed) {
        const label = current.preprocess?.method_label || "预处理后";
        signalSeries.push({ key: "processed", name: label, x: current.series.time || [], y: current.series.processed, color: "#fb7185" });
      }
      const progress = current.series.realtime_progress;
      const title = progress
        ? `随机信号采集与预处理 · 实时采集中 · 第 ${progress.chunk_index} 片`
        : "随机信号采集与预处理";
      drawChart($("signalChart"), signalSeries, title, {
        selectedKey: state.selectedSeriesKey,
        interactive: true,
        legend: "wrap",
        zoomable: !progress,
        xUnit: "时间 / s",
        yUnit: "幅值 / a.u."
      });
      const selected = selectedAnalysis(current);
      if (selected?.frequency?.length) {
        drawChart($("spectrumChart"), [
          { key: `${state.selectedSeriesKey}_spectrum`, name: `${selected.label} 功率谱`, x: selected.frequency, y: selected.power, color: "#a78bfa" }
        ], progress ? `频域功率谱 · 动态估计 · 第 ${progress.chunk_index} 片` : "频域功率谱", {
          zoomable: !progress,
          xUnit: "频率 / Hz",
          yUnit: "功率 / a.u."
        });
      } else if (current.series.frequency?.length) {
        drawChart($("spectrumChart"), [
          { key: "spectrum", name: "功率谱", x: current.series.frequency, y: current.series.power, color: "#a78bfa" }
        ], "频域功率谱", {
          zoomable: !progress,
          xUnit: "频率 / Hz",
          yUnit: "功率 / a.u."
        });
      } else {
        clearChart($("spectrumChart"), "分析后显示功率谱");
      }
    }

    function resizeCanvasToDisplaySize(canvas) {
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(320, Math.round(rect.width));
      const height = Math.max(210, Math.round(rect.height));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
    }

    function clearChart(canvas, text) {
      resizeCanvasToDisplaySize(canvas);
      canvas.__chartMeta = null;
      canvas.__seriesHitRegions = [];
      setChartToolsVisible(canvas.id, false);
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#101823";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#a8b3c7";
      ctx.font = "16px Microsoft YaHei, Segoe UI, Arial";
      ctx.fillText(text, 38, 42);
    }

    function niceTickStep(span, targetCount) {
      if (!Number.isFinite(span) || span <= 0) return 1;
      const rough = span / Math.max(2, targetCount);
      const power = Math.pow(10, Math.floor(Math.log10(rough)));
      const fraction = rough / power;
      const niceFraction = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
      return niceFraction * power;
    }

    function axisTicks(min, max, targetCount) {
      if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return [];
      const step = niceTickStep(max - min, targetCount);
      const ticks = [];
      const first = Math.ceil(min / step) * step;
      for (let value = first; value <= max + step * 0.25; value += step) {
        if (value >= min - step * 0.05 && value <= max + step * 0.05) ticks.push(value);
        if (ticks.length >= 10) break;
      }
      return ticks;
    }

    function formatTick(value, span) {
      if (!Number.isFinite(value)) return "";
      const abs = Math.abs(value);
      if (abs >= 10000 || (abs > 0 && abs < 0.001)) return value.toExponential(1);
      if (span >= 100) return value.toFixed(0);
      if (span >= 10) return value.toFixed(1);
      if (span >= 1) return value.toFixed(2);
      return value.toFixed(3);
    }

    function drawChart(canvas, series, title, options = {}) {
      resizeCanvasToDisplaySize(canvas);
      const ctx = canvas.getContext("2d");
      const width = canvas.width;
      const height = canvas.height;
      const padLeft = 76;
      const padRight = 34;
      const padBottom = 64;
      const hitRegions = [];
      canvas.__seriesHitRegions = hitRegions;
      const legendLayout = layoutLegend(ctx, series, width, padLeft, options);
      const plotTop = Math.min(height - padBottom - 90, Math.max(46, legendLayout.plotTop));
      const plotHeight = Math.max(90, height - padBottom - plotTop);
      const allX = series.flatMap(item => item.x);
      const allY = series.flatMap(item => item.y);
      if (!allX.length || !allY.length) {
        clearChart(canvas, title);
        return;
      }
      const xMin = Math.min(...allX);
      const xMax = Math.max(...allX);
      const view = chartViewFor(canvas.id, xMin, xMax, Boolean(options.zoomable));
      const viewMin = view ? view.min : xMin;
      const viewMax = view ? view.max : xMax;
      const visibleY = [];
      series.forEach(item => {
        item.y.forEach((value, i) => {
          const xValue = Number(item.x[i]);
          if (xValue >= viewMin && xValue <= viewMax) visibleY.push(Number(value));
        });
      });
      const yValues = visibleY.length ? visibleY : allY;
      let yMin = Math.min(...yValues);
      let yMax = Math.max(...yValues);
      if (Math.abs(yMax - yMin) < 1e-12) {
        yMin -= 1;
        yMax += 1;
      }
      const yPadding = (yMax - yMin) * 0.08;
      yMin -= yPadding;
      yMax += yPadding;
      const plotLeft = padLeft;
      const plotRight = width - padRight;
      const plotBottom = height - padBottom;
      const plotWidth = Math.max(plotRight - plotLeft, 1);
      canvas.__chartMeta = {
        chartId: canvas.id,
        zoomable: Boolean(options.zoomable),
        xMin,
        xMax,
        viewMin,
        viewMax,
        plotLeft,
        plotRight,
        plotTop,
        plotBottom
      };
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#101823";
      ctx.fillRect(0, 0, width, height);
      const xTicks = axisTicks(viewMin, viewMax, Math.max(3, Math.floor(plotWidth / 120)));
      const yTicks = axisTicks(yMin, yMax, Math.max(3, Math.floor(plotHeight / 56)));
      ctx.strokeStyle = "#1f2d3e";
      ctx.lineWidth = 1;
      yTicks.forEach(value => {
        const y = plotBottom - (value - yMin) / ((yMax - yMin) || 1) * plotHeight;
        ctx.beginPath();
        ctx.moveTo(plotLeft, y);
        ctx.lineTo(plotRight, y);
        ctx.stroke();
      });
      xTicks.forEach(value => {
        const x = plotLeft + (value - viewMin) / ((viewMax - viewMin) || 1) * plotWidth;
        ctx.beginPath();
        ctx.moveTo(x, plotTop);
        ctx.lineTo(x, plotBottom);
        ctx.stroke();
      });
      ctx.strokeStyle = "#3a4d66";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(plotLeft, plotBottom);
      ctx.lineTo(plotRight, plotBottom);
      ctx.moveTo(plotLeft, plotTop);
      ctx.lineTo(plotLeft, plotBottom);
      ctx.stroke();
      ctx.fillStyle = "#a8b3c7";
      ctx.font = "11px Microsoft YaHei, Segoe UI, Arial";
      ctx.textBaseline = "middle";
      ctx.textAlign = "right";
      yTicks.forEach(value => {
        const y = plotBottom - (value - yMin) / ((yMax - yMin) || 1) * plotHeight;
        const isNearYAxisUnit = options.yUnit && y < plotTop + 28;
        ctx.strokeStyle = "#4a5f7a";
        ctx.beginPath();
        ctx.moveTo(plotLeft - 5, y);
        ctx.lineTo(plotLeft, y);
        ctx.stroke();
        if (!isNearYAxisUnit) ctx.fillText(formatTick(value, yMax - yMin), plotLeft - 8, y);
      });
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      xTicks.forEach(value => {
        const x = plotLeft + (value - viewMin) / ((viewMax - viewMin) || 1) * plotWidth;
        ctx.strokeStyle = "#4a5f7a";
        ctx.beginPath();
        ctx.moveTo(x, plotBottom);
        ctx.lineTo(x, plotBottom + 5);
        ctx.stroke();
        ctx.fillText(formatTick(value, viewMax - viewMin), x, plotBottom + 9);
      });
      ctx.fillStyle = "#c4d2e5";
      ctx.font = "12px Microsoft YaHei, Segoe UI, Arial";
      if (options.xUnit) {
        ctx.textAlign = "right";
        ctx.textBaseline = "top";
        ctx.fillText(options.xUnit, plotRight, plotBottom + 30);
      }
      if (options.yUnit) {
        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        ctx.fillText(options.yUnit, plotLeft - 58, plotTop + 4);
      }
      ctx.fillStyle = "#eaf2ff";
      ctx.font = "14px Microsoft YaHei, Segoe UI, Arial";
      ctx.textAlign = "left";
      ctx.textBaseline = "alphabetic";
      ctx.fillText(title, padLeft, 24);
      if (options.zoomable) {
        const zoomText = `${chartZoomLevel(canvas.id).toFixed(1)}x`;
        ctx.fillStyle = "#a8b3c7";
        ctx.font = "12px Microsoft YaHei, Segoe UI, Arial";
        ctx.fillText(`滚轮缩放，拖拽平移 · ${zoomText}`, padLeft, Math.max(40, plotTop - 8));
      }
      series.forEach((item, idx) => {
        const selected = options.selectedKey && item.key === options.selectedKey;
        const dimmed = options.selectedKey && !selected;
        ctx.strokeStyle = item.color;
        ctx.globalAlpha = dimmed ? 0.32 : 1;
        ctx.lineWidth = selected ? 3.2 : 2;
        ctx.beginPath();
        const points = [];
        let started = false;
        item.y.forEach((value, i) => {
          const xValue = Number(item.x[i]);
          if (xValue < viewMin || xValue > viewMax) return;
          const px = plotLeft + (xValue - viewMin) / ((viewMax - viewMin) || 1) * plotWidth;
          const py = plotBottom - (value - yMin) / ((yMax - yMin) || 1) * plotHeight;
          points.push([px, py]);
          if (!started) {
            ctx.moveTo(px, py);
            started = true;
          } else {
            ctx.lineTo(px, py);
          }
        });
        ctx.stroke();
        if (options.interactive && item.key) {
          hitRegions.push({ key: item.key, points });
        }
        ctx.globalAlpha = 1;
        const legend = legendLayout.items[idx];
        if (!legend) return;
        const legendX = legend.x;
        const legendY = legend.y;
        const legendWidth = legend.width;
        if (options.interactive && item.key) {
          hitRegions.push({ key: item.key, rect: [legendX - 4, legendY - 13, legendWidth, 22] });
        }
        if (selected) {
          ctx.fillStyle = "rgba(96, 165, 250, 0.14)";
          ctx.strokeStyle = "#60a5fa";
          ctx.lineWidth = 1;
          ctx.fillRect(legendX - 7, legendY - 17, legendWidth + 8, 25);
          ctx.strokeRect(legendX - 7, legendY - 17, legendWidth + 8, 25);
        }
        ctx.fillStyle = item.color;
        ctx.fillRect(legendX, legendY, 18, 4);
        ctx.fillStyle = "#c4d2e5";
        ctx.font = "12px Microsoft YaHei, Segoe UI, Arial";
        ctx.fillText(item.name, legendX + 24, legendY + 6);
      });
      setChartToolsVisible(canvas.id, Boolean(options.zoomable));
      updateChartTools(canvas.id);
    }

    function layoutLegend(ctx, series, width, pad, options = {}) {
      ctx.font = "12px Microsoft YaHei, Segoe UI, Arial";
      const maxLegendWidth = Math.max(110, Math.min(190, Math.floor((width - pad * 2) / 2)));
      const rowHeight = 26;
      const startY = 46;
      let x = pad;
      let y = startY;
      const items = series.map(item => {
        const textWidth = ctx.measureText(item.name).width;
        const itemWidth = Math.min(maxLegendWidth, Math.max(104, 34 + textWidth));
        if ((options.legend === "wrap" || series.length > 3) && x + itemWidth > width - pad) {
          x = pad;
          y += rowHeight;
        }
        const layout = { x, y, width: itemWidth };
        x += itemWidth + 12;
        return layout;
      });
      const rows = items.length ? Math.round((items[items.length - 1].y - startY) / rowHeight) + 1 : 0;
      return { items, rows, plotTop: rows ? startY + rows * rowHeight + 8 : pad };
    }

    function clampChartView(min, max, fullMin, fullMax) {
      const fullSpan = Math.max(fullMax - fullMin, 1e-12);
      const minSpan = fullSpan / MAX_CHART_ZOOM;
      let span = Math.min(fullSpan, Math.max(max - min, minSpan));
      let nextMin = min;
      let nextMax = min + span;
      if (nextMin < fullMin) {
        nextMin = fullMin;
        nextMax = fullMin + span;
      }
      if (nextMax > fullMax) {
        nextMax = fullMax;
        nextMin = fullMax - span;
      }
      return { min: nextMin, max: nextMax };
    }

    function chartViewFor(chartId, fullMin, fullMax, zoomable) {
      if (!zoomable || !Number.isFinite(fullMin) || !Number.isFinite(fullMax) || fullMax <= fullMin) {
        state.chartViews[chartId] = null;
        return null;
      }
      const current = state.chartViews[chartId];
      if (!current || Math.abs(current.fullMin - fullMin) > 1e-9 || Math.abs(current.fullMax - fullMax) > 1e-9) {
        state.chartViews[chartId] = { fullMin, fullMax, min: fullMin, max: fullMax };
      } else {
        const clamped = clampChartView(current.min, current.max, fullMin, fullMax);
        state.chartViews[chartId] = { ...current, ...clamped, fullMin, fullMax };
      }
      return state.chartViews[chartId];
    }

    function chartZoomLevel(chartId) {
      const view = state.chartViews[chartId];
      if (!view) return 1;
      const fullSpan = Math.max(view.fullMax - view.fullMin, 1e-12);
      const span = Math.max(view.max - view.min, 1e-12);
      return Math.min(MAX_CHART_ZOOM, Math.max(MIN_CHART_ZOOM, fullSpan / span));
    }

    function zoomChart(chartId, factor, anchorRatio = 0.5) {
      const view = state.chartViews[chartId];
      if (!view) return;
      const fullSpan = Math.max(view.fullMax - view.fullMin, 1e-12);
      const currentSpan = Math.max(view.max - view.min, 1e-12);
      const nextSpan = Math.min(fullSpan / MIN_CHART_ZOOM, Math.max(fullSpan / MAX_CHART_ZOOM, currentSpan / factor));
      const anchor = view.min + currentSpan * Math.max(0, Math.min(1, anchorRatio));
      const nextMin = anchor - nextSpan * Math.max(0, Math.min(1, anchorRatio));
      state.chartViews[chartId] = {
        ...view,
        ...clampChartView(nextMin, nextMin + nextSpan, view.fullMin, view.fullMax)
      };
      renderCharts(state.renderedState || state.agentState);
    }

    function panChart(chartId, deltaRatio) {
      const view = state.chartViews[chartId];
      if (!view) return;
      const span = view.max - view.min;
      const delta = span * deltaRatio;
      state.chartViews[chartId] = {
        ...view,
        ...clampChartView(view.min + delta, view.max + delta, view.fullMin, view.fullMax)
      };
      renderCharts(state.renderedState || state.agentState);
    }

    function resetChartView(chartId) {
      const view = state.chartViews[chartId];
      if (!view) return;
      state.chartViews[chartId] = {
        ...view,
        min: view.fullMin,
        max: view.fullMax
      };
      renderCharts(state.renderedState || state.agentState);
    }

    function setChartToolsVisible(chartId, visible) {
      const tools = document.querySelector(`[data-chart-tools="${chartId}"]`);
      if (tools) tools.hidden = !visible;
    }

    function updateChartTools(chartId) {
      const tools = document.querySelector(`[data-chart-tools="${chartId}"]`);
      if (!tools || tools.hidden) return;
      const zoom = chartZoomLevel(chartId);
      const label = tools.querySelector("[data-chart-zoom-label]");
      if (label) label.textContent = `${zoom.toFixed(1)}x`;
      const outButton = tools.querySelector('[data-chart-zoom="out"]');
      const inButton = tools.querySelector('[data-chart-zoom="in"]');
      const resetButton = tools.querySelector('[data-chart-zoom="reset"]');
      if (outButton) outButton.disabled = zoom <= MIN_CHART_ZOOM + 0.01;
      if (inButton) inButton.disabled = zoom >= MAX_CHART_ZOOM - 0.01;
      if (resetButton) resetButton.disabled = zoom <= MIN_CHART_ZOOM + 0.01;
    }

    function nearestSeriesKey(canvas, event) {
      const rect = canvas.getBoundingClientRect();
      const sx = canvas.width / rect.width;
      const sy = canvas.height / rect.height;
      const x = (event.clientX - rect.left) * sx;
      const y = (event.clientY - rect.top) * sy;
      const regions = canvas.__seriesHitRegions || [];
      for (const region of regions) {
        if (!region.rect) continue;
        const [rx, ry, rw, rh] = region.rect;
        if (x >= rx && x <= rx + rw && y >= ry && y <= ry + rh) {
          return region.key;
        }
      }
      let bestKey = null;
      let bestDistance = Infinity;
      for (const region of regions) {
        if (!region.points) continue;
        for (let i = 0; i < region.points.length; i += 5) {
          const [px, py] = region.points[i];
          const dist = Math.hypot(px - x, py - y);
          if (dist < bestDistance) {
            bestDistance = dist;
            bestKey = region.key;
          }
        }
      }
      return bestDistance <= 16 ? bestKey : null;
    }

    function chartAnchorRatio(canvas, event) {
      const meta = canvas.__chartMeta;
      if (!meta || !meta.zoomable) return 0.5;
      const rect = canvas.getBoundingClientRect();
      const sx = canvas.width / rect.width;
      const x = (event.clientX - rect.left) * sx;
      return (x - meta.plotLeft) / Math.max(meta.plotRight - meta.plotLeft, 1);
    }

    function eventInsidePlot(canvas, event) {
      const meta = canvas.__chartMeta;
      if (!meta || !meta.zoomable) return false;
      const rect = canvas.getBoundingClientRect();
      const sx = canvas.width / rect.width;
      const sy = canvas.height / rect.height;
      const x = (event.clientX - rect.left) * sx;
      const y = (event.clientY - rect.top) * sy;
      return x >= meta.plotLeft && x <= meta.plotRight && y >= meta.plotTop && y <= meta.plotBottom;
    }

    function initChartZooming() {
      document.querySelectorAll("[data-chart-tools]").forEach(tools => {
        tools.addEventListener("click", event => {
          const button = event.target.closest("[data-chart-zoom]");
          if (!button) return;
          const chartId = tools.dataset.chartTools;
          const action = button.dataset.chartZoom;
          if (action === "in") zoomChart(chartId, CHART_ZOOM_STEP, 0.5);
          if (action === "out") zoomChart(chartId, 1 / CHART_ZOOM_STEP, 0.5);
          if (action === "reset") resetChartView(chartId);
        });
      });

      ["signalChart", "spectrumChart"].forEach(chartId => {
        const canvas = $(chartId);
        if (!canvas) return;
        let dragStart = null;
        canvas.addEventListener("wheel", event => {
          const meta = canvas.__chartMeta;
          if (!meta?.zoomable || !eventInsidePlot(canvas, event)) return;
          event.preventDefault();
          const factor = event.deltaY < 0 ? CHART_ZOOM_STEP : 1 / CHART_ZOOM_STEP;
          zoomChart(chartId, factor, chartAnchorRatio(canvas, event));
        }, { passive: false });
        canvas.addEventListener("pointerdown", event => {
          const meta = canvas.__chartMeta;
          if (!meta?.zoomable || !eventInsidePlot(canvas, event) || chartZoomLevel(chartId) <= MIN_CHART_ZOOM + 0.01) return;
          dragStart = {
            x: event.clientX,
            moved: false,
            width: Math.max(meta.plotRight - meta.plotLeft, 1)
          };
          canvas.setPointerCapture(event.pointerId);
        });
        canvas.addEventListener("pointermove", event => {
          if (!dragStart) return;
          const dx = event.clientX - dragStart.x;
          if (Math.abs(dx) < 2) return;
          dragStart.moved = true;
          dragStart.x = event.clientX;
          panChart(chartId, -dx / dragStart.width);
        });
        canvas.addEventListener("pointerup", event => {
          if (dragStart?.moved) {
            canvas.__suppressNextClick = true;
            window.setTimeout(() => { canvas.__suppressNextClick = false; }, 0);
          }
          dragStart = null;
          if (canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
        });
        canvas.addEventListener("pointercancel", event => {
          dragStart = null;
          if (canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
        });
      });
    }

    function updateWorkspaceSizing() {
      const workspace = document.querySelector(".workspace");
      if (!workspace || window.matchMedia("(max-width: 1180px)").matches) return;
      workspace.style.setProperty("--chart-height", "300px");
    }

    function initResizableLayout() {
      const root = $("layoutRoot");
      const leftSplitter = document.querySelector('[data-splitter="left"]');
      const rightSplitter = document.querySelector('[data-splitter="right"]');
      if (!root || !leftSplitter || !rightSplitter) return;
      const saved = JSON.parse(localStorage.getItem("rs_agent_layout") || "{}");
      const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
      let left = Number(saved.left) || 390;
      let right = Number(saved.right) || 360;

      function applyLayout() {
        const available = root.clientWidth - 28 - 16;
        const compact = window.matchMedia("(max-width: 1180px)").matches;
        if (compact || available <= 0) return;
        const minLeft = 280;
        const minCenter = 420;
        const minRight = 280;
        const maxLeft = Math.max(minLeft, available - minCenter - minRight);
        left = clamp(left, minLeft, maxLeft);
        const maxRight = Math.max(minRight, available - minCenter - left);
        right = clamp(right, minRight, maxRight);
        root.style.setProperty("--left-width", `${left}px`);
        root.style.setProperty("--right-width", `${right}px`);
        localStorage.setItem("rs_agent_layout", JSON.stringify({ left, right }));
      }

      function startDrag(which, event) {
        event.preventDefault();
        const splitter = which === "left" ? leftSplitter : rightSplitter;
        const startX = event.clientX;
        const startLeft = left;
        const startRight = right;
        document.body.classList.add("resizing");
        splitter.classList.add("active");
        function move(moveEvent) {
          const dx = moveEvent.clientX - startX;
          if (which === "left") left = startLeft + dx;
          if (which === "right") right = startRight - dx;
          applyLayout();
          updateWorkspaceSizing();
          renderCharts(state.renderedState || state.agentState);
        }
        function stop() {
          document.body.classList.remove("resizing");
          splitter.classList.remove("active");
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", stop);
          updateWorkspaceSizing();
          renderCharts(state.renderedState || state.agentState);
        }
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", stop);
      }
      leftSplitter.addEventListener("pointerdown", (event) => startDrag("left", event));
      rightSplitter.addEventListener("pointerdown", (event) => startDrag("right", event));
      window.addEventListener("resize", () => {
        applyLayout();
        updateWorkspaceSizing();
        renderCharts(state.renderedState || state.agentState);
      });
      applyLayout();
    }

    function comparisonMaxHeight() {
      const workspace = document.querySelector(".workspace");
      const base = workspace?.clientHeight || window.innerHeight || 720;
      return Math.max(220, Math.min(560, Math.round(base * 0.55)));
    }

    function applyComparisonHeight(value) {
      const box = $("preprocessComparison");
      if (!box) return COMPARISON_DEFAULT_HEIGHT;
      const max = comparisonMaxHeight();
      const raw = Number(value) || COMPARISON_DEFAULT_HEIGHT;
      const next = Math.max(COMPARISON_MIN_HEIGHT, Math.min(max, raw));
      box.style.setProperty("--comparison-height", `${Math.round(next)}px`);
      const handle = box.querySelector(".comparison-resize-handle");
      if (handle) {
        handle.setAttribute("aria-valuemin", String(COMPARISON_MIN_HEIGHT));
        handle.setAttribute("aria-valuemax", String(max));
        handle.setAttribute("aria-valuenow", String(Math.round(next)));
      }
      return next;
    }

    function initComparisonResizer() {
      const box = $("preprocessComparison");
      if (!box) return;
      let currentHeight = applyComparisonHeight(localStorage.getItem("rs_agent_comparison_height"));

      box.addEventListener("pointerdown", event => {
        const handle = event.target.closest?.(".comparison-resize-handle");
        if (!handle) return;
        event.preventDefault();
        event.stopPropagation();
        const startY = event.clientY;
        const startHeight = box.getBoundingClientRect().height || currentHeight || COMPARISON_DEFAULT_HEIGHT;
        document.body.classList.add("resizing-y");
        box.classList.add("resizing");

        function move(moveEvent) {
          const dy = moveEvent.clientY - startY;
          currentHeight = applyComparisonHeight(startHeight - dy);
        }

        function stop() {
          document.body.classList.remove("resizing-y");
          box.classList.remove("resizing");
          localStorage.setItem("rs_agent_comparison_height", String(Math.round(currentHeight)));
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", stop);
          updateWorkspaceSizing();
          renderCharts(state.renderedState || state.agentState);
        }

        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", stop);
      });

      window.addEventListener("resize", () => {
        currentHeight = applyComparisonHeight(currentHeight);
      });
    }

    function initWorkspaceSizingObserver() {
      if (!window.ResizeObserver) return;
      const targets = [document.querySelector(".workspace"), $("metricsModule"), $("metricsContent"), $("audioResult"), $("insightsModule"), $("insights"), $("preprocessComparison")].filter(Boolean);
      const observer = new ResizeObserver(() => {
        cancelAnimationFrame(sizingFrame);
        sizingFrame = requestAnimationFrame(() => {
          updateWorkspaceSizing();
          renderCharts(state.renderedState || state.agentState);
        });
      });
      targets.forEach(target => observer.observe(target));
    }

    $("signalChart").addEventListener("click", event => {
      if ($("signalChart").__suppressNextClick) return;
      const key = nearestSeriesKey($("signalChart"), event);
      if (key) selectSeries(key);
    });
    $("signalChart").addEventListener("mousemove", event => {
      const canvas = $("signalChart");
      if (eventInsidePlot(canvas, event) && chartZoomLevel("signalChart") > MIN_CHART_ZOOM + 0.01) {
        canvas.style.cursor = "grab";
      } else {
        canvas.style.cursor = nearestSeriesKey(canvas, event) ? "pointer" : "default";
      }
    });
    $("sendButton").addEventListener("click", () => sendMessage());
    $("metricsToggle").addEventListener("click", () => toggleMetricsModule());
    $("metricsToggle").addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleMetricsModule();
      }
    });
    $("insightsToggle").addEventListener("click", () => toggleInsightsModule());
    $("insightsToggle").addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleInsightsModule();
      }
    });
    $("stopRealtimeButton").addEventListener("click", () => stopRealtimeAcquisition());
    $("microphoneButton").addEventListener("click", () => toggleMicrophoneCapture());
    $("agentModeToggle").addEventListener("click", () => toggleAgentMode());
    $("messageInput").addEventListener("keydown", event => {
      if (event.key === "Enter") sendMessage();
    });
    $("uploadButton").addEventListener("click", uploadFile);
    renderAgentModeToggle();
    addMessage("assistant", "你好，我是谛听 · 随机信号智能体。你可以通过仿真实验、实时流式采集、文件上传或麦克风网关接入信号；开启 Agent 模式后，我会自动搜索预处理最优参数、比较多种处理方法，并输出对应的时域/频域分析结果。");
    initResizableLayout();
    initComparisonResizer();
    initWorkspaceSizingObserver();
    initChartZooming();
    initToolLibrary();
    renderDashboard();
    refreshAgentState().catch(() => {});
