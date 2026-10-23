/* Keep the existing controls and handlers; reorganize their presentation. */
window.createCommunicationLayout = function(core) {
  'use strict';
  const {root,byId,esc,get}=core,small=matchMedia('(max-width:1000px)');
  const find=s=>root.querySelector(s),make=(tag,cls,html='')=>{const e=document.createElement(tag);e.className=cls;e.innerHTML=html;return e};
  const move=(id,to)=>to.append(byId(id));
  const redraw=()=>requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));
  root.classList.add('cm-layout');root.dataset.mobilePane='chain';
  const tools=make('section','cm-commandbar','<div class="cm-command-main"></div><div class="cm-command-status"></div>');
  tools.setAttribute('aria-label','工程与运行工具栏');byId('cmForm').before(tools);
  const main=tools.firstElementChild,status=tools.lastElementChild;
  main.append(byId('cmDocumentName').closest('label'));
  move('cmProjectSave',main);
  const libraryButton=make('button','', '🧭 实验库');libraryButton.type='button';libraryButton.id='cmOpenExperiments';main.append(libraryButton);
  for(const id of ['cmUndo','cmRedo','cmBuild','cmRun'])move(id,main);
  byId('cmBuild').setAttribute('form','cmForm');const primary=make('div','cm-primary-actions');byId('cmBuild').before(primary);move('cmBuild',primary);move('cmRun',primary);
  function menu(title,cls){const d=make('details','cm-command-menu '+cls,`<summary>${title}</summary><div class="cm-menu-body"></div>`);main.append(d);return d.lastElementChild}
  const project=menu('🗂️ 工程','cm-file-menu');
  for(const id of ['cmProjectList','cmProjectVersions'])project.append(byId(id).closest('label'));
  for(const id of ['cmProjectOpen','cmProjectCopy','cmImport','cmReset','cmProjectExport','cmExport','cmReport','cmFile'])move(id,project);
  byId('cmExport').textContent='🧩 导出链路配置 JSON';byId('cmProjectExport').textContent='📦 导出完整工程 JSON';
  const debug=menu('🐾 调试','cm-debug-menu');debug.append(find('.cm-debug-controls'));
  const settings=menu('⚙️ 参数','cm-global-menu'),oldSettings=find('.cm-settings');
  settings.append(oldSettings);oldSettings.querySelectorAll('[data-global]').forEach(e=>e.setAttribute('form','cmForm'));oldSettings.open=true;oldSettings.querySelector('summary').hidden=true;
  for(const id of ['cmBuildBadge','cmJobProgress','cmJobBar','cmExperienceStatus'])move(id,status);
  find('.cm-projects').hidden=true;find('.cm-project-bar').hidden=true;

  const mobile=make('nav','cm-mobile-nav','<button type="button" data-mobile="palette">🧱 积木库</button><button type="button" data-mobile="chain">🧬 链路</button><button type="button" data-mobile="params">🎛️ 参数</button><button type="button" data-mobile="results">📊 结果</button>');
  mobile.setAttribute('aria-label','通信工作区切换');tools.after(mobile);
  function mobilePane(name){root.dataset.mobilePane=name;mobile.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mobile===name)));redraw()}
  mobilePane('chain');
  const right=find('.cm-right'),inspector=find('.cm-inspector'),viewer=find('.cm-viewer');
  const sideTabs=make('div','cm-side-tabs','<button type="button" data-side="params">🎛️ 积木参数</button><button type="button" data-side="sink">📺 信宿观察</button>');right.prepend(sideTabs);sideTabs.after(inspector);
  function side(name){sideTabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.side===name)));inspector.hidden=name!=='params';viewer.hidden=name!=='sink';redraw()}
  sideTabs.addEventListener('click',e=>{if(e.target.dataset.side)side(e.target.dataset.side)});side('params');
  const drawer=make('dialog','cm-parameter-drawer','<header><strong>🎛️ 积木参数</strong><button type="button">完成</button></header><fieldset></fieldset>');drawer.setAttribute('aria-label','选中积木参数');root.append(drawer);
  drawer.querySelector('button').onclick=()=>drawer.close();
  drawer.addEventListener('close',()=>{sideTabs.after(inspector);side('params')});
  function edit(){side('params');if(small.matches){drawer.querySelector('fieldset').append(inspector);if(!drawer.open)drawer.showModal();}}
  root.addEventListener('cm-select',edit);
  mobile.addEventListener('click',e=>{const name=e.target.dataset.mobile;if(!name)return;if(name==='params')edit();else{mobilePane(name);if(name==='results')openAnalysis()}});
  small.addEventListener('change',()=>{if(!small.matches&&drawer.open)drawer.close();redraw()});

  find('.cm-canvas-tools').after(find('.cm-organize'));
  const batch=make('button','cm-batch-button','☑ 批量选择');batch.type='button';batch.setAttribute('aria-pressed','false');find('.cm-canvas-tools').prepend(batch);
  batch.onclick=()=>{const on=root.classList.toggle('cm-batch-mode');batch.setAttribute('aria-pressed',String(on))};
  // Dragging a selection marquee also makes the resulting selection visible.
  byId('cmProgram').addEventListener('pointerdown',e=>{if(e.target.closest('button,input,.cm-block,.cm-group')||get().busy)return;root.classList.add('cm-batch-mode');batch.setAttribute('aria-pressed','true')});

  const dock=make('section','cm-analysis-dock','<header><h3>📊 实验分析</h3><div><button type="button" id="cmAnalysisExpand">⛶ 展开大图</button><button type="button" id="cmAnalysisCollapse" aria-expanded="true">收起分析</button></div></header><div class="cm-dock-body"><div role="tablist" aria-label="分析视图"></div><div class="cm-dock-panels"></div></div>');
  dock.id='cmAnalysisDock';byId('cmForm').after(dock);
  const tabs=dock.querySelector('[role=tablist]'),panels=dock.querySelector('.cm-dock-panels');
  const names={overview:'结果总览',signals:'信号观察',rf:'射频测量',compare:'性能对照',learning:'🎓 业务与教学'},panes={};
  for(const [id,label] of Object.entries(names)){const b=make('button','',label);b.type='button';b.id='cmTab-'+id;b.dataset.analysis=id;b.setAttribute('role','tab');b.setAttribute('aria-controls','cmPane-'+id);tabs.append(b);const p=make('div','cm-analysis-pane');p.id='cmPane-'+id;p.setAttribute('role','tabpanel');p.setAttribute('aria-labelledby',b.id);panels.append(p);panes[id]=p;}
  const results=find('.cm-results'),scopes=find('.cm-scopes'),sweep=find('.cm-sweep'),rf=byId('cmRFPanel');
  panes.overview.append(results);panes.signals.append(scopes);panes.rf.append(rf);rf.open=true;
  const task=make('section','cm-task-pane cm-experience','<h3>🧭 实验任务对照</h3>');panes.compare.append(task);
  task.append(byId('cmRFTask').closest('.cm-experience-row'));
  for(const id of ['cmRFGoal','cmTaskStatus','cmRFContext','cmRFComparisons','cmRFCompareChart','cmRFCompareCaption'])move(id,task);
  const comparePlot=make('label','cm-compare-plot','对照图<select id="cmComparisonPlot"><option value="spectrum">Welch 功率谱</option><option value="ccdf">功率 CCDF</option><option value="evm">方案 EVM</option><option value="papr">方案 PAPR</option></select>');byId('cmRFCompareChart').before(comparePlot);
  byId('cmComparisonPlot').onchange=()=>{byId('cmRFMode').value=byId('cmComparisonPlot').value;byId('cmRFMode').dispatchEvent(new Event('change'))};byId('cmRFMode').addEventListener('change',()=>{byId('cmComparisonPlot').value=['spectrum','ccdf','papr'].includes(byId('cmRFMode').value)?byId('cmRFMode').value:'evm'});
  panes.compare.append(sweep);sweep.open=true;
  const dataMenu=make('details','cm-data-export','<summary>📥 导出实验数据</summary><div></div>');panes.overview.append(dataMenu);
  for(const id of ['cmDownloadCSV','cmDownloadResult','cmRFExport','cmSweepExport','cmSweepCSV'])move(id,dataMenu.lastElementChild);
  const host=make('span','cm-dock-anchor');dock.before(host);
  const enlarged=make('dialog','cm-analysis-dialog');enlarged.setAttribute('aria-label','实验分析大图');root.append(enlarged);
  enlarged.addEventListener('close',()=>{host.after(dock);byId('cmAnalysisExpand').textContent='⛶ 展开大图';redraw()});
  function openAnalysis(){dock.querySelector('.cm-dock-body').hidden=false;byId('cmAnalysisCollapse').textContent='收起分析';byId('cmAnalysisCollapse').setAttribute('aria-expanded','true');redraw()}
  byId('cmAnalysisExpand').onclick=()=>{if(enlarged.open){enlarged.close();return}openAnalysis();enlarged.append(dock);enlarged.showModal();byId('cmAnalysisExpand').textContent='↙ 返回工作区';redraw()};
  byId('cmAnalysisCollapse').onclick=()=>{if(enlarged.open)enlarged.close();const body=dock.querySelector('.cm-dock-body');body.hidden=!body.hidden;byId('cmAnalysisCollapse').textContent=body.hidden?'展开分析':'收起分析';byId('cmAnalysisCollapse').setAttribute('aria-expanded',String(!body.hidden));redraw()};
  function analysis(id){tabs.querySelectorAll('button').forEach(b=>{const on=b.dataset.analysis===id;b.setAttribute('aria-selected',String(on));b.tabIndex=on?0:-1});Object.entries(panes).forEach(([key,p])=>p.hidden=key!==id);redraw()}
  tabs.onclick=e=>{if(e.target.dataset.analysis)analysis(e.target.dataset.analysis)};
  tabs.onkeydown=e=>{const list=[...tabs.querySelectorAll('button')],i=list.indexOf(document.activeElement);if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?list.length-1:(i+(e.key==='ArrowRight'?1:-1)+list.length)%list.length;analysis(list[next].dataset.analysis);list[next].focus()};analysis('overview');

  const library=make('dialog','cm-experiment-library','<header><h3>🧭 实验库</h3><button type="button" id="cmLibraryClose">关闭</button></header><div class="cm-library-filter"><label>搜索实验<input id="cmExperimentSearch" type="search" placeholder="名称、算法、通信环节"></label><label>通信主题<select id="cmExperimentTopic"><option value="all">全部主题</option><option value="tasks">🔬 任务对照（7）</option></select></label></div><p id="cmExperimentCount" role="status"></p><div id="cmExperimentCards"></div>');
  library.setAttribute('aria-label','搜索与选择通信实验');root.append(library);
  const topic=(label,key)=>/音频|图像|文件|Huffman|ADPCM/.test(label)?'业务与信源编码':/DSSS|RAKE|扩频|MIMO|Alamouti|分集/.test(label)?'扩频与多天线':/^rf_(iq|dc|adc|notch)$/.test(key)?'射频与硬件':/线路码|^基带/.test(label)?'线路编码与基带':/同步|接收估计|重采样/.test(label)?'同步与接收':/均衡|衰落|突发/.test(label)?'信道与均衡':/OFDM|多载波|削峰|功放/.test(label)?'OFDM 与射频':/编码|译码|检错|打孔/.test(label)?'编码与纠错':/线性|模拟|PCM/.test(label)?'模拟通信':'数字调制与传输';
  const entries=Object.entries(get().catalog.presets).map(([key,p])=>({key,label:p.label,topic:topic(p.label,key),task:get().catalog.tasks.find(t=>t.preset===key)}));
  for(const name of [...new Set(entries.map(e=>e.topic))]){const o=document.createElement('option');o.value=name;o.textContent=name;byId('cmExperimentTopic').append(o)}
  function libraryList(){const words=byId('cmExperimentSearch').value.trim().toLowerCase().split(/\s+/),group=byId('cmExperimentTopic').value,items=entries.filter(e=>(group==='all'||group===e.topic||group==='tasks'&&e.task)&&words.every(w=>(e.label+' '+e.topic+' '+(e.task?.goal||'')).toLowerCase().includes(w)));byId('cmExperimentCount').textContent=`${items.length} / ${entries.length} 个示例 · 含 ${get().catalog.tasks.length} 项任务对照`;byId('cmExperimentCards').innerHTML=items.length?items.map(e=>`<button type="button" data-experiment="${esc(e.key)}"><small>${esc(e.topic)}</small><strong>${esc(e.label)}</strong><span>${e.task?'🔬 含任务对照':'载入示例链路'}</span></button>`).join(''):'没有匹配的实验，试试其他名称或主题。'}
  libraryButton.onclick=()=>{libraryList();library.showModal();byId('cmExperimentSearch').focus()};byId('cmLibraryClose').onclick=()=>library.close();
  byId('cmExperimentSearch').oninput=libraryList;byId('cmExperimentTopic').onchange=libraryList;
  byId('cmExperimentCards').onclick=async e=>{const key=e.target.closest('[data-experiment]')?.dataset.experiment;if(!key||get().busy)return;library.close();byId('cmPreset').value=key;await byId('cmPreset').onchange({target:byId('cmPreset')});if(byId('cmPreset').value===key){const t=entries.find(e=>e.key===key)?.task;if(t){byId('cmRFTask').value=t.id;byId('cmRFTask').onchange()}}mobilePane('chain');if(byId('cmPreset').value===key&&byId('cmExperimentTopic').value==='tasks')root.dispatchEvent(new Event('cm-task-loaded'))};
  // Original selectors stay available to existing APIs and project loaders.
  byId('cmScenario').closest('label').hidden=true;byId('cmPreset').closest('label').hidden=true;
  root.addEventListener('cm-state',()=>{const busy=get().busy;byId('cmBuild').disabled=busy;libraryButton.disabled=busy;batch.disabled=busy;drawer.querySelector('fieldset').disabled=busy;oldSettings.querySelectorAll('input,select').forEach(e=>e.disabled=busy);for(const id of ['cmImport','cmReset','cmExport'])byId(id).disabled=busy;});
  root.addEventListener('cm-task-loaded',()=>{analysis('compare');if(small.matches)mobilePane('results');openAnalysis()});
  root.addEventListener('cm-block-added',()=>{if(small.matches)mobilePane('chain')});
  tools.addEventListener('toggle',e=>{if(e.target.classList.contains('cm-command-menu')&&e.target.open)tools.querySelectorAll('.cm-command-menu').forEach(d=>{if(d!==e.target)d.open=false})},true);
  root.addEventListener('keydown',e=>{if(e.key==='Escape')tools.querySelectorAll('.cm-command-menu[open]').forEach(d=>{d.open=false;d.querySelector('summary').focus()})});
  document.addEventListener('click',e=>{if(!tools.contains(e.target))tools.querySelectorAll('.cm-command-menu').forEach(d=>d.open=false)});
  new MutationObserver(()=>{if(!root.hidden)redraw();else{if(drawer.open)drawer.close();if(enlarged.open)enlarged.close()}}).observe(root,{attributes:true,attributeFilter:['hidden']});
  return {analysis,edit,showAnalysis:id=>{analysis(id);if(small.matches)mobilePane('results');openAnalysis()}};
};
