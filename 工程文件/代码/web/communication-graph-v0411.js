/* Editable one-fork signal graph, frozen receiver runs and measured CFAR. */
window.createCommunicationGraphV0411=function(core,ctx){
  'use strict';
  const {byId,esc,get,clone}=core,M=window.CommunicationGraphModel;
  const host=document.createElement('details');host.id='cmGraph411';host.className='cm-graph-editor';
  host.innerHTML=`<summary>🪸 可视接线与分支实验 <small>v0.4.11</small></summary><div class="cm-graph-content">
    <div class="cm-graph-toolbar"><button type="button" id="cmGraphDemo">🧪 NLMS / DFE 示例</button><button type="button" id="cmGraphSenseDemo">🛰️ 多目标 CFAR 示例</button><button type="button" id="cmGraphConvert">🔗 转为可视工程</button><button type="button" id="cmGraphLeave">📋 保留当前线性链路</button></div>
    <div id="cmGraphWorkspace" hidden><div class="cm-graph-toolbar"><label>🎛️ 编辑接收分支<select id="cmGraphBranch"></select></label><button type="button" id="cmGraphAdd">＋ 克隆分支</button><button type="button" id="cmGraphRemoveBranch">移除分支</button><button type="button" id="cmGraphArrange">🧭 自动布局</button><button type="button" id="cmGraphBuild">🧱 Build 接线</button><button type="button" id="cmGraphRun">▶️ 完整运行</button><button type="button" id="cmGraphPartial">⚡ 局部重跑</button></div>
    <div class="cm-graph-toolbar"><label>汇合输入 A<select id="cmGraphInputA"></select></label><label>汇合输入 B<select id="cmGraphInputB"></select></label><label>汇合方式<select id="cmGraphMode"><option value="select">选择一路</option><option value="weighted">加权相加</option></select></label><label>选中输入<select id="cmGraphChoice"><option value="0">A</option><option value="1">B</option></select></label><label>A 权重<input id="cmGraphWeightA" type="number" step="0.1" min="-10" max="10"></label><label>B 权重<input id="cmGraphWeightB" type="number" step="0.1" min="-10" max="10"></label></div>
    <p class="cm-graph-status" id="cmGraphHelp">拖动标题排列积木；点击输出端口，再点击输入端口完成接线。选择积木后在原参数面板编辑。虚线边框表示本次复用。</p>
    <div class="cm-graph-scroll" tabindex="0" aria-label="可视接线画布，可横向滚动"><div id="cmGraphStage" class="cm-graph-stage"></div></div>
    <div class="cm-graph-toolbar"><label>连接起点<select id="cmGraphFrom"></select></label><label>输出端口<select id="cmGraphOutput"><option value="out">主输出</option><option value="power">距离—速度功率</option></select></label><label>连接终点<select id="cmGraphTo"></select></label><label>输入端口<select id="cmGraphInput"><option value="in">主输入</option><option value="a">汇合 A</option><option value="b">汇合 B</option></select></label><button type="button" id="cmGraphConnect">🔌 连接</button></div>
    <div class="cm-graph-toolbar"><label>已有连接<select id="cmGraphEdge"></select></label><button type="button" id="cmGraphDisconnect">断开连接</button><button type="button" id="cmGraphDelete">删除选中积木</button><button type="button" id="cmGraphCfarAdd">🎯 添加 CFAR 分析</button><button type="button" id="cmGraphPython">🐍 导出 Python</button><button type="button" id="cmGraphJSON">📦 完整工程 JSON</button></div>
    <div id="cmGraphResults" class="cm-graph-results"></div><details id="cmGraphCfar" class="cm-graph-cfar"><summary>🎯 二维 CA-CFAR 检测与门限</summary><label>分析节点<select id="cmGraphCfarNode"></select></label><div id="cmGraphCfarControls" class="cm-graph-cfar-controls"></div><label>热图<select id="cmGraphCfarView"><option value="power">接收功率 / dB</option><option value="threshold">CFAR 门限 / dB</option><option value="noise">局部噪声 / dB</option></select></label><canvas id="cmGraphCfarCanvas" aria-label="距离速度谱、CFAR 检测标记及有效边界"></canvas><div id="cmGraphCfarResult" class="cm-graph-results"></div></details>
    </div><p id="cmGraphStatus" class="cm-graph-status" role="status">从均衡对比或多目标通感实验开始，也可转换现有接收分支。</p></div>`;
  byId('cmForm').after(host);
  let compiled=null,lastProjection='',selected='',pending=null,drag=null,editorError='';
  const meta=()=>ctx.meta(),graph=()=>meta().graph;
  const status=t=>byId('cmGraphStatus').textContent=t;
  const label=n=>n.kind==='branch_merge'?'🔗 '+(graph().merge.domain==='llr'?'LLR':'复符号')+' 双输入汇合':n.kind==='analysis_cfar2d'?'🎯 二维 CA-CFAR':get().definitions[n.kind]?.label||n.kind;
  const active=()=>meta().graphActiveBranch||graph()?.branches[0]?.id;
  function project(){const p=M.projection(graph(),active());Object.assign(get().program,p);lastProjection=JSON.stringify(p);}
  function edit(fn,message,layout=false){
    try{const g=clone(graph());fn(g);(layout?core.mutateLayout:core.mutate)(()=>{meta().graph=g;if(!layout)project();},message);render();status(message);}
    catch(e){render();status(e.message);}
  }
  function install(g){core.mutate(()=>{meta().graph=g;meta().graphActiveBranch=g.branches[0].id;meta().branches=[];meta().groups=[];meta().graphResult=null;meta().name='可视接线实验';project();},'可视工程已载入；可编辑参数并 Build / Run。');byId('cmGraphOutput').value='out';byId('cmGraphInput').value='in';host.open=true;render();status('可视工程已载入；可编辑参数并 Build / Run。');}
  async function load(payload){core.setBusy(true);try{const v=await ctx.request('graph-create',payload);core.setBusy(false);install(v.graph);}catch(e){status(e.message);}finally{core.setBusy(false);}}
  byId('cmGraphDemo').onclick=()=>load({demo:'equalizer'});
  byId('cmGraphSenseDemo').onclick=()=>load({demo:'sensing'});
  byId('cmGraphConvert').onclick=()=>{ctx.syncBranches();const branches=meta().branches||[],programs=branches.length>1?branches.map(b=>clone(b.program)):[clone(get().program),clone(get().program)];const soft=programs.every(p=>p.blocks.some(b=>b.kind.startsWith('soft_')));load({programs,names:branches.map(b=>b.name),domain:soft?'llr':'symbols'});};
  byId('cmGraphLeave').onclick=()=>core.mutate(()=>{delete meta().graph;delete meta().graphResult;compiled=null;lastProjection='';},'已保留当前接收分支的完整线性链路。');
  function sync(){
    if(!graph())return;const p=JSON.stringify(get().program);if(p===lastProjection)return;
    if(!lastProjection){lastProjection=p;return;}
    try{const g=M.absorb(clone(graph()),get().program,active(),get().definitions);meta().graph=g;lastProjection=p;editorError='';}
    catch(e){editorError=e.message;status(e.message);}
  }
  function invalidate(){sync();compiled=null;meta().graphResult=null;render();}
  function replaceProgram(){delete meta().graph;delete meta().graphResult;compiled=null;lastProjection='';selected='';}
  function loadState(){compiled=null;lastProjection='';selected='';editorError='';}
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
  byId('cmGraphArrange').onclick=()=>edit(g=>{g.layout=M.arrange(g);},'已自动排列积木。',true);
  for(const id of ['cmGraphInputA','cmGraphInputB','cmGraphMode','cmGraphChoice','cmGraphWeightA','cmGraphWeightB'])byId(id).onchange=()=>edit(g=>{
    const inputs=[byId('cmGraphInputA').value,byId('cmGraphInputB').value];if(inputs[0]===inputs[1])throw Error('A、B 选择两条不同的接收分支。');
    g.merge={...g.merge,inputs,mode:byId('cmGraphMode').value,select:Number(byId('cmGraphChoice').value),weights:[Number(byId('cmGraphWeightA').value),Number(byId('cmGraphWeightB').value)]};g.edges=M.connections(g);
  },'汇合参数已更新。');
  async function build(){
    sync();if(editorError)throw Error(editorError);
    compiled=await ctx.request('graph-build',{graph:clone(graph())});
    meta().graph=compiled.graph;project();
    const i=graph().branches.findIndex(b=>b.id===active());core.restoreResult(compiled.builds[i],null);
    status(`🧱 接线通过 · ${graph().branches.length} 条分支 · ${graph().merge.domain==='llr'?'LLR = log(P0/P1)':'复符号'} · 输入版本 ${compiled.input_version.slice(0,12)}`);core.status('可视工程 Build 已通过。');ctx.persist();render();return compiled;
  }
  async function action(fn){core.setBusy(true);status('🌊 正在处理可视工程…');try{await fn();}catch(e){status(e.message);core.status(e.message,true);}finally{core.setBusy(false);render();}}
  byId('cmGraphBuild').onclick=()=>action(build);
  async function run(partial){
    const b=compiled||await build();const value=await ctx.runJob('graph',{graph:clone(graph()),token:b.token,partial});meta().graphResult=value;
    const index=graph().branches.findIndex(x=>x.id===active());core.restoreResult(b.builds[index],value.branches[index].result);ctx.persist();
    status(`✅ ${value.shared_reused?'复用了冻结的共享信道输入':'完成一次发送与信道计算'} · 输入 SHA-256 ${value.input_hash} · 工程 ${value.graph_token.slice(0,12)}`);
    core.status('可视工程运行完成，已更新分支、汇合与分析结果。');
  }
  byId('cmGraphRun').onclick=()=>action(()=>run(false));byId('cmGraphPartial').onclick=()=>action(()=>run(true));
  for(const [id,fn] of [['cmBuild',()=>action(build)],['cmRun',()=>action(()=>run(false))]])byId(id).addEventListener('click',e=>{if(graph()){e.preventDefault();e.stopImmediatePropagation();fn();}},true);
  function connect(edge){edit(g=>M.connect(g,edge),'已连接端口，Build 检查数据类型与对齐。');pending=null;}
  byId('cmGraphConnect').onclick=()=>connect({from:byId('cmGraphFrom').value,to:byId('cmGraphTo').value,output:byId('cmGraphOutput').value,input:byId('cmGraphInput').value});
  byId('cmGraphDisconnect').onclick=()=>edit(g=>{g.edges.splice(Number(byId('cmGraphEdge').value),1);},'连接已断开，选择端口可重新接线。');
  byId('cmGraphDelete').onclick=()=>edit(g=>{
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
  byId('cmGraphJSON').onclick=()=>core.download('可视接线工程.json',JSON.stringify(ctx.documentValue(),null,2),'application/json');
  const table=(heads,rows)=>`<table><thead><tr>${heads.map(v=>`<th>${esc(v)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${esc(typeof v==='number'?Number(v.toPrecision(6)):String(v??'—'))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  function draw(){
    const g=graph();if(!g)return;const all=M.nodes(g),layout={...M.arrange(g),...g.layout};
    const width=Math.max(900,...Object.values(layout).map(p=>p.x+230)),height=Math.max(500,...Object.values(layout).map(p=>p.y+130));
    const stage=byId('cmGraphStage');stage.style.width=width+'px';stage.style.height=height+'px';
    const line=(e,i)=>{const a=layout[e.from],b=layout[e.to];if(!a||!b)return '';const x1=a.x+102,y1=a.y+94,x2=b.x+(e.input==='a'?55:e.input==='b'?150:102),y2=b.y;
      return `<path class="cm-graph-edge ${e.output==='power'?'analysis':''}" data-graph-edge="${i}" d="M${x1},${y1} C${x1},${y1+45} ${x2},${y2-45} ${x2},${y2}" marker-end="url(#cmGraphArrow)"/>`;};
    stage.innerHTML=`<svg class="cm-graph-svg" width="${width}" height="${height}" aria-label="信号连接"><defs><marker id="cmGraphArrow" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#6894af"/></marker></defs>${g.edges.map(line).join('')}</svg>`+all.map(n=>{
      const p=layout[n.key],port=compiled?.ports[n.key],executed=meta().graphResult?.execution.find(e=>e.section===n.lane),state=executed?.executed.includes(n.id)?'executed':executed?.reused.includes(n.id)?'reused':'';
      const inlet=n.lane==='merge'?['a','b']:n.lane==='shared'&&n.id===g.prefix[0].id?[]:['in'];
      const outlets=n.kind==='sink'||n.lane==='analysis'?[]:n.kind==='rx_isac_ofdm'?['out','power']:['out'];
      const portButton=(name,direction)=>`<button type="button" class="cm-graph-port" data-graph-port="${name}" data-direction="${direction}" data-node="${esc(n.key)}" aria-label="${esc(label(n))} ${direction==='out'?'输出':'输入'} ${name}">${direction==='out'?'● '+(name==='power'?'功率':'输出'):(name==='in'?'输入':name.toUpperCase())+' ●'}</button>`;
      return `<div class="cm-graph-node ${selected===n.key?'selected':''} ${state}" data-key="${esc(n.key)}" data-lane="${n.lane}" style="left:${p.x}px;top:${p.y}px"><button type="button" class="cm-graph-title" data-node-title="${esc(n.key)}">${esc(label(n))}</button><small>${esc(n.lane==='shared'?'🌊 共享前段':n.lane==='tail'?'📺 公共尾段':g.branches.find(b=>b.id===n.lane)?.name||'分析与汇合')}${port?' · '+esc(port.output)+' · '+port.count:''}</small><div class="cm-graph-ports">${inlet.map(v=>portButton(v,'in')).join('')}${outlets.map(v=>portButton(v,'out')).join('')}</div></div>`;
    }).join('');
    // Draw from the actual clickable ports, including both merge inputs.
    const origin=stage.getBoundingClientRect(),portElements=[...stage.querySelectorAll('[data-graph-port]')];
    g.edges.forEach((e,i)=>{
      const start=portElements.find(p=>p.dataset.node===e.from&&p.dataset.direction==='out'&&p.dataset.graphPort===e.output),end=portElements.find(p=>p.dataset.node===e.to&&p.dataset.direction==='in'&&p.dataset.graphPort===e.input);
      if(!start||!end)return;const a=start.getBoundingClientRect(),b=end.getBoundingClientRect(),x1=a.right-origin.left,y1=(a.top+a.bottom)/2-origin.top,x2=b.left-origin.left,y2=(b.top+b.bottom)/2-origin.top;
      const bend=Math.max(30,Math.min(100,Math.abs(x2-x1)/2));stage.querySelector(`[data-graph-edge="${i}"]`).setAttribute('d',`M${x1},${y1} C${x1+bend},${y1} ${x2-bend},${y2} ${x2},${y2}`);
    });
  }
  function select(key){selected=key;const n=M.nodes(graph()).find(n=>n.key===key);if(!n)return;
    if(n.kind==='branch_merge'&&compiled&&meta().graphResult){const r=meta().graphResult,index=compiled.builds.findIndex(b=>b.token===r.merged_result.token);if(index>=0){branchSelect(graph().branches[index].id);core.restoreResult(compiled.builds[index],r.merged_result);ctx.locateObservation('merge-output');}}
    if(graph().branches.some(b=>b.id===n.lane)&&active()!==n.lane)branchSelect(n.lane);
    if(n.id&&n.lane!=='analysis'){core.selectBlock(n.id);if(Object.keys(get().definitions[n.kind]?.params||{}).length)ctx.layout.edit(true);}
    if(n.lane==='analysis'){byId('cmGraphCfar').open=true;byId('cmGraphCfarNode').value=key;renderCfar();}
    draw();
  }
  byId('cmGraphStage').onclick=e=>{
    const port=e.target.closest('[data-graph-port]'),title=e.target.closest('[data-node-title]'),edge=e.target.closest('[data-graph-edge]');
    if(port){const key=port.dataset.node;if(port.dataset.direction==='out'){pending={from:key,output:port.dataset.graphPort};byId('cmGraphStage').querySelectorAll('.pending').forEach(p=>p.classList.remove('pending'));port.classList.add('pending');status('已选择输出，点击目标输入端口完成连接。');}
      else if(pending){connect({...pending,to:key,input:port.dataset.graphPort});}else status('先选择一个输出端口。');}
    else if(title)select(title.dataset.nodeTitle);else if(edge){byId('cmGraphEdge').value=edge.dataset.graphEdge;status('已选择连接，可点击断开连接。');}
  };
  byId('cmGraphStage').onpointerdown=e=>{const title=e.target.closest('[data-node-title]');if(!title||get().busy||e.button!==0)return;const key=title.dataset.nodeTitle,pos=({...M.arrange(graph()),...graph().layout})[key];drag={key,x:e.clientX,y:e.clientY,original:pos,moved:false};title.setPointerCapture(e.pointerId);};
  byId('cmGraphStage').onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)<5)return;drag.moved=true;drag.position={x:Math.max(0,Math.min(10000,drag.original.x+dx)),y:Math.max(0,Math.min(10000,drag.original.y+dy))};const node=[...byId('cmGraphStage').querySelectorAll('[data-key]')].find(n=>n.dataset.key===drag.key);node.style.left=drag.position.x+'px';node.style.top=drag.position.y+'px';};
  byId('cmGraphStage').onpointerup=()=>{if(!drag)return;const value=drag;drag=null;if(value.moved)edit(g=>{g.layout[value.key]=value.position;},'已保存积木位置；构建与运行结果保持有效。',true);};
  byId('cmGraphStage').onpointercancel=()=>{drag=null;draw();};
  function renderCfar(){
    const list=graph()?.analyses||[],old=byId('cmGraphCfarNode').value;
    byId('cmGraphCfarNode').innerHTML=list.map(a=>`<option value="${a.id}">${esc(a.id+' · '+a.source)}</option>`).join('');if(list.some(a=>a.id===old))byId('cmGraphCfarNode').value=old;
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
    byId('cmGraphCfarResult').innerHTML=`<p>🎯 ${data.detections.length} 个聚类峰 · ${data.tested_cells} 个有效检测单元 · 超门限比例 ${data.crossing_fraction.toExponential(3)} · Pfa ${data.settings.pfa} · 黄色框为完整训练窗区域</p>`+table(['距离 / m','速度 / m/s','功率','门限','局部噪声','聚类单元'],data.detections.map(p=>[p.range_m,p.velocity_mps,p.power,p.threshold,p.noise,p.cluster_cells]));
  }
  byId('cmGraphCfarNode').onchange=renderCfar;byId('cmGraphCfarView').onchange=drawCfar;byId('cmGraphCfar').ontoggle=drawCfar;window.addEventListener('resize',()=>{if(graph())drawCfar();});
  function render(){
    const g=graph();byId('cmGraphWorkspace').hidden=!g;byId('cmGraphLeave').disabled=!g||get().busy;if(!g)return;
    if(!lastProjection)lastProjection=JSON.stringify(get().program);
    const branchOptions=g.branches.map(b=>`<option value="${b.id}">${esc(b.name)}</option>`).join('');
    for(const id of ['cmGraphBranch','cmGraphInputA','cmGraphInputB'])byId(id).innerHTML=branchOptions;
    byId('cmGraphBranch').value=active();byId('cmGraphInputA').value=g.merge.inputs[0];byId('cmGraphInputB').value=g.merge.inputs[1];byId('cmGraphMode').value=g.merge.mode;byId('cmGraphChoice').value=g.merge.select;byId('cmGraphWeightA').value=g.merge.weights[0];byId('cmGraphWeightB').value=g.merge.weights[1];
    const all=M.nodes(g),options=all.map(n=>`<option value="${esc(n.key)}">${esc(n.lane+' · '+label(n))}</option>`).join('');
    for(const id of ['cmGraphFrom','cmGraphTo']){const old=byId(id).value;byId(id).innerHTML=options;if(all.some(n=>n.key===old))byId(id).value=old;}
    const old=byId('cmGraphEdge').value;byId('cmGraphEdge').innerHTML=g.edges.map((e,i)=>`<option value="${i}">${esc(e.from+' ['+e.output+'] → '+e.to+' ['+e.input+']')}</option>`).join('');if(Number(old)<g.edges.length)byId('cmGraphEdge').value=old;
    const r=meta().graphResult;byId('cmGraphResults').innerHTML=r?table(['接收路径','BER','EVM / %'],[...r.branches.map(b=>[b.name,b.result.metrics.ber,b.result.metrics.evm_percent]),['🔗 汇合结果',r.merged_result.metrics.ber,r.merged_result.metrics.evm_percent]])+table(['执行区段','本次执行积木数','复用积木数'],r.execution.map(e=>[e.section,e.executed.length,e.reused.length]))+`<p class="cm-graph-status">输入 ${esc(r.input_hash)} · 共享采样接收路径的加权效果按实测 BER / EVM 比较</p>`:'';
    draw();renderCfar();buttons(get().busy);
  }
  function buttons(busy){host.querySelectorAll('button,input,select').forEach(e=>e.disabled=busy);byId('cmGraphLeave').disabled=busy||!graph();if(graph()){byId('cmGraphAdd').disabled=busy||graph().branches.length>=4;byId('cmGraphRemoveBranch').disabled=busy||graph().branches.length<=2;}}
  function restoreEdit(preserve=false){
    if(!preserve)loadState();else{lastProjection=JSON.stringify(get().program);if(compiled){const index=graph().branches.findIndex(b=>b.id===active());core.restoreResult(compiled.builds[index],meta().graphResult?.branches[index]?.result||null);}}
    render();
  }
  return {render,buttons,invalidate,replaceProgram,loadState,restoreEdit,sync,onResult:()=>{},active:()=>!!graph()};
};
