/* Scratch-inspired ordered signal blocks; Build snapshots configuration, Run uses that snapshot. */
(() => {
  'use strict';
  const root=document.querySelector('[data-view="communications"]'), byId=id=>document.getElementById(id), esc=escapeHtml;
  const storageKey='rs_communication_draft_v1', categories={source:'信源',tx_converter:'发转换器',modulator:'调制器',channel:'信道',demodulator:'解调器',rx_converter:'收转换器'};
  const categoryEmoji={source:'🎲',tx_converter:'🔀',modulator:'📡',channel:'🌊',demodulator:'🎛️',rx_converter:'🔄',sink:'📺'};
  let catalog=null,definitions={},program=null,compiled=null,result=null,category='source',busy=false,revision=0;
  let undo=[],redo=[],drag=null,plot='constellation',snowTimer=0,selectedId=null;
  let sweeps=[];
  let studio=null;
  const inspectorState=new Map();
  const clone=value=>JSON.parse(JSON.stringify(value));
  const empty=()=>({schema:catalog.schema,...clone(catalog.defaults),blocks:[{id:'sink',kind:'sink',params:{}}]});
  const uid=()=>`comm-${createSessionId()}`;
  function status(message,error=false){byId('cmStatus').textContent=message;byId('cmStatus').classList.toggle('cm-error',error)}
  function buttons(){
    byId('cmFields').disabled=busy||!catalog;
    byId('cmRun').disabled=busy||!compiled;
    byId('cmSweepRun').disabled=busy||!compiled||!byId('cmSweepNoise').value;
    byId('cmSweepExport').disabled=busy||!sweeps.length;byId('cmSweepCSV').disabled=busy||!sweeps.length;
    byId('cmUndo').disabled=busy||!undo.length;byId('cmRedo').disabled=busy||!redo.length;
    byId('cmDownloadCSV').disabled=busy||!result;byId('cmDownloadResult').disabled=busy||!result;
    byId('cmBuildBadge').classList.toggle('ready',!!compiled);
    byId('cmBuildBadge').textContent=busy?'处理中…':compiled?'Build 已通过':'等待构建';
    studio?.buttons(busy);
  }
  function persist(){try{localStorage.setItem(storageKey,JSON.stringify(program))}catch{status('当前浏览器无法保存草稿，可使用“导出工程 JSON”。',true)}studio?.persist()}
  function invalidate(message='配置已改变，请重新 Build，再 Run。'){
    revision++;compiled=null;result=null;studio?.invalidate();persist();buttons();showResult();status(message);
  }
  function checkpoint(){undo.push({program:clone(program),experience:studio?.editSnapshot()});if(undo.length>30)undo.shift();redo=[]}
  function confirmReplace(message){
    const dialog=byId('cmReplaceDialog');dialog.returnValue='cancel';byId('cmReplaceMessage').textContent=message;
    return new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue==='replace'),{once:true});dialog.showModal()});
  }
  function change(fn,message){if(busy||!catalog)return;checkpoint();fn();invalidate(message);renderProgram()}
  function setProgram(next,message){change(()=>{studio?.replaceProgram();program=clone(next);selectedId=program.blocks[0]?.id},message)}
  function history(direction){if(busy)return;const from=direction==='undo'?undo:redo,to=direction==='undo'?redo:undo;if(!from.length)return;to.push({program:clone(program),experience:studio?.editSnapshot()});const item=from.pop();program=item.program||item;if(item.experience)studio?.restoreEdit(item.experience);invalidate('已'+(direction==='undo'?'撤销':'重做')+'，重新 Build 后即可运行。');renderProgram()}
  async function api(action,payload){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),60000);
    try{
      const response=await fetch(`/api/communications/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal});
      const data=await response.json();if(!response.ok)throw Error(data.error||'通信实验请求失败。');return data;
    }catch(error){if(error.name==='AbortError')throw Error('请求超时，请重新尝试。');throw error}finally{clearTimeout(timer)}
  }
  function palette(){
    const available=catalog.blocks.filter(b=>b.kind!=='sink'&&(studio?studio.matches(b,category):b.category===category));
    byId('cmCategories').innerHTML=Object.entries(categories).map(([key,label])=>`<button type="button" data-cm-filter="${key}" data-cm-category="${key}" aria-pressed="${key===category}"><span aria-hidden="true">${categoryEmoji[key]}</span>${label}</button>`).join('');
    byId('cmCategoryName').textContent=`${categoryEmoji[category]} ${categories[category]}`;
    byId('cmCategoryCount').textContent=`${available.length} 个模块`;
    byId('cmPalette').innerHTML=available.map(b=>`<button type="button" class="cm-palette-block" draggable="true" data-cm-kind="${b.kind}" data-cm-category="${b.category}" aria-label="添加 ${esc(b.label)}"><span class="cm-add-symbol" aria-hidden="true">＋</span><strong>${esc(b.label)}</strong><small>${esc(b.description)}</small></button>`).join('');studio?.decoratePalette();
  }
  function parameterHTML(b,entries=Object.entries(definitions[b.kind].params)){
    return entries.map(([key,spec])=>{
      const val=Object.hasOwn(b.params,key)?b.params[key]:spec.default,data=`data-block-id="${esc(b.id)}" data-param="${key}"`,id=esc(`cm-${b.id}-${key}`),label=esc(spec.label);
      if(spec.type==='boolean')return `<label class="cm-boolean" for="${id}"><input id="${id}" ${data} type="checkbox" ${val?'checked':''}>${label}</label>`;
      if(spec.type==='select')return `<label for="${id}">${label}<select id="${id}" ${data}>${spec.choices.map(v=>`<option value="${v}" ${v===val?'selected':''}>${esc(String(spec.choice_labels?.[v]??v))}</option>`).join('')}</select></label>`;
      if(spec.type==='text')return `<label class="cm-wide" for="${id}">${label}<textarea id="${id}" ${data} maxlength="${spec.max_length}" required>${esc(val)}</textarea></label>`;
      return `<label for="${id}">${label}<input id="${id}" ${data} type="number" min="${spec.min}" max="${spec.max}" step="${spec.type==='integer'?'1':'any'}" value="${val??''}" required></label>`;
    }).join('');
  }
  function summaryHTML(b){
    const def=definitions[b.kind],preferred=b.kind.startsWith('demod_')&&Object.hasOwn(def.params,'equalizer')?['equalizer','adaptive_algorithm']:b.kind==='mod_baseband'?['pulse','sps']:b.kind==='mod_pam'?['order','pulse']:Object.keys(def.params).slice(0,2);
    return preferred.map(key=>{const spec=def.params[key],value=Object.hasOwn(b.params,key)?b.params[key]:spec.default;
      const label=spec.type==='boolean'?(value?'开启':'关闭'):spec.type==='select'?(spec.choice_labels?.[value]??value):value;
      const text=label===null||label===''?'待填写':String(label);
      return `<span class="cm-slot" title="${esc(spec.label+': '+text)}">${esc(text.length>22?text.slice(0,22)+'…':text)}</span>`;
    }).join('');
  }
  function renderInspector(){
    const pane=byId('cmInspector');
    if(pane.dataset.blockId)inspectorState.set(pane.dataset.blockId,[...pane.querySelectorAll('details[open]')].map(d=>d.dataset.group));
    const b=program.blocks.find(item=>item.id===selectedId),def=definitions[b.kind],entries=Object.entries(def.params);
    pane.dataset.blockId=b.id;
    const sections=b.kind.startsWith('demod_')&&Object.hasOwn(def.params,'equalizer')?[
      ['基础参数',entries.filter(([k])=>['compensate','filter','cutoff_hz','sample_offset'].includes(k))],
      ['🕒 符号同步',entries.filter(([k])=>['timing_mode','loop_bandwidth','gate_spacing'].includes(k))],
      ['🎛️ 均衡设置',entries.filter(([k])=>['equalizer','adaptive_algorithm','step_size'].includes(k))],
      ['高级参数',entries.filter(([k])=>!['compensate','filter','cutoff_hz','sample_offset','timing_mode','loop_bandwidth','gate_spacing','equalizer','adaptive_algorithm','step_size'].includes(k))]
    ]:[['基础参数',entries.slice(0,4)],['高级参数',entries.slice(4)]];
    const opened=inspectorState.get(b.id);
    pane.innerHTML=`<div class="cm-selected-block" data-cm-category="${def.category}"><strong>${categoryEmoji[def.category]} ${esc(def.label)}</strong><small>${categories[def.category]||'输出观察'}</small></div><p class="cm-inspector-description">${esc(def.description)}</p>`+sections.filter(([,items])=>items.length).map(([name,items],i)=>i?`<details data-group="${name}" ${opened?opened.includes(name)?'open':'':(name==='🎛️ 均衡设置'&&b.params.equalizer||name==='🕒 符号同步'&&b.params.timing_mode)?'open':''}><summary>${name}</summary><div class="cm-fields">${parameterHTML(b,items)}</div></details>`:`<div class="cm-fields">${parameterHTML(b,items)}</div>`).join('');
  }
  function selectBlock(id){
    if(!program.blocks.some(b=>b.id===id))return;selectedId=id;
    byId('cmProgram').querySelectorAll('[data-cm-select]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.cmSelect===id)));
    byId('cmProgram').querySelectorAll('[data-cm-id]').forEach(card=>card.classList.toggle('cm-selected',card.dataset.cmId===id));renderInspector();studio?.selection();
  }
  function validateFields(){
    const global=root.querySelector('[data-global]:invalid');
    if(global){global.closest('details').open=true;global.reportValidity();return false}
    for(const b of program.blocks){
      const fields=document.createElement('div');fields.innerHTML=parameterHTML(b);const invalid=fields.querySelector(':invalid');
      if(invalid){selectBlock(b.id);const input=byId(invalid.id);input.closest('details')?.setAttribute('open','');status(`${definitions[b.kind].label}：请检查${definitions[b.kind].params[invalid.dataset.param].label}。`,true);input.reportValidity();return false}
    }
    return true;
  }
  function renderProgram(){
    if(!program)return;
    const oldNoise=byId('cmSweepNoise').value;
    byId('cmSweepNoise').innerHTML=program.blocks.filter(b=>['awgn','complex_awgn','sample_awgn','bandlimited_awgn'].includes(b.kind)).map(b=>`<option value="${esc(b.id)}">${esc(definitions[b.kind].label)} · ${program.blocks.indexOf(b)+1}</option>`).join('');
    if([...byId('cmSweepNoise').options].some(o=>o.value===oldNoise))byId('cmSweepNoise').value=oldNoise;
    for(const input of root.querySelectorAll('[data-global]'))input.value=program[input.dataset.global]??'';
    byId('cmBlockCount').textContent=`${program.blocks.length} 块积木`;
    if(!program.blocks.some(b=>b.id===selectedId))selectedId=program.blocks[0].id;
    const preset=Object.values(catalog.presets).find(p=>JSON.stringify(p.program)===JSON.stringify(program));
    byId('cmProjectName').textContent=preset?.label||'我的通信工程';
    byId('cmClockSummary').textContent=`Rs = ${program.symbol_rate} Baud · 种子 ${program.seed}`;
    byId('cmProgram').innerHTML=(program.blocks.length===1?'<div class="cm-empty"><span aria-hidden="true">🧩</span>从积木工坊添加信源，<br>开始搭建通信链路。</div>':'<div class="cm-start">🚩 当实验开始</div>')+program.blocks.map((b,i)=>{
      const def=definitions[b.kind];
      const id=esc(b.id),select=`<button type="button" class="cm-block-select" data-cm-select="${id}" aria-pressed="${b.id===selectedId}" aria-label="编辑 ${esc(def.label)} 参数"><strong>${b.kind==='sink'?'📺 ':''}${esc(def.label)}</strong><span class="cm-slots">${summaryHTML(b)}</span></button>`;
      if(b.kind==='sink')return `<article class="cm-block cm-sink ${b.id===selectedId?'cm-selected':''}" data-cm-category="sink" data-cm-id="${id}" data-cm-index="${i}">${select}</article>`;
      return `<article class="cm-block ${b.id===selectedId?'cm-selected':''}" data-cm-category="${def.category}" data-cm-id="${id}" data-cm-index="${i}"><div class="cm-block-head"><button type="button" class="cm-handle" draggable="true" data-cm-move="${id}" aria-label="拖动 ${esc(def.label)}" title="拖动改变链路顺序">⠿</button>${select}<span class="cm-block-controls"><button type="button" data-cm-up="${id}" aria-label="上移 ${esc(def.label)}" ${i===0?'disabled':''}>↑</button><button type="button" data-cm-down="${id}" aria-label="下移 ${esc(def.label)}" ${i===program.blocks.length-2?'disabled':''}>↓</button><button type="button" class="cm-remove" data-cm-remove="${id}" aria-label="移除 ${esc(def.label)}">×</button></span></div></article>`;
    }).join('');renderInspector();studio?.render();buttons();
  }
  function add(kind,index=program.blocks.length-1){
    if(arguments.length<2&&studio)index=studio.insertionIndex(index);
    if(program.blocks.length>=catalog.limits.max_blocks){status(`最多放置 ${catalog.limits.max_blocks} 个积木，请移除不需要的模块。`,true);return}
    change(()=>{selectedId=uid();program.blocks.splice(Math.max(0,Math.min(index,program.blocks.length-1)),0,{id:selectedId,kind,params:Object.fromEntries(Object.entries(definitions[kind].params).map(([k,v])=>[k,v.default]))});studio?.used(kind)});
  }
  function move(id,index){
    const from=program.blocks.findIndex(b=>b.id===id);if(from<0||program.blocks[from].kind==='sink')return;
    index=Math.max(0,Math.min(index,program.blocks.length-1));if(index===from||index===from+1)return;
    change(()=>{const [b]=program.blocks.splice(from,1);program.blocks.splice(index>from?index-1:index,0,b)})
  }
  root.addEventListener('click',event=>{
    const el=event.target.closest('button');if(!el||busy||!catalog)return;
    if(el.dataset.cmFilter){category=el.dataset.cmFilter;palette();return}
    if(el.dataset.cmSelect){selectBlock(el.dataset.cmSelect);return}
    if(el.dataset.cmKind){add(el.dataset.cmKind);return}
    if(el.dataset.cmRemove){change(()=>{program.blocks=program.blocks.filter(b=>b.id!==el.dataset.cmRemove)});return}
    if(el.dataset.cmUp){const i=program.blocks.findIndex(b=>b.id===el.dataset.cmUp);move(el.dataset.cmUp,i-1);return}
    if(el.dataset.cmDown){const i=program.blocks.findIndex(b=>b.id===el.dataset.cmDown);move(el.dataset.cmDown,i+2);return}
    if(el.dataset.cmPlot){plot=el.dataset.cmPlot;byId('cmStage').value='';root.querySelectorAll('[data-cm-plot]').forEach(b=>b.setAttribute('aria-pressed',b===el?'true':'false'));drawAnalysis()}
  });
  root.addEventListener('input',event=>{
    const el=event.target;if(busy||!program||(!el.dataset.param&&!el.dataset.global))return;
    checkpoint();
    if(el.dataset.global)program[el.dataset.global]=el.value===''?null:Number(el.value);
    else{
      const b=program.blocks.find(b=>b.id===el.dataset.blockId),spec=definitions[b.kind].params[el.dataset.param];
      b.params[el.dataset.param]=spec.type==='boolean'?el.checked:spec.type==='text'?el.value:el.value===''?null:Number(el.value);
      studio?.parameterChanged();
    }
    invalidate();
    byId('cmProjectName').textContent='我的通信工程';
    byId('cmClockSummary').textContent=`Rs = ${program.symbol_rate} Baud · 种子 ${program.seed}`;
    if(el.dataset.param){const b=program.blocks.find(b=>b.id===el.dataset.blockId),card=[...byId('cmProgram').querySelectorAll('[data-cm-id]')].find(card=>card.dataset.cmId===b.id);card.querySelector('.cm-slots').innerHTML=summaryHTML(b);}
  });
  root.addEventListener('dragstart',event=>{
    const item=event.target.closest('[data-cm-kind],[data-cm-move]');if(busy||!item){event.preventDefault();return}
    drag=item.dataset.cmKind?{kind:item.dataset.cmKind}:{id:item.dataset.cmMove};
    event.dataTransfer.effectAllowed=drag.id?'move':'copy';event.dataTransfer.setData('application/x-ocean-communication',JSON.stringify(drag));
  });
  const clearDrag=()=>{byId('cmProgram').classList.remove('cm-drag-over');byId('cmProgram').querySelectorAll('.cm-drop-before,.cm-drop-after').forEach(e=>e.classList.remove('cm-drop-before','cm-drop-after'))};
  byId('cmProgram').addEventListener('dragover',event=>{
    if(!drag||busy)return;event.preventDefault();event.dataTransfer.dropEffect=drag.id?'move':'copy';clearDrag();byId('cmProgram').classList.add('cm-drag-over');
    const card=event.target.closest('[data-cm-index]');if(card)card.classList.add(card.classList.contains('cm-sink')||event.clientY<card.getBoundingClientRect().top+card.getBoundingClientRect().height/2?'cm-drop-before':'cm-drop-after');
  });
  byId('cmProgram').addEventListener('drop',event=>{
    if(!drag||busy)return;event.preventDefault();const card=event.target.closest('[data-cm-index]');let index=program.blocks.length-1;
    if(card){index=Number(card.dataset.cmIndex);if(!card.classList.contains('cm-sink')&&event.clientY>=card.getBoundingClientRect().top+card.getBoundingClientRect().height/2)index++}
    const item=drag;drag=null;clearDrag();if(item.kind)add(item.kind,index);else move(item.id,index);
  });
  root.addEventListener('dragend',()=>{drag=null;clearDrag()});
  byId('cmUndo').onclick=()=>history('undo');byId('cmRedo').onclick=()=>history('redo');
  byId('cmLocate').onclick=()=>{const card=[...byId('cmProgram').querySelectorAll('[data-cm-id]')].find(card=>card.dataset.cmId===selectedId);card?.scrollIntoView({block:'nearest',inline:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});};
  byId('cmPreset').onchange=async event=>{
    const preset=catalog.presets[event.target.value];if(!preset)return;
    if(program.blocks.length>1&&!await confirmReplace('用示例替换当前链路？可通过“撤销”恢复。')){event.target.value='';return}
    setProgram(preset.program,'示例已载入，点击 Build 构建，再 Run 观察结果。');
  };
  byId('cmReset').onclick=async()=>{if(program.blocks.length>1&&!await confirmReplace('清空当前链路？信宿将保留，可通过“撤销”恢复。'))return;byId('cmPreset').value='';setProgram(empty(),'信宿已就位，从积木箱添加信源。')};
  byId('cmForm').onsubmit=async event=>{
    event.preventDefault();if(busy||!catalog||!validateFields())return;
    busy=true;compiled=null;result=null;showResult();buttons();status('Build：正在检查信号类型、参数与收发配对…');
    try{compiled=await api('build',{program:clone(program)});program=compiled.program;persist();renderProgram();showTrace();status(`Build 完成：${compiled.summary}。点击 Run 开始传输。`)}
    catch(error){compiled=null;status(error.message,true);studio?.markError(error.message)}finally{busy=false;buttons()}
  };
  byId('cmRun').onclick=async()=>{
    if(busy||!compiled)return;busy=true;result=null;showResult();buttons();const rev=revision,built=compiled;status('Run：正在生成信源、传输并译码…');
    try{const received=studio?await studio.runJob('run',{program:built.program,token:built.token}):await api('run',{program:built.program,token:built.token});if(rev!==revision)return;result=received;showResult();status(result.transport==='analog'?`Run 完成：${result.analog.scheme} 恢复 ${result.sink.count} 个模拟样本，RMSE ${result.metrics.rmse.toPrecision(4)}。`:`Run 完成：信宿收到 ${result.sink.count} ${result.sink.kind==='analog'?'个样本':'个比特'}，错误比特 ${result.metrics.bit_errors} / ${result.metrics.bit_count}。`)}
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
      if(file.size>(catalog.limits.max_project_bytes||8388608))throw Error('工程文件须小于 8 MiB。');
      const parsed=JSON.parse(await file.text());
      if(parsed.document_schema===2&&studio){busy=false;buttons();await studio.importDocument(parsed,true);return}
      const checked=await api('validate',{program:parsed});
      const sinks=checked.program.blocks.filter(b=>b.kind==='sink');if(sinks.length!==1||checked.program.blocks.at(-1).kind!=='sink')throw Error('工程须保留一个位于末端的信宿。');
      if(program.blocks.length===1||await confirmReplace('用导入的工程替换当前链路？可通过“撤销”恢复。'))imported=checked.program;
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
  byId('cmStage').onchange=()=>{if(byId('cmStage').value)plot='stage';drawAnalysis()};
  byId('cmSweepMetric').onchange=drawSweep;
  byId('cmSweepNoise').onchange=buttons;
  byId('cmSweepClear').onclick=()=>{sweeps=[];drawSweep();buttons();studio?.persist();byId('cmSweepStatus').textContent='曲线已清空。'};
  byId('cmSweepExport').onclick=()=>download('communication-sweeps.json',JSON.stringify({sweeps},null,2)+'\n','application/json');
  byId('cmSweepCSV').onclick=()=>{
    const rows=['curve,axis,db,frames,bit_count,bit_errors,ber,ber_low,ber_high,ser,ser_low,ser_high,fer,fer_low,fer_high,theory_ber,rmse,stop_reason'];
    for(const s of sweeps)for(const p of s.points)rows.push([s.name,s.axis,p.db,p.frames,p.bit_count,p.bit_errors,p.ber,...p.ber_interval,p.ser,...p.ser_interval,p.fer,...p.fer_interval,p.theory_ber??'',p.rmse??'',p.stop_reason].map(v=>'"'+String(v).replaceAll('"','""')+'"').join(','));
    download('communication-sweeps.csv',rows.join('\n')+'\n','text/csv');
  };
  byId('cmSweepRun').onclick=async()=>{
    if(busy||!compiled)return;
    for(const input of root.querySelectorAll('.cm-sweep input'))if(!input.checkValidity()){input.reportValidity();return}
    const settings={block_id:byId('cmSweepNoise').value,mode:byId('cmSweepMode').value,start:Number(byId('cmSweepStart').value),stop:Number(byId('cmSweepStop').value),step:Number(byId('cmSweepStep').value),frames:Number(byId('cmSweepFrames').value),target_errors:Number(byId('cmSweepErrors').value)};
    busy=true;buttons();byId('cmSweepStatus').textContent='正在累计各信噪比下的多帧误码结果…';
    try{
      Object.assign(settings,studio?.sweepSettings()||{});
      const data=studio?await studio.runJob('sweep',{program:compiled.program,token:compiled.token,settings}):await api('sweep',{program:compiled.program,token:compiled.token,settings});
      data.name=byId('cmSweepName').value.trim()||byId('cmProjectName').textContent;
      if(sweeps.length>=6)sweeps.shift();sweeps.push(data);studio?.persist();drawSweep();
      byId('cmSweepStatus').textContent=`${data.complete?'扫描完成':'扫描已暂停，保留已完成统计，可续跑'}：${data.points.length} 个点，${data.points.reduce((n,p)=>n+p.frames,0)} 帧。最多保留 6 条曲线；零错误点以空心上界标记显示。`;
    }catch(error){byId('cmSweepStatus').textContent=error.message}finally{busy=false;buttons()}
  };
  byId('cmOffset').oninput=drawSink;
  function showTrace(){
    const data=result||compiled,plan=data?.plan||[];byId('cmModel').textContent=data?.model||'复基带 · 1 样本/符号 · 理想定时 · 硬判决';
    byId('cmTrace').innerHTML=plan.length?`<table><thead><tr><th>积木</th><th>输出类型</th><th>数量</th></tr></thead><tbody>${plan.map(row=>`<tr><td>${esc(row.label)}</td><td>${esc(row.output)}</td><td>${row.count}</td></tr>`).join('')}</tbody></table>`:'Build 后显示逐级信号类型和数据量。';
    if(!result){byId('cmDetails').textContent='';return}
    const m=result.metrics;
    if(result.advanced){
      const a=result.advanced,r=a.recovery,f=r.frame;
      byId('cmDetails').textContent=`${a.scheme}；SER ${(100*m.ser).toFixed(3)}%；${m.crc_pass===null?'':`CRC ${m.crc_pass?'通过':'未通过'}；`}${r.frequency?`估计频偏 ${r.frequency.estimated_hz.toFixed(3)} Hz；`:''}${f?`帧同步${f.detected?'成功':'未锁定'}，相关峰 ${f.peak.toFixed(3)}，起点 ${f.start_symbol}；`:''}${a.ofdm?`OFDM ${a.ofdm.nfft} 点，CP ${a.ofdm.cp}，PAPR ${a.ofdm.papr_db.toFixed(2)} dB；`:''}${(a.codecs||[]).filter(v=>v.kind==='ldpc_decode').map(v=>`LDPC ${v.iterations} 次迭代，${v.failed_codewords} 个码字校验未通过。`).join('')}`;return;
    }
    if(result.transport==='baseband'){
      const b=result.baseband,r=b.recovery,t=r?.timing,e=r?.equalizer;
      byId('cmDetails').textContent=`线路码/PAM：${b.scheme}；${b.symbol_rate} 码元/s × ${b.sps} 点/码元 = ${b.sample_rate} Hz。${b.pulse}；线路电平/编码位数 ${m.line_expansion.toFixed(3)}；线路违例 ${m.line_violations}。均衡前电平 RMSE ${m.before_equalizer_rmse.toPrecision(4)}，均衡后 ${m.level_rmse.toPrecision(4)}。前向抽头 [${b.equalizer_coefficients.map(v=>v.toPrecision(4)).join(', ')}]。${r?` 公共前导 ${r.training_symbols} / 完整帧 ${r.frame_symbols} 码元，数据占比 ${(100*r.payload_efficiency).toFixed(1)}%。`:''}${t?` ${t.method}：时钟分量${t.clock_informative?'已提取':'不足'}；初相 ${t.initial_phase.toFixed(4)}T，末相 ${t.final_phase.toFixed(4)}T；频率估计 ${t.frequency_ppm.toFixed(1)} ppm；末段相位抖动 ${t.phase_jitter.toPrecision(3)}T。`:''}${e?` ${e.method} / ${e.algorithm}；反馈抽头 [${e.feedback_coefficients.map(v=>v.toPrecision(4)).join(', ')}]；系数更新 ${e.updates} 次。${e.training_final_mse===null?'':` 训练 MSE ${e.training_initial_mse.toPrecision(4)} → ${e.training_final_mse.toPrecision(4)}。`}`:''}${result.sink.kind==='analog'?'信宿 RMSE 包含 PCM 量化误差。':''}`;return;
    }
    if(result.transport==='analog'){
      byId('cmDetails').textContent=`${result.analog.family} · ${result.analog.scheme}；模拟采样率 ${result.analog.sample_rate} Hz。最大全段绝对误差 ${m.max_abs_error.toPrecision(4)}；发送复包络功率 ${m.transmit_power.toPrecision(4)}；相位参考样本 ${result.analog.pilot_samples} 个。`+(m.overmodulated_samples?` AM 过调制样本 ${m.overmodulated_samples} 个。`:'');return;
    }
    byId('cmDetails').textContent=`解调后 / 译码前 BER：${m.coded_bit_errors} / ${m.coded_bit_count}；符号错误：${m.symbol_errors} / ${m.symbol_count}；判决前 EVM：${m.evm_percent.toPrecision(4)}%。有效码率含填充与终止位。`+(result.sink.kind==='analog'?` PCM 饱和样本：${m.clipped_samples}；译码后 BER 以源 PCM 比特为参考，RMSE 以原始模拟信源为参考。`:'')+(m.hamming_syndromes?` Hamming 非零综合征码字：${m.hamming_syndromes}（多位错误可能误纠正）。`:'');
  }
  function showResult(){
    studio?.onResult(result);
    byId('cmNoSignal').hidden=!!result;byId('cmSignalLed').classList.toggle('on',!!result);byId('cmSignalStatus').textContent=result?'信号已抵达':'无信号';byId('cmLegend').hidden=!result;
    byId('cmTextResult').hidden=!result?.text;byId('cmReceivedText').textContent=result?.text?.received||'';
    const m=result?.metrics,analog=result?.sink.kind==='analog',direct=result?.transport==='analog',wave=result?.analog||result?.baseband||result?.advanced;
    const rows=direct?[
      ['信宿 RMSE',m.rmse.toPrecision(4),'相对原始模拟信源'],
      ['恢复样本数',String(result.sink.count),`${result.analog.scheme} · ${result.analog.sample_rate} Hz`],
      ['输出信误比',m.rmse<=1e-12?'无误差':m.output_snr_db===null?'—':m.output_snr_db.toFixed(2)+' dB','原始信源功率 / 全段误差功率'],
      ['复包络误差',m.channel_error_percent===null?'—':m.channel_error_percent.toPrecision(4)+'%','补偿后接收包络相对发送包络']
    ]:[['译码后误码率',m?(100*m.ber).toFixed(3)+'%':'—',m?`${m.bit_errors} / ${m.bit_count} bit`:'等待传输'],['传输符号数',m?String(m.symbol_count):'—',m?`${result.baseband?.scheme||result.constellation.scheme.toUpperCase()} · ${program.symbol_rate} Baud`:'等待传输'],['有效码率',m?m.effective_rate.toFixed(3):'—','源比特 / 编码后比特'],[analog?'信宿 RMSE':result?.baseband?'判决前电平 RMSE':'判决前 EVM',m?(analog?m.rmse.toPrecision(4):result.baseband?m.level_rmse.toPrecision(4):m.evm_percent.toPrecision(4)+'%'):'—',analog?'相对原始模拟信源':'相对发送符号']];
    if(m?.crc_pass!==undefined&&m.crc_pass!==null)rows.push(['CRC 校验',m.crc_pass?'通过':'未通过','整帧接收校验']);
    byId('cmMetrics').innerHTML=rows.map(([label,value,note])=>`<div class="cm-metric"><span>${label}</span><strong>${value}</strong><small>${esc(note)}</small></div>`).join('');
    byId('cmStageLabel').hidden=!result?.advanced?.stages.length;
    byId('cmStage').innerHTML='<option value="">选择处理积木…</option>'+(result?.advanced?.stages||[]).map(s=>`<option value="${esc(s.id)}">${esc(s.label)}</option>`).join('');
    byId('cmSinkCaption').textContent=result?`${analog?'接收模拟波形':'接收比特序列'} · 显示前 ${result.sink.plot_count} / ${result.sink.count} ${analog?'点':'位'}`:'信宿等待接收';
    byId('cmWindow').hidden=!result||result.sink.count<=result.sink.plot_count;byId('cmOffset').max=result?Math.max(0,result.sink.count-result.sink.plot_count):0;byId('cmOffset').value=0;
    byId('cmLegend').querySelector('span:last-child').hidden=!!analog;
    byId('cmAnalogWarnings').hidden=!wave||!wave.warnings.length;
    byId('cmAnalogWarnings').textContent=wave?wave.warnings.join(' '):'';
    const recovery=result?.baseband?.recovery||result?.advanced?.recovery;
    for(const tab of root.querySelectorAll('[data-cm-plot]'))tab.hidden=tab.dataset.cmPlot==='timing'?!recovery?.timing:tab.dataset.cmPlot==='convergence'?!recovery?.equalizer?.updates:tab.dataset.cmPlot==='eye'?!wave?.eye:tab.dataset.cmPlot==='constellation'?!result?.constellation:tab.dataset.cmPlot==='correlation'?!(result?.advanced?.recovery.frame||result?.advanced?.source_correlation):tab.dataset.cmPlot==='ofdm'?!result?.advanced?.ofdm:['transmitter','spectrum'].includes(tab.dataset.cmPlot)?!wave:false;
    root.querySelector('[data-cm-plot="transmitter"]').textContent=result?.baseband?'发送波形':'已调 I / Q';
    root.querySelector('[data-cm-plot="spectrum"]').textContent=result?.baseband?'发送频谱':'已调频谱';
    root.querySelector('[data-cm-plot="channel"]').textContent=result?.baseband?'信道波形':'信道 I / Q';
    if(wave&&((plot==='constellation'&&!result.constellation)||(plot==='eye'&&!wave.eye)))plot='transmitter';
    if(plot==='stage'||(!wave&&['transmitter','spectrum','eye'].includes(plot)))plot='constellation';
    if(root.querySelector(`[data-cm-plot="${plot}"]`)?.hidden)plot=wave?'transmitter':'constellation';
    root.querySelectorAll('[data-cm-plot]').forEach(tab=>tab.setAttribute('aria-pressed',tab.dataset.cmPlot===plot?'true':'false'));
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
    const wave=result.analog||result.baseband||result.advanced,recovery=wave?.recovery;
    if(plot==='stage'&&result.advanced){
      const s=result.advanced.stages.find(s=>s.id===byId('cmStage').value);if(!s)return;
      const values=[...s.i,...s.q],low=Math.min(...values),high=Math.max(...values),margin=Math.max(.1,(high-low)*.1),end=Math.max(1,s.plot_count-1)/s.symbol_rate;
      const axis=axes(view,low-margin,high+margin,end,'时间 / s');axis.xEnd=end;line(view,s.i,axis,'#5264c4');line(view,s.q,axis,'#219782');byId('cmAnalysisCaption').textContent=`${s.label} 输出 · 蓝色 I / 绿色 Q · ${s.plot_count} / ${s.count} 点。`;return;
    }
    if(plot==='correlation'&&result.advanced){
      const f=result.advanced.recovery.frame,values=f?.correlation||result.advanced.source_correlation,end=(values.length-1)*(f?.correlation_step||1),axis=axes(view,-.1,1.1,end,'延迟 / 码元');axis.xEnd=end;
      line(view,values,axis,'#8058b6');byId('cmAnalysisCaption').textContent=f?`公共前导归一化相关；峰值 ${f.peak.toFixed(3)}，${f.detected?'已锁定':'未锁定'}。`:'PN 源序列的周期自相关，零延迟归一化为 1。';return;
    }
    if(plot==='ofdm'&&result.advanced?.ofdm){
      const o=result.advanced.ofdm,grid=o.grid_i,dx=(width-65)/o.nfft,dy=(height-50)/grid.length;
      for(let r=0;r<grid.length;r++)for(let c=0;c<o.nfft;c++){const v=Math.min(1.5,Math.hypot(grid[r][c],o.grid_q[r][c]));x.fillStyle=`hsl(${225-v*90} 65% ${90-v*28}%)`;x.fillRect(45+c*dx,20+r*dy,dx+.5,dy+.5)}
      x.fillStyle='#526b8e';x.fillText('OFDM 符号',3,13);x.fillText('子载波 0 → '+(o.nfft-1),45,height-12);byId('cmAnalysisCaption').textContent=`均衡后子载波幅度 · 前 ${grid.length} 个 OFDM 符号；DC 为零，${o.pilot_carriers.length} 个梳状导频。`;return;
    }
    if(recovery&&plot==='timing'){
      const t=recovery.timing,values=t.phases,low=Math.min(...values),high=Math.max(...values),margin=Math.max(.03,(high-low)*.08),end=Math.max(1,values.length-1)*(t.phase_step||1);
      const axis=axes(view,low-margin,high+margin,end,'帧内码元 / 相位 T');axis.xEnd=end;line(view,values,axis,'#8058b6');
      byId('cmAnalysisCaption').textContent=`${t.method} · 接收样本估计的时钟相位 / T；末段频率 ${t.frequency_ppm.toFixed(1)} ppm。曲线包含公共前导。`;return;
    }
    if(recovery&&plot==='convergence'){
      const e=recovery.equalizer,trace=e.error_trace,values=trace.map(v=>10*Math.log10(Math.max(v.mse,1e-12))),low=Math.min(-40,...values),high=Math.max(0,...values),end=Math.max(1,trace.at(-1).symbol);
      const axis=axes(view,low,high,end,'帧内码元 / MSE dB');axis.xEnd=end;line(view,values,axis,'#248c79');
      byId('cmAnalysisCaption').textContent=e.algorithm==='CMA'?'CMA · 每 32 码元平均恒模代价 (R − |y|²)²。':`${e.method} / ${e.algorithm} · 32 码元平均误差均方（MSE）；前 ${e.training_symbols} 码元为训练误差，之后为判决误差。`;return;
    }
    if(wave?.eye&&plot==='eye'){
      const eye=wave.eye,all=eye.traces.flat(),low=Math.min(-.1,...all),high=Math.max(.1,...all),margin=(high-low)*.08;
      const axis=axes(view,low-margin,high+margin,2,'码元间隔 / T');axis.xEnd=2;
      eye.traces.forEach(values=>line(view,values,axis,'#5264c442',false,1));
      byId('cmAnalysisCaption').textContent=`${wave.scheme} 眼图 · 接收滤波后、均衡前 · ${eye.traces.length} 段真实波形，每段 2 个码元${result.advanced?'，包含 I/Q 两路':''}。`;return;
    }
    if(wave&&plot==='spectrum'){
      const s=wave.spectrum,low=s.frequency_hz[0],span=s.frequency_hz.at(-1)-low;
      const axis=axes(view,Math.max(-100,Math.min(...s.density_db)),Math.max(0,...s.density_db),span,result.baseband?'基带频率 / Hz':'相对载频 / Hz',false,low);axis.xEnd=span;
      line(view,s.density_db,axis,'#8058b6');byId('cmAnalysisCaption').textContent=`${wave.scheme} 发送基带频谱 · 全帧双边周期图 / dB每Hz。`;return;
    }
    if(plot==='channel'||plot==='transmitter'){
      const c=plot==='transmitter'?wave.transmitter:result.channel,all=[...c.i,...c.q],min=Math.min(...all),max=Math.max(...all),margin=Math.max(.1,(max-min)*.1),end=(c.plot_count-1)/(wave?wave.sample_rate:c.symbol_rate);
      const axis=axes(view,min-margin,max+margin,end,'时间 / s');axis.xEnd=end;
      line(view,c.i,axis,'#5264c4');line(view,c.q,axis,'#219782');
      byId('cmAnalysisCaption').textContent=`${plot==='transmitter'?(result.baseband?'发送端基带波形':'发送端已调复包络'):'信道输出（解调前）'} · 蓝色 I / 绿色 Q · ${c.plot_count} / ${c.count} ${wave?'个采样点':'个符号'}${result.baseband?'（显示数据起始窗口，Q 为零）':''}。`;return;
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
  function drawSweep(){
    if(root.hidden||!root.querySelector('.cm-sweep').open)return;
    const view=surface('cmSweepCanvas'),{x,width,height}=view,metric=byId('cmSweepMetric').value,axisName=sweeps.at(-1)?.axis;
    const curves=sweeps.filter(s=>s.axis===axisName),points=curves.flatMap(s=>s.points),colors=['#5365cf','#238879','#af5390','#bd7a21','#3797b5','#8059a6'];
    byId('cmSweepTable').innerHTML=curves.length?'<table><thead><tr><th>曲线</th><th>参数值</th><th>帧数</th><th>'+metric.toUpperCase()+'</th><th>95% 区间</th><th>停止条件</th></tr></thead><tbody>'+curves.flatMap(s=>s.points.map(p=>`<tr><td>${esc(s.name)}</td><td>${p.db}</td><td>${p.frames}</td><td>${p[metric]?.toExponential(3)??'—'}</td><td>${p[metric+'_interval']?.map(v=>v.toExponential(2)).join(' – ')??'—'}</td><td>${({target_errors:'目标误码数',frame_limit:'帧数上限',time_limit:'时长上限',cancelled:'已取消',running:'运行中'})[p.stop_reason]}</td></tr>`)).join('')+'</tbody></table>':'';
    if(!points.length){x.fillStyle='#526b8e';x.textAlign='center';x.fillText('扫描后显示性能曲线，可修改链路继续加入对比。',width/2,height/2);return}
    if(metric==='rmse'){
      const values=points.filter(p=>Number.isFinite(p.rmse));if(!values.length)return;
      const min=Math.min(...points.map(p=>p.db)),max=Math.max(...points.map(p=>p.db)),axis=axes(view,0,Math.max(.000001,...values.map(p=>p.rmse))*1.1,Math.max(1,max-min),'',false,min);
      curves.forEach((s,i)=>{x.strokeStyle=colors[i];x.fillStyle=colors[i];x.beginPath();s.points.filter(p=>Number.isFinite(p.rmse)).forEach((p,j)=>{if(j)x.lineTo(axis.px(p.db-min),axis.py(p.rmse));else x.moveTo(axis.px(p.db-min),axis.py(p.rmse))});x.stroke();x.fillText(s.name.slice(0,24),axis.p.left+8,axis.p.top+15+i*15)});return;
    }
    const minX=Math.min(...points.map(p=>p.db)),maxX=Math.max(...points.map(p=>p.db)),lower=Math.max(-8,Math.floor(Math.log10(Math.min(...points.map(p=>Math.max(p[metric+'_interval'][0]||p[metric+'_interval'][1],1e-8))))));
    const axis=axes(view,lower,0,Math.max(1,maxX-minX),'',false,minX);axis.xEnd=Math.max(1,maxX-minX);
    for(let i=0;i<curves.length;i++){
      const s=curves[i],color=colors[i%colors.length];x.strokeStyle=color;x.fillStyle=color;x.lineWidth=1.7;x.beginPath();
      s.points.forEach((p,j)=>{const xx=axis.px(p.db-minX),yy=axis.py(Math.log10(Math.max(p[metric]||p[metric+'_interval'][1],1e-8)));if(j)x.lineTo(xx,yy);else x.moveTo(xx,yy)});x.stroke();
      for(const p of s.points){const xx=axis.px(p.db-minX),bounds=p[metric+'_interval'],yy=axis.py(Math.log10(Math.max(p[metric]||bounds[1],1e-8))),top=axis.py(Math.log10(Math.max(bounds[1],10**lower))),bottom=axis.py(Math.log10(Math.max(bounds[0],10**lower)));
        x.beginPath();x.moveTo(xx,top);x.lineTo(xx,bottom);x.moveTo(xx-3,top);x.lineTo(xx+3,top);x.moveTo(xx-3,bottom);x.lineTo(xx+3,bottom);x.stroke();x.beginPath();x.arc(xx,yy,3,0,2*Math.PI);if(p[metric])x.fill();else x.stroke();
      }
      if(metric==='ber'&&s.points.every(p=>p.theory_ber!==undefined)){x.setLineDash([4,4]);x.beginPath();s.points.forEach((p,j)=>{const xx=axis.px(p.db-minX),yy=axis.py(Math.max(lower,Math.log10(Math.max(p.theory_ber,1e-12))));if(j)x.lineTo(xx,yy);else x.moveTo(xx,yy)});x.stroke();x.setLineDash([])}
      x.textAlign='left';x.fillText(s.name.slice(0,24),axis.p.left+8,axis.p.top+15+i*15);
    }
    x.fillStyle='#526b8e';x.textAlign='left';x.font=chartFont(10);x.fillText('log₁₀ '+metric.toUpperCase()+' · '+axisName,axis.p.left,13);
  }
  root.querySelector('.cm-sweep').addEventListener('toggle',drawSweep);
  window.addEventListener('resize',()=>{drawSink();drawAnalysis();drawSweep()});document.addEventListener('visibilitychange',()=>{if(document.hidden)stopSnow();else drawSink()});
  async function init(){
    buttons();
    try{
      const response=await fetch('/api/communications/catalog');if(!response.ok)throw Error('积木箱加载失败，请刷新重试。');catalog=await response.json();definitions=Object.fromEntries(catalog.blocks.map(b=>[b.kind,b]));program=empty();
      studio=window.createCommunicationExperience?.({root,byId,esc,api,clone,uid,
        get:()=>({program,compiled,result,catalog,definitions,selectedId,busy,sweeps}),
        mutate:(fn,message)=>change(fn,message),setProgram,selectBlock,palette,renderProgram,status,
        setBusy:value=>{busy=value;buttons()},setResult:value=>{result=value;showResult()},
        applyDocument:doc=>change(()=>{program=clone(doc.program);selectedId=program.blocks[0].id;studio.loadState(doc);sweeps=clone(doc.sweeps||[])},'工程已载入。'),
        restoreResult:(built,value)=>{compiled=built;result=value;showResult();buttons()},
        addCurves:curves=>{for(const curve of curves){const prior=curve.resume_of?sweeps.findIndex(s=>s.job_id===curve.resume_of):-1;if(prior>=0)sweeps.splice(prior,1);if(sweeps.length>=6)sweeps.shift();sweeps.push(curve)}drawSweep();persist();buttons()},
        repaintSweeps:drawSweep,download});
      root.querySelector('[data-global="sample_count"]').max=catalog.limits.max_samples;
      let saved=null;try{saved=localStorage.getItem(storageKey)}catch{status('浏览器草稿存储不可用，仍可搭建链路并导出工程。')}
      if(saved){
        try{
          const data=await api('validate',{program:JSON.parse(saved)});
          if(data.program.blocks.filter(b=>b.kind==='sink').length!==1||data.program.blocks.at(-1).kind!=='sink')throw Error('信宿不在末端');
          program=data.program;status('已恢复浏览器草稿。点击 Build，再 Run。');
        }catch{status('原草稿无法读取，已打开空白链路。可导入工程 JSON 继续。',true)}
      }
      studio?.restoreDraft();
      byId('cmPreset').innerHTML='<option value="">选择一个实验示例…</option>'+Object.entries(catalog.presets).map(([key,v])=>`<option value="${key}">${esc(v.label)}</option>`).join('');palette();renderProgram();showResult();studio?.ready();
    }catch(error){status(error.message,true);buttons()}
  }
  showResult();init();
})();
