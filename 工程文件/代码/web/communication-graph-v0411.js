/* Scratch receiver stacks backed by the canonical graph and measured CFAR. */
window.createCommunicationGraphV0411=function(core,ctx){
  'use strict';
  const {byId,esc,get,clone}=core,M=window.CommunicationGraphModel;
  const host=document.createElement('section');host.id='cmGraph411';host.className='cm-graph-editor';
  host.innerHTML=`<summary>🪸 可视接线与分支实验 <small>v0.4.11</small></summary><div class="cm-graph-content">
    <div class="cm-graph-toolbar"><button type="button" id="cmGraphDemo">🧪 NLMS / DFE 示例</button><button type="button" id="cmGraphSenseDemo">🛰️ 多目标 CFAR 示例</button><button type="button" id="cmGraphConvert">🔗 转为可视工程</button><button type="button" id="cmGraphLeave">📋 保留当前线性链路</button></div>
    <div id="cmGraphWorkspace" hidden><div class="cm-graph-toolbar"><label>🎛️ 编辑接收分支<select id="cmGraphBranch"></select></label><button type="button" id="cmGraphAdd">＋ 克隆分支</button><button type="button" id="cmGraphRemoveBranch">移除分支</button><button type="button" id="cmGraphArrange">🧭 自动布局</button><button type="button" id="cmGraphBuild">🧱 Build 接线</button><button type="button" id="cmGraphRun">▶️ 完整运行</button><button type="button" id="cmGraphPartial">⚡ 局部重跑</button></div>
    <div class="cm-graph-toolbar"><label>汇合输入 A<select id="cmGraphInputA"></select></label><label>汇合输入 B<select id="cmGraphInputB"></select></label><label>汇合方式<select id="cmGraphMode"><option value="select">选择一路</option><option value="weighted">加权相加</option></select></label><label>选中输入<select id="cmGraphChoice"><option value="0">A</option><option value="1">B</option></select></label><label>A 权重<input id="cmGraphWeightA" type="number" step="0.1" min="-10" max="10"></label><label>B 权重<input id="cmGraphWeightB" type="number" step="0.1" min="-10" max="10"></label></div>
    <p class="cm-graph-status" id="cmGraphHelp">拖动标题排列积木；点击输出端口，再点击输入端口完成接线。选择积木后在原参数面板编辑。虚线边框表示本次复用。</p>
    <div class="cm-graph-scroll" tabindex="0" aria-label="并行接收积木拼接画布"><div id="cmGraphStage" class="cm-graph-stage"></div></div>
    <div class="cm-graph-toolbar"><label>连接起点<select id="cmGraphFrom"></select></label><label>输出端口<select id="cmGraphOutput"><option value="out">主输出</option><option value="power">距离—速度功率</option></select></label><label>连接终点<select id="cmGraphTo"></select></label><label>输入端口<select id="cmGraphInput"><option value="in">主输入</option><option value="a">汇合 A</option><option value="b">汇合 B</option></select></label><button type="button" id="cmGraphConnect">🔌 连接</button></div>
    <div class="cm-graph-toolbar"><label>已有连接<select id="cmGraphEdge"></select></label><button type="button" id="cmGraphDisconnect">断开连接</button><button type="button" id="cmGraphDelete">删除选中积木</button><button type="button" id="cmGraphCfarAdd">🎯 添加 CFAR 分析</button><button type="button" id="cmGraphPython">🐍 导出 Python</button><button type="button" id="cmGraphJSON">📦 完整工程 JSON</button></div>
    <div id="cmGraphResults" class="cm-graph-results"></div><details id="cmGraphCfar" class="cm-graph-cfar"><summary>🎯 二维 CA-CFAR 检测与门限</summary><label>分析节点<select id="cmGraphCfarNode"></select></label><div id="cmGraphCfarControls" class="cm-graph-cfar-controls"></div><label>热图<select id="cmGraphCfarView"><option value="power">接收功率 / dB</option><option value="threshold">CFAR 门限 / dB</option><option value="noise">局部噪声 / dB</option></select></label><canvas id="cmGraphCfarCanvas" aria-label="距离速度谱、CFAR 检测标记及有效边界"></canvas><div id="cmGraphCfarResult" class="cm-graph-results"></div></details>
    </div><p id="cmGraphStatus" class="cm-graph-status" role="status">从均衡对比或多目标通感实验开始，也可转换现有接收分支。</p></div>`;
  byId('cmProgram').before(host);
  host.querySelector('summary').remove();
  const settings=document.createElement('details');settings.className='cm-command-menu cm-graph-menu';
  settings.innerHTML='<summary>🪸 分支</summary><div class="cm-menu-body"></div>';
  core.root.querySelector('.cm-command-main').append(settings);
  const menu=settings.lastElementChild;
  host.querySelectorAll('.cm-graph-toolbar').forEach(row=>menu.append(row));
  const advanced=document.createElement('details');advanced.className='cm-graph-advanced';advanced.innerHTML='<summary>🔎 高级连接检查</summary>';
  [...menu.querySelectorAll('.cm-graph-toolbar')].slice(3).forEach(row=>advanced.append(row));menu.append(advanced);
  menu.append(byId('cmGraphHelp'));
  byId('cmGraphHelp').textContent='拖动积木上下拼接；在接收槽内独立编辑。连接检查保留导入工程的拓扑信息。';
  const detail=document.createElement('details');detail.className='cm-graph-analysis';
  detail.innerHTML='<summary>🪸 分支结果与二维 CFAR</summary>';
  detail.append(byId('cmGraphResults'),byId('cmGraphCfar'));
  byId('cmPane-spatial').append(detail);
  host.append(byId('cmGraphStatus'));
  byId('cmGraphBuild').hidden=true;byId('cmGraphRun').hidden=true;
  byId('cmGraphBuild').textContent='🔨 Build';byId('cmGraphRun').textContent='▶ Run';
  core.root.querySelector('.cm-primary-actions').append(byId('cmGraphPartial'));
  byId('cmGraphArrange').textContent='🧭 整理积木';
  byId('cmGraphConvert').textContent='🧩 封装并行接收';byId('cmGraphLeave').textContent='📋 展开当前接收链';
  byId('cmGraphPython').textContent='🐍 导出整图 Python';
  const canvasTools=document.createElement('div');canvasTools.className='cm-scratch-tools';
  canvasTools.innerHTML='<button type="button" id="cmGraphCopy">复制勾选</button><button type="button" id="cmGraphCut">剪切勾选</button><button type="button" id="cmGraphPaste">粘贴</button><button type="button" id="cmGraphSelectAll">全选</button><button type="button" id="cmGraphGroup">封装勾选</button><button type="button" id="cmGraphUnpack">展开组合</button><button type="button" id="cmGraphNote">📝 注释</button><label>组合名称<input id="cmGraphGroupName" maxlength="80" placeholder="我的接收机"></label>';
  menu.append(canvasTools);
  const notes=document.createElement('label');notes.className='cm-scratch-note-editor';notes.hidden=true;
  notes.innerHTML='📝 积木注释<textarea id="cmGraphNoteText" maxlength="1000" rows="3"></textarea>';
  menu.append(notes);
  const toolStack=document.createElement('div');toolStack.id='cmToolStack';
  const viewport=document.createElement('div');viewport.id='cmScratchViewport';viewport.className='cm-scratch-viewport';viewport.tabIndex=0;viewport.setAttribute('aria-label','积木拼接画布');
  byId('cmProgram').before(viewport);viewport.append(host,byId('cmProgram'),toolStack);
  const scratchUI=()=>{const m=meta();return m.scratch||(m.scratch={zoom:1,notes:{},collapsed:{},groups:[]});};
  let chosen=new Set(),clipboard=[],pointerPan=null;

  let compiled=null,lastProjection='',selected='',drag=null,editorError='';
  const meta=()=>ctx.meta(),graph=()=>meta().graph;
  const status=t=>byId('cmGraphStatus').textContent=t;
  const label=n=>n.kind==='branch_merge'?'🔗 '+(graph().merge.domain==='llr'?'LLR':'复符号')+' 双输入汇合':n.kind==='analysis_cfar2d'?'🎯 二维 CA-CFAR':get().definitions[n.kind]?.label||n.kind;
  const active=()=>meta().graphActiveBranch||graph()?.branches[0]?.id;
  function project(){const p=M.projection(graph(),active());Object.assign(get().program,p);lastProjection=JSON.stringify(p);}
  function edit(fn,message,layout=false){
    try{const g=clone(graph());fn(g);(layout?core.mutateLayout:core.mutate)(()=>{meta().graph=g;if(!layout)project();},message);render();status(message);}
    catch(e){render();status(e.message);}
  }
  function clearResults(){for(const key of ['workbenchResult','workbenchTaskResult','physicalBranch'])delete meta()[key];meta().graphResult=null;compiled=null;}
  function install(g,convert=false){chosen.clear();selected='';core.mutate(()=>{meta().tools=convert?M.remapTools(meta().tools,g,g.branches[0].id):[];clearResults();meta().graph=g;meta().graphActiveBranch=g.branches[0].id;meta().branches=[];meta().groups=[];meta().breakpoints=[];meta().scratch={zoom:1,notes:{},groups:[],collapsed:{}};meta().name='并行接收实验';project();},'并行接收工程已载入，可以编辑参数并 Build / Run。');core.root.dispatchEvent(new Event('cm-select'));byId('cmGraphOutput').value='out';byId('cmGraphInput').value='in';settings.open=false;render();status('并行接收工程已载入，可以编辑参数并 Build / Run。');}
  async function load(payload){core.setBusy(true);try{const v=await ctx.request('graph-create',payload);core.setBusy(false);install(v.graph,!!payload.programs);}catch(e){status(e.message);}finally{core.setBusy(false);}}
  byId('cmGraphDemo').onclick=()=>load({demo:'equalizer'});
  byId('cmGraphSenseDemo').onclick=()=>load({demo:'sensing'});
  byId('cmGraphConvert').onclick=()=>{ctx.syncBranches();const branches=meta().branches||[],programs=branches.length>1?branches.map(b=>clone(b.program)):[clone(get().program),clone(get().program)];const soft=programs.every(p=>p.blocks.some(b=>b.kind.startsWith('soft_')));load({programs,names:branches.map(b=>b.name),domain:soft?'llr':'symbols'});};
  byId('cmGraphLeave').onclick=()=>{core.mutate(()=>{meta().tools=M.remapTools(meta().tools,graph(),active(),false);clearResults();delete meta().graph;delete meta().graphResult;meta().breakpoints=[];lastProjection='';},'已保留当前接收分支的完整线性链路和有效实验工具。');core.root.dispatchEvent(new Event('cm-select'));};
  function sync(){
    if(!graph())return;const p=JSON.stringify(get().program);if(p===lastProjection)return;
    if(!lastProjection){lastProjection=p;return;}
    try{const g=M.absorb(clone(graph()),get().program,active(),get().definitions);meta().graph=g;lastProjection=p;editorError='';}
    catch(e){editorError=e.message;status(e.message);}
  }
  function invalidate(){sync();compiled=null;meta().graphResult=null;render();status('积木配置已更新，Build 后即可运行。');}
  function replaceProgram(){delete meta().graph;delete meta().graphResult;compiled=null;lastProjection='';selected='';chosen.clear();}
  function loadState(){compiled=null;lastProjection='';selected='';editorError='';chosen.clear();status('工程已载入，Build 后即可运行。');}
  function branchSelect(id){
    core.mutateLayout(()=>{meta().graphActiveBranch=id;project();},'正在编辑 '+graph().branches.find(b=>b.id===id).name);
    core.renderProgram();
    const index=graph().branches.findIndex(b=>b.id===id),value=meta().graphResult?.branches[index]?.result;
    if(compiled)core.restoreResult(compiled.builds[index],value||null);
    render();
  }
  byId('cmGraphBranch').onchange=()=>branchSelect(byId('cmGraphBranch').value);
  byId('cmGraphAdd').onclick=()=>edit(g=>{if(g.branches.length>=4)throw Error('可视工程最多包含 4 条接收分支。');let i=1;while(g.branches.some(b=>b.id==='rx'+i))i++;const b=clone(g.branches.find(b=>b.id===active()));b.id='rx'+i;b.name='接收分支 '+i;g.branches.push(b);g.edges=M.connections(g);},'已克隆接收分支。');
  byId('cmGraphRemoveBranch').onclick=()=>edit(g=>{if(g.branches.length<=2)throw Error('保留两条分支即可继续汇合实验。');const id=active();g.branches=g.branches.filter(b=>b.id!==id);g.analyses=g.analyses.filter(a=>!a.source.startsWith(id+'/'));g.merge.inputs=g.branches.slice(0,2).map(b=>b.id);for(const key of Object.keys(g.layout))if(key.startsWith(id+'/')||!M.nodes(g).some(n=>n.key===key))delete g.layout[key];meta().graphActiveBranch=g.branches[0].id;g.edges=M.connections(g);},'已移除接收分支。');
  byId('cmGraphArrange').onclick=()=>{core.mutateLayout(()=>{scratchUI().collapsed={};scratchUI().zoom=1;},'积木已按运行顺序排列。');draw();};
  for(const id of ['cmGraphInputA','cmGraphInputB','cmGraphMode','cmGraphChoice','cmGraphWeightA','cmGraphWeightB'])byId(id).onchange=()=>edit(g=>{
    const inputs=[byId('cmGraphInputA').value,byId('cmGraphInputB').value];if(inputs[0]===inputs[1])throw Error('A、B 选择两条不同的接收分支。');
    g.merge={...g.merge,inputs,mode:byId('cmGraphMode').value,select:Number(byId('cmGraphChoice').value),weights:[Number(byId('cmGraphWeightA').value),Number(byId('cmGraphWeightB').value)]};g.edges=M.connections(g);
  },'汇合参数已更新。');
  async function build(){
    sync();if(editorError)throw Error(editorError);
    if(meta().tools?.length)await ctx.request('workbench-build',{document:ctx.documentValue()});
    compiled=await ctx.request('graph-build',{graph:clone(graph())});
    meta().graph=compiled.graph;project();
    const i=graph().branches.findIndex(b=>b.id===active());core.restoreResult(compiled.builds[i],null);
    status(`🧱 接线通过   ${graph().branches.length} 条分支   ${graph().merge.domain==='llr'?'LLR = log(P0/P1)':'复符号'}   输入版本 ${compiled.input_version.slice(0,12)}`);core.status('可视工程 Build 已通过。');ctx.persist();render();return compiled;
  }
  async function action(fn){core.setBusy(true);status('🌊 正在处理可视工程…');try{await fn();}catch(e){status(e.message);core.status(e.message,true);}finally{core.setBusy(false);render();}}
  byId('cmGraphBuild').onclick=()=>action(build);
  async function run(partial){
    const b=compiled||await build();const value=await ctx.runJob('graph',{graph:clone(graph()),token:b.token,partial});meta().graphResult=value;
    const index=graph().branches.findIndex(x=>x.id===active());core.restoreResult(b.builds[index],value.branches[index].result);ctx.persist();
    status(`✅ ${value.shared_reused?'复用了冻结的共享信道输入':'完成一次发送与信道计算'}   输入 SHA-256 ${value.input_hash}   工程 ${value.graph_token.slice(0,12)}`);
    core.status('可视工程运行完成，已更新分支、汇合与分析结果。');
  }
  byId('cmGraphRun').onclick=()=>action(()=>run(false));byId('cmGraphPartial').onclick=()=>action(()=>run(true));
  for(const [id,fn] of [['cmBuild',()=>action(build)],['cmRun',()=>action(()=>run(false))]])byId(id).addEventListener('click',e=>{if(graph()){e.preventDefault();e.stopImmediatePropagation();fn();}},true);
  function connect(edge){edit(g=>M.connect(g,edge),'已连接端口，Build 检查数据类型与对齐。');}
  byId('cmGraphConnect').onclick=()=>connect({from:byId('cmGraphFrom').value,to:byId('cmGraphTo').value,output:byId('cmGraphOutput').value,input:byId('cmGraphInput').value});
  byId('cmGraphDisconnect').onclick=()=>edit(g=>{g.edges.splice(Number(byId('cmGraphEdge').value),1);},'连接已断开，选择端口可重新接线。');
  byId('cmGraphDelete').onclick=()=>edit(g=>{
    if(chosen.size){M.remove(g,[...chosen]);chosen.clear();selected='';return;}
    const n=M.nodes(g).find(n=>n.key===selected);if(!n||n.kind==='sink'||n.kind==='branch_merge')throw Error('选择普通积木或分析节点进行删除。');
    if(n.lane==='analysis')g.analyses=g.analyses.filter(a=>a.id!==n.key);
    else{const blocks=M.lanes(g).find(([lane])=>lane===n.lane)[1];if(blocks.length<=1)throw Error('每段保留至少一个积木。');blocks.splice(blocks.findIndex(b=>b.id===n.id),1);g.analyses=g.analyses.filter(a=>a.source!==n.key);}
    const keys=new Set(M.nodes(g).map(n=>n.key));for(const key of Object.keys(g.layout))if(!keys.has(key))delete g.layout[key];g.edges=M.connections(g);selected='';
  },'已删除选中积木并连接相邻节点。');
  byId('cmGraphCfarAdd').onclick=()=>edit(g=>{
    const source=M.nodes(g).find(n=>n.key===selected&&n.kind==='rx_isac_ofdm')||M.nodes(g).find(n=>n.kind==='rx_isac_ofdm');if(!source)throw Error('添加 OFDM 通信与测距测速积木后即可连接 CFAR。');
    if(g.analyses.length>=4)throw Error('每个工程最多包含 4 个分析节点。');let i=1;while(g.analyses.some(a=>a.id==='cfar'+i))i++;
    g.analyses.push({id:'cfar'+i,kind:'analysis_cfar2d',source:source.key,params:{training_range:2,training_doppler:4,guard_range:1,guard_doppler:1,pfa:.001,direct_bins:1,cluster_radius:1}});g.edges=M.connections(g);
  },'已连接二维 CFAR 分析端口。');
  byId('cmGraphPython').onclick=()=>action(async()=>{const value=await ctx.request('graph-export',{graph:graph()});core.download(value.filename,value.code,'text/x-python');});
  byId('cmGraphJSON').onclick=()=>core.download('Scratch通信工程.json',JSON.stringify(ctx.documentValue(),null,2),'application/json');
  const table=(heads,rows)=>`<table><thead><tr>${heads.map(v=>`<th>${esc(v)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${esc(typeof v==='number'?Number(v.toPrecision(6)):String(v??'—'))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  function inline(n){
    const specs=get().definitions[n.kind]?.params||{};
    return Object.entries(specs).filter(([,v])=>v.type!=='text').slice(0,2).map(([key,spec])=>{
      const value=n.params[key]??spec.default,data=`data-scratch-param="${esc(key)}" data-scratch-key="${esc(n.key)}" aria-label="${esc(label(n)+' '+spec.label)}"`;
      if(spec.type==='select')return `<label class="cm-scratch-inline">${esc(spec.label)}<select ${data}>${spec.choices.map(v=>`<option value="${esc(String(v))}" ${v===value?'selected':''}>${esc(String(spec.choice_labels?.[v]??v))}</option>`).join('')}</select></label>`;
      if(spec.type==='boolean')return `<label class="cm-scratch-inline"><input ${data} type="checkbox" ${value?'checked':''}>${esc(spec.label)}</label>`;
      return `<label class="cm-scratch-inline">${esc(spec.label)}<input ${data} type="number" value="${value??''}" min="${spec.min??''}" max="${spec.max??''}" step="${spec.type==='integer'?1:'any'}"></label>`;
    }).join('');
  }
  function draw(){
    const g=graph();if(!g)return;const all=M.nodes(g),ui=scratchUI(),stage=byId('cmGraphStage');
    byId('cmBlockCount').textContent=all.length+' 块积木'+(meta().tools?.length?'  '+meta().tools.length+' 个工具':'');
    const card=n=>{
      const def=get().definitions[n.kind],execution=meta().graphResult?.execution.find(e=>e.section===n.lane),state=execution?.executed.includes(n.id)?'executed':execution?.reused.includes(n.id)?'reused':'';
      return `<article class="cm-scratch-block ${selected===n.key?'selected':''} ${chosen.has(n.key)?'checked':''} ${state} ${n.kind==='sink'?'cm-scratch-sink':''}" data-key="${esc(n.key)}" data-lane="${esc(n.lane)}" data-cm-category="${def?.category||'demodulator'}"><div class="cm-scratch-head"><label class="cm-scratch-check"><input type="checkbox" data-graph-check="${esc(n.key)}" aria-label="勾选 ${esc(label(n))}" ${chosen.has(n.key)?'checked':''}></label><button type="button" class="cm-scratch-grip" draggable="${n.kind!=='sink'}" data-scratch-drag="${esc(n.key)}" aria-label="拖动 ${esc(label(n))}">⠿</button><button type="button" class="cm-scratch-title" data-node-title="${esc(n.key)}">${esc(label(n))}</button>${inline(n)}</div>${ui.notes?.[n.key]?`<p class="cm-scratch-note">📝 ${esc(ui.notes[n.key])}</p>`:''}${state==='reused'?'<small class="cm-scratch-reused">本次复用</small>':''}</article>`;
    };
    const lane=(id,blocks)=>{
      const list=blocks.map(b=>all.find(n=>n.key===id+'/'+b.id)),groups=[...(ui.groups||[])];
      if(id===active())for(const group of meta().groups||[])groups.push({id:'old-'+group.id,name:group.name,keys:group.members.map(k=>id+'/'+k)});
      const grouped=new Set();let html='';
      for(const n of list){if(grouped.has(n.key))continue;const at=list.indexOf(n),group=groups.find(x=>x.keys[0]===n.key&&x.keys.every((k,i)=>list[at+i]?.key===k));
        if(group){group.keys.forEach(k=>grouped.add(k));html+=`<details class="cm-scratch-group" data-scratch-collapse="${esc(group.id)}" ${ui.collapsed?.[group.id]?'':'open'}><summary>🧩 ${esc(group.name)} <small>${group.keys.length} 块</small></summary><div>${group.keys.map(k=>card(list.find(v=>v.key===k))).join('')}</div></details>`;}
        else html+=card(n);
      }
      return `<div class="cm-scratch-lane" data-scratch-lane="${esc(id)}">${html}<div class="cm-scratch-insert" data-insert-lane="${esc(id)}" tabindex="0" role="button" aria-label="在${esc(id)}末尾添加积木">＋ 在此拼接</div></div>`;
    };
    stage.innerHTML='<div class="cm-start">🚩 当点击 Run 时</div>'+lane('shared',g.prefix)+`<section class="cm-scratch-parallel" aria-label="并行接收"><header>🧩 并行接收 <strong>${g.branches.length} 路</strong><small>共享本次信道输入</small></header>${g.branches.map((b,i)=>`<details class="cm-scratch-branch" data-scratch-collapse="${b.id}" ${ui.collapsed?.[b.id]?'':'open'}><summary><button type="button" data-branch-edit="${esc(b.id)}" aria-pressed="${active()===b.id}">${esc(b.name)}</button><span>${b.blocks.length} 块积木</span></summary>${lane(b.id,b.blocks)}</details>`).join('')}<footer class="cm-scratch-merge ${selected==='merge'?'selected':''}" data-key="merge"><button type="button" data-node-title="merge">🔗 ${g.merge.domain==='llr'?'LLR':'复符号'} 汇合</button><select data-inline-merge="mode" aria-label="汇合方式"><option value="select" ${g.merge.mode==='select'?'selected':''}>选择一路</option><option value="weighted" ${g.merge.mode==='weighted'?'selected':''}>加权相加</option></select><select data-inline-merge="select" aria-label="选中汇合输入"><option value="0" ${g.merge.select===0?'selected':''}>输入 A</option><option value="1" ${g.merge.select===1?'selected':''}>输入 B</option></select>${g.merge.mode==='weighted'?g.merge.weights.map((v,i)=>`<label>权重 ${i?'B':'A'}<input type="number" data-inline-weight="${i}" aria-label="汇合权重 ${i?'B':'A'}" step="0.1" min="-10" max="10" value="${v}"></label>`).join(''):''}</footer></section>`+lane('tail',g.tail)+(g.analyses.length?`<details class="cm-scratch-analyses" open><summary>🎯 感知分析积木</summary>${g.analyses.map(a=>`<article class="cm-scratch-block" data-key="${esc(a.id)}" data-lane="analysis" data-cm-category="rx_converter"><button type="button" data-node-title="${esc(a.id)}">🎯 二维 CA-CFAR</button><small>${esc(a.source)}</small></article>`).join('')}</details>`:'');
    stage.style.zoom=String(ui.zoom||1);stage.style.width='';stage.style.height='';
    stage.querySelectorAll('details[data-scratch-collapse]').forEach(d=>d.ontoggle=()=>{const key=d.dataset.scratchCollapse,value=!d.open;if(!!scratchUI().collapsed?.[key]===value)return;core.mutateLayout(()=>{const u=scratchUI();(u.collapsed||(u.collapsed={}))[key]=value;},'已保存积木折叠状态。');});
    const note=scratchUI().notes?.[selected]||'';notes.hidden=!selected;if(document.activeElement!==byId('cmGraphNoteText'))byId('cmGraphNoteText').value=note;
    core.root.dispatchEvent(new Event('cm-scratch-render'));
  }
  function locateSelected(key){const card=byId('cmGraphStage').querySelector(`[data-key="${CSS.escape(key)}"]`);for(let e=card?.parentElement;e&&e!==byId('cmGraphStage');e=e.parentElement)if(e.tagName==='DETAILS')e.open=true;card?.scrollIntoView({block:'nearest',inline:'nearest'});}
  function select(key,observeOnly=false){selected=key;const n=M.nodes(graph()).find(n=>n.key===key);if(!n)return;
    if(observeOnly){draw();locateSelected(key);return;}
    if(n.kind==='branch_merge'&&compiled&&meta().graphResult){const r=meta().graphResult,index=compiled.builds.findIndex(b=>b.token===r.merged_result.token);if(index>=0){branchSelect(graph().branches[index].id);core.restoreResult(compiled.builds[index],r.merged_result);ctx.locateObservation('merge-output');}}
    if(graph().branches.some(b=>b.id===n.lane)&&active()!==n.lane)branchSelect(n.lane);
    if(n.id&&n.lane!=='analysis'){core.selectBlock(n.id);ctx.layout.edit();}
    if(n.lane==='analysis'){detail.open=true;byId('cmGraphCfar').open=true;byId('cmGraphCfarNode').value=key;renderCfar();ctx.layout.showAnalysis('spatial');}
    draw();locateSelected(key);
  }
  const chosenKeys=()=>chosen.size?[...chosen]:selected?[selected]:[];
  function copy(){clipboard=M.nodes(graph()).filter(n=>chosenKeys().includes(n.key)&&n.params&&n.kind!=='sink'&&n.lane!=='analysis').map(n=>({id:n.id,kind:n.kind,params:clone(n.params)}));status(`已复制 ${clipboard.length} 块积木。`);}
  function insertTarget(){const n=M.nodes(graph()).find(n=>n.key===selected),id=n&&M.lanes(graph()).some(([lane])=>lane===n.lane)?n.lane:active(),blocks=M.lane(graph(),id),at=n?blocks.findIndex(b=>b.id===n.id)+1:blocks.length;return {id,index:Math.max(0,Math.min(at,blocks.at(-1)?.kind==='sink'?blocks.length-1:blocks.length))};}
  function insert(kind,lane,index){edit(g=>{const blocks=M.lane(g,lane),def=get().definitions[kind];if(!def||kind==='sink')throw Error('请选择信号处理积木。');if(M.projection(g,active()).blocks.length>=get().catalog.limits.max_blocks)throw Error('当前链路已达到积木数量上限。');const id=core.uid();blocks.splice(Math.min(index,blocks.at(-1)?.kind==='sink'?blocks.length-1:blocks.length),0,{id,kind,params:Object.fromEntries(Object.entries(def.params).map(([k,s])=>[k,s.default]))});selected=lane+'/'+id;g.edges=M.connections(g);},'积木已拼接，可点击编辑参数。');}
  byId('cmGraphCopy').onclick=copy;
  byId('cmGraphCut').onclick=()=>{copy();edit(g=>M.remove(g,chosenKeys()),'已剪切选中积木。');chosen.clear();selected='';draw();};
  byId('cmGraphPaste').onclick=()=>{if(!clipboard.length)return;const target=insertTarget();edit(g=>{const blocks=M.lane(g,target.id),items=clipboard.map(b=>({...clone(b),id:core.uid()}));blocks.splice(target.index,0,...items);chosen=new Set(items.map(b=>target.id+'/'+b.id));selected=[...chosen][0];g.edges=M.connections(g);},'已粘贴独立的积木副本。');};
  byId('cmGraphSelectAll').onclick=()=>{chosen=new Set(M.nodes(graph()).filter(n=>n.id&&n.kind!=='sink'&&n.lane!=='analysis').map(n=>n.key));draw();};
  byId('cmGraphGroup').onclick=()=>{const keys=chosenKeys(),nodes=M.nodes(graph()).filter(n=>keys.includes(n.key));if(!nodes.length||nodes.some(n=>n.lane!==nodes[0].lane||n.kind==='sink')){status('选择同一序列中的相邻处理积木。');return;}const blocks=M.lane(graph(),nodes[0].lane),indices=nodes.map(n=>blocks.findIndex(b=>b.id===n.id));if(indices.some((v,i)=>v!==indices[0]+i)){status('选择相邻积木后即可封装。');return;}core.mutateLayout(()=>{const u=scratchUI();u.groups=(u.groups||[]).filter(g=>!g.keys.some(k=>keys.includes(k)));u.groups.push({id:core.uid(),name:byId('cmGraphGroupName').value.trim()||'组合积木',keys:nodes.map(n=>n.key)});},'已封装组合积木。');draw();};
  byId('cmGraphUnpack').onclick=()=>{core.mutateLayout(()=>{scratchUI().groups=(scratchUI().groups||[]).filter(g=>!g.keys.some(k=>chosenKeys().includes(k)));},'已展开所选组合。');draw();};
  byId('cmGraphNote').onclick=()=>{if(!selected){status('先选择需要注释的积木。');return;}notes.hidden=false;settings.open=true;byId('cmGraphNoteText').focus();};
  byId('cmGraphNoteText').onchange=e=>{if(!selected)return;const key=selected,value=e.target.value;core.mutateLayout(()=>{const u=scratchUI();(u.notes||(u.notes={}))[key]=value;},'注释已保存。');draw();};
  byId('cmGraphStage').onclick=e=>{
    const branch=e.target.closest('[data-branch-edit]'),title=e.target.closest('[data-node-title]'),target=e.target.closest('[data-insert-lane]');
    if(branch){branchSelect(branch.dataset.branchEdit);e.preventDefault();}
    else if(title)select(title.dataset.nodeTitle);
    else if(target){const id=target.dataset.insertLane;if(graph().branches.some(b=>b.id===id))branchSelect(id);selected=id+'/'+M.lane(graph(),id).at(-1).id;status('已选中插入位置，从左侧选择积木即可拼接。');draw();}
  };
  byId('cmGraphStage').onchange=e=>{
    const el=e.target;
    if(el.dataset.graphCheck){if(el.checked)chosen.add(el.dataset.graphCheck);else chosen.delete(el.dataset.graphCheck);el.closest('article').classList.toggle('checked',el.checked);return;}
    if(el.dataset.scratchParam){if(!el.checkValidity()){el.reportValidity();return;}const n=M.nodes(graph()).find(n=>n.key===el.dataset.scratchKey),spec=get().definitions[n.kind].params[el.dataset.scratchParam],value=spec.type==='boolean'?el.checked:spec.type==='select'?spec.choices.find(v=>String(v)===el.value):Number(el.value);edit(g=>{M.nodes(g).find(v=>v.key===n.key).params[el.dataset.scratchParam]=value;},'积木参数已更新。');return;}
    if(el.dataset.inlineMerge){edit(g=>{g.merge[el.dataset.inlineMerge]=el.dataset.inlineMerge==='select'?Number(el.value):el.value;},'汇合参数已更新。');return;}
    if(el.dataset.inlineWeight!==undefined)edit(g=>{g.merge.weights[Number(el.dataset.inlineWeight)]=Number(el.value);},'汇合权重已更新。');
  };
  byId('cmGraphStage').ondragstart=e=>{const grip=e.target.closest('[data-scratch-drag]');if(!grip||get().busy)return;const key=grip.dataset.scratchDrag;drag={keys:chosen.has(key)?[...chosen]:[key]};if(e.shiftKey){const n=M.nodes(graph()).find(n=>n.key===key),blocks=M.lane(graph(),n.lane);drag.keys=blocks.slice(blocks.findIndex(b=>b.id===n.id)).filter(b=>b.kind!=='sink').map(b=>n.lane+'/'+b.id);}e.dataTransfer.setData('application/x-ocean-graph',JSON.stringify(drag));e.dataTransfer.effectAllowed='copyMove';e.stopPropagation();};
  const clearDrop=()=>byId('cmGraphStage').querySelectorAll('.cm-drop-before,.cm-drop-after').forEach(e=>e.classList.remove('cm-drop-before','cm-drop-after'));
  const dropTarget=e=>{const card=e.target.closest('[data-key][data-lane]'),lane=e.target.closest('[data-scratch-lane]');if(!lane)return null;const id=lane.dataset.scratchLane,blocks=M.lane(graph(),id);let index=blocks.length;if(card){index=blocks.findIndex(b=>id+'/'+b.id===card.dataset.key);if(e.clientY>=card.getBoundingClientRect().top+card.getBoundingClientRect().height/2&&blocks[index]?.kind!=='sink')index++;}return {id,index,card};};
  byId('cmGraphStage').ondragover=e=>{const types=[...e.dataTransfer.types];if(!types.some(t=>['application/x-ocean-graph','application/x-ocean-communication'].includes(t)))return;const target=dropTarget(e);if(!target||get().busy)return;e.preventDefault();e.stopPropagation();clearDrop();if(target.card)target.card.classList.add(target.index===M.lane(graph(),target.id).findIndex(b=>target.id+'/'+b.id===target.card.dataset.key)?'cm-drop-before':'cm-drop-after');e.dataTransfer.dropEffect=types.includes('application/x-ocean-graph')&&!e.ctrlKey?'move':'copy';};
  byId('cmGraphStage').ondrop=e=>{const graphData=e.dataTransfer.getData('application/x-ocean-graph'),paletteData=e.dataTransfer.getData('application/x-ocean-communication');if(!graphData&&!paletteData)return;const target=dropTarget(e);if(!target||get().busy)return;e.preventDefault();e.stopPropagation();clearDrop();if(graphData){const data=JSON.parse(graphData);edit(g=>{chosen=new Set(M.reorder(g,data.keys,target.id,target.index,{copy:e.ctrlKey,uid:core.uid}));selected=[...chosen][0];},e.ctrlKey?'积木已复制并拼接。':'积木已移动并拼接。');}else if(paletteData){const data=JSON.parse(paletteData);if(data.kind)insert(data.kind,target.id,target.index);}drag=null;};
  byId('cmGraphStage').ondragend=()=>{drag=null;clearDrop();};
  byId('cmLocate').addEventListener('click',e=>{if(graph()){e.stopImmediatePropagation();const target=selected||active()+'/'+M.lane(graph(),active())[0].id;select(target);}},true);
  core.root.addEventListener('click',e=>{const b=e.target.closest('[data-cm-kind]');if(!graph()||!b||get().busy)return;e.preventDefault();e.stopImmediatePropagation();const target=insertTarget();insert(b.dataset.cmKind,target.id,target.index);},true);
  core.root.addEventListener('keydown',e=>{if(!graph()||get().busy||e.target.matches('input,textarea,select')||e.target.isContentEditable)return;if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='c'){e.preventDefault();copy();}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='v'){e.preventDefault();byId('cmGraphPaste').click();}if(e.key==='Delete'&&chosenKeys().length){e.preventDefault();byId('cmGraphDelete').click();}});
  const scroller=viewport;
  scroller.onpointerdown=e=>{if(!graph()||e.button!==1&&!(e.button===0&&e.target===byId('cmGraphStage')))return;pointerPan={x:e.clientX,y:e.clientY,left:scroller.scrollLeft,top:scroller.scrollTop};scroller.setPointerCapture(e.pointerId);e.preventDefault();};
  scroller.onpointermove=e=>{if(!pointerPan)return;scroller.scrollLeft=pointerPan.left-e.clientX+pointerPan.x;scroller.scrollTop=pointerPan.top-e.clientY+pointerPan.y;};
  scroller.onpointerup=scroller.onpointercancel=()=>{pointerPan=null;};

  function moveSelection(direction){
    const keys=chosenKeys(),items=M.nodes(graph()).filter(n=>keys.includes(n.key));
    if(!items.length||items.some(n=>n.lane!==items[0].lane)){status('选择同一序列中的积木后移动。');return;}
    const lane=items[0].lane,blocks=M.lane(graph(),lane),indices=items.map(n=>blocks.findIndex(b=>b.id===n.id)),index=direction<0?Math.min(...indices)-1:Math.max(...indices)+2;
    edit(g=>{chosen=new Set(M.reorder(g,keys,lane,index,{uid:core.uid}));selected=[...chosen][0];},'选中积木已移动。');
  }
  function renderCfar(){
    const list=graph()?.analyses||[],old=byId('cmGraphCfarNode').value;
    byId('cmGraphCfarNode').innerHTML=list.map(a=>`<option value="${a.id}">${esc(a.id+'   '+a.source)}</option>`).join('');if(list.some(a=>a.id===old))byId('cmGraphCfarNode').value=old;
    const a=list.find(a=>a.id===byId('cmGraphCfarNode').value),labels={training_range:'距离训练宽度',training_doppler:'速度训练宽度',guard_range:'距离保护宽度',guard_doppler:'速度保护宽度',pfa:'目标虚警概率',direct_bins:'直达排除列数',cluster_radius:'相邻检测聚类半径'};
    byId('cmGraphCfarControls').innerHTML=a?Object.entries(a.params).map(([key,value])=>`<label>${labels[key]}<input type="number" data-cfar-param="${key}" value="${value}" step="${key==='pfa'?'0.0001':'1'}" min="${key==='pfa'?'0.000001':'0'}"></label>`).join(''):'';
    byId('cmGraphCfarControls').querySelectorAll('input').forEach(e=>e.onchange=()=>edit(g=>{g.analyses.find(v=>v.id===a.id).params[e.dataset.cfarParam]=Number(e.value);},'CFAR 参数已更新；局部重跑将复用接收分支。'));
    drawCfar();
  }
  function drawCfar(){
    const data=meta().graphResult?.analyses.find(a=>a.id===byId('cmGraphCfarNode').value),canvas=byId('cmGraphCfarCanvas'),width=Math.max(250,canvas.clientWidth||800),height=300,dpr=Math.min(2,devicePixelRatio||1);canvas.width=width*dpr;canvas.height=height*dpr;const x=canvas.getContext('2d');x.scale(dpr,dpr);x.fillStyle='#f3f9fe';x.fillRect(0,0,width,height);x.font='11px sans-serif';x.fillStyle='#456981';
    if(!data){x.fillText('运行后显示实测距离—速度谱与 CFAR 检测。',15,30);byId('cmGraphCfarResult').innerHTML='';return;}
    const matrix=data[byId('cmGraphCfarView').value],h=matrix.length,w=matrix[0].length,left=55,top=15,pw=width-70,ph=240,valid=matrix.flat().filter(v=>v!==null),max=10*Math.log10(Math.max(...valid,1e-20)),low=max-60;
    matrix.forEach((row,i)=>row.forEach((v,j)=>{const z=v===null?0:Math.max(0,Math.min(1,(10*Math.log10(Math.max(v,1e-20))-low)/60));x.fillStyle=v===null?'#d6e0e9':`hsl(${219-z*62} ${45+z*30}% ${96-z*66}%)`;x.fillRect(left+j*pw/w,top+(h-i-1)*ph/h,pw/w+1,ph/h+1);}));
    const region=data.valid_region;x.strokeStyle='#dbc373';x.lineWidth=1.5;x.strokeRect(left+region.column[0]*pw/w,top+(h-region.row[1])*ph/h,(region.column[1]-region.column[0])*pw/w,(region.row[1]-region.row[0])*ph/h);
    x.strokeStyle='#fff1a4';x.lineWidth=2;for(const p of data.detections){const xx=left+(p.column+.5)*pw/w,yy=top+(h-p.row-.5)*ph/h;x.beginPath();x.arc(xx,yy,5,0,Math.PI*2);x.stroke();}
    x.fillStyle='#395675';x.fillText('速度 m/s',3,12);x.fillText('距离 m',width-60,295);
    for(let i=0;i<5;i++){const col=Math.round(i*(w-1)/4),row=Math.round(i*(h-1)/4);x.fillText(Math.round(data.range_axis_m[col]),left+col*pw/w,275);x.fillText(Math.round(data.velocity_axis_mps[row]),2,top+(h-row-.5)*ph/h);}
    byId('cmGraphCfarResult').innerHTML=`<p>🎯 ${data.detections.length} 个聚类峰   ${data.tested_cells} 个有效检测单元   超门限比例 ${data.crossing_fraction.toExponential(3)}   Pfa ${data.settings.pfa}   黄色框为完整训练窗区域</p>`+table(['距离 / m','速度 / m/s','功率','门限','局部噪声','聚类单元'],data.detections.map(p=>[p.range_m,p.velocity_mps,p.power,p.threshold,p.noise,p.cluster_cells]));
  }
  byId('cmGraphCfarNode').onchange=renderCfar;byId('cmGraphCfarView').onchange=drawCfar;byId('cmGraphCfar').ontoggle=drawCfar;window.addEventListener('resize',()=>{if(graph())drawCfar();});
  function render(){
    const g=graph();host.hidden=!g;byId('cmProgram').hidden=!!g;core.root.classList.toggle('cm-has-graph',!!g);byId('cmGraphWorkspace').hidden=!g;byId('cmGraphLeave').disabled=!g||get().busy;byId('cmGraphPartial').hidden=!g;canvasTools.hidden=!g;notes.hidden=!g||!selected;advanced.hidden=!g;
    menu.querySelectorAll('.cm-graph-toolbar').forEach((row,i)=>row.hidden=i>0&&!g);detail.hidden=!g;
    if(!g){chosen.clear();return;}
    if(!lastProjection)lastProjection=JSON.stringify(get().program);
    const branchOptions=g.branches.map(b=>`<option value="${b.id}">${esc(b.name)}</option>`).join('');
    for(const id of ['cmGraphBranch','cmGraphInputA','cmGraphInputB'])byId(id).innerHTML=branchOptions;
    byId('cmGraphBranch').value=active();byId('cmGraphInputA').value=g.merge.inputs[0];byId('cmGraphInputB').value=g.merge.inputs[1];byId('cmGraphMode').value=g.merge.mode;byId('cmGraphChoice').value=g.merge.select;byId('cmGraphWeightA').value=g.merge.weights[0];byId('cmGraphWeightB').value=g.merge.weights[1];
    const all=M.nodes(g),options=all.map(n=>`<option value="${esc(n.key)}">${esc(n.lane+'   '+label(n))}</option>`).join('');
    for(const id of ['cmGraphFrom','cmGraphTo']){const old=byId(id).value;byId(id).innerHTML=options;if(all.some(n=>n.key===old))byId(id).value=old;}
    const old=byId('cmGraphEdge').value;byId('cmGraphEdge').innerHTML=g.edges.map((e,i)=>`<option value="${i}">${esc(e.from+' ['+e.output+'] → '+e.to+' ['+e.input+']')}</option>`).join('');if(Number(old)<g.edges.length)byId('cmGraphEdge').value=old;
    const r=meta().graphResult;byId('cmGraphResults').innerHTML=r?table(['接收路径','BER','EVM / %'],[...r.branches.map(b=>[b.name,b.result.metrics.ber,b.result.metrics.evm_percent]),['🔗 汇合结果',r.merged_result.metrics.ber,r.merged_result.metrics.evm_percent]])+table(['执行区段','本次执行积木数','复用积木数'],r.execution.map(e=>[e.section,e.executed.length,e.reused.length]))+`<p class="cm-graph-status">输入 ${esc(r.input_hash)}   共享采样接收路径的加权效果按实测 BER / EVM 比较</p>`:'';
    draw();renderCfar();buttons(get().busy);
  }
  function buttons(busy){for(const node of [host,settings,detail])node.querySelectorAll('button,input,select,textarea').forEach(e=>e.disabled=busy);byId('cmGraphPartial').disabled=busy;byId('cmGraphLeave').disabled=busy||!graph();if(graph()){byId('cmGraphAdd').disabled=busy||graph().branches.length>=4;byId('cmGraphRemoveBranch').disabled=busy||graph().branches.length<=2;}}
  function restoreEdit(preserve=false){
    if(!preserve)loadState();else{lastProjection=JSON.stringify(get().program);if(compiled){const index=graph().branches.findIndex(b=>b.id===active());core.restoreResult(compiled.builds[index],meta().graphResult?.branches[index]?.result||null);}}
    render();
  }
  function acceptBuild(value){compiled=value;meta().graph=value.graph;lastProjection=JSON.stringify(get().program);const r=meta().graphResult;if(r)status(`✅ ${r.shared_reused?'复用了冻结的共享信道输入':'完成一次发送与信道计算'}   输入 SHA-256 ${r.input_hash}   工程 ${r.graph_token.slice(0,12)}`);}
  return {render,buttons,invalidate,replaceProgram,loadState,restoreEdit,sync,build,run,graph,branchSelect,select,selectedKey:()=>selected,moveSelection,getBuild:()=>compiled,acceptBuild,onResult:()=>{},active:()=>!!graph()};
};
