/* Ocean block studio: discover, organize, observe, debug and reuse experiments. */
window.createCommunicationExperience = function (core) {
  'use strict';
  const {root,byId,esc,clone,api,uid}=core;
  const storage='rs_communication_experience_v2';
  const defaults=()=>({name:'我的通信工程',groups:[],library:[],branches:[],activeBranch:0,probes:[],favorites:[],recent:[],scope:{},comparisons:null,result:null,projectId:null,projectVersion:null});
  let meta=defaults(),search='',filter='all',ports=[],diagnostic=0,diagnosticTimer=0,saveTimer=0,restoring=false,activeJob=null,receipt=null,observations=[],windowA=null,windowB=null,windowRevision=0,selected=new Set(),lastSelected=null,wasBusy=false,saves=Promise.resolve();
  const session=()=>localStorage.getItem('rs_agent_session')||'default';
  const request=(action,payload={})=>api(action,{session_id:session(),...payload});
  const message=text=>{byId('cmExperienceStatus').textContent=text};
  const get=()=>core.get();
  const terminal=status=>['completed','failed','cancelled','interrupted'].includes(status);
  const noiseKeys={awgn:'esn0_db',complex_awgn:'snr_db',sample_awgn:'snr_db',bandlimited_awgn:'snr_db'};
  const numeric=spec=>['number','integer','select'].includes(spec.type);
  const projectPanel=document.createElement('section');projectPanel.className='cm-experience cm-projects';projectPanel.setAttribute('aria-label','通信工程与调试控制');
  projectPanel.innerHTML=`<div class="cm-experience-row"><label>🗂️ 工程名称<input id="cmDocumentName" maxlength="120" value="我的通信工程"></label><label>已保存工程<select id="cmProjectList"><option value="">选择工程…</option></select></label><label>版本快照<select id="cmProjectVersions"><option value="">最新版本</option></select></label><button id="cmProjectOpen" type="button">打开</button><button id="cmProjectSave" type="button">💾 保存快照</button><button id="cmProjectCopy" type="button">复制工程</button><button id="cmProjectExport" type="button">📦 导出完整工程</button><button id="cmReport" type="button">📄 实验报告</button></div>
    <div class="cm-experience-row cm-debug-controls"><button id="cmCompleteReceiver" type="button">🔗 补齐接收链路</button><label class="cm-inline"><input id="cmLinkedParams" type="checkbox" checked>联动配对参数</label><button id="cmDebugStart" type="button">🐾 开始单步</button><button id="cmDebugStep" type="button" disabled>下一积木</button><button id="cmDebugContinue" type="button" disabled>继续</button><button id="cmDebugPause" type="button" disabled>暂停</button><button id="cmJobCancel" type="button" disabled>停止任务</button><button id="cmSweepResume" type="button" disabled>续跑扫描</button><label>多帧数<input id="cmContinuousFrames" type="number" value="10" min="1" max="100"></label><button id="cmContinuous" type="button">🌊 保持状态运行</button></div>
    <div id="cmJobProgress" role="status" class="cm-job-progress">Build 后可逐块调试、运行分支或连续多帧。</div><progress id="cmJobBar" max="1" value="0" aria-label="通信实验进度"></progress><p id="cmExperienceStatus" role="status"></p>`;
  byId('cmForm').before(projectPanel);
  const paletteTools=document.createElement('div');paletteTools.className='cm-discovery';
  paletteTools.innerHTML=`<label>🔎 寻找积木<input id="cmSearch" type="search" placeholder="名称、缩写、算法或用途" maxlength="80"></label><div class="cm-discovery-tabs"><button type="button" data-cm-discover="all" aria-pressed="true">全部</button><button type="button" data-cm-discover="favorites">⭐ 收藏</button><button type="button" data-cm-discover="recent">🕘 最近</button></div><label>🧭 实验入口<select id="cmScenario"><option value="">按目标开始…</option><option value="text">传输文字</option><option value="soft_viterbi">纠错与软译码</option><option value="complex_receiver">载波与符号同步</option><option value="fractional_equalizer">抗多径与均衡</option><option value="ofdm_cfo_tracking">OFDM 与导频跟踪</option><option value="analog_am">模拟调制</option></select></label><label class="cm-inline"><input id="cmInsertAfter" type="checkbox">添加到选中积木后</label>`;
  byId('cmPalette').before(paletteTools);
  const library=document.createElement('details');library.className='cm-library';library.innerHTML='<summary>🧰 我的组合积木</summary><div id="cmLibrary"></div>';byId('cmPalette').after(library);
  const organize=document.createElement('details');organize.className='cm-organize';
  organize.innerHTML=`<summary>🧩 组合积木与接收分支</summary><div class="cm-experience-row"><label>组合名称<input id="cmGroupName" maxlength="80" placeholder="例如：QPSK 接收机"></label><button type="button" id="cmGroupCreate">封装勾选积木</button><button type="button" id="cmGroupExpand">全部展开</button><button type="button" id="cmGroupUnpack">解开所选组合</button><button type="button" id="cmProbePin">📌 标记观察点</button></div><label>组合对外参数<select id="cmGroupExpose" multiple size="4" aria-label="组合积木对外参数"></select></label><div class="cm-experience-row"><label>接收分支<select id="cmBranchSelect"><option value="0">主链路</option></select></label><label>分支名称<input id="cmBranchName" maxlength="80" placeholder="新分支名称"></label><button type="button" id="cmBranchAdd">＋ 接收分支</button><button type="button" id="cmBranchesRun">运行共享信道对比</button><label>自动对照<select id="cmContrastType"><option value="soft">硬 / 软译码</option><option value="equalizer">关闭 / 启用均衡</option><option value="coding">无编码 / Hamming / 卷积码</option></select></label><button type="button" id="cmContrastRun">生成并运行对照</button></div><div id="cmFlow" class="cm-flow" aria-label="通信链路与分支流程"></div><div id="cmBranchResults"></div></details>`;
  byId('cmProgram').parentElement.before(organize);
  const scope=document.createElement('section');scope.className='cm-experience cm-scopes';scope.setAttribute('aria-label','多图联动信号观察');
  scope.innerHTML=`<header><h3>🔬 积木输出与联动观察</h3><span id="cmExecutionSummary">运行后选择任意积木输出</span></header><div class="cm-experience-row"><label>观察点 A<select id="cmProbeA"></select></label><label>观察点 B<select id="cmProbeB"></select></label><label>视图<select id="cmProbePlot"><option value="wave">波形 / 比特 / LLR</option><option value="scatter">I/Q 星座</option><option value="spectrum">窗口频谱</option></select></label><label>起始点<input id="cmProbeOffset" type="number" min="0" value="0" step="1"></label><button id="cmProbeWindow" type="button">载入窗口</button><label class="cm-inline"><input id="cmScopeScale" type="checkbox" checked>共享纵轴</label><label class="cm-inline"><input id="cmScopeDifference" type="checkbox" checked>显示差值</label><label class="cm-inline"><input id="cmScopeAlign" type="checkbox">互相关自动对齐</label></div><p id="cmAlignmentStatus"></p><canvas id="cmScopeOverlay" height="220" aria-label="对齐后的 A B 波形叠加"></canvas><div class="cm-scope-grid"><div><canvas id="cmScopeA" width="600" height="220" aria-label="观察点 A"></canvas><p id="cmScopeInfoA"></p></div><div><canvas id="cmScopeB" width="600" height="220" aria-label="观察点 B"></canvas><p id="cmScopeInfoB"></p></div></div><label class="cm-cursor-label">联动游标<input id="cmScopeCursor" type="range" min="0" max="255" value="0"><span id="cmScopeCursorInfo"></span></label><canvas id="cmScopeDiff" width="1000" height="150" aria-label="对齐后的观察点差值"></canvas><div id="cmFrameTable" class="cm-trace-scroll"></div>`;
  byId('cmForm').after(scope);
  const sweepParameter=document.createElement('label');sweepParameter.innerHTML='扫描参数<select id="cmSweepParameter"></select>';byId('cmSweepNoise').closest('label').after(sweepParameter);
  const sweepValues=document.createElement('label');sweepValues.innerHTML='指定值（可选，逗号分隔）<input id="cmSweepValues" type="text" maxlength="160" placeholder="例如 128,256,512">';byId('cmSweepErrors').closest('label').after(sweepValues);
  byId('cmSweepNoise').closest('label').firstChild.textContent='扫描积木 / 全局参数';
  const reportDialog=document.createElement('dialog');reportDialog.id='cmReportDialog';reportDialog.className='cm-replace-dialog';reportDialog.innerHTML='<h3>📄 通信实验报告</h3><div id="cmReportPreview"></div><div class="cm-experience-row"><button id="cmReportDownload" type="button">下载 PDF</button><button id="cmReportClose" type="button">关闭</button></div>';root.append(reportDialog);

  const rf=window.createCommunicationAnalysis(core,{meta:()=>meta,persist,runJob});
  const layout=window.createCommunicationLayout(core);
  const learning=window.createCommunicationLearning(core,{meta:()=>meta,persist,runJob,documentValue,request,layout});
  const experiments=window.createCommunicationExperiments(core,{meta:()=>meta,persist,runJob,documentValue,request,layout});
  const spatial=window.createCommunicationSpatial(core,{meta:()=>meta,persist,request,layout,selected:()=>[...selected],insertionIndex,selectMembers:ids=>{selected=new Set(ids);render()},jobId:()=>get().result?.experience?.job_id});

  function documentValue(){
    syncBranches();return {document_schema:2,...clone(meta),program:clone(get().program),sweeps:clone(get().sweeps),result:clone(get().result||meta.result)};
  }
  function persist(){
    if(!get().program)return;
    try{localStorage.setItem(storage,JSON.stringify(documentValue()))}catch{message('工程草稿较大，可保存到工程库或导出完整工程。')}
    clearTimeout(saveTimer);
    if(meta.projectId&&!get().busy)saveTimer=setTimeout(()=>save(false).catch(e=>message(e.message)),1800);
  }
  function invalidate(){if(!restoring){rf.invalidate();learning.invalidate();experiments.invalidate();spatial.invalidate();meta.result=null;meta.comparisons=null;observations=[];windowA=windowB=null;byId('cmProbeA').innerHTML='';byId('cmProbeB').innerHTML='';byId('cmExecutionSummary').textContent='链路已更新，运行后选择积木输出';byId('cmBranchResults').innerHTML='';drawScopes()}scheduleDescribe()}
  function editSnapshot(){return clone(meta)}
  function restoreEdit(value){meta={...defaults(),...clone(value)}}
  function loadState(doc){meta={...defaults(),...clone(doc)};delete meta.program;delete meta.sweeps;delete meta.document_schema;restoring=true}
  function replaceProgram(){meta.groups=[];meta.branches=[];meta.activeBranch=0;meta.comparisons=null;meta.scope={};learning.replaceProgram();experiments.replaceProgram();spatial.replaceProgram();selected.clear()}
  function restoreDraft(){
    try{const saved=JSON.parse(localStorage.getItem(storage)||'null');if(saved?.document_schema===2){restoring=true;core.applyDocument(saved);restoring=false}}
    catch{message('已打开链路草稿；完整工程草稿无法读取。')}
  }
  function keywords(b){
    let words=b.label+' '+b.description+' '+b.kind+' '+b.category;
    if(/timing|clock/.test(b.kind))words+=' 定时 timing 同步 时钟 Gardner';
    if(/encode|decode|soft_/.test(b.kind))words+=' FEC 编码 译码 纠错';
    if(/equal|cma|fse/.test(b.kind))words+=' 均衡 多径 equalizer';
    if(/rrc|matched/.test(b.kind))words+=' 滤波 成形 匹配 pulse filter';
    if(/frequency|carrier/.test(b.kind))words+=' 频偏 载波 CFO PLL 同步';
    return words.toLowerCase();
  }
  function matches(b,category){
    const words=keywords(b),terms=search.toLowerCase().trim().split(/\s+/).filter(Boolean);
    if(terms.length&&!terms.every(term=>words.includes(term)))return false;
    if(filter==='favorites')return meta.favorites.includes(b.kind);
    if(filter==='recent')return meta.recent.includes(b.kind);
    return terms.length>0||b.category===category;
  }
  function insertionIndex(fallback){if(!byId('cmInsertAfter').checked)return fallback;return Math.min(get().program.blocks.length-1,get().program.blocks.findIndex(b=>b.id===get().selectedId)+1)}
  function used(kind){meta.recent=[kind,...meta.recent.filter(k=>k!==kind)].slice(0,16)}
  function decoratePalette(){
    if(search||filter!=='all')byId('cmCategoryName').textContent=search?'🔎 搜索结果':filter==='favorites'?'⭐ 收藏积木':'🕘 最近使用';
    const index=insertionIndex(get().program.blocks.length-1),previous=ports[index-1],domain=previous?.output||'起点';
    byId('cmPalette').querySelectorAll('[data-cm-kind]').forEach(button=>{
      const kind=button.dataset.cmKind,b=get().definitions[kind],accepts=b.inputs||[],compatible=accepts.includes(domain)||b.category==='source'&&index===0;
      const wrapper=document.createElement('div');wrapper.className='cm-palette-entry';button.before(wrapper);wrapper.append(button);
      const star=document.createElement('button');star.type='button';star.className='cm-favorite';star.dataset.cmFavorite=kind;star.setAttribute('aria-label',(meta.favorites.includes(kind)?'取消收藏 ':'收藏 ')+b.label);star.textContent=meta.favorites.includes(kind)?'★':'☆';wrapper.append(star);
      button.classList.toggle('cm-port-compatible',compatible);button.title=`输入：${accepts.join(' / ')}；输出：${b.output}${compatible?' · 可接当前位置':''}`;
    });
  }
  function markError(text){
    const match=/第\s*(\d+)\s*块/.exec(text),block=match?get().program.blocks[Number(match[1])-1]:null;
    if(block){core.selectBlock(block.id);byId('cmProgram').querySelector(`[data-cm-id="${block.id}"]`)?.classList.add('cm-invalid-block')}
  }
  async function describe(){
    const revision=++diagnostic;
    try{const info=await request('describe',{program:clone(get().program)});if(revision!==diagnostic)return;ports=info.ports;
      byId('cmProgram').querySelectorAll('[data-cm-id]').forEach(card=>{
        const p=ports.find(p=>p.id===card.dataset.cmId);if(!p)return;
        let line=card.querySelector('.cm-port-line');if(!line){line=document.createElement('div');line.className='cm-port-line';card.append(line)}
        line.textContent=`${p.input} → ${p.output}${p.count!==undefined?' · '+p.count+' 点':''}${p.sample_rate?' · '+Number(p.sample_rate.toPrecision(6))+' Hz':''}${p.filter_delay_seconds?' · 群时延 '+(1000*p.filter_delay_seconds).toPrecision(3)+' ms':''}`;
        card.classList.toggle('cm-invalid-block',info.error?.id===p.id);card.title=info.error?.id===p.id?info.error.message:line.textContent;
      });
      byId('cmConnectionHint').textContent=info.error?.message||'链路类型与参数检查通过。';core.palette();
    }catch(e){byId('cmConnectionHint').textContent=e.message}
  }
  function scheduleDescribe(){clearTimeout(diagnosticTimer);diagnostic++;diagnosticTimer=setTimeout(describe,250)}
  function parameterChanged(){
    if(!byId('cmLinkedParams').checked)return;
    const p=get().program,stack=[],definitions=get().definitions;
    const pairs={pcm_decode:'pcm_encode',repeat_decode:'repeat_encode',hamming_decode:'hamming_encode',conv_decode:'conv_encode',conv_soft_decode:'conv_encode',ldpc_decode:'ldpc_encode',deinterleave:'interleave',crc_check:'crc_append',descramble:'scramble',compand_decode:'compand_encode',dpcm_decode:'dpcm_encode',delta_decode:'delta_encode',huffman_decode:'huffman_encode',adpcm_decode:'adpcm_encode',bch_decode:'bch_encode',rs_decode:'rs_encode',packet_decode:'packet_encode',rx_despread:'tx_dsss'};
    for(const b of p.blocks)if(b.kind.startsWith('line_')&&b.kind.endsWith('_decode'))pairs[b.kind]=b.kind.replace('_decode','_encode');
    const encoders=new Set(Object.values(pairs));
    for(const b of p.blocks){if(encoders.has(b.kind))stack.push(b);else if(pairs[b.kind]&&stack.length){const tx=stack.pop();if(pairs[b.kind]===tx.kind)for(const name of Object.keys(definitions[b.kind].params))if(Object.hasOwn(tx.params,name))b.params[name]=tx.params[name]}}
    const noises=p.blocks.filter(b=>b.kind==='awgn');if(noises.length===1&&p.blocks.every(b=>get().definitions[b.kind].category!=='channel'||['awgn','ideal'].includes(b.kind))&&Number.isFinite(noises[0].params.esn0_db))for(const b of p.blocks)if(b.kind.startsWith('soft_'))b.params.noise_variance=Math.max(.000001,Math.min(100,10**(-noises[0].params.esn0_db/10)));
    syncBranches();
  }
  function selection(){
    const b=get().program.blocks.find(b=>b.id===get().selectedId);if(!b)return;
    byId('cmProbePin').textContent=(meta.probes.includes(b.id)?'📍 取消观察点':'📌 标记观察点');core.palette();
  }
  function exposedWidget(b,key){
    const spec=get().definitions[b.kind].params[key];if(!spec)return '';const value=b.params[key]??spec.default,data=`data-block-id="${esc(b.id)}" data-param="${esc(key)}"`;
    const input=spec.type==='boolean'?`<input ${data} type="checkbox" ${value?'checked':''}>`:spec.type==='select'?`<select ${data}>${spec.choices.map(v=>`<option value="${v}" ${v===value?'selected':''}>${esc(spec.choice_labels?.[v]??v)}</option>`).join('')}</select>`:spec.type==='text'?`<input ${data} value="${esc(value)}" maxlength="${spec.max_length}">`:`<input ${data} type="number" value="${value}" min="${spec.min}" max="${spec.max}" step="${spec.type==='integer'?'1':'any'}">`;
    return `<label>${esc(get().definitions[b.kind].label+' · '+spec.label)}${input}</label>`;
  }
  function syncBranches(){
    if(!meta.branches.length||!get().program)return;
    meta.activeBranch=Math.min(meta.activeBranch,meta.branches.length-1);meta.branches[meta.activeBranch].program=clone(get().program);
    const current=get().program,split=current.blocks.findIndex(b=>['demodulator','rx_converter'].includes(get().definitions[b.kind].category));if(split<0)return;
    for(let i=0;i<meta.branches.length;i++)if(i!==meta.activeBranch){const p=meta.branches[i].program,index=p.blocks.findIndex(b=>['demodulator','rx_converter'].includes(get().definitions[b.kind].category));if(index>=0)p.blocks=[...clone(current.blocks.slice(0,split)),...p.blocks.slice(index)];for(const k of ['seed','sample_rate','sample_count','symbol_rate'])p[k]=current[k]}
  }
  function render(){
    if(!get().program)return;syncBranches();const blocks=get().program.blocks,ids=blocks.map(b=>b.id);
    meta.groups=meta.groups.filter(g=>g.members.every(id=>ids.includes(id))&&g.members.every((id,i)=>ids.indexOf(id)===ids.indexOf(g.members[0])+i));
    selected=new Set([...selected].filter(id=>ids.includes(id)));
    byId('cmDocumentName').value=meta.name;if(meta.projectId||meta.name!=='我的通信工程')byId('cmProjectName').textContent=meta.name;
    byId('cmProgram').querySelectorAll('.cm-group').forEach(group=>{group.querySelectorAll('[data-cm-id]').forEach(card=>group.before(card));group.remove()});
    byId('cmProgram').querySelectorAll('[data-cm-id]').forEach(card=>{
      if(card.classList.contains('cm-sink'))return;
      card.querySelector('.cm-multi')?.remove();
      const label=document.createElement('label');label.className='cm-multi';label.innerHTML=`<input type="checkbox" data-cm-multi="${esc(card.dataset.cmId)}" aria-label="勾选 ${esc(get().definitions[blocks.find(b=>b.id===card.dataset.cmId).kind].label)}" ${selected.has(card.dataset.cmId)?'checked':''}>`;card.querySelector('.cm-block-head').prepend(label);
      if(meta.probes.includes(card.dataset.cmId))card.classList.add('cm-probed');
    });
    for(const g of meta.groups){
      const cards=g.members.map(id=>[...byId('cmProgram').querySelectorAll('[data-cm-id]')].find(card=>card.dataset.cmId===id));if(cards.some(c=>!c))continue;
      const group=document.createElement('details');group.className='cm-group';group.dataset.groupId=g.id;group.open=!g.collapsed;
      group.innerHTML=`<summary>🧩 ${esc(g.name)} <small>${g.members.length} 个积木</small></summary><div class="cm-group-fields">${(g.exposed||[]).map(v=>{const [id,key]=v.split(':');const b=blocks.find(b=>b.id===id);return b?exposedWidget(b,key):''}).join('')}</div><div class="cm-group-body"></div>`;
      cards[0].before(group);cards.forEach(card=>group.querySelector('.cm-group-body').append(card));group.addEventListener('toggle',()=>{g.collapsed=!group.open;persist()});
    }
    byId('cmLibrary').innerHTML=meta.library.length?meta.library.map((g,i)=>`<button type="button" data-cm-library="${i}">🧩 ${esc(g.name)} · ${g.blocks.length} 块</button>`).join(''):'勾选相邻积木，封装后即可复用。';
    byId('cmGroupExpose').innerHTML=blocks.filter(b=>selected.has(b.id)).flatMap(b=>Object.entries(get().definitions[b.kind].params).map(([key,spec])=>`<option value="${esc(b.id+':'+key)}">${esc(get().definitions[b.kind].label+' · '+spec.label)}</option>`)).join('');
    byId('cmBranchSelect').innerHTML=meta.branches.length?meta.branches.map((b,i)=>`<option value="${i}">${esc(b.name)}</option>`).join(''):'<option value="0">主链路</option>';byId('cmBranchSelect').value=String(meta.activeBranch);
    renderFlow();renderSweepParameters();selection();scheduleDescribe();learning.render();experiments.render();spatial.render();
  }
  function renderFlow(){
    const blocks=get().program.blocks,split=blocks.findIndex(b=>['demodulator','rx_converter'].includes(get().definitions[b.kind].category));
    const label=b=>`<span>${esc(get().definitions[b.kind].label)}</span>`;
    byId('cmFlow').innerHTML=meta.branches.length>1?`<div class="cm-flow-prefix">${blocks.slice(0,split).map(label).join(' → ')}</div><div class="cm-flow-branches">${meta.branches.map((b,i)=>{const idx=b.program.blocks.findIndex(v=>['demodulator','rx_converter'].includes(get().definitions[v.kind].category));return `<div><strong>${esc(b.name)}</strong><div>${b.program.blocks.slice(idx).map(label).join(' → ')}</div></div>`}).join('')}</div>`:`<div class="cm-flow-prefix">${blocks.map(label).join(' → ')}</div>`;
  }
  function renderSweepParameters(changed=false){
    const previous=meta.sweepSettings||{},selectedBlock=previous.block_id||byId('cmSweepNoise').value;
    const candidates=get().program.blocks.filter(b=>Object.values(get().definitions[b.kind].params).some(numeric));
    byId('cmSweepNoise').innerHTML=candidates.map(b=>`<option value="${esc(b.id)}">${esc(get().definitions[b.kind].label)}</option>`).join('')+'<option value="@global">全局参数</option>';
    byId('cmSweepNoise').value=candidates.some(b=>b.id===selectedBlock)||selectedBlock==='@global'?selectedBlock:(candidates.find(b=>noiseKeys[b.kind])?.id||candidates[0]?.id||'@global');
    const block=get().program.blocks.find(b=>b.id===byId('cmSweepNoise').value),specs=block?get().definitions[block.kind].params:{seed:{label:'随机种子',type:'integer',min:0,max:4294967294,default:42},sample_rate:{label:'模拟采样率 / Hz',type:'number',min:16,max:48000,default:256},sample_count:{label:'模拟样本数',type:'integer',min:32,max:get().catalog.limits.max_samples,default:256},symbol_rate:{label:'码元率 / OFDM 子载波间隔',type:'number',min:1,max:100000,default:1000}};
    const old=changed?'':byId('cmSweepParameter').value||previous.parameter;
    byId('cmSweepParameter').innerHTML=Object.entries(specs).filter(([,s])=>numeric(s)).map(([key,s])=>`<option value="${key}">${esc(s.label)}</option>`).join('');
    const key=old&&Object.hasOwn(specs,old)?old:block&&noiseKeys[block.kind]||Object.keys(specs).find(k=>numeric(specs[k]));byId('cmSweepParameter').value=key;
    const spec=specs[key];if(!spec)return;
    const noise=block&&noiseKeys[block.kind]===key;byId('cmSweepMode').disabled=!noise;if(!noise)byId('cmSweepMode').value='native';
    const lo=spec.min??Math.min(...spec.choices),hi=spec.max??Math.max(...spec.choices);
    for(const id of ['cmSweepStart','cmSweepStop']){byId(id).min=noise?-10:lo;byId(id).max=noise?40:hi;if(changed||Number(byId(id).value)<Number(byId(id).min)||Number(byId(id).value)>Number(byId(id).max))byId(id).value=id==='cmSweepStart'?Math.max(noise?0:lo,Math.min(hi,spec.default)):Math.min(noise?12:hi,Math.max(lo,spec.default*2))}
    if(changed){byId('cmSweepValues').value=spec.type==='select'?spec.choices.slice(0,6).join(','):'';byId('cmSweepStep').value=spec.type==='integer'||spec.type==='select'?1:Math.max(.000001,(Number(byId('cmSweepStop').value)-Number(byId('cmSweepStart').value))/4||.01)}
    byId('cmSweepStep').min=.000001;byId('cmSweepStep').max=Math.max(20,hi-lo);byId('cmSweepStep').step='any';byId('cmSweepStart').step=spec.type==='integer'||spec.type==='select'?'1':'any';byId('cmSweepStop').step=byId('cmSweepStart').step;
  }
  function sweepSettings(){
    const block=byId('cmSweepNoise').value,param=byId('cmSweepParameter').value;let extra=block==='@global'?{global:param,block_id:undefined}:{parameter:param};
    const text=byId('cmSweepValues').value.trim();if(text)extra.values=text.split(',').map(v=>Number(v.trim()));meta.sweepSettings={block_id:block,parameter:param};return extra;
  }
  function buttons(busy){
    rf.buttons(busy);learning.buttons(busy);experiments.buttons(busy);spatial.buttons(busy);
    if(wasBusy&&!busy)persist();wasBusy=busy;
    const built=!!get().compiled;
    for(const id of ['cmDebugStart','cmContinuous','cmBranchesRun','cmContrastRun'])byId(id).disabled=busy||!built;
    for(const id of ['cmCompleteReceiver','cmProjectOpen','cmProjectSave','cmProjectCopy','cmProjectExport','cmReport','cmGroupCreate','cmBranchAdd','cmGroupUnpack'])byId(id).disabled=busy;
    byId('cmDebugStep').disabled=!activeJob||activeJob.status!=='paused';byId('cmDebugContinue').disabled=!activeJob||terminal(activeJob.status);byId('cmDebugPause').disabled=!activeJob||activeJob.kind!=='debug'||activeJob.status!=='running';
    byId('cmJobCancel').disabled=!activeJob||terminal(activeJob.status);byId('cmSweepResume').disabled=busy||!receipt;
  }
  async function watch(job){
    activeJob=job;let lastRevision=-1;
    while(true){
      job=await request('job-status',{id:job.id});activeJob=job;buttons(get().busy);
      if(job.revision!==lastRevision){lastRevision=job.revision;const p=job.progress||{},completed=p.completed_frames??p.completed??job.observations.length,total=p.total_frames??p.total??get().program.blocks.length;
        byId('cmJobProgress').textContent=`${({queued:'排队中',running:'执行中',paused:'已暂停',completed:'已完成',cancelled:'已停止',failed:'执行失败',interrupted:'可续跑'})[job.status]||job.status} · ${completed} / ${total}${job.error?' · '+job.error:''}`;byId('cmJobBar').max=Math.max(1,total);byId('cmJobBar').value=completed;
        if(job.observations.length)setObservations(job.observations,job.id);
        if(job.kind==='sweep'&&p.points){byId('cmSweepStatus').textContent=`正在累计：${p.points.length} 个参数点，${p.completed_frames||0} 帧。可停止并保留检查点。`}
        if(p.frames&&job.kind==='continuous')renderFrames(p);
      }
      if(terminal(job.status))break;
      await new Promise(resolve=>setTimeout(resolve,220));
    }
    if(job.kind==='sweep'){receipt=job.result?.complete?null:job.id;meta.sweepReceipt=receipt;persist()}
    if(job.status==='failed')throw Error(job.error||'实验执行失败。');if(job.status==='cancelled'&&!job.result)throw Error(job.error||'实验已停止。');
    if(job.result&&typeof job.result==='object')job.result.job_id=job.id;
    if(job.result?.branches)setObservations(job.result.branches.flatMap((branch,index)=>branch.result.experience.observations.map(v=>({...v,label:branch.name+' · '+v.label,branch:index}))),job.id);
    return job.result;
  }
  async function runJob(kind,payload){const job=await request('job-start',{kind,payload});return watch(job)}
  function onResult(result){rf.onResult(result);learning.onResult(result);experiments.onResult(result);spatial.onResult(result);if(result){meta.result=clone(result);if(result.experience)setObservations(result.experience.observations,result.experience.job_id||result.job_id);persist()}}
  function setObservations(values,jobId){
    observations=values.map(v=>({...v,job_id:jobId}));const a=byId('cmProbeA').value,b=byId('cmProbeB').value;
    const options=observations.map((v,i)=>`<option value="${i}">${meta.probes.includes(v.id)?'📌 ':''}${esc(v.label)} · ${esc(v.domain)} · ${v.count}</option>`).join('');byId('cmProbeA').innerHTML=options;byId('cmProbeB').innerHTML=options;
    const first=observations.findIndex(v=>meta.probes.includes(v.id));byId('cmProbeA').value=Number(a)<values.length&&a!==''?a:String(Math.max(0,first));byId('cmProbeB').value=Number(b)<values.length&&b!==''?b:String(Math.max(0,values.length-1));
    windowA=observations[Number(byId('cmProbeA').value)];windowB=observations[Number(byId('cmProbeB').value)];byId('cmExecutionSummary').textContent=`${values.length} 个已执行积木 · ${values.reduce((n,v)=>n+v.elapsed_ms,0).toFixed(1)} ms`;
    const executed=new Set(values.map(v=>v.id));byId('cmProgram').querySelectorAll('[data-cm-id]').forEach(card=>card.classList.toggle('cm-executed',executed.has(card.dataset.cmId)));drawScopes();
  }
  function persistScope(){meta.scope={align:byId('cmScopeAlign').checked,a:byId('cmProbeA').value,b:byId('cmProbeB').value,plot:byId('cmProbePlot').value,offset:byId('cmProbeOffset').value,scale:byId('cmScopeScale').checked,difference:byId('cmScopeDifference').checked,cursor:byId('cmScopeCursor').value};persist()}
  function canvas(id){const c=byId(id),r=c.getBoundingClientRect(),width=Math.max(200,r.width),height=Math.max(120,r.height),dpr=Math.min(2,devicePixelRatio||1);c.width=Math.round(width*dpr);c.height=Math.round(height*dpr);const x=c.getContext('2d');x.setTransform(dpr,0,0,dpr,0,0);x.fillStyle='#f4f8ff';x.fillRect(0,0,width,height);x.font=chartFont(10);return {x,width,height}}
  function fft(valuesI,valuesQ){
    let n=1;while(n*2<=valuesI.length)n*=2;const re=valuesI.slice(0,n),im=valuesQ.slice(0,n);for(let i=1,j=0;i<n;i++){let bit=n>>1;for(;j&bit;bit>>=1)j^=bit;j^=bit;if(i<j){[re[i],re[j]]=[re[j],re[i]];[im[i],im[j]]=[im[j],im[i]]}}
    for(let len=2;len<=n;len*=2){const angle=-2*Math.PI/len;for(let i=0;i<n;i+=len)for(let j=0;j<len/2;j++){const c=Math.cos(j*angle),s=Math.sin(j*angle),r=re[i+j+len/2]*c-im[i+j+len/2]*s,k=re[i+j+len/2]*s+im[i+j+len/2]*c;re[i+j+len/2]=re[i+j]-r;im[i+j+len/2]=im[i+j]-k;re[i+j]+=r;im[i+j]+=k}}
    return Array.from({length:n},(_,i)=>{const j=(i+Math.floor(n/2))%n;return 10*Math.log10(Math.max(1e-12,(re[j]**2+im[j]**2)/n))});
  }
  function plotWindow(id,v,bounds){
    const {x,width,height}=canvas(id);if(!v){x.fillStyle='#60718a';x.fillText('执行积木后显示输出',20,35);return}
    const mode=byId('cmProbePlot').value,p={l:38,r:12,t:20,b:25},w=width-p.l-p.r,h=height-p.t-p.b;
    if(mode==='scatter'){
      const bound=Math.max(.1,...v.i.map(Math.abs),...v.q.map(Math.abs))*1.1,px=a=>p.l+(a/bound+1)*w/2,py=a=>p.t+(1-a/bound)*h/2;x.strokeStyle='#c4d3eb';x.beginPath();x.moveTo(px(0),p.t);x.lineTo(px(0),p.t+h);x.moveTo(p.l,py(0));x.lineTo(p.l+w,py(0));x.stroke();x.fillStyle='#2b948975';v.i.forEach((a,i)=>{x.beginPath();x.arc(px(a),py(v.q[i]),2,0,Math.PI*2);x.fill()});return;
    }
    let series=[v.i,v.q],low=bounds[0],high=bounds[1];if(mode==='spectrum'){series=[fft(v.i,v.q)];low=Math.min(-80,...series[0]);high=Math.max(0,...series[0])}
    const py=y=>p.t+h-(y-low)/Math.max(high-low,1e-12)*h;x.fillStyle='#60718a';x.strokeStyle='#d1dced';
    for(let i=0;i<=4;i++){const yy=p.t+i*h/4;x.beginPath();x.moveTo(p.l,yy);x.lineTo(p.l+w,yy);x.stroke();x.textAlign='right';x.fillText((high-(high-low)*i/4).toPrecision(2),p.l-4,yy+3)}
    series.forEach((values,index)=>{if(index===1&&values.every(y=>y===0))return;x.strokeStyle=index?'#258b79':'#5865cb';x.lineWidth=1.5;x.beginPath();values.forEach((y,i)=>{const xx=p.l+i/Math.max(1,values.length-1)*w;if(i)x.lineTo(xx,py(y));else x.moveTo(xx,py(y))});x.stroke()});
    if(mode==='wave'){const cursor=Number(byId('cmScopeCursor').value)/255;x.strokeStyle='#af5390';x.beginPath();x.moveTo(p.l+cursor*w,p.t);x.lineTo(p.l+cursor*w,p.t+h);x.stroke()}
    x.textAlign='left';x.fillStyle='#60718a';const start=v.offset||0,end=start+Math.max(0,v.i.length-1);x.fillText(mode==='spectrum'?'归一化频率 −0.5 → 0.5':v.sample_rate?`${(start/v.sample_rate).toPrecision(4)} → ${(end/v.sample_rate).toPrecision(4)} s`:`序号 ${start} → ${end}`,p.l,height-7);
  }
  function drawScopes(){
    if(root.hidden)return;const aligned=window.communicationAlign(windowA,windowB,byId('cmScopeAlign').checked),a=aligned.a,b=aligned.b;byId('cmAlignmentStatus').textContent=aligned.text+' · 叠加图：紫蓝 A-I，绿色 B-I；差值图保留 I/Q';const all=[...(a?.i||[]),...(a?.q||[]),...(b?.i||[]),...(b?.q||[])],low=Math.min(-.1,...all),high=Math.max(.1,...all),margin=Math.max(.05,(high-low)*.08),shared=[low-margin,high+margin];
    for(const [id,v,label] of [['cmScopeA',a,'A'],['cmScopeB',b,'B']]){
      const values=[...(v?.i||[]),...(v?.q||[])],range=byId('cmScopeScale').checked?shared:[Math.min(-.1,...values)-.1,Math.max(.1,...values)+.1];plotWindow(id,v,range);
      byId('cmScopeInfo'+label).textContent=v?`${v.label} · ${v.domain} · ${v.dtype} · ${v.count} 点${v.sample_rate?' · '+Number(v.sample_rate.toPrecision(6))+' Hz':''} · RMS ${v.rms.toPrecision(4)}`:'等待执行';
    }
    const difference=byId('cmScopeDifference').checked&&a&&b&&a.unit===b.unit&&a.domain===b.domain;byId('cmScopeDiff').hidden=!difference;
    if(difference){const n=Math.min(a.i.length,b.i.length),v={...a,i:a.i.slice(0,n).map((a,i)=>a-b.i[Math.min(b.i.length-1,Math.round(i/Math.max(1,n-1)*(b.i.length-1)))]),q:a.q.slice(0,n).map((v,i)=>v-b.q[i])};const bound=Math.max(.1,...v.i.map(Math.abs),...v.q.map(Math.abs))*1.1;plotWindow('cmScopeDiff',v,[-bound,bound])}
    byId('cmScopeOverlay').hidden=!difference||byId('cmProbePlot').value!=='wave';
    if(difference&&byId('cmProbePlot').value==='wave'){plotWindow('cmScopeOverlay',{...a,i:a.i,q:b.i},shared)}
    const ratio=Number(byId('cmScopeCursor').value)/255,values=[a,b].map(v=>v?`${v.label}: I=${v.i[Math.round(ratio*Math.max(0,v.i.length-1))]?.toPrecision(4)}`:'');byId('cmScopeCursorInfo').textContent=values.join(' · ');
  }
  async function loadWindows(){
    const revision=++windowRevision,selectedA=observations[Number(byId('cmProbeA').value)],selectedB=observations[Number(byId('cmProbeB').value)];if(!selectedA||!selectedB)return;
    const offset=Math.max(0,Number(byId('cmProbeOffset').value)||0),seconds=selectedA.sample_rate?offset/selectedA.sample_rate:null;
    const load=async v=>{const off=Math.min(v.count-1,Math.round(seconds!==null&&v.sample_rate?seconds*v.sample_rate:offset)),count=Math.min(1024,Math.ceil(256*(selectedA.sample_rate&&v.sample_rate?v.sample_rate/selectedA.sample_rate:1)));
      try{return {...await request('window',{id:v.job_id,block_id:v.id,offset:off,count,branch:v.branch}),label:v.label}}catch{if(off===0)return v;throw Error('完整窗口数据已过期，请重新运行工程。')}};
    try{const [a,b]=await Promise.all([load(selectedA),load(selectedB)]);if(revision!==windowRevision)return;windowA=a;windowB=b;drawScopes()}catch(e){message(e.message)}
  }
  function renderFrames(value){rf.frames(value);byId('cmFrameTable').innerHTML='<table><thead><tr><th>帧</th><th>BER</th><th>EVM</th><th>保留状态数</th></tr></thead><tbody>'+value.frames.map(r=>`<tr><td>${r.frame}</td><td>${r.ber?.toPrecision(4)??'—'}</td><td>${r.evm_percent?.toPrecision(4)??'—'}</td><td>${r.state_count}</td></tr>`).join('')+'</tbody></table>'}
  async function refreshProjects(){const data=await request('project-list');byId('cmProjectList').innerHTML='<option value="">选择工程…</option>'+data.projects.map(p=>`<option value="${p.id}">${esc(p.name)} · v${p.version}</option>`).join('');if(meta.projectId)byId('cmProjectList').value=meta.projectId;byId('cmProjectList')._projects=data.projects;versions()}
  function versions(){const p=(byId('cmProjectList')._projects||[]).find(p=>p.id===byId('cmProjectList').value);byId('cmProjectVersions').innerHTML='<option value="">最新版本</option>'+(p?.versions||[]).slice().reverse().map(v=>`<option value="${v.version}">v${v.version} · ${esc(new Date(v.updated).toLocaleString())}</option>`).join('')}
  function save(copyProject=false){clearTimeout(saveTimer);saves=saves.catch(()=>{}).then(()=>performSave(copyProject));return saves}
  async function performSave(copyProject=false){
    const doc=documentValue();doc.name=byId('cmDocumentName').value.trim()||'我的通信工程';if(copyProject)doc.name+=' · 副本';
    const saved=await request('project-save',{document:doc,id:copyProject?null:meta.projectId,version:copyProject?null:meta.projectVersion});meta.name=saved.document.name;meta.projectId=saved.id;meta.projectVersion=saved.version;byId('cmDocumentName').value=meta.name;
    try{localStorage.setItem(storage,JSON.stringify(documentValue()))}catch{}message(`已保存「${meta.name}」快照 v${meta.projectVersion}。`);await refreshProjects();
  }
  async function importDocument(doc,detach=false){
    if(detach)doc={...doc,projectId:null,projectVersion:null};
    const checked=await request('document-check',{document:doc});restoring=true;core.applyDocument(checked.document);restoring=false;render();
    if(checked.document.result){try{const built=await api('build',{program:get().program});core.restoreResult(built,checked.document.result)}catch{message('工程已打开，保存的结果可导出；修改链路后请重新 Build。')}}
    else if(checked.document.sweeps?.length)core.repaintSweeps();persist();
  }
  function make(kind,id=null,params={}){return {id:id||uid(),kind,params:Object.fromEntries(Object.entries(get().definitions[kind].params).map(([k,s])=>[k,params[k]??s.default]))}}
  async function contrast(){
    const type=byId('cmContrastType').value,p=clone(get().program);
    if(type==='coding'){
      const programs=[],names=[];for(const [encoder,decoder,name] of [[null,null,'无信道编码'],['hamming_encode','hamming_decode','Hamming (7,4)'],['conv_encode','conv_decode','卷积码 / Viterbi']]){
        const trial=clone(p),remove=new Set(['repeat_encode','repeat_decode','hamming_encode','hamming_decode','conv_encode','conv_decode','conv_soft_decode','ldpc_encode','ldpc_decode']);trial.blocks=trial.blocks.filter(b=>!remove.has(b.kind));
        for(let i=0;i<trial.blocks.length;i++)if(trial.blocks[i].kind.startsWith('soft_'))trial.blocks[i]=make('demod_'+trial.blocks[i].kind.slice(5),trial.blocks[i].id);
        if(encoder){const tx=trial.blocks.findIndex(b=>b.kind==='interleave'||b.kind.startsWith('mod_'));trial.blocks.splice(tx,0,make(encoder));const rx=trial.blocks.findIndex(b=>['crc_check','descramble','pcm_decode','compand_decode','dpcm_decode','delta_decode','sink'].includes(b.kind));trial.blocks.splice(rx,0,make(decoder))}
        programs.push(trial);names.push(name);
      }
      const selectedNoise=p.blocks.find(b=>noiseKeys[b.kind]);if(!selectedNoise)throw Error('编码对照需要一个白噪声积木。');
      const settings={block_id:selectedNoise.id,mode:'ebn0',start:0,stop:6,step:2,frames:Number(byId('cmSweepFrames').value),target_errors:Number(byId('cmSweepErrors').value)};
      const result=await runJob('experiments',{programs,names,settings});core.addCurves(result.curves);byId('cmBranchResults').textContent='已加入三组按信息比特 Eb/N₀ 标定的编码性能曲线。';return;
    }
    const a=clone(p),b=clone(p);
    if(type==='soft'){
      if(!p.blocks.some(v=>v.kind==='conv_encode'))throw Error('硬/软对照需要卷积码链路。');
      for(const trial of [a,b]){const demod=trial.blocks.findIndex(v=>v.kind.startsWith('demod_')||v.kind.startsWith('soft_')),scheme=trial.blocks[demod]?.kind.split('_')[1];if(!['bpsk','qpsk','qam16'].includes(scheme))throw Error('硬/软对照支持 BPSK、QPSK 和 16QAM。');trial.blocks[demod]=make((trial===a?'demod_':'soft_')+scheme,trial.blocks[demod].id);const decoder=trial.blocks.findIndex(v=>['conv_decode','conv_soft_decode'].includes(v.kind));trial.blocks[decoder]=make(trial===a?'conv_decode':'conv_soft_decode',trial.blocks[decoder].id)}
    }else{
      const equalizer=a.blocks.findIndex(v=>['rx_equalizer','rx_cma','rx_fse'].includes(v.kind));
      if(equalizer>=0){const old=a.blocks[equalizer];if(old.kind==='rx_fse')a.blocks[equalizer]=make('rx_timing',old.id);else a.blocks.splice(equalizer,1)}
      else{const demod=a.blocks.find(v=>v.params?.equalizer!==undefined);if(!demod)throw Error('请先添加均衡器。');demod.params.equalizer=0}
    }
    meta.comparisons=await runJob('branches',{programs:[a,b],names:type==='soft'?['硬判决 Viterbi','软判决 Viterbi']:['关闭均衡','启用均衡']});renderComparisons();persist();
  }
  function renderComparisons(){const value=meta.comparisons;if(!value?.branches)return;byId('cmBranchResults').innerHTML='<table><thead><tr><th>方案</th><th>BER</th><th>EVM</th><th>共享信道</th></tr></thead><tbody>'+value.branches.map(b=>`<tr><td>${esc(b.name)}</td><td>${b.result.metrics.ber?.toPrecision(5)??'—'}</td><td>${b.result.metrics.evm_percent?.toPrecision(4)??'—'}</td><td>同一接收样本</td></tr>`).join('')+'</tbody></table>'}
  async function action(fn){try{await fn()}catch(e){message(e.message);core.status(e.message,true)}finally{buttons(get().busy)}}
  root.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button)return;
    if(button.dataset.cmFavorite){event.preventDefault();event.stopImmediatePropagation();const kind=button.dataset.cmFavorite;meta.favorites=meta.favorites.includes(kind)?meta.favorites.filter(k=>k!==kind):[...meta.favorites,kind];persist();core.palette()}
    if(button.dataset.cmDiscover){filter=button.dataset.cmDiscover;root.querySelectorAll('[data-cm-discover]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));core.palette()}
    if(button.dataset.cmLibrary!==undefined)action(async()=>{const item=meta.library[Number(button.dataset.cmLibrary)],mapping={};core.mutate(()=>{const blocks=item.blocks.map(b=>{const id=uid();mapping[b.id]=id;return {...clone(b),id}});if(get().program.blocks.length+blocks.length>get().catalog.limits.max_blocks)throw Error('组合积木超过链路块数上限。');const index=insertionIndex(get().program.blocks.length-1);get().program.blocks.splice(index,0,...blocks);meta.groups.push({id:uid(),name:item.name,members:blocks.map(b=>b.id),collapsed:false,exposed:(item.exposed||[]).map(v=>{const [id,key]=v.split(':');return mapping[id]+':'+key})})},'已添加组合积木。')});
  },true);
  root.addEventListener('click',event=>{const input=event.target;if(input.dataset.cmMulti&&event.shiftKey&&lastSelected){const ids=get().program.blocks.filter(b=>b.kind!=='sink').map(b=>b.id),a=ids.indexOf(lastSelected),b=ids.indexOf(input.dataset.cmMulti);if(a>=0&&b>=0)ids.slice(Math.min(a,b),Math.max(a,b)+1).forEach(id=>selected.add(id))}});
  root.addEventListener('change',event=>{const input=event.target;if(input.dataset.cmMulti){const id=input.dataset.cmMulti;if(input.checked)selected.add(id);else selected.delete(id);lastSelected=id;core.renderProgram()}});
  byId('cmProgram').addEventListener('pointerdown',event=>{
    if(event.button!==0||get().busy||event.target.closest('.cm-block,.cm-group,button,input,select'))return;
    const start={x:event.clientX,y:event.clientY},box=document.createElement('div');box.className='cm-marquee';document.body.append(box);if(!event.shiftKey)selected.clear();
    const move=e=>{const left=Math.min(start.x,e.clientX),top=Math.min(start.y,e.clientY),right=Math.max(start.x,e.clientX),bottom=Math.max(start.y,e.clientY);Object.assign(box.style,{position:'fixed',left:left+'px',top:top+'px',width:right-left+'px',height:bottom-top+'px',zIndex:9999,pointerEvents:'none'});byId('cmProgram').querySelectorAll('.cm-block:not(.cm-sink)').forEach(card=>{const r=card.getBoundingClientRect(),hit=r.left<right&&r.right>left&&r.top<bottom&&r.bottom>top;card.classList.toggle('cm-marquee-selected',hit);if(hit)selected.add(card.dataset.cmId);else if(!event.shiftKey)selected.delete(card.dataset.cmId)})};
    const up=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',up);window.removeEventListener('pointercancel',up);box.remove();core.renderProgram()};window.addEventListener('pointermove',move);window.addEventListener('pointerup',up,{once:true});window.addEventListener('pointercancel',up,{once:true});event.preventDefault();
  });
  byId('cmSearch').oninput=event=>{search=event.target.value;core.palette()};byId('cmInsertAfter').onchange=()=>core.palette();
  byId('cmScenario').onchange=event=>{if(event.target.value){byId('cmPreset').value=event.target.value;byId('cmPreset').dispatchEvent(new Event('change',{bubbles:true}))}};
  byId('cmDocumentName').onchange=()=>{meta.name=byId('cmDocumentName').value.trim()||'我的通信工程';persist();core.renderProgram()};
  byId('cmCompleteReceiver').onclick=()=>action(async()=>{const data=await request('receiver',{program:get().program});core.mutate(()=>Object.assign(get().program,data.program),'已补齐接收处理与配对译码。')});
  byId('cmProjectList').onchange=versions;byId('cmProjectSave').onclick=()=>action(()=>save(false));byId('cmProjectCopy').onclick=()=>action(()=>save(true));
  byId('cmProjectOpen').onclick=()=>action(async()=>{const key=byId('cmProjectList').value;if(!key)throw Error('请选择已保存工程。');const version=byId('cmProjectVersions').value;const saved=await request('project-load',{id:key,version:version?Number(version):undefined});saved.document.projectId=saved.id;saved.document.projectVersion=version?null:saved.version;if(version)saved.document.projectId=null;await importDocument(saved.document);message(version?'已打开历史快照，保存时创建新的工程。':'工程、参数和结果已恢复。')});
  byId('cmProjectExport').onclick=()=>core.download('communication-project-v2.json',JSON.stringify(documentValue(),null,2)+'\n','application/json');
  byId('cmDebugStart').onclick=()=>action(async()=>{core.setBusy(true);try{const built=get().compiled;const result=await runJob('debug',{program:built.program,token:built.token});core.setResult(result)}finally{core.setBusy(false)}});
  for(const [id,control] of [['cmDebugStep','step'],['cmDebugContinue','continue'],['cmDebugPause','pause'],['cmJobCancel','cancel']])byId(id).onclick=()=>action(async()=>{if(activeJob)activeJob=await request('job-control',{id:activeJob.id,control})});
  byId('cmContinuous').onclick=()=>action(async()=>{const input=byId('cmContinuousFrames');if(!input.checkValidity()){input.reportValidity();return}core.setBusy(true);try{const b=get().compiled,value=await runJob('continuous',{program:b.program,token:b.token,frames:Number(input.value)});renderFrames(value);if(value.last)core.setResult(value.last);message(`多帧完成 ${value.frames.length} 帧，累计 BER ${value.ber.toPrecision(5)}，保留 ${value.state_count} 组算法状态。`)}finally{core.setBusy(false)}});
  byId('cmSweepResume').onclick=()=>action(async()=>{if(!receipt)return;core.setBusy(true);try{const prior=receipt,job=await request('job-control',{id:prior,control:'resume-sweep'}),curve=await watch(job);curve.name=byId('cmSweepName').value||meta.name;curve.resume_of=prior;core.addCurves([curve]);byId('cmSweepStatus').textContent=curve.complete?'续跑完成。':'已保存新的续跑检查点。'}finally{core.setBusy(false)}});
  byId('cmProbePin').onclick=()=>core.mutate(()=>{const id=get().selectedId;meta.probes=meta.probes.includes(id)?meta.probes.filter(v=>v!==id):[...meta.probes,id]},'观察点已更新。');
  byId('cmGroupCreate').onclick=()=>action(async()=>{const blocks=get().program.blocks.filter(b=>selected.has(b.id)),indices=blocks.map(b=>get().program.blocks.indexOf(b));if(!blocks.length||indices.some((v,i)=>v!==indices[0]+i))throw Error('请勾选相邻积木后封装。');const name=byId('cmGroupName').value.trim()||'我的组合积木';const exposed=[...byId('cmGroupExpose').selectedOptions].map(o=>o.value);core.mutate(()=>{meta.groups=meta.groups.filter(g=>!g.members.some(id=>selected.has(id)));const group={id:uid(),name,members:blocks.map(b=>b.id),exposed,collapsed:false};meta.groups.push(group);meta.library.push({name,blocks:clone(blocks),exposed});if(meta.library.length>16)meta.library.shift();selected.clear()},'组合积木已保存，可展开和复用。')});
  byId('cmGroupExpand').onclick=()=>{meta.groups.forEach(g=>g.collapsed=false);core.renderProgram();persist()};byId('cmGroupUnpack').onclick=()=>core.mutate(()=>{meta.groups=meta.groups.filter(g=>!g.members.includes(get().selectedId))},'组合已展开为普通积木。');
  byId('cmBranchAdd').onclick=()=>action(async()=>{if(meta.branches.length>=4)throw Error('最多保留 4 个接收分支。');core.mutate(()=>{if(!meta.branches.length)meta.branches.push({name:'接收方案 A',program:clone(get().program)});meta.branches.push({name:byId('cmBranchName').value.trim()||`接收方案 ${meta.branches.length+1}`,program:clone(get().program)});meta.activeBranch=meta.branches.length-1},'已添加接收分支，发送与信道参数保持联动。')});
  byId('cmBranchSelect').onchange=()=>{const index=Number(byId('cmBranchSelect').value);syncBranches();if(meta.branches[index]){core.mutate(()=>{meta.activeBranch=index;Object.assign(get().program,clone(meta.branches[index].program))},'已切换接收分支。')}};
  byId('cmBranchesRun').onclick=()=>action(async()=>{syncBranches();if(meta.branches.length<2)throw Error('请先添加一个接收分支。');core.setBusy(true);try{meta.comparisons=await runJob('branches',{programs:meta.branches.map(b=>b.program),names:meta.branches.map(b=>b.name)});renderComparisons();persist()}finally{core.setBusy(false)}});
  byId('cmContrastRun').onclick=()=>action(async()=>{core.setBusy(true);try{await contrast()}finally{core.setBusy(false)}});
  byId('cmSweepNoise').addEventListener('change',()=>{meta.sweepSettings={block_id:byId('cmSweepNoise').value};renderSweepParameters(true);meta.sweepSettings.parameter=byId('cmSweepParameter').value});byId('cmSweepParameter').onchange=()=>{const key=byId('cmSweepParameter').value;meta.sweepSettings={block_id:byId('cmSweepNoise').value,parameter:key};renderSweepParameters(false);byId('cmSweepValues').value='';const spec=get().definitions[get().program.blocks.find(b=>b.id===byId('cmSweepNoise').value)?.kind]?.params[key];if(spec){byId('cmSweepStart').value=spec.default;byId('cmSweepStop').value=Math.min(spec.max??Math.max(...spec.choices),spec.default*2||1);byId('cmSweepStep').value=spec.type==='number'?Math.max(.000001,(byId('cmSweepStop').value-spec.default)/4||.01):1;if(spec.type==='select')byId('cmSweepValues').value=spec.choices.join(',')}};
  for(const id of ['cmProbeA','cmProbeB'])byId(id).onchange=()=>{persistScope();loadWindows()};byId('cmProbeWindow').onclick=()=>{persistScope();loadWindows()};for(const id of ['cmProbePlot','cmScopeScale','cmScopeDifference','cmScopeAlign'])byId(id).onchange=()=>{persistScope();drawScopes()};byId('cmScopeCursor').oninput=()=>{persistScope();drawScopes()};
  byId('cmReport').onclick=()=>action(async()=>{const preview=await request('report-preview',{document:documentValue()});byId('cmReportPreview').innerHTML=preview.sections.map(s=>`<p><strong>${esc(s)}</strong></p>`).join('')+preview.summary.map(s=>`<p>${esc(s)}</p>`).join('');reportDialog.showModal()});byId('cmReportClose').onclick=()=>reportDialog.close();
  byId('cmReportDownload').onclick=()=>action(async()=>{const response=await fetch('/api/communications/report-pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:session(),document:documentValue()})});if(!response.ok){const data=await response.json();throw Error(data.error||'报告生成失败。')}const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download='communication-experiment.pdf';link.click();setTimeout(()=>URL.revokeObjectURL(url),30000)});
  const hint=document.createElement('p');hint.id='cmConnectionHint';hint.className='cm-connection-hint';byId('cmInspector').after(hint);
  window.addEventListener('resize',drawScopes);document.addEventListener('visibilitychange',()=>{if(!document.hidden)drawScopes()});
  async function ready(){receipt=meta.sweepReceipt||null;renderComparisons();try{await refreshProjects()}catch(e){message(e.message)}if(meta.result){try{const b=await api('build',{program:get().program});core.restoreResult(b,meta.result)}catch{}}const saved=meta.scope||{};for(const [key,id] of [['a','cmProbeA'],['b','cmProbeB'],['plot','cmProbePlot'],['offset','cmProbeOffset'],['cursor','cmScopeCursor']])if(saved[key]!==undefined)byId(id).value=saved[key];if(saved.align!==undefined)byId('cmScopeAlign').checked=saved.align;if(saved.scale!==undefined)byId('cmScopeScale').checked=saved.scale;if(saved.difference!==undefined)byId('cmScopeDifference').checked=saved.difference;buttons(get().busy);if(observations.length)loadWindows()}
  return {matches,decoratePalette,render,selection,insertionIndex,used,parameterChanged,persist,invalidate,editSnapshot,restoreEdit,loadState,restoreDraft,replaceProgram,ready,buttons,runJob,onResult,markError,sweepSettings,importDocument,prepare:learning.prepare};
};
