/* Exercise the production workbench lifecycle with controlled requests and jobs. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const M=require('../web/communication-graph-model-v0411.js'),clone=v=>JSON.parse(JSON.stringify(v));
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){
  const elements=new Map(),created=[],events=new Map(),requests=[],jobs=[],observations=[];
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.value='';this.hidden=false;this.disabled=false;this.children=[];this.nodes=new Map();this.dataset={};this.style={};created.push(this);}
    set id(value){this._id=value;elements.set(value,this);}get id(){return this._id;}
    set innerHTML(text){this.html=text;for(const m of text.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)){const e=byId(m[2]);e.tagName=m[1].toUpperCase();const value=/\bvalue="([^"]*)"/.exec(m[0]);if(value)e.value=value[1];if(e.tagName==='SELECT'){const content=text.slice(m.index+m[0].length).split('</select>')[0];e.value=/<option value="([^"]*)"/.exec(content)?.[1]||'';}}if(this.tagName==='SELECT')this.value=/<option value="([^"]*)"/.exec(text)?.[1]||'';}
    get innerHTML(){return this.html||'';}
    append(...nodes){this.children.push(...nodes);}prepend(...nodes){this.children.unshift(...nodes);}before(){}after(){}
    querySelector(selector){if(!this.nodes.has(selector))this.nodes.set(selector,new Element());return this.nodes.get(selector);}
    querySelectorAll(selector){return selector==='button,input,select'?[...elements.values()].filter(e=>['BUTTON','INPUT','SELECT'].includes(e.tagName)):[];}
    addEventListener(name,fn){const list=events.get(name)||[];list.push(fn);events.set(name,list);}
    dispatchEvent(event){for(const fn of events.get(event.type)||[])fn(event);}
    setAttribute(name,value){this[name]=String(value);}click(){return this.onclick?.();}
  }
  const byId=id=>{if(!elements.has(id)){const e=new Element();e.id=id;elements.set(id,e);}return elements.get(id);};
  const program={schema:1,seed:42,blocks:[{id:'source',kind:'random_bits',params:{count:32}},{id:'noise',kind:'awgn',params:{esn0_db:10}},{id:'sink',kind:'sink',params:{}}]};
  let meta={name:'海洋实验',tools:[]},current={program:clone(program),definitions:{random_bits:{label:'随机比特信源'},awgn:{label:'加性高斯白噪声'},sink:{label:'信宿观察'}},selectedId:'noise',busy:false},serial=0,ui,located='',restored=null;
  const built=()=>({token:'whole-project-token',parameters:[{path:'linear/noise/esn0_db',label:'噪声 信噪比'}],built:{program:clone(current.program),token:'chain-token'}});
  let request=async action=>action==='workbench-build'?built():{diagnostics:[]};
  let job=async(_,payload)=>({document_token:payload.token,result:{token:'chain-token',metrics:{ber:.125}},tools:[],observations:[]});
  const root=new Element(),context={window:{CommunicationGraphModel:M},document:{createElement:tag=>new Element(tag),activeElement:null},innerWidth:1270,console,Event};
  vm.runInNewContext(fs.readFileSync(__dirname+'/../web/communication-workbench-v0412.js','utf8'),context);
  const core={root,byId,clone,esc:v=>String(v??''),uid:()=>`tool-${++serial}`,get:()=>current,status(){},download(){},
    mutate(fn){if(current.busy)return;fn();ui.invalidate();ui.render();},setBusy(value){current.busy=value;ui?.buttons(value);},
    setResult(value){current.result=value;},restoreResult(b,value){current.compiled=b;current.result=value;},selectBlock(id){located=id;}};
  const ctx={meta:()=>meta,persist(){},documentValue:()=>clone({document_schema:2,...meta,program:current.program}),
    request:async(action,payload)=>{requests.push({action,payload:clone(payload)});return request(action,payload);},
    runJob:async(kind,payload)=>{jobs.push({kind,payload:clone(payload)});return job(kind,payload);},
    restoreDocument:async doc=>{const wasBusy=current.busy;core.setBusy(false);restored=clone(doc);meta=clone(doc);current.program=clone(doc.program);ui.invalidate();ui.render();core.setBusy(wasBusy);},
    layout:{edit(){},showAnalysis(){}},graphEditor:{selectedKey:()=>'',select:key=>located=key,acceptBuild(){}},observe:(...args)=>observations.push(args)};
  ui=context.window.createCommunicationWorkbenchV0412(core,ctx);ui.render();
  const palette=created.find(e=>e.className==='cm-workbench-palette');
  return {ui,byId,core,root,requests,jobs,observations,meta:()=>meta,get:()=>current,restored:()=>restored,located:()=>located,
    setMeta:v=>meta=clone(v),setJob:fn=>job=fn,setRequest:fn=>request=fn,
    add:kind=>palette.onclick({target:{closest:()=>({dataset:{analysisKind:kind}})}})};
}
const graph=()=>({schema:1,globals:{seed:42},prefix:[{id:'source',kind:'random_bits',params:{count:32}}],branches:['rx1','rx2'].map(id=>({id,name:id==='rx1'?'接收机 A':'接收机 B',blocks:[{id:'noise',kind:'awgn',params:{esn0_db:10}}]})),tail:[{id:'sink',kind:'sink',params:{}}],merge:{inputs:['rx1','rx2'],domain:'symbols',mode:'select',select:0,weights:[.5,.5]},analyses:[],layout:{},edges:[]});
async function main(){let failed=0;async function test(name,fn){try{await fn();console.log('PASS '+name);}catch(e){failed++;console.error('FAIL '+name,e.stack);}}
  await test('probe and reference show measured sample values and alignment in their editor',()=>{
    const f=fixture();f.add('probe');const id=f.meta().tools[0].id;assert.equal(f.meta().tools[0].source,'linear/noise');
    f.meta().workbenchResult={tools:[{id,kind:'probe',domain:'复样本',start:8,count:2,total_count:64,sample_rate:8000,i:[1.25,-.5],q:[.75,0]}]};
    f.byId('cmToolStack').onclick({target:{closest:s=>s==='[data-wb-tool]'?{dataset:{wbTool:id}}:null}});
    assert.match(f.byId('cmWBToolResult').innerHTML,/<td>1.25<\/td>/);assert.match(f.byId('cmWBToolResult').innerHTML,/<td>8<\/td>/);
    f.add('reference');const ref=f.meta().tools.at(-1);f.meta().workbenchResult={tools:[{id:ref.id,kind:'reference',metric:'mse',value:.0125,count:16,reference_start:2,source_start:4}]};
    f.byId('cmToolStack').onclick({target:{closest:s=>s==='[data-wb-tool]'?{dataset:{wbTool:ref.id}}:null}});
    assert.match(f.byId('cmWBToolResult').innerHTML,/MSE 0.0125/);assert.match(f.byId('cmWBToolResult').innerHTML,/参考起点 2/);
    assert.match(f.byId('cmToolStack').innerHTML,/加性高斯白噪声/);assert.doesNotMatch(f.byId('cmToolStack').innerHTML,/linear\/noise/);
  });
  await test('whole graph queue captures independent parameters and diagnoses locate scoped nodes',async()=>{
    const f=fixture();f.setMeta({name:'分支实验',graph:graph(),tools:[]});f.ui.render();f.byId('cmWBQueueAdd').onclick();f.meta().graph.branches[0].blocks[0].params.esn0_db=25;
    assert.equal(f.meta().workbenchQueue[0].document.graph.branches[0].blocks[0].params.esn0_db,10);
    f.setRequest(async()=>({diagnostics:[{node:'rx2/noise',message:'调整分支参数',action:'定位积木'}]}));await f.byId('cmWBBuild').onclick();
    f.byId('cmWBDiagnostics').onclick({target:{closest:()=>({dataset:{diagnosticNode:'rx2/noise'}})}});assert.equal(f.located(),'rx2/noise');
  });
  await test('Pareto submits two objectives and parameter axes while editing stays locked',async()=>{
    const f=fixture();f.byId('cmWBMode').value='pareto';f.byId('cmWBValues').value='-2,8';f.byId('cmWBObjective').value='merged.ber';f.byId('cmWBObjective2').value='merged.evm_percent';f.byId('cmWBDirection2').value='max';
    let release;f.setJob(()=>new Promise(resolve=>release=resolve));const pending=f.byId('cmWBTask').onclick();await settle();
    assert.equal(f.get().busy,true);assert.equal(f.byId('cmWBToolSave').disabled,true);const sent=f.jobs[0];assert.equal(sent.payload.token,'whole-project-token');assert.deepEqual(sent.payload.settings.axes,[{path:'linear/noise/esn0_db',values:[-2,8]}]);assert.equal(sent.payload.settings.objectives[1].direction,'max');
    release({completed:2,total:2,complete:true,summaries:[{name:'候选一',parameters:{'linear/noise/esn0_db':8},metrics:{'merged.ber':.125,'merged.evm_percent':5.5},feasible:true,pareto:true,ber_interval:[.1,.15]}],rows:[]});await pending;
    assert.equal(f.get().busy,false);assert.match(f.byId('cmWBResults').innerHTML,/噪声 信噪比 = 8/);assert.match(f.byId('cmWBResults').innerHTML,/0.125/);assert.match(f.byId('cmWBResults').innerHTML,/0.1 至 0.15/);assert.equal(f.byId('cmWBValues').value,'-2,8');
  });
  await test('replay restores the full graph and recorded seed before running the saved task',async()=>{
    const f=fixture(),savedGraph=graph();savedGraph.globals.seed=1042;const document={document_schema:2,name:'保存候选',graph:savedGraph,program:{...clone(f.get().program),seed:1042},tools:[]};
    f.meta().workbenchTaskResult={completed:1,total:1,complete:true,summaries:[],rows:[{seed:1042,metrics:{'merged.ber':0}}]};
    f.setRequest(async(action,payload)=>action==='workbench-restore'?{document}:action==='workbench-build'?{token:'restored-token',parameters:[],built:{program:payload.document.program,token:'chain-token'}}:{});
    await f.byId('cmWBResults').onclick({target:{closest:()=>({dataset:{wbReplay:'0'}})}});
    await settle();assert.equal(f.restored()?.graph.globals.seed,1042);assert.equal(f.jobs.at(-1).payload.document.graph.globals.seed,1042);assert.equal(f.jobs.at(-1).payload.token,'restored-token');assert.equal(f.meta().workbenchTaskResult.rows[0].seed,1042);assert.equal(f.meta().workbenchResult.document_token,'restored-token');
  });
  await test('direct course and debug runs own the edit lock through asynchronous jobs',async()=>{
    const f=fixture();let release;f.setJob(()=>new Promise(resolve=>release=resolve));const pending=f.ui.runDocument(undefined,{debug:true,mode:'continue'});await settle();
    assert.equal(f.get().busy,true);assert.equal(f.byId('cmWBToolSave').disabled,true);assert.equal(f.jobs[0].kind,'workbench-debug');assert.equal(f.jobs[0].payload.debug_mode,'continue');
    release({document_token:'whole-project-token',result:{metrics:{ber:0}},tools:[],observations:[{id:'linear/noise'}],job_id:'same-debug-job'});await pending;
    assert.equal(f.get().busy,false);assert.equal(f.observations[0][1],'same-debug-job');
  });
  await test('switching the experiment clears previous tool measurements and stale editor',()=>{
    const f=fixture();f.add('probe');f.meta().workbenchResult={tools:[{id:f.meta().tools[0].id,kind:'probe'}]};f.ui.replaceProgram();f.ui.render();
    assert.equal(f.meta().tools.length,0);assert.equal(f.meta().workbenchResult,undefined);assert.equal(f.byId('cmToolStack').innerHTML,'');
    assert.equal(f.byId('cmWBToolInspector').hidden,true);
  });
  await test('failed runs restore their prior edit lock and reject stale result versions',async()=>{
    const f=fixture();f.setJob(async()=>{throw Error('测量失败');});await assert.rejects(f.ui.runDocument(),/测量失败/);assert.equal(f.get().busy,false);
    f.core.setBusy(true);await assert.rejects(f.ui.runDocument(),/测量失败/);assert.equal(f.get().busy,true);f.core.setBusy(false);
    f.setJob(async()=>({document_token:'stale',result:{metrics:{}},tools:[]}));await assert.rejects(f.ui.runDocument(),/版本/);assert.equal(f.meta().workbenchResult,undefined);assert.equal(f.get().busy,false);
  });
  await test('saved graph results restore only their matching document and execution tokens',async()=>{
    const f=fixture(),g=graph();f.setMeta({name:'已保存工程',graph:g,tools:[],result:{token:'branch-token',metrics:{ber:.03125}},graphResult:{graph_token:'graph-token'},workbenchResult:{document_token:'saved-token',job_id:'saved-job',tools:[],observations:[]}});
    f.setRequest(async()=>({kind:'graph',token:'saved-token',signal_token:'graph-token',parameters:[],built:{graph:g,builds:[{token:'branch-token',program:f.get().program}]}}));
    assert.equal(await f.ui.restoreSaved(),true);assert.equal(f.get().result.metrics.ber,.03125);assert.equal(f.meta().workbenchResult.document_token,'saved-token');
    assert.equal(f.meta().workbenchResult.result,undefined);assert.equal(f.meta().workbenchResult.graph_result,undefined);assert.equal(f.observations[0][1],'saved-job');
  });
  await test('stale imported graph results are cleared before the next experiment',async()=>{
    const f=fixture(),g=graph();f.setMeta({graph:g,tools:[],result:{token:'branch-token'},graphResult:{graph_token:'older-graph'},workbenchResult:{document_token:'saved-token'}});
    f.setRequest(async()=>({kind:'graph',token:'saved-token',signal_token:'graph-token',built:{builds:[{token:'branch-token'}]}}));
    assert.equal(await f.ui.restoreSaved(),false);assert.equal(f.meta().workbenchResult,undefined);assert.equal(f.meta().graphResult,undefined);assert.equal(f.meta().result,null);
  });
  if(failed)process.exitCode=1;
}
main().catch(e=>{console.error(e);process.exitCode=1;});
