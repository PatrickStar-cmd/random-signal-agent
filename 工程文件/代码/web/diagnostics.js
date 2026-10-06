/* Diagnostic actions share the durable task queue and snapshot state. */
(() => {
  const labels={impulse:'脉冲',narrowband:'局部窄带',drift:'基线漂移',clipping:'削顶',dropout:'短暂归零',frequency_shift:'主频改变'},esc=escapeHtml;
  let report=null,lab={},busy=false,selected=null,revision=0;
  const status=(s,error=false)=>{$('dgStatus').textContent=s;$('dgStatus').classList.toggle('studio-error',error)};
  async function view(){
    const rev=++revision,response=await fetch(`/api/diagnostics/view?session_id=${encodeURIComponent(sessionId)}`),data=await response.json();
    if(!response.ok)throw Error(data.error||'读取诊断失败');if(rev!==revision)return;
    report=data.diagnostics;lab=data.lab;render();if(!busy)status('已恢复上次诊断；可重新诊断更新。');
  }
  async function action(kind,extra={}){
    if(busy)return;busy=true;revision++;
    document.querySelectorAll('#diagnosticPanel button').forEach(b=>b.disabled=true);status('正在计算…可在任务面板取消。');
    try{
      const data=await window.workbench.runPending({path:`/api/diagnostics/${kind}`,payload:{session_id:sessionId,request_id:createSessionId(),...extra}});
      lab=data.state.diagnostic_lab||{};
      if(data.diagnostics?.spectrogram){report=data.diagnostics;render()}
      else if(kind==='verify'){showTrial(data.diagnostics)}
      else await view();
      status(kind==='adopt'?'已采用处理结果，原始观测保留。':'已完成并自动保存。');
    }catch(e){status(e.message,true)}finally{busy=false;document.querySelectorAll('#diagnosticPanel button').forEach(b=>b.disabled=false)}
  }
  function options(){const o={source:$('dgSource').value,window:+$('dgWindow').value,overlap:+$('dgOverlap').value,start:+$('dgStart').value};if($('dgEnd').value!=='')o.end=+$('dgEnd').value;return o}
  function canvas(id){const c=$(id);c.width=Math.max(280,Math.round(c.getBoundingClientRect().width));c.height=id==='dgHeat'?260:180;const ctx=c.getContext('2d');ctx.fillStyle='#101c2c';ctx.fillRect(0,0,c.width,c.height);ctx.font='13px system-ui';return [c,ctx]}
  const left=55,right=18,top=12,bottom=30;
  function wave(id,t,series,range){
    const [c,x]=canvas(id);if(!t?.length)return;const w=c.width-left-right,h=c.height-top-bottom;
    let min=Infinity,max=-Infinity;series.forEach(s=>s.values.forEach(v=>{min=Math.min(min,v);max=Math.max(max,v)}));if(min===max){min-=1;max+=1}
    const a=t[0],z=t[t.length-1],px=v=>left+(v-a)/Math.max(z-a,1e-9)*w,py=v=>top+h-(v-min)/(max-min)*h;
    if(range){x.fillStyle='#fb923c33';x.fillRect(px(Math.max(a,range.start)),top,Math.max(0,px(Math.min(z,range.end))-px(Math.max(a,range.start))),h)}
    series.forEach(s=>{x.strokeStyle=s.color;x.lineWidth=1.4;x.beginPath();t.forEach((v,i)=>i?x.lineTo(px(v),py(s.values[i])):x.moveTo(px(v),py(s.values[i])));x.stroke()});
    x.fillStyle='#bac9df';x.fillText(max.toPrecision(3),2,top+10);x.fillText(min.toPrecision(3),2,top+h);x.fillText(`${a.toFixed(3)} s`,left,c.height-8);x.fillText(`${z.toFixed(3)} s`,c.width-85,c.height-8);
  }
  function heat(){
    const [c,x]=canvas('dgHeat');if(!report)return;const g=report.spectrogram,w=c.width-left-right,h=c.height-top-bottom,rows=g.db.length,bins=g.frequency.length;
    g.db.forEach((row,i)=>row.forEach((db,j)=>{const v=(db+80)/80;x.fillStyle=`hsl(${250-190*v} 80% ${18+42*v}%)`;x.fillRect(left+i*w/rows,top+(bins-j-1)*h/bins,w/rows+1,h/bins+1)}));
    x.fillStyle='#bac9df';x.fillText(`${g.frequency[bins-1].toFixed(1)} Hz`,0,top+10);x.fillText('0 Hz',4,top+h);x.fillText(`${report.parameters.start.toFixed(3)} s`,left,c.height-8);x.fillText(`${report.parameters.end.toFixed(3)} s`,c.width-85,c.height-8);
    const duration=report.parameters.end-report.parameters.start,edge=Math.min(w/2,g.edge_seconds/duration*w);x.fillStyle='#ffffff16';x.fillRect(left,top,edge,h);x.fillRect(left+w-edge,top,edge,h);
    if(selected){x.strokeStyle='#fb923c';x.lineWidth=3;x.strokeRect(left+(selected.start-report.parameters.start)/duration*w,top,(selected.end-selected.start)/duration*w,h)}
  }
  function render(){
    if(!report)return;
    const p=report.parameters;selected=null;$('dgSource').value=p.source;$('dgWindow').value=p.window;$('dgOverlap').value=p.overlap;$('dgStart').value=p.start;$('dgEnd').value=p.end;
    $('dgResolution').textContent=`${report.sample_count} 点 · 有效窗长 ${p.effective_window} 点 / ${report.window_seconds.toFixed(4)} s · 频率间隔 ${report.frequency_resolution_hz.toFixed(3)} Hz · 帧步长 ${report.hop_seconds.toFixed(4)} s。两端浅色区域受零填充影响；长信号图像做最大值聚合。`;
    heat();wave('dgWave',report.waveform.time,[{values:report.waveform.observed,color:'#22d3ee'}]);
    $('dgEvents').innerHTML=report.events.length?report.events.map(e=>`<article class="dg-card"><h3>${esc(e.label)}</h3><p>${e.start.toFixed(3)}–${e.end.toFixed(3)} s</p><p>证据：${esc(JSON.stringify(e.evidence))}</p><p>${esc(e.alternatives)}</p><button data-select="${e.id}">定位波形</button>${e.kind!=='frequency_shift'?`<button data-verify="${e.id}">运行验证实验</button>`:''}</article>`).join(''):'<p>未检测到显著特征；这不代表不存在故障。</p>';
    if(report.truncated_events)$('dgEvents').insertAdjacentHTML('beforeend','<p>事件已达 64 条上限，请缩小区间进一步检查。</p>');
    document.querySelectorAll('[data-select]').forEach(b=>b.onclick=()=>select(report.events.find(e=>e.id===b.dataset.select)));
    document.querySelectorAll('[data-verify]').forEach(b=>b.onclick=()=>action('verify',{event_id:b.dataset.verify,token:report.token}));
    $('dgTruth').textContent=lab.challenge?(lab.blind&&!lab.revealed?'盲测中：真值、种子、参考误差已隐藏。':JSON.stringify({seed:lab.seed,truth:lab.truth,evaluation:lab.evaluation},null,2)):'';
    $('dgVerification').hidden=!lab.verification;if(lab.verification)showTrial(lab.verification);
  }
  function select(e){if(!e)return;selected=e;$('dgStart').value=e.start;$('dgEnd').value=e.end;heat();wave('dgWave',report.waveform.time,[{values:report.waveform.observed,color:'#22d3ee'}],e)}
  function showTrial(v){$('dgVerification').hidden=false;$('dgVerdict').textContent=v.method+' · '+v.verdict;$('dgMetrics').textContent=JSON.stringify(v.metrics,null,2);if(v.plot)wave('dgTrial',v.plot.time,[{values:v.plot.before,color:'#22d3ee'},{values:v.plot.after,color:'#4ade80'}],v);else{canvas('dgTrial');$('dgVerdict').textContent+='（恢复的快照保留指标；重新验证可显示曲线）'}}
  function addFault(){
    if($('dgFaults').children.length>=8)return;const row=document.createElement('div');row.className='dg-fault';row.innerHTML=`<label>类型<select data-key="kind">${Object.entries(labels).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label>开始 / s<input data-key="start" type="number" value="2.4" min="0" step="any"></label><label>结束 / s<input data-key="end" type="number" value="3.5" min="0" step="any"></label><label>强度<input data-key="strength" type="number" value="2" min="0" step="any"></label><label>频率 / Hz<input data-key="frequency" type="number" value="38" min="0" step="any"></label><button type="button">移除</button>`;
    row.querySelector('select').value='narrowband';row.querySelector('select').onchange=e=>{const k=e.target.value;row.querySelector('[data-key="frequency"]').disabled=!['narrowband','frequency_shift'].includes(k);row.querySelector('[data-key="strength"]').value=k==='clipping'?'.6':'2'};row.querySelector('button').onclick=()=>row.remove();$('dgFaults').append(row);
  }
  $('dgAddFault').onclick=addFault;addFault();
  $('dgAnalyze').onclick=()=>action('analyze',{options:options()});
  $('dgFull').onclick=()=>{$('dgStart').value=0;$('dgEnd').value='';selected=null;heat()};
  $('dgDemo').onclick=()=>{if(window.confirm('载入 8 秒故障演示将替换当前工作区信号；需要保留时请先保存快照。'))action('demo',{blind:$('dgBlind').checked})};
  $('dgInject').onclick=()=>{if(!window.confirm('注入将替换当前观测并清除当前处理结果；已保存快照保留。'))return;const faults=Array.from($('dgFaults').children).map(row=>Object.fromEntries(Array.from(row.querySelectorAll('[data-key]')).filter(e=>!e.disabled).map(e=>[e.dataset.key,e.dataset.key==='kind'?e.value:+e.value])));action('inject',{faults,seed:+$('dgSeed').value,blind:$('dgBlind').checked})};
  $('dgReveal').onclick=()=>action('reveal');$('dgAdopt').onclick=()=>action('adopt');
  $('dgReport').onclick=async()=>{try{const r=await fetch(`/api/diagnostics/view?session_id=${encodeURIComponent(sessionId)}&format=html`);if(!r.ok)throw Error((await r.json()).error);const u=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=u;a.download='diagnostics.html';a.click();setTimeout(()=>URL.revokeObjectURL(u),30000)}catch(e){status(e.message,true)}};
  let drag=null;const timeAt=e=>{const c=$('dgHeat'),rect=c.getBoundingClientRect(),x=(e.clientX-rect.left)*c.width/rect.width;return report.parameters.start+Math.max(0,Math.min(1,(x-left)/(c.width-left-right)))*(report.parameters.end-report.parameters.start)};
  $('dgHeat').onpointerdown=e=>{if(!report||busy)return;drag=timeAt(e);e.currentTarget.setPointerCapture(e.pointerId)};
  $('dgHeat').onpointerup=e=>{if(drag===null)return;const end=timeAt(e),start=drag;drag=null;if(Math.abs(end-start)<16/(report.parameters.effective_window/report.window_seconds)){status('选择区间至少需要 16 点，请拖动更宽的范围。',true);return}select({start:Math.min(start,end),end:Math.max(start,end)})};
  window.addEventListener('experiment-state',e=>{lab=e.detail?.diagnostic_lab||{};if(busy)return;if(lab.analysis){view().catch(err=>status(err.message,true))}else{revision++;report=null;selected=null;canvas('dgHeat');canvas('dgWave');$('dgEvents').textContent='';$('dgVerification').hidden=true;$('dgTruth').textContent='';$('dgResolution').textContent=''}});
  window.addEventListener('resize',()=>{heat();if(report)wave('dgWave',report.waveform.time,[{values:report.waveform.observed,color:'#22d3ee'}],selected)});
})();
