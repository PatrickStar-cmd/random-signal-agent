/* Scratch-inspired ordered signal blocks; Build snapshots configuration, Run uses that snapshot. */
(() => {
  'use strict';
  const root=document.querySelector('[data-view="communications"]'), byId=id=>document.getElementById(id), esc=escapeHtml;
  const storageKey='rs_communication_draft_v1', categories={source:'信源',transmit:'发送端',channel:'信道',receive:'接收端'};
  let catalog=null,definitions={},program=null,compiled=null,result=null,category='source',busy=false,revision=0;
  let undo=[],redo=[],drag=null,plot='constellation',snowTimer=0;
  const clone=value=>JSON.parse(JSON.stringify(value));
  const empty=()=>({schema:catalog.schema,...clone(catalog.defaults),blocks:[{id:'sink',kind:'sink',params:{}}]});
  const uid=()=>`comm-${createSessionId()}`;
  function status(message,error=false){byId('cmStatus').textContent=message;byId('cmStatus').classList.toggle('cm-error',error)}
  function buttons(){
    byId('cmFields').disabled=busy||!catalog;
    byId('cmRun').disabled=busy||!compiled;
    byId('cmUndo').disabled=busy||!undo.length;byId('cmRedo').disabled=busy||!redo.length;
    byId('cmDownloadCSV').disabled=busy||!result;byId('cmDownloadResult').disabled=busy||!result;
    byId('cmBuildBadge').classList.toggle('ready',!!compiled);
    byId('cmBuildBadge').textContent=busy?'处理中…':compiled?'Build 已通过':'等待构建';
  }
  function persist(){try{localStorage.setItem(storageKey,JSON.stringify(program))}catch{status('当前浏览器无法保存草稿，可使用“导出工程 JSON”。',true)}}
  function invalidate(message='配置已改变，请重新 Build，再 Run。'){
    revision++;compiled=null;result=null;persist();buttons();showResult();status(message);
  }
  function checkpoint(){undo.push(clone(program));if(undo.length>30)undo.shift();redo=[]}
  function change(fn,message){if(busy||!catalog)return;checkpoint();fn();invalidate(message);renderProgram()}
  function setProgram(next,message){change(()=>{program=clone(next)},message)}
  function history(direction){if(busy)return;const from=direction==='undo'?undo:redo,to=direction==='undo'?redo:undo;if(!from.length)return;to.push(clone(program));program=from.pop();invalidate('已'+(direction==='undo'?'撤销':'重做')+'，重新 Build 后即可运行。');renderProgram()}
  async function api(action,payload){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),60000);
    try{
      const response=await fetch(`/api/communications/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal});
      const data=await response.json();if(!response.ok)throw Error(data.error||'通信实验请求失败。');return data;
    }catch(error){if(error.name==='AbortError')throw Error('请求超时，请重新尝试。');throw error}finally{clearTimeout(timer)}
  }
  function palette(){
    byId('cmCategories').innerHTML=Object.entries(categories).map(([key,label])=>`<button type="button" data-cm-filter="${key}" aria-pressed="${key===category}">${label}</button>`).join('');
    byId('cmPalette').innerHTML=catalog.blocks.filter(b=>b.category===category).map(b=>`<button type="button" class="cm-palette-block" draggable="true" data-cm-kind="${b.kind}" data-cm-category="${b.category}" aria-label="添加 ${esc(b.label)}"><span class="cm-add-symbol" aria-hidden="true">＋</span><strong>${esc(b.label)}</strong><small>${esc(b.description)}</small></button>`).join('');
  }
  function parameterHTML(b){
    return Object.entries(definitions[b.kind].params).map(([key,spec])=>{
      const val=b.params[key],data=`data-block-id="${b.id}" data-param="${key}"`,id=`cm-${b.id}-${key}`,label=esc(spec.label);
      if(spec.type==='boolean')return `<label class="cm-boolean" for="${id}"><input id="${id}" ${data} type="checkbox" ${val?'checked':''}>${label}</label>`;
      if(spec.type==='select')return `<label for="${id}">${label}<select id="${id}" ${data}>${spec.choices.map(v=>`<option value="${v}" ${v===val?'selected':''}>${v}</option>`).join('')}</select></label>`;
      if(spec.type==='text')return `<label class="cm-wide" for="${id}">${label}<textarea id="${id}" ${data} maxlength="${spec.max_length}" required>${esc(val)}</textarea></label>`;
      return `<label for="${id}">${label}<input id="${id}" ${data} type="number" min="${spec.min}" max="${spec.max}" step="${spec.type==='integer'?'1':'any'}" value="${val??''}" required></label>`;
    }).join('');
  }
  function renderProgram(){
    if(!program)return;
    for(const input of root.querySelectorAll('[data-global]'))input.value=program[input.dataset.global]??'';
    byId('cmBlockCount').textContent=`${program.blocks.length} 块积木`;
    byId('cmProgram').innerHTML=(program.blocks.length===1?'<div class="cm-empty"><span aria-hidden="true">🧩</span>信宿已就位。<br>从左侧拖入一个信源，<br>再连接编码、调制和接收端。</div>':'')+program.blocks.map((b,i)=>{
      const def=definitions[b.kind];
      if(b.kind==='sink')return `<article class="cm-block cm-sink" data-cm-category="sink" data-cm-id="${b.id}" data-cm-index="${i}"><div class="cm-block-head"><strong>📺 信宿</strong></div><p class="cm-block-description">译码后的输出 → 右侧观察窗口</p></article>`;
      return `<article class="cm-block" data-cm-category="${def.category}" data-cm-id="${b.id}" data-cm-index="${i}"><div class="cm-block-head"><button type="button" class="cm-handle" draggable="true" data-cm-move="${b.id}" aria-label="拖动 ${esc(def.label)}" title="拖动改变链路顺序">⠿</button><strong>${esc(def.label)}</strong><button type="button" data-cm-up="${b.id}" aria-label="上移 ${esc(def.label)}" ${i===0?'disabled':''}>↑</button><button type="button" data-cm-down="${b.id}" aria-label="下移 ${esc(def.label)}" ${i===program.blocks.length-2?'disabled':''}>↓</button><button type="button" class="cm-remove" data-cm-remove="${b.id}" aria-label="移除 ${esc(def.label)}">×</button></div><p class="cm-block-description">${esc(def.description)}</p>${Object.keys(def.params).length?`<div class="cm-fields">${parameterHTML(b)}</div>`:''}</article>`;
    }).join('');buttons();
  }
  function add(kind,index=program.blocks.length-1){
    if(program.blocks.length>=catalog.limits.max_blocks){status(`最多放置 ${catalog.limits.max_blocks} 个积木，请移除不需要的模块。`,true);return}
    change(()=>{program.blocks.splice(Math.max(0,Math.min(index,program.blocks.length-1)),0,{id:uid(),kind,params:Object.fromEntries(Object.entries(definitions[kind].params).map(([k,v])=>[k,v.default]))})});
  }
  function move(id,index){
    const from=program.blocks.findIndex(b=>b.id===id);if(from<0||program.blocks[from].kind==='sink')return;
    index=Math.max(0,Math.min(index,program.blocks.length-1));if(index===from||index===from+1)return;
    change(()=>{const [b]=program.blocks.splice(from,1);program.blocks.splice(index>from?index-1:index,0,b)})
  }
  root.addEventListener('click',event=>{
    const el=event.target.closest('button');if(!el||busy||!catalog)return;
    if(el.dataset.cmFilter){category=el.dataset.cmFilter;palette();return}
    if(el.dataset.cmKind){add(el.dataset.cmKind);return}
    if(el.dataset.cmRemove){change(()=>{program.blocks=program.blocks.filter(b=>b.id!==el.dataset.cmRemove)});return}
    if(el.dataset.cmUp){const i=program.blocks.findIndex(b=>b.id===el.dataset.cmUp);move(el.dataset.cmUp,i-1);return}
    if(el.dataset.cmDown){const i=program.blocks.findIndex(b=>b.id===el.dataset.cmDown);move(el.dataset.cmDown,i+2);return}
    if(el.dataset.cmPlot){plot=el.dataset.cmPlot;root.querySelectorAll('[data-cm-plot]').forEach(b=>b.setAttribute('aria-pressed',b===el?'true':'false'));drawAnalysis()}
  });
  root.addEventListener('input',event=>{
    const el=event.target;if(busy||!program||(!el.dataset.param&&!el.dataset.global))return;
    checkpoint();
    if(el.dataset.global)program[el.dataset.global]=el.value===''?null:Number(el.value);
    else{
      const b=program.blocks.find(b=>b.id===el.dataset.blockId),spec=definitions[b.kind].params[el.dataset.param];
      b.params[el.dataset.param]=spec.type==='boolean'?el.checked:spec.type==='text'?el.value:el.value===''?null:Number(el.value);
    }
    invalidate();
  });
  root.addEventListener('dragstart',event=>{
    const item=event.target.closest('[data-cm-kind],[data-cm-move]');if(busy||!item){event.preventDefault();return}
    drag=item.dataset.cmKind?{kind:item.dataset.cmKind}:{id:item.dataset.cmMove};
    event.dataTransfer.effectAllowed=drag.id?'move':'copy';event.dataTransfer.setData('application/x-ocean-communication',JSON.stringify(drag));
  });
  const clearDrag=()=>{byId('cmProgram').classList.remove('cm-drag-over');byId('cmProgram').querySelectorAll('.cm-drop-before,.cm-drop-after').forEach(e=>e.classList.remove('cm-drop-before','cm-drop-after'))};
  byId('cmProgram').addEventListener('dragover',event=>{
    if(!drag||busy)return;event.preventDefault();clearDrag();byId('cmProgram').classList.add('cm-drag-over');
    const card=event.target.closest('[data-cm-index]');if(card)card.classList.add(card.classList.contains('cm-sink')||event.clientY<card.getBoundingClientRect().top+card.getBoundingClientRect().height/2?'cm-drop-before':'cm-drop-after');
  });
  byId('cmProgram').addEventListener('drop',event=>{
    if(!drag||busy)return;event.preventDefault();const card=event.target.closest('[data-cm-index]');let index=program.blocks.length-1;
    if(card){index=Number(card.dataset.cmIndex);if(!card.classList.contains('cm-sink')&&event.clientY>=card.getBoundingClientRect().top+card.getBoundingClientRect().height/2)index++}
    const item=drag;drag=null;clearDrag();if(item.kind)add(item.kind,index);else move(item.id,index);
  });
  root.addEventListener('dragend',()=>{drag=null;clearDrag()});
  byId('cmUndo').onclick=()=>history('undo');byId('cmRedo').onclick=()=>history('redo');
  byId('cmPreset').onchange=event=>{
    const preset=catalog.presets[event.target.value];if(!preset)return;
    if(program.blocks.length>1&&!confirm('用示例替换当前链路？可通过“撤销”恢复。')){event.target.value='';return}
    setProgram(preset.program,'示例已载入，点击 Build 构建，再 Run 观察结果。');
  };
  byId('cmReset').onclick=()=>{if(program.blocks.length>1&&!confirm('清空当前链路？信宿将保留，可通过“撤销”恢复。'))return;setProgram(empty(),'信宿已就位，从积木箱添加信源。');byId('cmPreset').value=''};
  byId('cmForm').onsubmit=async event=>{
    event.preventDefault();if(busy||!catalog||!byId('cmForm').reportValidity())return;
    busy=true;compiled=null;result=null;showResult();buttons();status('Build：正在检查信号类型、参数与收发配对…');
    try{compiled=await api('build',{program:clone(program)});program=compiled.program;persist();renderProgram();showTrace();status(`Build 完成：${compiled.summary}。点击 Run 开始传输。`)}
    catch(error){compiled=null;status(error.message,true)}finally{busy=false;buttons()}
  };
  byId('cmRun').onclick=async()=>{
    if(busy||!compiled)return;busy=true;result=null;showResult();buttons();const rev=revision,built=compiled;status('Run：正在生成信源、传输并译码…');
    try{const received=await api('run',{program:built.program,token:built.token});if(rev!==revision)return;result=received;showResult();status(`Run 完成：信宿收到 ${result.sink.count} ${result.sink.kind==='analog'?'个样本':'个比特'}，错误比特 ${result.metrics.bit_errors} / ${result.metrics.bit_count}。`)}
    catch(error){status(error.message,true)}finally{busy=false;buttons()}
  };
  function download(name,content,mime){const url=URL.createObjectURL(new Blob([content],{type:mime})),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000)}
  byId('cmExport').onclick=()=>download('ocean-communication-project.json',JSON.stringify(program,null,2)+'\n','application/json');
  byId('cmImport').onclick=()=>byId('cmFile').click();
  byId('cmFile').onchange=async event=>{
    const file=event.target.files[0];event.target.value='';if(!file||busy)return;
    busy=true;buttons();status('正在读取工程…');
    let imported=null;
    try{
      if(file.size>256*1024)throw Error('工程文件须小于 256 KiB。');
      const checked=await api('validate',{program:JSON.parse(await file.text())});
      const sinks=checked.program.blocks.filter(b=>b.kind==='sink');if(sinks.length!==1||checked.program.blocks.at(-1).kind!=='sink')throw Error('工程须保留一个位于末端的信宿。');
      if(program.blocks.length===1||confirm('用导入的工程替换当前链路？可通过“撤销”恢复。'))imported=checked.program;
      else status('已取消导入。');
    }catch(error){status(error.message,true)}finally{busy=false;buttons()}
    if(imported)setProgram(imported,'工程已导入；点击 Build 校验链路，再 Run。');
  };
  byId('cmDownloadCSV').onclick=()=>{
    if(!result)return;const s=result.sink,analog=s.kind==='analog';
    const lines=[analog?'sample_index,time_s,source,received':'bit_index,source,received,bit_error'];
    for(let i=0;i<s.count;i++)lines.push(analog?`${i},${i/s.sample_rate},${s.reference[i]},${s.values[i]}`:`${i},${s.reference[i]},${s.values[i]},${s.reference[i]!==s.values[i]?1:0}`);
    download('communication-sink.csv',lines.join('\n')+'\n','text/csv');
  };
  byId('cmDownloadResult').onclick=()=>{if(result)download('communication-result.json',JSON.stringify({program:compiled.program,...result},null,2)+'\n','application/json')};
  byId('cmReference').onchange=drawSink;
  byId('cmOffset').oninput=drawSink;
  function showTrace(){
    const data=result||compiled,plan=data?.plan||[];byId('cmModel').textContent=data?.model||'复基带 · 1 样本/符号 · 理想定时 · 硬判决';
    byId('cmTrace').innerHTML=plan.length?`<table><thead><tr><th>积木</th><th>输出类型</th><th>数量</th></tr></thead><tbody>${plan.map(row=>`<tr><td>${esc(row.label)}</td><td>${esc(row.output)}</td><td>${row.count}</td></tr>`).join('')}</tbody></table>`:'Build 后显示逐级信号类型和数据量。';
    if(!result){byId('cmDetails').textContent='';return}
    const m=result.metrics;
    byId('cmDetails').textContent=`解调后 / 译码前 BER：${m.coded_bit_errors} / ${m.coded_bit_count}；符号错误：${m.symbol_errors} / ${m.symbol_count}；判决前 EVM：${m.evm_percent.toPrecision(4)}%。有效码率含填充与终止位。`+(result.sink.kind==='analog'?` PCM 饱和样本：${m.clipped_samples}；译码后 BER 以源 PCM 比特为参考，RMSE 以原始模拟信源为参考。`:'')+(m.hamming_syndromes?` Hamming 非零综合征码字：${m.hamming_syndromes}（多位错误可能误纠正）。`:'');
  }
  function showResult(){
    byId('cmNoSignal').hidden=!!result;byId('cmSignalLed').classList.toggle('on',!!result);byId('cmSignalStatus').textContent=result?'信号已抵达':'无信号';byId('cmLegend').hidden=!result;
    byId('cmTextResult').hidden=!result?.text;byId('cmReceivedText').textContent=result?.text?.received||'';
    const m=result?.metrics,analog=result?.sink.kind==='analog';
    const rows=[['译码后误码率',m?(100*m.ber).toFixed(3)+'%':'—',m?`${m.bit_errors} / ${m.bit_count} bit`:'等待传输'],['传输符号数',m?String(m.symbol_count):'—',m?`${result.constellation.scheme.toUpperCase()} · ${program.symbol_rate} Baud`:'等待传输'],['有效码率',m?m.effective_rate.toFixed(3):'—','源比特 / 编码后比特'],[analog?'信宿 RMSE':'判决前 EVM',m?(analog?m.rmse.toPrecision(4):m.evm_percent.toPrecision(4)+'%'):'—',analog?'相对原始模拟信源':'相对发送符号']];
    byId('cmMetrics').innerHTML=rows.map(([label,value,note])=>`<div class="cm-metric"><span>${label}</span><strong>${value}</strong><small>${esc(note)}</small></div>`).join('');
    byId('cmSinkCaption').textContent=result?`${analog?'接收模拟波形':'接收比特序列'} · 显示前 ${result.sink.plot_count} / ${result.sink.count} ${analog?'点':'位'}`:'信宿等待接收';
    byId('cmWindow').hidden=!result||result.sink.count<=result.sink.plot_count;byId('cmOffset').max=result?Math.max(0,result.sink.count-result.sink.plot_count):0;byId('cmOffset').value=0;
    byId('cmLegend').querySelector('span:last-child').hidden=!!analog;
    showTrace();drawSink();drawAnalysis();buttons();
  }
  function surface(id,dark=false){
    const canvas=byId(id),rect=canvas.getBoundingClientRect(),width=Math.max(240,Math.round(rect.width)),height=Math.round(rect.height)||260,dpr=Math.min(2,devicePixelRatio||1);
    canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);const x=canvas.getContext('2d');x.setTransform(dpr,0,0,dpr,0,0);x.fillStyle=dark?'#102237':'#f1f7ff';x.fillRect(0,0,width,height);x.font=chartFont(12);return {canvas,x,width,height};
  }
  const noiseCanvas=document.createElement('canvas');noiseCanvas.width=160;noiseCanvas.height=96;
  function stopSnow(){if(snowTimer)clearTimeout(snowTimer);snowTimer=0}
  function snow(){
    stopSnow();if(result||root.hidden||document.hidden)return;
    const {x,width,height}=surface('cmSinkCanvas',true),nx=noiseCanvas.getContext('2d'),image=nx.createImageData(160,96);
    for(let i=0;i<image.data.length;i+=4){const v=45+Math.floor(Math.random()*150);image.data[i]=v;image.data[i+1]=v+5;image.data[i+2]=Math.min(255,v+12);image.data[i+3]=255}
    nx.putImageData(image,0,0);x.imageSmoothingEnabled=false;x.drawImage(noiseCanvas,0,0,width,height);
    if(!matchMedia('(prefers-reduced-motion: reduce)').matches)snowTimer=setTimeout(snow,160);
  }
  function axes(view,min,max,xEnd,xUnit,dark=false,xStart=0){
    const {x,width,height}=view,p={left:43,right:15,top:24,bottom:32};p.w=width-p.left-p.right;p.h=height-p.top-p.bottom;
    const px=v=>p.left+v/Math.max(xEnd,1e-12)*p.w,py=v=>p.top+p.h-(v-min)/Math.max(max-min,1e-12)*p.h;
    x.lineWidth=1;x.strokeStyle=dark?'#6a91b42e':'#bfd0e45c';x.fillStyle=dark?'#c0d5e8':'#526b8e';
    for(let i=0;i<=4;i++){const y=p.top+i*p.h/4;x.beginPath();x.moveTo(p.left,y);x.lineTo(width-p.right,y);x.stroke();x.textAlign='right';x.fillText((max-(max-min)*i/4).toPrecision(2),p.left-7,y+4)}
    for(let i=0;i<=4;i++){const xx=p.left+i*p.w/4;x.beginPath();x.moveTo(xx,p.top);x.lineTo(xx,p.top+p.h);x.stroke();x.textAlign='center';x.fillText(Number((xStart+xEnd*i/4).toPrecision(4)).toString(),xx,height-14)}
    x.textAlign='right';x.fillText(xUnit,width-p.right,14);return {px,py,p};
  }
  function line(view,values,axis,color,step=false,lineWidth=1.5){
    const {x}=view;x.save();x.beginPath();x.rect(axis.p.left,axis.p.top,axis.p.w,axis.p.h);x.clip();x.strokeStyle=color;x.lineWidth=lineWidth;x.beginPath();
    if(values.length===1){x.fillStyle=color;x.arc(axis.px(0),axis.py(values[0]),3,0,2*Math.PI);x.fill();x.restore();return}
    values.forEach((v,i)=>{const xx=axis.px(i/(values.length-1)*axis.xEnd),yy=axis.py(v);if(!i)x.moveTo(xx,yy);else{if(step)x.lineTo(xx,axis.py(values[i-1]));x.lineTo(xx,yy)}});x.stroke();x.restore();
  }
  function drawSink(){
    stopSnow();if(root.hidden)return;if(!result){snow();return}
    const s=result.sink,n=s.plot_count,start=Number(byId('cmOffset').value),values=s.values.slice(start,start+n),reference=s.reference.slice(start,start+n),analog=s.kind==='analog';
    const all=byId('cmReference').checked?[...values,...reference]:values,min=analog?Math.min(...all):-.15,max=analog?Math.max(...all):1.15;
    const margin=analog?Math.max(.08,(max-min)*.12):0,view=surface('cmSinkCanvas',true),end=analog?(n-1)/s.sample_rate:n-1;
    const axis=axes(view,min-margin,max+margin,end,analog?'时间 / s':'比特序号',true,analog?start/s.sample_rate:start);axis.xEnd=end;
    byId('cmSinkCaption').textContent=`${analog?'接收模拟波形':'接收比特序列'} · 第 ${start+1}–${start+n} / ${s.count} ${analog?'点':'位'}`;
    if(byId('cmReference').checked)line(view,reference,axis,'#c8adfa',!analog,1.3);
    line(view,values,axis,'#70ead0',!analog,1.8);
    if(!analog){view.x.fillStyle='#ff9cae';values.forEach((v,i)=>{if(v!==reference[i]){view.x.beginPath();view.x.arc(axis.px(i),axis.py(v),3,0,2*Math.PI);view.x.fill()}})}
  }
  function drawAnalysis(){
    if(root.hidden)return;const view=surface('cmAnalysisCanvas'),{x,width,height}=view;
    if(!result){byId('cmAnalysisCaption').textContent='Run 后显示接收星座与信道 I / Q。';x.fillStyle='#6b80a0';x.textAlign='center';x.fillText('Run 后，观察信号在信道中的变化。',width/2,height/2);return}
    if(plot==='channel'){
      const c=result.channel,all=[...c.i,...c.q],min=Math.min(...all),max=Math.max(...all),margin=Math.max(.1,(max-min)*.1),end=(c.plot_count-1)/c.symbol_rate;
      const axis=axes(view,min-margin,max+margin,end,'时间 / s');axis.xEnd=end;
      line(view,c.i,axis,'#5264c4');line(view,c.q,axis,'#219782');
      byId('cmAnalysisCaption').textContent=`信道输出（解调前）· 蓝色 I / 绿色 Q · 前 ${c.plot_count} / ${c.count} 个符号。`;return;
    }
    const c=result.constellation,bound=Math.max(1.3,...c.i.map(Math.abs),...c.q.map(Math.abs))*1.15;
    const area=Math.min(width-80,height-55),left=(width-area)/2,top=18,px=v=>left+(v/bound+1)*area/2,py=v=>top+(1-v/bound)*area/2;
    x.strokeStyle='#c7d5e8';x.lineWidth=1;x.fillStyle='#59708e';
    for(let tick=-1;tick<=1;tick+=.5){const v=bound*tick;x.beginPath();x.moveTo(px(v),top);x.lineTo(px(v),top+area);x.stroke();x.beginPath();x.moveTo(left,py(v));x.lineTo(left+area,py(v));x.stroke();x.textAlign='center';x.fillText(v.toPrecision(2),px(v),top+area+16);x.textAlign='right';x.fillText(v.toPrecision(2),left-7,py(v)+4)}
    x.fillStyle='#248b8050';for(let i=0;i<c.i.length;i++){x.beginPath();x.arc(px(c.i[i]),py(c.q[i]),2,0,2*Math.PI);x.fill()}
    x.strokeStyle='#7658bd';x.lineWidth=2;c.ideal_i.forEach((v,i)=>{const a=px(v),b=py(c.ideal_q[i]);x.beginPath();x.moveTo(a-5,b);x.lineTo(a+5,b);x.moveTo(a,b-5);x.lineTo(a,b+5);x.stroke()});
    x.fillStyle='#536b8e';x.textAlign='left';x.fillText('Q',left-9,12);x.fillText('I',left+area+9,top+area/2);
    byId('cmAnalysisCaption').textContent=`${c.scheme.toUpperCase()} 判决前星座 · 绿色接收点（前 ${c.count} 个）/ 紫色理想点；按解调器设置进行已知增益与相位补偿。`;
  }
  window.addEventListener('resize',()=>{drawSink();drawAnalysis()});document.addEventListener('visibilitychange',()=>{if(document.hidden)stopSnow();else drawSink()});
  async function init(){
    buttons();
    try{
      const response=await fetch('/api/communications/catalog');if(!response.ok)throw Error('积木箱加载失败，请刷新重试。');catalog=await response.json();definitions=Object.fromEntries(catalog.blocks.map(b=>[b.kind,b]));program=empty();
      root.querySelector('[data-global="sample_count"]').max=catalog.limits.max_samples;
      let saved=null;try{saved=localStorage.getItem(storageKey)}catch{status('浏览器草稿存储不可用，仍可搭建链路并导出工程。')}
      if(saved){
        try{
          const data=await api('validate',{program:JSON.parse(saved)});
          if(data.program.blocks.filter(b=>b.kind==='sink').length!==1||data.program.blocks.at(-1).kind!=='sink')throw Error('信宿不在末端');
          program=data.program;status('已恢复浏览器草稿。点击 Build，再 Run。');
        }catch{status('原草稿无法读取，已打开空白链路。可导入工程 JSON 继续。',true)}
      }
      byId('cmPreset').innerHTML='<option value="">选择一个实验示例…</option>'+Object.entries(catalog.presets).map(([key,v])=>`<option value="${key}">${esc(v.label)}</option>`).join('');palette();renderProgram();showResult();
    }catch(error){status(error.message,true);buttons()}
  }
  showResult();init();
})();
