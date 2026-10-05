/* Experiment controls share the existing agent canvas and chat renderer. */
(() => {
  let busy = false;
  let experiments = [];
  let limits = {max_samples:200000, experiment_package_bytes:67108864};
  const status = (message, error = false) => {
    $("wbStatus").textContent = message;
    $("wbStatus").classList.toggle("wb-status-error", error);
  };
  const recoverVisibility = () => { $("wbRecover").hidden = !sessionStorage.getItem("rs_pending_chat") && !sessionStorage.getItem("rs_pending_workbench"); };
  async function api(path, payload) {
    const response = await fetch(path, payload ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)} : {});
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }
  function renderList() {
    const selected = $("wbExperiments").value;
    const query = $("wbSearch").value.trim().toLocaleLowerCase();
    const visible = experiments.filter(e => e.name.toLocaleLowerCase().includes(query));
    $("wbExperiments").innerHTML = `<option value="">${visible.length ? '选择已保存的实验' : '没有匹配的实验'}</option>` + visible.map(e => `<option value="${escapeHtml(e.id)}">${escapeHtml(e.name)} · ${new Date(e.updated * 1000).toLocaleString()}</option>`).join("");
    $("wbExperiments").value = selected;
  }
  async function refreshList(preferred) {
    experiments = (await api(`/api/experiments?session_id=${encodeURIComponent(sessionId)}`)).experiments;
    if (preferred) $("wbSearch").value = "";
    renderList();
    if (preferred) $("wbExperiments").value = preferred;
    window.dispatchEvent(new CustomEvent('experiments-list', {detail:experiments}));
  }
  function selectedExperiment() {
    const selected = experiments.find(e => e.id === $("wbExperiments").value);
    if (!selected) throw new Error("先选择一个已保存的实验");
    return selected;
  }
  $("wbSearch").addEventListener("input", renderList);
  function updateMode() {
    const current = $("wbTemplate").value === 'current';
    document.querySelectorAll('#wbForm input').forEach(input => input.disabled = current);
  }
  $("wbTemplate").addEventListener("change", updateMode);
  async function action(fn) {
    if (busy) return;
    busy = true;
    document.querySelectorAll('.workbench button').forEach(b => b.disabled = true);
    status("正在处理…");
    try { await fn(); } catch (error) { status(error.message, true); }
    finally {
      busy = false;
      document.querySelectorAll('.workbench button').forEach(b => b.disabled = false);
      recoverVisibility();
    }
  }
  function payload(extra = {}) { return {session_id: sessionId, request_id: createSessionId(), ...extra}; }
  function apply(data) {
    if (data.state) {
      applyAgentState(data.state, {skipRealtimePlayback: true});
      if (Array.isArray(data.state.messages)) {
        state.messages = data.state.messages.map(m => ({role: m.role, text: m.content}));
        renderMessages();
      }
    }
  }
  async function runPending(saved) {
    sessionStorage.setItem("rs_pending_workbench", JSON.stringify(saved));
    const accepted = await api(saved.path, {...saved.payload, respond_async: true});
    const response = await fetch(`/api/tasks/${accepted.task_id}/events?session_id=${encodeURIComponent(sessionId)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = "", final = null;
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream:true});
      const blocks = buffer.split(/\r?\n\r?\n/); buffer = blocks.pop() || "";
      for (const block of blocks) {
        const line = block.split("\n").find(l => l.startsWith("data: "));
        if (!line || line === "data: [DONE]") continue;
        const event = JSON.parse(line.slice(6));
        if (event.event === "progress") { receiveTaskProgress(event); status(`${event.tool} · ${event.status}`); }
        if (event.event === "error") { sessionStorage.removeItem("rs_pending_workbench"); throw new Error(event.error); }
        if (event.event === "done") final = event;
      }
    }
    if (!final) throw new Error("连接中断；点击恢复未完成请求继续等待同一任务。");
    sessionStorage.removeItem("rs_pending_workbench");
    apply(final); status("已完成并自动保存"); await refreshList();
    $("agentProgressStatus").textContent = "已完成";
  }
  $("wbForm").addEventListener("submit", event => {
    event.preventDefault();
    action(async () => {
      const config = $("wbTemplate").value === 'current' ? {} : {sample_rate:+$("wbRate").value,duration:+$("wbDuration").value,base_frequency:+$("wbFrequency").value,
        noise_std:+$("wbNoise").value,amplitude:+$("wbAmplitude").value,seed:+$("wbSeed").value,ar_coefficient:+$("wbAR").value,impulse_probability:+$("wbImpulse").value};
      if (config.sample_rate * config.duration > limits.max_samples) throw new Error(`采样点数超过 ${limits.max_samples}，请减小采样率或时长。`);
      await runPending({path:"/api/experiment/run", payload:payload({template:$("wbTemplate").value,goal:$("wbGoal").value,config,tool_library:state.toolLibrary})});
    });
  });
  $("wbSave").onclick = () => action(async () => {
    const data = await api('/api/experiments/save', payload({name:$("wbName").value}));
    await refreshList(data.id); status("已保存独立快照；后续操作不会覆盖它");
  });
  $("wbOpen").onclick = () => action(async () => {
    const {id, name} = selectedExperiment();
    apply(await api('/api/experiments/open', payload({id})));
    $("wbName").value = name; status("实验已恢复");
  });
  $("wbDuplicate").onclick = () => action(async () => {
    const selected = selectedExperiment();
    const name = Array.from(selected.name).slice(0, 117).join('') + " 副本";
    const data = await api('/api/experiments/duplicate', payload({id:selected.id,name}));
    await refreshList(data.id); status("已复制快照");
  });
  $("wbRename").onclick = () => action(async () => {
    const selected = selectedExperiment();
    const data = await api('/api/experiments/rename', payload({id:selected.id,name:$("wbName").value}));
    await refreshList(data.id); $("wbName").value=data.name; status("快照已重命名");
  });
  $("wbDelete").onclick = () => {
    if (busy) return;
    let selected;
    try { selected = selectedExperiment(); } catch (error) { status(error.message, true); return; }
    if (!window.confirm(`删除快照「${selected.name}」？此操作不可撤销。当前工作区和其他快照会保留。`)) return;
    action(async () => {
      await api('/api/experiments/delete', payload({id:selected.id}));
      await refreshList(); status("快照已删除；当前工作区和其他快照已保留");
    });
  };
  document.querySelectorAll('[data-export]').forEach(button => button.onclick = () => action(async () => {
    const format = button.dataset.export;
    const response = await fetch(`/api/experiments/export?session_id=${encodeURIComponent(sessionId)}&format=${format}&name=${encodeURIComponent($("wbName").value)}`);
    if (!response.ok) { const error = await response.json(); throw new Error(error.error); }
    const url = URL.createObjectURL(await response.blob()), a = document.createElement('a');
    a.href=url; a.download=`experiment.${format}`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
    status("已导出；CSV 保留全部采样点");
  }));
  $("wbImport").onchange = () => action(async () => {
    const file = $("wbImport").files[0]; if (!file) return;
    if (file.size > limits.experiment_package_bytes) throw new Error(`实验包不能超过 ${limits.experiment_package_bytes / 1024 / 1024} MiB`);
    const form = new FormData(); form.append('session_id',sessionId); form.append('request_id',createSessionId()); form.append('file',file);
    const response = await fetch('/api/experiments/import',{method:'POST',body:form});
    const data = await response.json(); if (!response.ok || data.error) throw new Error(data.error);
    apply(data); await refreshList(data.id); $("wbName").value="Imported experiment"; status("实验包已校验并导入"); $("wbImport").value="";
  });
  $("wbRecover").onclick = () => action(async () => {
    const saved = sessionStorage.getItem("rs_pending_workbench");
    if (saved) return runPending(JSON.parse(saved));
    const chat = sessionStorage.getItem("rs_pending_chat");
    if (!chat) return;
    const data = await api('/api/chat',JSON.parse(chat)); apply(data);
    sessionStorage.removeItem("rs_pending_chat"); status("原请求已恢复，没有重复执行");
  });
  const terms = {rmse_reduction:"RMSE 改善",reference_correlation:"参考相关性",reference_roughness_penalty:"参考粗糙度惩罚",roughness_reduction:"平滑收益",residual_correlation_penalty:"残差相关惩罚",amplitude_change_penalty:"幅值变化惩罚",peak_change_penalty:"峰值变化惩罚"};
  window.addEventListener('experiment-state', event => {
    const current = event.detail, comparison=current?.preprocess_comparison;
    const config = current?.signal?.config;
    if (config) {
      for (const [id, key] of Object.entries({wbRate:'sample_rate',wbDuration:'duration',wbFrequency:'base_frequency',wbNoise:'noise_std',wbAmplitude:'amplitude',wbSeed:'seed',wbAR:'ar_coefficient',wbImpulse:'impulse_probability'})) $(id).value=typeof config[key]==='number'?Number(config[key].toPrecision(10)):config[key];
      $("wbTemplate").value='current';
      updateMode();
    }
    $("wbGoal").value=current?.comparison_goal || 'waveform';
    if (!comparison) { $("wbScoreContent").textContent="运行比较后显示。"; return; }
    $("wbScoreContent").innerHTML=`<p>${comparison.reference_mode === 'clean_reference' ? '有干净参考信号：显示真实 SNR 与误差指标。' : '无干净参考信号：SNR 不可计算；以下分数为启发式诊断。'} ${escapeHtml(comparison.score_note || '')}</p><div class="wb-score-scroll"><table class="wb-score-table"><thead><tr><th>方法</th><th>得分</th><th>SNR / dB</th><th>搜索耗时 / ms</th><th>评分分项</th><th>参数</th></tr></thead><tbody>${comparison.methods.map(m=>`<tr><td>${escapeHtml(m.label)}${m.method===comparison.recommended?' ★':''}</td><td>${m.score.toFixed(3)}</td><td>${m.processed_snr_db==null?'不适用':m.processed_snr_db.toFixed(2)}</td><td>${m.duration_ms ?? '—'} / ${m.candidate_count} 组</td><td>${Object.entries(m.score_terms||{}).map(([k,v])=>`${terms[k]||escapeHtml(k)}: ${Number(v).toFixed(2)}`).join('<br>')}</td><td><details><summary>查看</summary><pre>${escapeHtml(JSON.stringify(m.parameters,null,2))}</pre></details></td></tr>`).join('')}</tbody></table></div>`;
  });
  refreshList().catch(error=>status(error.message,true)); recoverVisibility();
  api('/api/health').then(data => { limits={...limits,...data.limits}; }).catch(()=>{});
  window.setInterval(recoverVisibility, 2000);
  window.workbench = {apply, refreshList};
})();
