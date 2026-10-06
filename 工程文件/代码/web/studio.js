/* Data import, task control and read-only snapshot comparisons. */
(() => {
  let preview=null, storage=null, importBusy=false, haveColumns=false, comparedIds=null;
  const esc=escapeHtml, colors=['#7965be','#168494','#b5672f','#237c60'];
  const goals={waveform:'保留波形',denoise:'抑噪',transient:'保留瞬态'};
  const statuses={queued:'排队中',running:'运行中',cancelling:'正在取消',cancelled:'已取消',done:'已完成',error:'失败'};
  const operations={diagnose:'时频诊断',demo:'故障演示',inject:'故障注入',reveal:'盲测揭晓',verify:'验证实验',adopt:'采用验证结果',task:'旧版任务',chat:'对话',experiment:'方法比较',save:'保存快照',open:'恢复快照',duplicate:'复制快照',rename:'重命名',delete:'删除快照',import:'导入实验包','import-data':'导入数据',upload:'上传',microphone:'音频处理',stop:'停止采集'};
  const tell=(id,text,error=false)=>{$(id).textContent=text;$(id).classList.toggle('studio-error',error)};
  async function api(path,payload){
    const response=await fetch(path,payload?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}:{});
    const data=await response.json();if(!response.ok||data.error)throw Error(data.error||`HTTP ${response.status}`);return data;
  }
  function options(){
    const value={delimiter:$('diDelimiter').value,header:$('diHeader').value,time_unit:$('diUnit').value,sample_rate:+$('diRate').value};
    if(haveColumns){value.signal_column=+$('diSignal').value;value.time_column=$('diTime').value===''?null:+$('diTime').value}
    return value;
  }
  function invalidate(){preview=null;$('diImport').disabled=true;tell('diStatus','设置已改变，请重新预览并校验。')}
  function timeMode(){$('diRate').disabled=haveColumns&&$('diTime').value!=='';$('diUnit').disabled=haveColumns&&$('diTime').value===''}
  $('diFile').onchange=()=>{haveColumns=false;$('diDelimiter').value='auto';$('diHeader').value='auto';$('diTable').innerHTML='';$('diIssues').innerHTML='';invalidate();timeMode();if($('diFile').files.length)previewFile()};
  ['diDelimiter','diHeader','diTime','diSignal','diUnit','diRate'].forEach(id=>$(id).addEventListener('change',()=>{if(id==='diDelimiter'||id==='diHeader')haveColumns=false;invalidate();timeMode()}));
  function form(token){
    const file=$('diFile').files[0];if(!file)throw Error('先选择 CSV/TXT 文件');
    const value=new FormData();value.append('file',file);value.append('session_id',sessionId);value.append('options',JSON.stringify(options()));
    if(token)value.append('token',token);return value;
  }
  function importControls(disabled){
    importBusy=disabled;$('dataPanel').querySelectorAll('input,select,button').forEach(e=>e.disabled=disabled);
    if(!disabled){timeMode();$('diImport').disabled=!preview?.valid}
  }
  async function previewFile(){
    if(importBusy)return;
    try{
      const body=form();importControls(true);tell('diStatus','正在读取并校验…');
      const response=await fetch('/api/data/preview',{method:'POST',body});const data=await response.json();
      if(!response.ok)throw Error(data.error||'预览失败');preview=data;
      const columns=data.columns.map((name,i)=>`<option value="${i}">${i+1} · ${esc(name)}</option>`).join('');
      $('diTime').innerHTML='<option value="">按采样率生成时间</option>'+columns;$('diSignal').innerHTML=columns;
      $('diTime').value=data.mapping.time_column===null?'':String(data.mapping.time_column);$('diSignal').value=String(data.mapping.signal_column);haveColumns=true;
      $('diDelimiter').value=data.mapping.delimiter;$('diHeader').value=data.mapping.header;
      $('diTable').innerHTML='<table><thead><tr><th>文件行</th>'+data.columns.map((name,i)=>`<th>${i+1} · ${esc(name)}</th>`).join('')+'</tr></thead><tbody>'+data.preview.map(row=>`<tr><td>${row.line}</td>${data.columns.map((_,i)=>`<td>${esc(row.cells[i]??'')}</td>`).join('')}</tr>`).join('')+'</tbody></table>';
      $('diIssues').innerHTML=data.issues.length?'<ul class="studio-error">'+data.issues.map(i=>`<li>第 ${i.line} 行，第 ${i.column} 列：${esc(i.message)}</li>`).join('')+'</ul>':'';
      tell('diStatus',data.valid?`${data.rows} 行 · ${Number(data.sample_rate).toPrecision(6)} Hz · 校验通过，可确认导入`:`发现 ${data.issue_count} 处问题（最多显示 20 处），请调整列设置或修正文件。`,!data.valid);
    }catch(error){preview=null;tell('diStatus',error.message,true)}finally{importControls(false)}
  }
  $('diPreview').onclick=previewFile;
  $('diImport').onclick=async()=>{
    if(importBusy||!preview?.valid)return;
    try{
      const body=form(preview.token);body.append('request_id',createSessionId());importControls(true);tell('diStatus','正在导入…');
      const response=await fetch('/api/data/import',{method:'POST',body});const data=await response.json();if(!response.ok||data.error)throw Error(data.error||'导入失败');
      window.workbench.apply(data);await window.workbench.refreshList();tell('diStatus','已导入当前工作区，可在“模板与实验”中比较方法。');
      $('wbPanel').open=true;window.dispatchEvent(new CustomEvent('workspace-navigate',{detail:'templates'}));
    }catch(error){tell('diStatus',error.message,true)}finally{importControls(false);refreshTasks()}
  };
  let taskLoading=false, lastActive=0;
  async function refreshTasks(){
    if(taskLoading||document.hidden)return;taskLoading=true;
    try{
      const {tasks}=await api(`/api/tasks?session_id=${encodeURIComponent(sessionId)}`);
      const active=tasks.filter(t=>['queued','running','cancelling'].includes(t.status));$('taskCount').textContent=active.length?`· ${active.length} 项待完成`:'';
      if(active.length&&!lastActive)$('taskPanel').open=true;lastActive=active.length;
      const html=tasks.slice(0,12).map(t=>`<div class="task-row"><span>${esc(operations[t.operation]||t.operation)} · ${statuses[t.status]||esc(t.status)}${t.queue_position?` · 队列位置 ${t.queue_position}`:''}<br><small>${new Date(t.created*1000).toLocaleString()} · ${esc(t.task_id.slice(0,8))}</small></span>${t.can_cancel?`<button data-cancel="${esc(t.task_id)}">取消</button>`:''}</div>`).join('')||'<p class="studio-hint">当前会话还没有任务</p>';
      if($('taskList').innerHTML!==html)$('taskList').innerHTML=html;
    }catch(error){tell('taskStatus',error.message,true)}finally{taskLoading=false}
  }
  $('taskList').onclick=async event=>{
    const button=event.target.closest('[data-cancel]');if(!button)return;button.disabled=true;
    try{const result=await api(`/api/tasks/${button.dataset.cancel}/cancel`,{session_id:sessionId});tell('taskStatus',result.cancel_requested?'已请求取消，将在安全检查点停止。':'任务已结束或正在保存结果，无法取消。');await refreshTasks()}
    catch(error){tell('taskStatus',error.message,true);button.disabled=false}
  };
  const bytes=value=>`${(value/1024/1024).toFixed(2)} MiB`;
  $('storagePreview').onclick=async()=>{
    $('storageClean').disabled=true;storage=null;
    try{storage=await api('/api/storage');tell('storageInfo',`采样文件 ${bytes(storage.total_bytes)}，数据库 ${bytes(storage.database_bytes)}；可清理 ${storage.unused_files} 个文件，共 ${bytes(storage.reclaimable_bytes)}。`);
      $('storageFiles').innerHTML=storage.files.map(f=>`<div><code>${esc(f.name.slice(0,12))}…npz</code> · ${bytes(f.bytes)}</div>`).join('');$('storageClean').disabled=!storage.unused_files;
    }catch(error){tell('storageInfo',error.message,true)}
  };
  $('storageClean').onclick=async()=>{
    if(!storage||!window.confirm(`清理已预览的 ${storage.unused_files} 个无引用采样文件（${bytes(storage.reclaimable_bytes)}）？当前实验和已保存快照会保留。`))return;
    $('storageClean').disabled=true;
    try{const result=await api('/api/storage/cleanup',{token:storage.token,confirm:true});storage=null;$('storageFiles').innerHTML='';tell('storageInfo',`已清理 ${result.removed_files} 个文件，释放 ${bytes(result.freed_bytes)}。`)}catch(error){storage=null;tell('storageInfo',error.message,true)}
  };
  function choices(experiments){
    const selected=new Set(Array.from(document.querySelectorAll('[data-compare-id]:checked'),e=>e.value));
    $('compareChoices').innerHTML=experiments.map(e=>`<label><input type="checkbox" data-compare-id value="${esc(e.id)}" ${selected.has(e.id)?'checked':''}>${esc(e.name)}</label>`).join('')||'<p class="studio-hint">先在工作台保存至少两个实验快照</p>';
    comparedIds=null;$('compareExport').disabled=true;
  }
  window.addEventListener('experiments-list',event=>choices(event.detail));
  $('compareChoices').onchange=()=>{comparedIds=null;$('compareExport').disabled=true;tell('compareStatus','选择已改变，请重新对比。')};
  const format=value=>value==null?'—':typeof value==='number'?Number(value.toPrecision(5)).toString():esc(value);
  $('compareRun').onclick=async()=>{
    const ids=Array.from(document.querySelectorAll('[data-compare-id]:checked'),e=>e.value);
    if(ids.length<2||ids.length>4){tell('compareStatus','请选择 2–4 个不同快照。',true);return}
    $('compareRun').disabled=true;$('compareExport').disabled=true;
    try{
      const data=await api('/api/experiments/compare',{session_id:sessionId,ids});comparedIds=ids;tell('compareStatus',data.note);
      const fields=[['name','实验'],['method','方法'],['goal','目标'],['sample_count','点数'],['sample_rate','采样率 / Hz'],['rms','RMS'],['peak','峰值'],['dominant_frequency_hz','主频 / Hz'],['rmse','RMSE'],['snr_db','SNR / dB'],['duration_ms','搜索 / ms']];
      if(data.score_comparable)fields.push(['score','评分']);
      const legend=data.experiments.map((e,i)=>`<span style="color:${colors[i]}">● ${esc(e.name)}</span>`).join('');
      $('compareResult').innerHTML='<p class="studio-hint">无干净参考时，RMSE 和真实 SNR 显示为 —。</p><div class="studio-scroll"><table><thead><tr>'+fields.map(([,label])=>`<th>${label}</th>`).join('')+'</tr></thead><tbody>'+data.experiments.map(e=>'<tr>'+fields.map(([key])=>`<td>${key==='goal'?esc(goals[e.goal]||e.goal):format(e[key])}</td>`).join('')+'</tr>').join('')+'</tbody></table></div>'+`<p class="compare-legend">${legend}</p><div class="compare-plots"><div><h3>波形</h3>${data.waveform_svg}</div><div><h3>频谱</h3>${data.spectrum_svg}</div></div><p class="studio-hint">${esc(data.plot_note)}</p>`+data.experiments.map(e=>`<details><summary>${esc(e.name)} · 参数</summary><pre>${esc(JSON.stringify({signal:e.signal_config,processing:e.parameters,input_sha256:e.input_sha256},null,2))}</pre></details>`).join('');
      $('compareExport').disabled=false;
    }catch(error){comparedIds=null;tell('compareStatus',error.message,true)}finally{$('compareRun').disabled=false}
  };
  $('compareExport').onclick=async()=>{
    if(!comparedIds)return;
    try{const response=await fetch('/api/experiments/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,ids:comparedIds,format:'html'})});
      if(!response.ok)throw Error((await response.json()).error);const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download='comparison.html';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
    }catch(error){tell('compareStatus',error.message,true)}
  };
  window.addEventListener('experiment-state',event=>{const signal=event.detail?.signal;if(signal)tell('dataSummary',`${signal.source} · ${signal.sample_count} 点 · ${Number(signal.sample_rate).toPrecision(5)} Hz`)});
  document.querySelectorAll('.workflow-nav a').forEach(a=>a.addEventListener('click',()=>{const target=document.querySelector(a.getAttribute('href'));if(target?.tagName==='DETAILS')target.open=true}));
  api(`/api/experiments?session_id=${encodeURIComponent(sessionId)}`).then(data=>choices(data.experiments)).catch(error=>tell('compareStatus',error.message,true));
  refreshTasks();setInterval(refreshTasks,2000);
})();
