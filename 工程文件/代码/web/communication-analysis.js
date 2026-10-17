/* Ocean RF instruments: all curves use measured result arrays. */
window.communicationAlign = function(a,b,enabled) {
  if(!a||!b||a.domain!==b.domain||a.unit!==b.unit)return {a,b,text:'选择相同信号类型的两个观察点'};
  const rate=a.sample_rate||1,ratio=(b.sample_rate||1)/rate;
  const n=Math.min(a.i.length,Math.floor((b.i.length-1)/ratio)+1);
  const sample=(values,pos)=>{const lo=Math.floor(pos),t=pos-lo;return values[lo]*(1-t)+(values[Math.min(lo+1,values.length-1)]||0)*t};
  const bi=Array.from({length:n},(_,i)=>sample(b.i,i*ratio)),bq=Array.from({length:n},(_,i)=>sample(b.q,i*ratio));
  let lag=0,best=0;
  if(enabled&&n>=16){
    const avg=v=>v.reduce((s,x)=>s+x,0)/v.length,ar=avg(a.i.slice(0,n)),ai=avg(a.q.slice(0,n)),br=avg(bi),bim=avg(bq),limit=Math.min(256,Math.floor(n/3));
    for(let shift=-limit;shift<=limit;shift++){
      let re=0,im=0,pa=0,pb=0;const begin=Math.max(0,-shift),end=Math.min(n,n-shift);
      for(let i=begin;i<end;i++){const u=a.i[i]-ar,v=a.q[i]-ai,x=bi[i+shift]-br,y=bq[i+shift]-bim;re+=u*x+v*y;im+=u*y-v*x;pa+=u*u+v*v;pb+=x*x+y*y}
      const score=Math.hypot(re,im)/Math.sqrt(Math.max(1e-30,pa*pb));
      if(score>best+1e-12||(Math.abs(score-best)<1e-12&&Math.abs(shift)<Math.abs(lag))){best=score;lag=shift}
    }
  }
  const start=Math.max(0,-lag),end=Math.min(n,n-lag),aa={...a,i:a.i.slice(start,end),q:a.q.slice(start,end),offset:(a.offset||0)+start},bb={...b,i:bi.slice(start+lag,end+lag),q:bq.slice(start+lag,end+lag),sample_rate:a.sample_rate,offset:aa.offset};
  return {a:aa,b:bb,lag,score:best,text:enabled?`B 相对 A 延迟 ${lag} 点${a.sample_rate?' / '+(lag/rate*1000).toPrecision(4)+' ms':''} · 归一化相关 ${best.toFixed(3)} · 当前窗口搜索 ±${Math.min(256,Math.floor(n/3))} 点`:'按采样率对齐当前时间窗'};
};

