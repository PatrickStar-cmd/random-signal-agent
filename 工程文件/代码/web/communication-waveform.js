/* Measured waveform, amplifier, synchronization and Polar instruments. */
window.createCommunicationWaveform = function(core,ctx) {
  'use strict';
  const {byId,esc}=core;
  const panel=document.createElement('section');panel.className='cm-experience cm-learning-panel';panel.id='cmWaveformPanel';
  panel.innerHTML=`<h3>🌊 新波形、同步与现代编码</h3><div class="cm-experience-row"><label>处理环节<select id="cmWaveformStage"></select></label><label>观察视图<select id="cmWaveformView"><option value="amplitude">AM/AM 幅度响应</option><option value="phase">AM/PM 相位响应</option><option value="spectrum">处理前后功率谱</option><option value="sync">前导捕获与时钟估计</option><option value="carriers">子载波映射与信道</option><option value="coefficients">DPD 系数</option><option value="polar">Polar 路径与冻结位</option></select></label><button type="button" id="cmWaveformExport">📦 导出观测数据</button></div><canvas id="cmWaveformCanvas" style="width:100%;height:280px;display:block" height="280" aria-label="波形与同步算法观测"></canvas><p id="cmWaveformCaption" role="status"></p><div class="cm-trace-scroll" id="cmWaveformTable"></div>`;
  byId('cmPane-rf').append(panel);
  let entries=[],current=null;
  const format=v=>typeof v==='number'?(Number.isInteger(v)?String(v):v.toPrecision(5)):v==null?'—':String(v);
  const table=(heads,rows)=>`<table><thead><tr>${heads.map(v=>`<th>${esc(v)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${esc(format(v))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  const caption=v=>byId('cmWaveformCaption').textContent=v;
  function canvas(){const c=byId('cmWaveformCanvas'),width=Math.max(240,c.clientWidth),height=280,dpr=Math.min(2,devicePixelRatio||1);c.width=width*dpr;c.height=height*dpr;const g=c.getContext('2d');g.scale(dpr,dpr);g.fillStyle='#f4f8ff';g.fillRect(0,0,width,height);g.font='12px sans-serif';g.fillStyle='#395675';return {g,width,height}}
  function lines(series,xLabel,yLabel,scatter=false){
    const {g,width:w,height:h}=canvas(),valid=series.filter(v=>v.x.length&&v.y.length);
    if(!valid.length)return;
    const xs=valid.flatMap(s=>s.x),ys=valid.flatMap(s=>s.y),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(0,...ys),ymax=Math.max(1e-9,...ys);
    const x=v=>48+(v-xmin)/Math.max(1e-12,xmax-xmin)*(w-70),y=v=>h-38-(v-ymin)/Math.max(1e-12,ymax-ymin)*(h-78);
    g.strokeStyle='#bdd1e5';g.strokeRect(48,30,w-70,h-68);g.fillText(yLabel,8,15);g.fillText(xLabel,w/2,h-7);g.fillText(format(ymax),2,41);g.fillText(format(ymin),2,h-38);
    valid.forEach((s,j)=>{g.fillStyle=g.strokeStyle=['#477ac7','#9673c8','#339a94','#d09a4b'][j%4];g.fillText(s.name,55+j*155,23);g.beginPath();s.y.forEach((v,i)=>{if(scatter){g.moveTo(x(s.x[i])+2,y(v));g.arc(x(s.x[i]),y(v),2,0,2*Math.PI)}else if(i)g.lineTo(x(s.x[i]),y(v));else g.moveTo(x(s.x[i]),y(v))});if(scatter)g.fill();else g.stroke()});
  }
  const sequence=v=>v.map((_,i)=>i);
  function draw(){
    canvas();byId('cmWaveformTable').innerHTML='';const item=entries.find(e=>e.id===byId('cmWaveformStage').value),v=item?.value;
    if(!v){caption('运行 DFT-s-OFDM、数字预失真、突发同步或 Polar 预设后查看算法观测。');return;}
    const mode=byId('cmWaveformView').value;
    if(mode==='amplitude'||mode==='phase'){
      const values=mode==='amplitude'?v.output_amplitude:v.output_phase_deg;
      if(!v.input_amplitude||!values){caption('选择功放回环采集、数字预失真器或记忆功放查看响应。');return;}
      lines([{name:item.label,x:v.input_amplitude,y:values}],'输入幅度',mode==='amplitude'?'输出幅度':'相位变化 / °',true);
      caption(`${values.length} 个实测样本 · ${v.memory_depth?'记忆深度 '+v.memory_depth:'输入输出对应样本'}`);
    }else if(mode==='spectrum'){
      if(!v.before||!v.after){caption('选择数字预失真器或记忆功放查看处理前后频谱。');return;}
      lines([{name:'处理前',x:v.before.frequency_hz,y:v.before.density_db},{name:'处理后',x:v.after.frequency_hz,y:v.after.density_db}],'频率 / Hz','Welch PSD / dB/Hz');
      caption(`功率 ${format(v.before.power)} → ${format(v.after.power)} · PAPR ${format(v.before.papr_db)} → ${format(v.after.papr_db)} dB`);
    }else if(mode==='sync'){
      if(!v.timing_metric){caption('选择突发捕获与采样时钟恢复积木。');return;}
      lines([{name:'重复前导度量',x:v.offsets,y:v.timing_metric},{name:'公开模板相关',x:v.offsets,y:v.correlation}],'搜索偏移 / 样本','归一化度量');
      caption(`${v.method} · 起点 ${format(v.start_sample)} · CFO ${format(v.frequency_hz)} Hz · SFO ${format(v.clock_ppm)} ppm`);
      byId('cmWaveformTable').innerHTML=table(['捕获','前导拟合误差','前后标记位置','有效波形样本'],[[v.detected?'已捕获':'继续调整接收参数',v.marker_error,v.marker_positions.map(format).join(' / '),v.payload_samples]]);
    }else if(mode==='carriers'){
      if(!v.carriers){caption('选择 SC-FDMA 映射或接收积木查看资源分配。');return;}
      const gains=v.channel_i?v.channel_i.map((x,i)=>Math.hypot(x,v.channel_q[i])):v.carriers.map(()=>1);
      lines([{name:v.mapping||'估计信道',x:v.carriers,y:gains}],'FFT 载波索引','幅度',true);caption(`${v.carriers.length} 个分配载波 · ${v.mapping||'公开训练估计与逐载波均衡'}`);
      byId('cmWaveformTable').innerHTML=table(['分配序号','FFT 索引','信道幅度'],v.carriers.map((n,i)=>[i,n,gains[i]]));
    }else if(mode==='coefficients'){
      if(!v.coefficients_i){caption('选择 DPD 逆模型估计或预失真器查看系数。');return;}
      lines([{name:'系数实部',x:sequence(v.coefficients_i),y:v.coefficients_i},{name:'系数虚部',x:sequence(v.coefficients_q),y:v.coefficients_q}],'系数序号','系数');
      caption(`延迟从小到大、每支路奇数阶从低到高排列${v.fit_error!==undefined?' · 训练归一化误差 '+format(v.fit_error):''}`);
      byId('cmWaveformTable').innerHTML=table(['序号','实部','虚部'],v.coefficients_i.map((x,i)=>[i,x,v.coefficients_q[i]]));
    }else if(mode==='polar'){
      if(!v.learning?.history){caption('选择 Polar 译码器查看幸存路径与冻结位。');return;}
      const rows=v.learning.history,width=Math.max(...rows.map(r=>r.path_metrics.length));
      lines(Array.from({length:Math.min(width,4)},(_,i)=>({name:'路径 '+(i+1),x:rows.map(r=>r.bit),y:rows.map(r=>r.path_metrics[Math.min(i,r.path_metrics.length-1)])})),'极化位序号','累积路径度量');
      caption(`Polar (${v.n}, ${v.k}) · L=${v.list_size} · ${v.codewords} 个码字 · CRC 通过 ${v.codewords-v.failed_codewords}/${v.codewords} · ${format(v.seconds)} s`);
      byId('cmWaveformTable').innerHTML=table(['位序号','位置类型','幸存路径数','最小度量'],rows.map(r=>[r.bit,r.frozen?'冻结位':'信息 / CRC 位',r.path_metrics.length,r.path_metrics[0]]));
    }
  }
  function preferred(v){return v.learning?.kind==='polar'?'polar':v.timing_metric?'sync':v.fit_error!==undefined?'coefficients':v.input_amplitude?'amplitude':v.carriers?'carriers':'coefficients'}
  byId('cmWaveformStage').onchange=()=>{const e=entries.find(v=>v.id===byId('cmWaveformStage').value);if(e)byId('cmWaveformView').value=preferred(e.value);draw()};byId('cmWaveformView').onchange=draw;
  byId('cmWaveformExport').onclick=()=>{if(current)core.download('波形同步与编码观测.json',JSON.stringify(entries,null,2),'application/json')};
  function onResult(result){current=result;entries=[];for(const [id,value] of Object.entries(result?.advanced?.wireless||{})){if(/^(tx_dft_spread|tx_scfdma|rx_scfdma|rx_dft_despread|tx_pa_probe|tx_dpd_fit|tx_dpd|tx_memory_pa|tx_burst_preamble|burst_clock|rx_burst_sync)$/.test(id))entries.push({id,label:core.get().definitions[id]?.label||id,value})}for(const [i,value] of (result?.advanced?.codecs||[]).entries())if(value.kind==='polar_decode')entries.push({id:'polar_'+i,label:'Polar 译码器',value});const old=byId('cmWaveformStage').value;byId('cmWaveformStage').innerHTML=entries.map(v=>`<option value="${esc(v.id)}">${esc(v.label)}</option>`).join('');const picked=entries.find(v=>v.id===old)||entries.find(v=>v.value.timing_metric||v.value.learning?.kind==='polar')||entries.find(v=>v.value.input_amplitude)||entries[0];if(picked){byId('cmWaveformStage').value=picked.id;byId('cmWaveformView').value=preferred(picked.value)}buttons(core.get().busy);draw()}
  function buttons(busy){byId('cmWaveformExport').disabled=busy||!entries.length;}
  window.addEventListener('resize',draw);byId('cmTab-rf').addEventListener('click',draw);
  return {onResult,render:draw,draw,buttons,invalidate:()=>onResult(null)};
};
