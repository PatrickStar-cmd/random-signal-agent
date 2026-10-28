/* Real MLSE state paths, MUSIC angular spectra and standard TDL observations. */
window.createCommunicationReceiverV0410=function(core,ctx){
  'use strict';
  const {byId,esc,get}=core;
  const panel=document.createElement('section');panel.id='cmReceiver410Panel';panel.className='cm-learning cm-spatial';
  panel.innerHTML=`<header><div><h3>🐬 序列检测、自动测向与标准信道</h3><span class="cm-learn-hint">跟随实际路径判决、角谱峰与衰落轨迹观察接收过程</span></div></header>
    <div class="cm-learning-grid"><label>处理积木<select id="cmReceiver410Stage"></select></label><label>观察视图<select id="cmReceiver410View"></select></label><label id="cmReceiver410PathLabel">衰落路径<select id="cmReceiver410Path"></select></label></div>
    <div class="cm-learn-actions"><button id="cmReceiver410Export" type="button">📥 导出算法观测</button></div>
    <label id="cmReceiver410StepLabel">Viterbi 检测步骤<input id="cmReceiver410Step" type="range" min="0" max="0" value="0"></label>
    <canvas id="cmReceiver410Canvas" style="width:100%;height:300px;display:block" height="300" aria-label="序列检测、测向和信道观测"></canvas>
    <p id="cmReceiver410Caption" role="status"></p><div id="cmReceiver410Table" class="cm-learn-scroll"></div>`;
  byId('cmPane-spatial').append(panel);
  let entries=[],current=null;
  const format=v=>typeof v==='number'?(Number.isInteger(v)?String(v):v.toPrecision(5)):v==null?'—':String(v);
  const table=(headers,rows)=>`<table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${esc(format(v))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  const caption=value=>byId('cmReceiver410Caption').textContent=value;
  const options=(id,values)=>{byId(id).innerHTML=values.map(([key,label])=>`<option value="${esc(key)}">${esc(label)}</option>`).join('');};
  const selected=()=>entries.find(v=>v.kind===byId('cmReceiver410Stage').value);
  function canvas(){
    const c=byId('cmReceiver410Canvas'),w=Math.max(280,c.clientWidth||800),h=300,dpr=Math.min(2,window.devicePixelRatio||1);
    c.width=w*dpr;c.height=h*dpr;const g=c.getContext('2d');g.scale(dpr,dpr);g.clearRect(0,0,w,h);g.font='12px sans-serif';g.fillStyle='#395675';
    return {g,w,h};
  }
  function plot(series,xLabel,yLabel,markers=[]){
    const {g,w,h}=canvas(),valid=series.filter(s=>s.x.length&&s.y.length);
    if(!valid.length)return;
    const xs=valid.flatMap(s=>s.x),ys=valid.flatMap(s=>s.y).filter(v=>typeof v==='number'&&Number.isFinite(v));
    if(!ys.length)return;
    let xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(0,...ys),ymax=Math.max(...ys);
    if(xmin===xmax){xmin-=.5;xmax+=.5;}if(ymin===ymax){ymin-=.5;ymax+=.5;}
    const x=v=>52+(v-xmin)/(xmax-xmin)*(w-78),y=v=>h-42-(v-ymin)/(ymax-ymin)*(h-87);
    g.strokeStyle='#bed2e7';g.strokeRect(52,45,w-78,h-87);g.fillText(yLabel,4,16);g.fillText(xLabel,w/2,h-5);
    g.fillText(format(ymax),2,48);g.fillText(format(ymin),2,h-42);g.fillText(format(xmin),52,h-23);g.fillText(format(xmax),w-70,h-23);
    valid.forEach((s,index)=>{
      g.fillStyle=g.strokeStyle=['#477ac7','#9673c8','#339a94','#c58e43'][index%4];g.fillText(s.name,57+index*160,34);g.beginPath();let started=false;
      s.y.forEach((value,i)=>{if(value==null||!Number.isFinite(value)){started=false;return;}
        if(s.stems){g.moveTo(x(s.x[i]),y(0));g.lineTo(x(s.x[i]),y(value));}
        else if(started)g.lineTo(x(s.x[i]),y(value));else g.moveTo(x(s.x[i]),y(value));started=true;});g.stroke();
    });
    markers.forEach(marker=>{g.strokeStyle=g.fillStyle=marker.color||'#c58e43';g.beginPath();g.moveTo(x(marker.x),45);g.lineTo(x(marker.x),h-42);g.stroke();g.fillText(marker.label,x(marker.x)+4,60);});
  }
  function setup(){
    const v=selected()?.value,views=[];
    if(v?.mlse)views.push(['metrics','Viterbi 状态路径度量'],['path','最终幸存路径'],['taps','公开训练信道估计']);
    if(v?.music)views.push(['music','MUSIC 角谱与目标'],['eigenvalues','协方差特征值']);
    if(v?.beam_pattern)views.push(['beam','自动 MVDR 波束方向图']);
    if(v?.profile)views.push(['pdp','标准功率时延谱'],['fading','逐路径 Jakes 衰落']);
    options('cmReceiver410View',views);options('cmReceiver410Path',(v?.delays_ns||[]).map((_,i)=>[String(i),'路径 '+(i+1)]));
    byId('cmReceiver410Step').max=Math.max(0,(v?.mlse?.trace_steps||1)-1);byId('cmReceiver410Step').value=0;draw();
  }
  function draw(){
    canvas();byId('cmReceiver410Table').innerHTML='';const item=selected(),v=item?.value,mode=byId('cmReceiver410View').value;
    byId('cmReceiver410StepLabel').hidden=mode!=='metrics';byId('cmReceiver410PathLabel').hidden=mode!=='fading';
    if(!v){caption('运行 MLSE、MUSIC 或 TDL 预设后，在这里查看实际算法观测。');return;}
    if(mode==='metrics'){
      const step=Number(byId('cmReceiver410Step').value),m=v.mlse,row=m.metric_history[step],state=m.survivor_states[step];
      plot([{name:'归一化路径度量',x:row.map((_,i)=>i),y:row,stems:true}],'状态编号','累计距离（减最小值）',[{x:state,label:'最终路径状态'}]);
      byId('cmReceiver410Table').innerHTML=table(['状态','前驱','度量','最终路径'],row.map((value,i)=>[i,m.predecessors[step][i],value,i===state?'●':'']));
      caption(`步骤 ${step+1} / ${m.steps} · ${m.state_count} 状态 · 每步 ${m.branch_count} 分支 · ${m.metric_evaluations} 次距离计算 · 展示前 ${m.trace_steps} 步。`);
    }else if(mode==='path'){
      const m=v.mlse;plot([{name:'幸存状态',x:m.survivor_states.map((_,i)=>i+1),y:m.survivor_states}],'检测步骤','状态编号');
      byId('cmReceiver410Table').innerHTML=table(['步骤','幸存状态','输入符号索引'],m.survivor_states.map((state,i)=>[i+1,state,m.input_indices[i]]));
      caption(`初始状态 ${m.initial_state} · 完整序列距离 ${format(m.sequence_metric)} · 公开终止符号约束最终回溯。`);
    }else if(mode==='taps'){
      const h=v.channel_estimate,x=h.i.map((_,i)=>i);plot([{name:'实部',x,y:h.i},{name:'虚部',x,y:h.q}],'FIR 抽头延迟 / 符号','估计系数');
      caption(`${v.training_symbols} 个公开训练符号 · 训练残差噪声方差 ${format(v.estimated_noise_variance)} · 输出为最大似然判决符号。`);
    }else if(mode==='music'){
      const m=v.music;plot([{name:'MUSIC 角谱',x:m.angles,y:m.spectrum_db}],'到达角 / °','归一化角谱 / dB',[{x:m.target_angle,label:'导频目标'}]);
      byId('cmReceiver410Table').innerHTML=table(['估计峰 / °','公开导频增益实部','虚部','目标'],m.estimated_angles.map((angle,i)=>[angle,m.pilot_coefficients.i[i],m.pilot_coefficients.q[i],i===m.target_index?'●':'']));
      caption(`${m.snapshots} 个接收快照 · 子阵长度 ${m.subarray_length} · 目标角 ${format(m.target_angle)}° · 导频相关增益选择目标峰。`);
    }else if(mode==='eigenvalues'){
      const m=v.music;plot([{name:'接收协方差特征值',x:m.eigenvalues.map((_,i)=>i+1),y:m.eigenvalues,stems:true}],'升序特征值编号','特征值');
      caption(`信号子空间 ${m.source_count} 维 · 噪声子空间 ${m.subarray_length-m.source_count} 维。`);
    }else if(mode==='beam'){
      plot(v.beam_pattern.db.map((row,i)=>({name:'MVDR '+(i+1),x:v.beam_pattern.angles,y:row})),'到达角 / °','方向图 / dB',[{x:v.music.target_angle,label:'估计目标'}]);
      caption(`自动观察角 ${format(v.music.target_angle)}° · 训练残差干扰噪声抑制 ${format(v.rejection_db)} dB。`);
    }else if(mode==='pdp'){
      plot([{name:v.profile,x:v.delays_ns,y:v.powers_db,stems:true}],'路径延迟 / ns','标准相对功率 / dB');
      byId('cmReceiver410Table').innerHTML=table(['路径','延迟 / ns','延迟 / 采样点','标准功率 / dB','归一化功率','本帧平均增益功率'],v.delays_ns.map((delay,i)=>[i+1,delay,v.delays_samples[i],v.powers_db[i],v.powers[i],v.measured_path_power[i]]));
      caption(`${v.profile} · RMS 时延扩展 ${format(v.rms_delay_ns)} ns · 最大多普勒 ${format(v.doppler_hz)} Hz · ${v.interpolation} · 公共滤波延迟 ${v.filter_delay_samples} 点 · 帧末保护 ${v.guard_samples} 点。`);
    }else if(mode==='fading'){
      const path=Number(byId('cmReceiver410Path').value);plot([{name:'路径增益实部',x:v.sample_indices,y:v.path_gains.i.map(row=>row[path])},{name:'路径增益虚部',x:v.sample_indices,y:v.path_gains.q.map(row=>row[path])}],'连续采样编号','复增益');
      caption(`路径 ${path+1} · 延迟 ${format(v.delays_ns[path])} ns · 截至本帧已处理 ${v.processed_samples} 点 · 相位与滤波历史跨帧延续。`);
    }
  }
  function onResult(result){current=result||null;const data=result?.advanced?.wireless||{};entries=Object.entries(data).filter(([,v])=>v.mlse||v.music||v.profile?.startsWith('TDL-')).map(([kind,value])=>({kind,value}));options('cmReceiver410Stage',entries.map(v=>[v.kind,get().definitions?.[v.kind]?.label||v.kind]));setup();buttons(get().busy);}
  function render(){const result=get().result||ctx.meta().result||null;if(current!==result)onResult(result);}
  function buttons(busy){panel.querySelectorAll('button,input,select').forEach(e=>e.disabled=busy);byId('cmReceiver410Export').disabled=busy||!entries.length;}
  function invalidate(){onResult(null);}
  byId('cmReceiver410Stage').onchange=setup;byId('cmReceiver410View').onchange=draw;byId('cmReceiver410Step').oninput=draw;byId('cmReceiver410Path').onchange=draw;
  byId('cmReceiver410Export').onclick=()=>{const item=selected();if(item)core.download('receiver-observation.json',JSON.stringify(item,null,2),'application/json');};
  window.addEventListener('resize',()=>{if(!byId('cmPane-spatial').hidden)draw();});
  setup();buttons(get().busy);return {render,onResult,buttons,invalidate,replaceProgram:invalidate};
};
