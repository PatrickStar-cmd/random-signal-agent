/* Preview and export share a content token; edits require a new preview. */
(() => {
  let token=null,busy=false,revision=0;
  const status=(message,error=false)=>{$('reportStatus').textContent=message;$('reportStatus').classList.toggle('wb-status-error',error)};
  const fields=()=>({title:$('reportTitle').value,author:$('reportAuthor').value,purpose:$('reportPurpose').value,unit:$('reportUnit').value,edition:$('reportEdition').value});
  const invalidate=()=>{revision++;token=null;$('reportDownload').disabled=true;$('reportSummary').hidden=true;status('数据或设置变化后，请重新预览报告。')};
  const syncButtons=()=>{$('reportPreview').disabled=busy;$('reportDownload').disabled=!token||busy};
  async function request(action){
    const r=await fetch('/api/reports/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,options:fields(),...(token?{token}:{})})});
    if(!r.ok){let data;try{data=await r.json()}catch(e){}throw Error(data?.error||'报告生成失败，请稍后重试。')}
    return r;
  }
  async function action(fn){if(busy)return;busy=true;syncButtons();document.querySelectorAll('#reportForm input,#reportForm select,#reportForm textarea').forEach(e=>e.disabled=true);
    try{await fn()}catch(e){token=null;status(e.message,true)}finally{busy=false;syncButtons();document.querySelectorAll('#reportForm input,#reportForm select,#reportForm textarea').forEach(e=>e.disabled=false)}}
  $('reportForm').addEventListener('input',invalidate);
  window.addEventListener('experiment-state',invalidate);
  $('reportForm').onsubmit=event=>{event.preventDefault();action(async()=>{
    const started=revision;token=null;status('正在整理当前实验与分析结论…');const data=await(await request('preview')).json();
    if(started!==revision){status('实验已变化，请重新预览报告。');return}token=data.token;
    $('reportSummary').innerHTML='<h3>'+escapeHtml(data.options.title)+'</h3>'+data.summary.map(t=>'<p>'+escapeHtml(t)+'</p>').join('')+
      '<h4>报告章节</h4><ol>'+data.sections.map(t=>'<li>'+escapeHtml(t)+'</li>').join('')+'</ol><h4>数据与解释边界</h4><ul>'+data.limitations.map(t=>'<li>'+escapeHtml(t)+'</li>').join('')+'</ul>';
    $('reportSummary').hidden=false;status('预览完成。下载将核对实验与设置是否仍一致。');
  })};
  $('reportDownload').onclick=()=>action(async()=>{
    status('正在排版 PDF，请稍候…');const response=await request('pdf');const blob=await response.blob();
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='signal-analysis.pdf';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);status('PDF 已生成，下载已开始。');
  });
  window.analysisReport={syncButtons};
})();