window.createCommunicationAnalysis = function(core,extras){
  'use strict';
  const {byId,esc,root}=core;const get=()=>core.get();let current=null;
  const panel=document.createElement('details');panel.className='cm-experience cm-rf-panel';panel.id='cmRFPanel';
  panel.innerHTML=`<summary>🌊 真实收发链路 · 测量仪表与实验任务</summary>
    <div class="cm-experience-row"><label>🧭 实验任务<select id="cmRFTask"></select></label><button id="cmRFLoad" type="button">载入任务链路</button><button id="cmRFCompare" type="button">运行任务对照</button></div><p id="cmRFGoal"></p><p id="cmRFStatus" role="status">运行链路后查看完整帧测量。</p>
    <div id="cmRFMetrics" class="cm-rf-metrics"></div>
    <div class="cm-experience-row"><label>测量位置<select id="cmRFPoint"></select></label><label>仪表<select id="cmRFMode"><option value="spectrum">Welch 功率谱</option><option value="ccdf">功率 CCDF</option><option value="evm">分段 / 多帧 EVM</option><option value="papr">逐帧峰均比</option><option value="carrier">逐子载波 EVM</option><option value="channel">子载波信道幅度</option></select></label><button type="button" id="cmRFExport">导出测量 JSON</button></div>
    <canvas id="cmRFChart" height="260" aria-label="射频性能测量曲线"></canvas><p id="cmRFCaption"></p>
    <details><summary>📶 主信道与邻道测量</summary><div class="cm-experience-row"><label>主信道中心 / Hz<input type="number" id="cmRFCenter" value="0"></label><label>主信道带宽 / Hz<input type="number" min="0.001" id="cmRFBand" value="300"></label><label>邻道中心间隔 / Hz<input type="number" min="0.001" id="cmRFSpacing" value="350"></label><label>邻道带宽 / Hz<input type="number" min="0.001" id="cmRFAdjacent" value="200"></label></div><p id="cmRFACLR"></p></details>
    <details id="cmRFGridPanel"><summary>🟦 OFDM 资源栅格</summary><canvas id="cmRFGrid" height="230" aria-label="OFDM 数据导频保护资源分配"></canvas><p id="cmRFGridInfo"></p></details>
    <div id="cmRFComparisons" class="cm-trace-scroll"></div><canvas id="cmRFCompareChart" height="250" aria-label="实验任务对照曲线"></canvas><p id="cmRFCompareCaption"></p>`;
  byId('cmForm').after(panel);
  byId('cmRFTask').innerHTML=get().catalog.tasks.map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join('');
  function state(){return extras.meta()}
  function selectedTask(){return get().catalog.tasks.find(t=>t.id===byId('cmRFTask').value)||get().catalog.tasks[0]}
  function goal(){byId('cmRFGoal').textContent=selectedTask().goal}
  function status(text){byId('cmRFStatus').textContent=text}
  // Keep CSS dimensions independent of the backing-store pixel ratio.
  function canvas(id){const c=byId(id),width=Math.max(200,c.getBoundingClientRect().width),height=id==='cmRFGrid'?230:260,dpr=Math.min(2,devicePixelRatio||1);c.width=width*dpr;c.height=height*dpr;const x=c.getContext('2d');x.setTransform(dpr,0,0,dpr,0,0);x.fillStyle='#f4f8ff';x.fillRect(0,0,width,height);x.font=chartFont(10);return {x,width,height}}
  const colors=['#5365cf','#238879','#af5390','#bd7a21','#3797b5'];
  function chart(id,series,xlabel,ylabel,log=false){
    const {x,width,height}=canvas(id),all=series.flatMap(s=>s.x.map((v,i)=>[v,s.y[i]])).filter(p=>p.every(Number.isFinite));
    if(!all.length){x.fillStyle='#60718a';x.fillText('运行对应实验后显示测量曲线',24,40);return}
    let loX=Math.min(...all.map(p=>p[0])),hiX=Math.max(...all.map(p=>p[0]));if(hiX===loX)hiX=loX+1;
    const value=v=>log?Math.log10(Math.max(1e-6,v)):v,ys=all.map(p=>value(p[1]));let lo=Math.min(...ys),hi=Math.max(...ys);if(hi===lo){hi+=1;lo-=1}const margin=(hi-lo)*.08;hi+=margin;lo-=margin;
    const plotHeight=height-72-Math.max(0,series.length-1)*12;const px=v=>48+(v-loX)/(hiX-loX)*(width-64),py=v=>height-32-(value(v)-lo)/(hi-lo)*plotHeight;
    x.strokeStyle='#d1dced';x.fillStyle='#526b8e';
    for(let i=0;i<=4;i++){const yy=height-32-i*plotHeight/4;x.beginPath();x.moveTo(48,yy);x.lineTo(width-16,yy);x.stroke();x.textAlign='right';x.fillText((lo+(hi-lo)*i/4).toPrecision(3),44,yy+3);x.textAlign='center';x.fillText((loX+(hiX-loX)*i/4).toPrecision(3),48+i*(width-64)/4,height-18)}
    series.forEach((s,index)=>{x.strokeStyle=colors[index%colors.length];x.lineWidth=1.6;x.beginPath();let started=false;s.x.forEach((v,i)=>{if(!Number.isFinite(v)||!Number.isFinite(s.y[i]))return;if(started)x.lineTo(px(v),py(s.y[i]));else{x.moveTo(px(v),py(s.y[i]));started=true}});x.stroke();x.fillStyle=x.strokeStyle;x.textAlign='left';x.fillText(s.name.slice(0,30),52,14+index*12)});
    x.fillStyle='#526b8e';x.textAlign='right';x.fillText(xlabel,width-12,height-3);x.textAlign='left';x.fillText((log?'log₁₀ ':'')+ylabel,3,30);
  }
  function locations(){const a=current?.analysis;if(!a)return [];return [{name:'发送端',data:a.tx},{name:'信道输出',data:a.channel},...(a.stages||[]).flatMap(s=>[{name:s.label+' · 输入',data:s.before},{name:s.label+' · 输出',data:s.after}])]}
  function point(){return locations()[Number(byId('cmRFPoint').value)]||locations()[0]}
  function fmt(v,unit=''){return Number.isFinite(v)?Number(v.toPrecision(5))+' '+unit:'—'}
  function bands(){
    const p=point()?.data;if(!p)return;
    const center=Number(byId('cmRFCenter').value),bw=Number(byId('cmRFBand').value),spacing=Number(byId('cmRFSpacing').value),adj=Number(byId('cmRFAdjacent').value),fs=p.sample_rate;
    if(![center,bw,spacing,adj].every(Number.isFinite)||Math.min(bw,spacing,adj)<=0||spacing<(bw+adj)/2||Math.abs(center)+bw/2>fs/2||Math.abs(center)+spacing+adj/2>fs/2){byId('cmRFACLR').textContent='请设置采样带宽内、互不重叠的主信道和两个邻道。';return}
    const power=(mid,width)=>p.density.reduce((sum,v,i)=>sum+(Math.abs(p.frequency_hz[i]-mid)<width/2?v*fs/p.density.length:0),0),main=power(center,bw),left=power(center-spacing,adj),right=power(center+spacing,adj);
    const ratio=v=>main>0&&v>0?fmt(10*Math.log10(main/v),'dB'):'无可测功率';
    byId('cmRFACLR').textContent=`ACLR 左 ${ratio(left)} · 右 ${ratio(right)} · 主信道积分功率 ${fmt(main)} · 分辨率 ${fmt(fs/p.density.length,'Hz')}`;
  }
  function grid(){
    const o=current?.advanced?.ofdm;byId('cmRFGridPanel').hidden=!o;if(!o)return;
    const {x,width,height}=canvas('cmRFGrid'),rows=Math.min(16,o.symbols+1),dx=(width-50)/o.nfft,dy=(height-45)/rows,palette={data:'#7887dc',pilot:'#3aaf9a',guard:'#d8e1ee',dc:'#b48bbd',training:'#e4bd71'};
    for(let row=0;row<rows;row++)for(let display=0;display<o.nfft;display++){const k=(display+o.nfft/2)%o.nfft,role=o.roles?.[k]||'data';x.fillStyle=palette[row===0&&['data','pilot'].includes(role)?'training':role];x.fillRect(38+display*dx,18+row*dy,Math.max(.5,dx-.5),Math.max(1,dy-1))}
    x.fillStyle='#526b8e';x.fillText('−Fs/2',38,height-8);x.fillText('0',width/2,height-8);x.textAlign='right';x.fillText('+Fs/2',width-12,height-8);
    byId('cmRFGridInfo').textContent=`金色：训练 · 紫蓝：数据 · 绿色：导频 · 灰色：保护 · 淡紫：直流；${o.data_carriers.length} 数据 / ${o.pilot_carriers.length} 导频，CP=${o.cp}，显示 ${rows} / ${o.symbols+1} 个 OFDM 符号。`;
  }
  function draw(){
    if(root.hidden||!panel.open)return;
    const a=current?.analysis,p=point()?.data,mode=byId('cmRFMode').value;let s=[],xlabel='',ylabel='',caption='';
    if(p&&mode==='spectrum'){s=[{name:point().name,x:p.frequency_hz,y:p.density_db}];xlabel='相对载频 / Hz';ylabel='dB/Hz';caption=`${p.method} · ${p.count} 点 · ${p.segments} 段 · Fs=${p.sample_rate} Hz`}
    if(p&&mode==='ccdf'){s=[{name:point().name,x:p.ccdf_db,y:p.ccdf}];xlabel='瞬时功率 / 平均功率 dB';ylabel='超越概率';caption='CCDF 统计整帧离散采样功率；PAPR 为当前采样波形峰均比。'}
    if(a&&mode==='evm'){const frames=state().rfFrames||[];s=[{name:frames.length?'逐帧 EVM':'每 128 符号 EVM',x:frames.length?frames.map(r=>r.frame):a.evm_trace.map(r=>r.symbol),y:frames.length?frames.map(r=>r.evm_percent):a.evm_trace.map(r=>r.evm_percent)}];xlabel=frames.length?'帧':'符号';ylabel='EVM %'}
    if(mode==='papr'){const f=state().rfFrames||[];s=[{name:'逐帧 PAPR',x:f.map(r=>r.frame),y:f.map(r=>r.papr_db)}];xlabel='帧';ylabel='PAPR dB';caption='使用「保持状态运行」累计多帧峰均比。'}
    if(a?.ofdm_evm&&mode==='carrier'){s=[{name:'数据子载波',x:a.ofdm_evm.carriers,y:a.ofdm_evm.percent}];xlabel='FFT 子载波编号';ylabel='EVM %'}
    const o=current?.advanced?.ofdm;if(o?.channel_i&&mode==='channel'){s=[{name:'接收信道估计',x:o.active_carriers,y:o.active_carriers.map(i=>Math.hypot(o.channel_i[i],o.channel_q[i]))}];xlabel='FFT 子载波编号';ylabel='|H|'}
    chart('cmRFChart',s,xlabel,ylabel,mode==='ccdf');byId('cmRFCaption').textContent=caption;bands();grid();compareChart();
  }
  function compareChart(){
    const variants=state().rfComparisons?.variants||[],mode=byId('cmRFMode').value;let series=[],xlabel='',ylabel='';
    if(['spectrum','ccdf'].includes(mode)){
      const location=Number(byId('cmRFPoint').value);series=variants.map(v=>{const a=v.result.analysis;const points=[a.tx,a.channel,...(a.stages||[]).flatMap(s=>[s.before,s.after])],p=points[location];if(!p)return null;return {name:v.name,x:mode==='spectrum'?p.frequency_hz:p.ccdf_db,y:mode==='spectrum'?p.density_db:p.ccdf}}).filter(Boolean);xlabel=mode==='spectrum'?'Hz':'峰值门限 dB';ylabel=mode==='spectrum'?'dB/Hz':'超越概率';
    }else{const key=mode==='papr'?'papr_db':'evm_percent';series=[{name:key,x:variants.map((_,i)=>i+1),y:variants.map(v=>v.result.metrics[key])}];xlabel='方案序号';ylabel=key==='papr_db'?'PAPR dB':'EVM %'}
    chart('cmRFCompareChart',series,xlabel,ylabel,mode==='ccdf');byId('cmRFCompareCaption').textContent=state().rfComparisons?.seed_policy||'任务对照会同时绘制各方案测量曲线。';
  }
  function comparisons(){const v=state().rfComparisons?.variants||[];byId('cmRFComparisons').innerHTML=v.length?'<table><thead><tr><th>方案</th><th>BER</th><th>EVM %</th><th>PAPR dB</th><th>净速率 bit/s</th><th>bit/s/Hz</th></tr></thead><tbody>'+v.map((r,i)=>`<tr><td>${i+1}. ${esc(r.name)}</td><td>${fmt(r.result.metrics.ber)}</td><td>${fmt(r.result.metrics.evm_percent)}</td><td>${fmt(r.result.metrics.papr_db)}</td><td>${fmt(r.result.metrics.net_bit_rate)}</td><td>${fmt(r.result.metrics.spectral_efficiency)}</td></tr>`).join('')+'</tbody></table>':'';compareChart()}
  function onResult(result){
    current=result;if(result&&!Number.isInteger(result.experience?.frame))state().rfFrames=[];const old=byId('cmRFPoint').value;byId('cmRFPoint').innerHTML=locations().map((p,i)=>`<option value="${i}">${esc(p.name)}</option>`).join('');if(Number(old)<locations().length)byId('cmRFPoint').value=old;
    const a=result?.analysis;byId('cmRFMetrics').innerHTML=a?[['净信息速率',fmt(a.net_bit_rate,'bit/s')],['频谱效率',fmt(a.spectral_efficiency,'bit/s/Hz')],['99% 占用带宽',fmt(a.tx.occupied_bandwidth_hz,'Hz')],['发送峰均比',fmt(a.tx.papr_db,'dB')],['判决前 EVM',fmt(result.metrics.evm_percent,'%')],['ADC 饱和样本',String(result.advanced?.adc?.clipped_samples??'—')]].map(([title,value])=>`<div><span>${title}</span><strong>${esc(value)}</strong></div>`).join(''):'';
    if(!a)status('运行链路后查看完整帧测量。');
    if(a){const fs=a.tx.sample_rate,prefs=state().rfSettings;if(prefs&&prefs.fs===fs)for(const [id,value] of Object.entries(prefs.bands))byId(id).value=value;else{byId('cmRFCenter').value=0;byId('cmRFBand').value=fs*.3;byId('cmRFSpacing').value=fs*.35;byId('cmRFAdjacent').value=fs*.2}status(a.net_bit_rate===null?'模拟调制按复包络统计功率、频谱和峰均比。':'速率包含实际发送的编码、前导、导频、CP 与填充开销；频谱效率以发送 99% 占用带宽计算。')}
    draw();comparisons();
  }
  function changed(){state().rfSettings={fs:current?.analysis?.tx.sample_rate,bands:Object.fromEntries(['cmRFCenter','cmRFBand','cmRFSpacing','cmRFAdjacent'].map(id=>[id,Number(byId(id).value)]))};extras.persist();draw()}
  byId('cmRFTask').onchange=goal;goal();
  byId('cmRFLoad').onclick=()=>{if(get().busy)return;core.setProgram(core.clone(get().catalog.presets[selectedTask().preset].program),'已载入 '+selectedTask().title);status(selectedTask().goal)};
  byId('cmRFCompare').onclick=async()=>{if(get().busy)return;core.setBusy(true);try{const b=await core.api('build',{program:get().program});const value=await extras.runJob('rf-task',{program:b.program,token:b.token,task_id:selectedTask().id});state().rfComparisons=value;if(value.baseline)core.restoreResult(b,value.baseline);extras.persist();comparisons();status(`${value.complete?'对照完成':'已停止'} · ${value.variants.length} 个方案`)}catch(e){status(e.message)}finally{core.setBusy(false)}};
  byId('cmRFExport').onclick=()=>core.download('communication-rf-analysis.json',JSON.stringify({analysis:current?.analysis,metrics:current?.metrics,frames:state().rfFrames||[],comparison:state().rfComparisons,settings:state().rfSettings},null,2),'application/json');
  for(const id of ['cmRFPoint','cmRFMode'])byId(id).onchange=draw;
  for(const id of ['cmRFCenter','cmRFBand','cmRFSpacing','cmRFAdjacent'])byId(id).onchange=changed;
  panel.addEventListener('toggle',draw);byId('cmRFGridPanel').addEventListener('toggle',grid);window.addEventListener('resize',draw);
  return {onResult,draw,frames:value=>{state().rfFrames=value.frames;draw()},invalidate:()=>{current=null;state().rfFrames=[];state().rfComparisons=null;onResult(null)},buttons:busy=>{byId('cmRFLoad').disabled=busy;byId('cmRFCompare').disabled=busy;byId('cmRFExport').disabled=!current?.analysis&&!state().rfComparisons}};
};
