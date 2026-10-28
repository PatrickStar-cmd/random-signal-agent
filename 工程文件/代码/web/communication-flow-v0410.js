/* Two typed receive paths and measured OFDM range/velocity, in the ocean UI. */
window.createCommunicationFlowV0410=function(core,ctx){
  'use strict';
  const {byId,esc,clone,get}=core,host=document.createElement('section');
  host.className='cm-learning cm-spatial';host.id='cmFlow410Panel';
  host.innerHTML=`<header><div><h3>🪸 接收汇合与 OFDM 通感</h3><span class="cm-learn-hint">共享同一段信道采样，在两路接收输出处汇合；用同一帧完成通信与目标探测</span></div></header>
    <details class="cm-experiment-details" open><summary>🔱 两路接收汇合</summary>
      <div id="cmMerge410Diagram" class="cm-flow"></div><div class="cm-learning-grid">
      <label>第二条接收分支<select id="cmMerge410Branch"></select></label><label>汇合数据<select id="cmMerge410Domain"><option value="symbols">复符号 · 解调之前</option><option value="llr">LLR · 软译码之前</option></select></label>
      <label>汇合方式<select id="cmMerge410Mode"><option value="weighted">加权相加</option><option value="select">选择一路</option></select></label><label>选择分支<select id="cmMerge410Select"><option value="0">当前接收链路</option><option value="1">第二条接收分支</option></select></label>
      <label>当前分支权重<input id="cmMerge410A" type="number" value="0.5" min="-10" max="10" step="0.1"></label><label>第二分支权重<input id="cmMerge410B" type="number" value="0.5" min="-10" max="10" step="0.1"></label></div>
      <div class="cm-learn-actions"><button type="button" id="cmMerge410Run">▶ 运行两路并汇合</button><button type="button" id="cmMerge410Export">📥 导出汇合实验</button></div><div id="cmMerge410Results" class="cm-learn-scroll"></div></details>
    <details class="cm-experiment-details" open><summary>🔭 OFDM 单目标测距测速</summary><div class="cm-learn-actions"><button type="button" id="cmIsac410Demo">📡 载入通感实验</button></div>
      <p id="cmIsac410Summary"></p><canvas id="cmIsac410Canvas" style="width:100%;height:300px;display:block" height="300" aria-label="实测距离速度二维谱"></canvas><div id="cmIsac410Metrics" class="cm-learn-scroll"></div></details><p id="cmFlow410Status" role="status"></p>`;
  byId('cmPane-spatial').append(host);let current=null;
  const meta=()=>ctx.meta().v0410||(ctx.meta().v0410={});
  const status=t=>byId('cmFlow410Status').textContent=t;
  const fmt=x=>typeof x==='number'?Number(x.toPrecision(5)):x??'—';
  const table=(head,rows)=>`<table><thead><tr>${head.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(x=>`<td>${esc(fmt(x))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  const settings=()=>({domain:byId('cmMerge410Domain').value,mode:byId('cmMerge410Mode').value,select:Number(byId('cmMerge410Select').value),weights:[Number(byId('cmMerge410A').value),Number(byId('cmMerge410B').value)]});
  function drawSense(){
    const data=current?.advanced?.wireless?.rx_isac_ofdm?.sensing,c=byId('cmIsac410Canvas'),w=Math.max(250,c.clientWidth||800),h=300,dpr=Math.min(2,devicePixelRatio||1);c.width=w*dpr;c.height=h*dpr;const x=c.getContext('2d');x.scale(dpr,dpr);x.fillStyle='#f4f8ff';x.fillRect(0,0,w,h);x.font='12px sans-serif';x.fillStyle='#526b8e';
    if(!data){x.fillText('载入 OFDM 通感预设，Build / Run 后显示实测谱',18,32);byId('cmIsac410Summary').textContent='距离来自回波延迟，速度来自跨 OFDM 符号的相位变化。';byId('cmIsac410Metrics').innerHTML='';return;}
    const rows=data.power_db,cols=data.range_axis_m,left=58,top=16,pw=w-left-18,ph=h-57,high=Math.max(...rows.flat()),low=high-60;
    rows.forEach((row,i)=>row.forEach((value,j)=>{const a=Math.max(0,Math.min(1,(value-low)/60));x.fillStyle=`hsl(${220-a*70} ${45+a*30}% ${96-a*66}%)`;x.fillRect(left+j*pw/cols.length,top+(rows.length-i-1)*ph/rows.length,pw/cols.length+1,ph/rows.length+1);}));
    x.fillStyle='#395675';x.fillText('速度 m/s',4,12);x.fillText('距离 m',w-65,h-5);
    for(let i=0;i<5;i++){const j=Math.round(i*(cols.length-1)/4);x.fillText(String(Math.round(cols[j])),left+j*pw/cols.length,h-20);const r=Math.round(i*(rows.length-1)/4);x.fillText(String(Math.round(data.velocity_axis_mps[r])),3,top+(rows.length-r-.5)*ph/rows.length);}
    byId('cmIsac410Summary').textContent=data.detected?`🎯 测得 ${fmt(data.range_m)} m · ${fmt(data.velocity_mps)} m/s · 峰值 / 背景 ${fmt(data.peak_background_db)} dB`:'当前观测低于目标检测阈值。';
    byId('cmIsac410Metrics').innerHTML=table(['通信 BER','距离分辨率 / m','速度分辨率 / m/s','数据 OFDM 符号'],[[current.metrics.ber,data.range_resolution_m,data.velocity_resolution_mps,data.data_ofdm_symbols]]);
  }
  function render(){
    const saved=meta().flowSettings||{domain:'symbols',mode:'weighted',select:0,weights:[.5,.5]};{byId('cmMerge410Domain').value=saved.domain;byId('cmMerge410Mode').value=saved.mode;byId('cmMerge410Select').value=String(saved.select);byId('cmMerge410A').value=String(saved.weights[0]);byId('cmMerge410B').value=String(saved.weights[1]);}
    const branches=ctx.meta().branches||[],active=ctx.meta().activeBranch||0,old=String(meta().flowPeer??'');
    byId('cmMerge410Branch').innerHTML=branches.map((b,i)=>i===active?'':`<option value="${i}">${esc(b.name)}</option>`).join('');if([...byId('cmMerge410Branch').options].some(o=>o.value===old))byId('cmMerge410Branch').value=old;
    const peer=branches[Number(byId('cmMerge410Branch').value)];
    byId('cmMerge410Diagram').innerHTML=`<div class="cm-flow-prefix">🌊 同一信源 → 发送处理 → 信道采样 → 🔱 分流</div><div class="cm-flow-branches"><div><strong>当前接收链路</strong><div>接收处理 → ${settings().domain==='llr'?'软解调 LLR':'复符号'}</div></div><div><strong>${esc(peer?.name||'在编程区添加第二条接收分支')}</strong><div>接收处理 → ${settings().domain==='llr'?'软解调 LLR':'复符号'}</div></div></div><div class="cm-flow-prefix">🔗 ${settings().mode==='select'?'选择一路':'加权相加'} → 后续解调 / 译码 → 信宿</div>`;
    const value=meta().flowResult;byId('cmMerge410Results').innerHTML=value?table(['路径','BER','EVM / %'],[...value.branches.map(b=>[b.name,b.result.metrics.ber,b.result.metrics.evm_percent]),['🔗 汇合输出',value.merged_result.metrics.ber,value.merged_result.metrics.evm_percent]]):'';
    drawSense();buttons(get().busy);
  }
  function buttons(busy){host.querySelectorAll('button,input,select').forEach(e=>e.disabled=busy);byId('cmMerge410Run').disabled=busy||!byId('cmMerge410Branch').options.length;byId('cmMerge410Export').disabled=busy||!meta().flowResult;}
  async function action(fn){core.setBusy(true);try{await fn()}catch(e){status(e.message);core.status(e.message,true)}finally{core.setBusy(false);render();}}
  byId('cmMerge410Run').onclick=()=>action(async()=>{ctx.syncBranches();const other=ctx.meta().branches[Number(byId('cmMerge410Branch').value)];if(!other)throw Error('请在编程区新增第二条接收分支。');const p=clone(get().program),built=await core.api('build',{program:p});const value=await ctx.runJob('branch-merge',{programs:[p,clone(other.program)],settings:settings()});meta().flowResult=value;meta().flowSettings=settings();core.restoreResult(built,value.merged_result);ctx.persist();status(`已共享 ${value.shared_prefix.length} 个前置积木，汇合 ${value.merge.count} 个${value.merge.domain==='llr'?' LLR':'复符号'}。`);});
  byId('cmMerge410Export').onclick=()=>core.download('接收汇合实验.json',JSON.stringify(meta().flowResult,null,2),'application/json');
  byId('cmIsac410Demo').onclick=()=>{core.setProgram(get().catalog.presets.ofdm_isac.program,'已载入 OFDM 通感实验，Build / Run 开始测距测速。');};
  host.querySelectorAll('input,select').forEach(e=>e.onchange=()=>{meta().flowSettings=settings();meta().flowPeer=Number(byId('cmMerge410Branch').value);ctx.persist();render();});
  function onResult(result){current=result;drawSense();}
  function invalidate(){current=null;drawSense();}
  function replaceProgram(){invalidate();}
  window.addEventListener('resize',drawSense);
  return {render,buttons,onResult,invalidate,replaceProgram};
};
