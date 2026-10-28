/* Observed self-describing frames, BCJR messages and mother-code HARQ buffers. */
window.createCommunicationFramingV0410=function(core,ctx){
  'use strict';
  const {byId,esc}=core;
  const panel=document.createElement('section');panel.id='cmFramingV0410';panel.className='cm-experience cm-learning-panel';
  panel.innerHTML=`<h3>📦 连续物理帧与迭代收发</h3><div class="cm-experience-row"><label>观测对象<select id="cmFramingStage"></select></label><label>视图<select id="cmFramingView"><option value="frames">连续帧与保护帧头</option><option value="turbo">Turbo 先验 / 外信息 / 后验</option><option value="harq">IR / Chase 母码软缓冲</option></select></label><button type="button" id="cmFramingExport">📥 导出观测</button></div><div class="cm-experience-row" id="cmFramingStepRow"><button type="button" id="cmFramingPrevious">◀ 上一步</button><label>迭代 / 重传<input id="cmFramingStep" type="range" min="0" max="0" value="0"></label><button type="button" id="cmFramingNext">下一步 ▶</button></div><canvas id="cmFramingCanvas" height="280" style="width:100%;height:280px;display:block" aria-label="连续帧、Turbo 迭代和 HARQ 缓冲观测"></canvas><p id="cmFramingCaption" role="status"></p><div id="cmFramingSummary" class="cm-learn-metrics"></div><div id="cmFramingTable" class="cm-trace-scroll"></div>`;
  byId('cmPane-rf').append(panel);
  let entries=[],selected=null,protocol=null,lastResult=null;
  const fmt=v=>v==null?'—':typeof v==='number'?(Number.isInteger(v)?String(v):Number(v.toPrecision(5)).toString()):String(v);
  const table=(heads,rows)=>`<table><thead><tr>${heads.map(v=>`<th>${esc(v)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${esc(fmt(v))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  const cards=rows=>rows.map(([label,value])=>`<div><small>${esc(label)}</small><strong>${esc(fmt(value))}</strong></div>`).join('');
  function canvas(){const c=byId('cmFramingCanvas'),w=Math.max(240,c.clientWidth||800),h=280,d=Math.min(2,devicePixelRatio||1);c.width=w*d;c.height=h*d;const g=c.getContext('2d');g.scale(d,d);g.clearRect(0,0,w,h);g.fillStyle='#f4f8ff';g.fillRect(0,0,w,h);g.fillStyle='#395675';g.font='12px sans-serif';return {g,w,h}}
  function plot(series,label){const {g,w,h}=canvas(),values=series.flatMap(s=>s.values).filter(Number.isFinite),lo=Math.min(0,...values),hi=Math.max(1,...values),top=w<600?83:45,bottom=h-30,left=45,right=w-15;g.strokeStyle='#bdd1e5';g.strokeRect(left,top,right-left,bottom-top);g.fillText(label,7,15);g.fillText(fmt(hi),3,top+12);g.fillText(fmt(lo),3,bottom);series.forEach((s,j)=>{g.strokeStyle=g.fillStyle=['#477ac7','#9673c8','#339a94'][j%3];g.fillText(s.name,w<600?left:left+j*170,w<600?34+j*17:32);g.beginPath();s.values.forEach((v,i)=>{const x=left+i/Math.max(1,s.values.length-1)*(right-left),y=bottom-(v-lo)/(hi-lo)*(bottom-top);if(i)g.lineTo(x,y);else g.moveTo(x,y)});g.stroke()});g.fillStyle='#395675';g.fillText('比特序号',left,h-8)}
  function modeFor(value){return value.learning?.kind==='turbo'?'turbo':value.events?'harq':'frames'}
  function fill(){const old=byId('cmFramingStage').value;entries=[];for(const [id,value] of Object.entries(lastResult?.advanced?.wireless||{}))if(value.kind==='self_frame_tx'||value.kind==='self_frame_rx')entries.push({id,label:value.kind==='self_frame_rx'?'接收物理帧与重组':'发送物理帧',value});for(const [i,value] of (lastResult?.advanced?.codecs||[]).entries())if(value.kind==='turbo_decode')entries.push({id:'turbo-'+i,label:'Turbo 迭代译码器',value});const p=protocol||ctx.meta().learning?.protocolResult;if(p?.events?.some(e=>e.mother_indices))entries.push({id:'harq',label:p.config.mode==='ir_harq'?'IR-HARQ 母码软缓冲':'Chase 母码软缓冲',value:p});byId('cmFramingStage').innerHTML=entries.map(v=>`<option value="${esc(v.id)}">${esc(v.label)}</option>`).join('');selected=entries.find(e=>e.id===old)||entries.find(e=>e.value.kind==='self_frame_rx')||entries[0];if(selected){byId('cmFramingStage').value=selected.id;byId('cmFramingView').value=modeFor(selected.value)}buttons(core.get().busy)}
  function draw(){
    canvas();byId('cmFramingSummary').innerHTML='';byId('cmFramingTable').innerHTML='';
    const item=entries.find(e=>e.id===byId('cmFramingStage').value),value=item?.value,mode=byId('cmFramingView').value,range=byId('cmFramingStep');
    byId('cmFramingStepRow').hidden=mode==='frames';
    if(!value){byId('cmFramingCaption').textContent='运行自描述帧、Turbo 或 IR-HARQ 实验，查看实际帧头、迭代软信息与重传覆盖。';return;}
    if(mode==='frames'){
      const rows=value.frames;if(!rows){byId('cmFramingCaption').textContent='选择发送或接收物理帧观测。';return;}
      const {g,w,h}=canvas(),end=Math.max(1,...rows.map(r=>r.end_sample)),height=Math.max(2,Math.min(22,(h-55)/Math.max(1,rows.length)));
      rows.forEach((r,i)=>{const x=48+r.start_sample/end*(w-65),right=48+r.end_sample/end*(w-65),y=25+i*height;g.fillStyle=r.payload_crc_pass===false?'#c89acc':'#70beb1';g.fillRect(x,y,Math.max(3,right-x),Math.max(2,height-4));if(rows.length<13||i%Math.ceil(rows.length/12)===0){g.fillStyle='#395675';g.fillText(String(r.sequence),10,y+11)}});g.fillStyle='#395675';g.fillText('包序号 / 实际样本位置',10,14);g.fillText(`0 → ${fmt(end)} 样本`,48,h-8);
      byId('cmFramingCaption').textContent=value.kind==='self_frame_rx'?'帧头经过 BPSK + 卷积码 + CRC16 保护；长度、MCS、序号与业务偏移来自接收波形。':'每包携带独立前导、保护帧头与载荷 CRC16，接收端逐包捕获。';
      byId('cmFramingSummary').innerHTML=cards([['业务比特',value.total_bits],['成功包',value.accepted_packets??rows.length],['接收比特',value.received_bits??value.total_bits],['完整恢复',value.complete_payload===undefined?'发送就绪':value.complete_payload?'完成':'查看覆盖区间']]);
      byId('cmFramingTable').innerHTML=table(['包序号','起点 / 样本','载荷位数','业务偏移','MCS','帧头 CRC','载荷 CRC'],rows.map(r=>[r.sequence,r.start_sample,r.payload_bits,r.offset_bits,r.mcs_name,r.header_crc_pass===undefined?'已编码':'通过',r.payload_crc_pass===undefined?'已编码':r.payload_crc_pass?'通过':r.truncated?'尾部截断':'校验失败']));
    }else if(mode==='turbo'){
      const history=value.learning?.history;if(value.learning?.kind!=='turbo'){byId('cmFramingCaption').textContent='选择 Turbo 迭代译码器。';return;}
      range.max=history.length-1;const index=Math.min(Number(range.value),history.length-1),step=history[index];range.value=index;
      plot([{name:'第一译码器先验',values:step.prior},{name:'第一译码器外信息',values:step.extrinsic},{name:'本轮后验',values:step.posterior}],'LLR · log P(0)/P(1)');
      byId('cmFramingCaption').textContent=`${value.algorithm} · 第 ${step.iteration} / ${value.iterations} 轮 · 首码字前 ${step.posterior.length} 位；外信息经交织后进入另一译码器。`;
      byId('cmFramingSummary').innerHTML=cards([['信息位 K',value.block_size],['码字数',value.codewords],['本轮硬判变化',step.changed_bits],['平均 |后验|',step.mean_abs_posterior]]);
      byId('cmFramingTable').innerHTML=table(['位序号','先验','外信息','后验'],step.posterior.map((v,i)=>[i,step.prior[i],step.extrinsic[i],v]));
    }else{
      const events=value.events;if(!events){byId('cmFramingCaption').textContent='在教学实验的协议与速率中运行 IR-HARQ，或选择同预算 Chase 对照。';return;}
      range.max=events.length-1;const index=Math.min(Number(range.value),events.length-1),event=events[index];range.value=index;
      plot([{name:'母码 LLR 缓冲',values:(event.llr_buffer||[]).slice(0,256)}],'LLR · 首 256 个母码位置');
      byId('cmFramingCaption').textContent=`包 ${event.packet} · 第 ${event.attempt} 次发送 · RV ${event.rv} · ${event.crc_pass?'CRC 通过':'继续积累软信息'}；按母码索引合并每次实际接收的 LLR。`;
      byId('cmFramingSummary').innerHTML=cards([['本轮编码位',event.coded_bits],['母码覆盖',`${fmt(100*event.mother_coverage)}%`],['发送样本',event.symbols],['累计发送能量',event.accumulated_tx_energy]]);
      byId('cmFramingTable').innerHTML=table(['包','次数','RV','编码位','母码覆盖','发送能量','CRC'],events.map(e=>[e.packet,e.attempt,e.rv,e.coded_bits,`${fmt(100*e.mother_coverage)}%`,e.tx_energy,e.crc_pass?'通过':'重传']));
    }
  }
  function render(){const result=core.get().result||ctx.meta().result||null;if(result!==lastResult){lastResult=result;protocol=null;byId('cmFramingStep').value=0}fill();draw()}
  function onResult(result){lastResult=result;protocol=null;byId('cmFramingStep').value=0;fill();draw()}
  function onProtocol(result){protocol=result;fill();byId('cmFramingStage').value='harq';byId('cmFramingView').value='harq';byId('cmFramingStep').value=0;draw()}
  function buttons(busy){panel.querySelectorAll('button,input,select').forEach(e=>e.disabled=busy);byId('cmFramingExport').disabled=busy||!entries.length}
  byId('cmFramingStage').onchange=()=>{selected=entries.find(e=>e.id===byId('cmFramingStage').value);if(selected)byId('cmFramingView').value=modeFor(selected.value);byId('cmFramingStep').value=0;draw()};byId('cmFramingView').onchange=draw;byId('cmFramingStep').oninput=draw;
  function step(delta){const r=byId('cmFramingStep');r.value=Math.max(0,Math.min(Number(r.max),Number(r.value)+delta));draw()}
  byId('cmFramingPrevious').onclick=()=>step(-1);byId('cmFramingNext').onclick=()=>step(1);
  byId('cmFramingExport').onclick=()=>core.download('物理帧与迭代收发观测.json',JSON.stringify(entries,null,2),'application/json');
  byId('cmTab-rf').addEventListener('click',render);window.addEventListener('resize',draw);
  core.root.addEventListener('cm-protocol-result',event=>onProtocol(event.detail));
  function invalidate(){lastResult=null;protocol=null;fill();draw()}
  render();return {render,onResult,onProtocol,buttons,invalidate,replaceProgram:invalidate};
};
