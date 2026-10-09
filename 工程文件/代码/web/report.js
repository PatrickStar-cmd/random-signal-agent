/* Immutable selections share a preview token with the final PDF. */
(() => {
  let token=null,busy=false,revision=0,refreshRevision=0;
  let entries=[],selected=new Set();
  const key=e=>e.kind+':'+e.id;
  const historical=()=>$('reportSource').value==='history';
  const status=(message,error=false)=>{$('reportStatus').textContent=message;$('reportStatus').classList.toggle('wb-status-error',error)};
  const fields=()=>({title:$('reportTitle').value,author:$('reportAuthor').value,purpose:$('reportPurpose').value,unit:$('reportUnit').value,edition:$('reportEdition').value});
  const syncButtons=()=>{
    $('reportPreview').disabled=busy;$('reportDownload').disabled=!token||busy;
    ['reportRefresh','reportSelectAll','reportClear'].forEach(id=>$(id).disabled=busy);
    $('reportCount').textContent=`已选 ${selected.size} / 50 组`;
  };
  const invalidate=()=>{revision++;token=null;$('reportSummary').hidden=true;syncButtons();status('数据、选择或设置变化后，请重新预览报告。')};
  function chosen(){
    const direction=$('reportOrder').value==='oldest'?1:-1;
    return entries.filter(e=>selected.has(key(e))).sort((a,b)=>direction*(a.created-b.created)||key(a).localeCompare(key(b))).map(({kind,id})=>({kind,id}));
  }
  function renderList(){
    for(const [kind,id] of [['history','reportHistory'],['snapshot','reportSnapshots']]){
      const rows=entries.filter(e=>e.kind===kind);
      $(id).innerHTML=rows.length?rows.map(e=>{
        const k=escapeHtml(key(e)),date=escapeHtml(new Date(e.created*1000).toLocaleString());
        const detail=e.locked?'盲测未揭晓时的存档':kind==='history'?`${e.sample_count.toLocaleString()} 点 · ${e.sample_rate} Hz`:'已保存实验快照';
        const url=`/api/reports/plot/${kind}/${encodeURIComponent(e.id)}?session_id=${encodeURIComponent(sessionId)}`;
        return `<label class="report-result"><input type="checkbox" data-report-entry="${k}" ${selected.has(key(e))?'checked':''} ${e.locked||busy?'disabled':''}><span><strong>${escapeHtml(e.name)}</strong><small>${date}</small><small>${escapeHtml(detail)}</small></span>${e.locked?'':`<img loading="lazy" src="${url}" alt="原始观测与处理结果波形缩略图">`}</label>`;
      }).join(''):`<p class="wb-hint">${kind==='history'?'暂无处理存档。完成一次处理后会自动出现在这里，升级前未保存的结果无法补回。':'暂无已保存实验。'}</p>`;
    }
    syncButtons();
  }
  async function refresh(){
    const current=++refreshRevision;
    try{
      const response=await fetch('/api/reports/history?session_id='+encodeURIComponent(sessionId));
      const data=await response.json();if(!response.ok)throw Error(data.error||'历史列表加载失败。');if(current!==refreshRevision)return;
      entries=[...data.history,...data.snapshots];const available=new Set(entries.filter(e=>!e.locked).map(key));
      const before=selected.size;selected=new Set([...selected].filter(k=>available.has(k)));
      if(before!==selected.size){invalidate();status('部分已选结果已不可用，已移除；请检查选择并重新预览。',true)}renderList();
    }catch(e){if(current===refreshRevision)status(e.message,true)}
  }
  async function request(action){
    const payload={session_id:sessionId,options:fields(),...(token?{token}:{})};
    if(historical()){if(!selected.size)throw Error('请先选择至少一组结果。');payload.selection=chosen()}
    const response=await fetch('/api/reports/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!response.ok){let data;try{data=await response.json()}catch(e){}throw Error(data?.error||'报告生成失败，请稍后重试。')}return response;
  }
  async function action(fn){
    if(busy)return;busy=true;syncButtons();document.querySelectorAll('#reportForm input,#reportForm select,#reportForm textarea,#reportPicker input').forEach(e=>e.disabled=true);
    try{await fn()}catch(e){token=null;status(e.message,true)}finally{busy=false;document.querySelectorAll('#reportForm input,#reportForm select,#reportForm textarea').forEach(e=>e.disabled=false);renderList();syncButtons()}
  }
  $('reportForm').addEventListener('input',invalidate);
  $('reportSource').addEventListener('change',()=>{$('reportPicker').hidden=!historical();if(historical())refresh()});
  $('reportPicker').addEventListener('change',event=>{
    const input=event.target,k=input.dataset.reportEntry;if(!k)return;
    if(input.checked){if(selected.size>=50){input.checked=false;status('最多选择 50 组，请先取消其他结果。',true);return}selected.add(k)}else selected.delete(k);invalidate();
  });
  $('reportRefresh').onclick=()=>{invalidate();refresh()};
  $('reportSelectAll').onclick=()=>{selected=new Set(entries.filter(e=>e.kind==='history'&&!e.locked).map(key));invalidate();renderList()};
  $('reportClear').onclick=()=>{selected.clear();invalidate();renderList()};
  window.addEventListener('experiment-state',()=>{invalidate();if(historical())refresh()});
  window.addEventListener('experiments-list',()=>{if(historical()){invalidate();refresh()}});
  $('reportForm').onsubmit=event=>{event.preventDefault();action(async()=>{
    const started=revision;token=null;status('正在整理所选结果与分析结论…');const data=await(await request('preview')).json();
    if(started!==revision){status('实验或选择已变化，请重新预览报告。');return}token=data.token;
    $('reportSummary').innerHTML='<h3>'+escapeHtml(data.options.title)+'</h3>'+data.summary.map(t=>'<p>'+escapeHtml(t)+'</p>').join('')+'<h4>报告章节</h4><ol>'+data.sections.map(t=>'<li>'+escapeHtml(t)+'</li>').join('')+'</ol><h4>数据与解释边界</h4><ul>'+data.limitations.map(t=>'<li>'+escapeHtml(t)+'</li>').join('')+'</ul>';
    $('reportSummary').hidden=false;status('预览完成。下载会核对所选结果，多组标准报告可能较长。');
  })};
  $('reportDownload').onclick=()=>action(async()=>{
    status(`正在排版 ${historical()?selected.size:1} 组结果的 PDF，请稍候…`);const response=await request('pdf');const blob=await response.blob();
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='signal-analysis.pdf';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);status('PDF 已生成，下载已开始。');
  });
  window.analysisReport={syncButtons};
})();
