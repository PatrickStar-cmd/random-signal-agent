/* Core experiment-panel lifecycle against the production module. */
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../web/communication-experiments.js'),'utf8');
function fixture(){
  const elements=new Map();
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.value='';this.dataset={};this.style={};this.disabled=false;this.hidden=false;this.children=[];this.nodes=new Map();}
    set innerHTML(value){this.html=value;for(const m of value.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)){if(!elements.has(m[2]))elements.set(m[2],new Element(m[1]));const e=elements.get(m[2]);e.id=m[2];const v=/\bvalue="([^"]*)"/.exec(m[0]);if(v)e.value=v[1];}if(this.tagName==='SELECT')this.value=/<option value="([^"]*)"/.exec(value)?.[1]||'';}
    get innerHTML(){return this.html||'';}
    append(...nodes){this.children.push(...nodes);}setAttribute(key,value){this[key]=String(value);}click(){return this.onclick?.();}
    querySelector(selector){if(!this.nodes.has(selector))this.nodes.set(selector,new Element());return this.nodes.get(selector);}
    querySelectorAll(selector){return selector==='button,input,select,textarea'?[...elements.values()]:[];}
    closest(){return new Element();}
  }
  const byId=id=>{if(!elements.has(id)){const e=new Element();e.id=id;elements.set(id,e);}return elements.get(id);};
  const clone=value=>JSON.parse(JSON.stringify(value));
  const program={seed:42,symbol_rate:1000,sample_rate:8000,sample_count:32,blocks:[{id:'source',kind:'random_bits',params:{count:32}},{id:'noise',kind:'awgn',params:{esn0_db:10}}]};
  let meta={name:'Ocean test',experiments:{tasks:[],queue:[]}},current={program:clone(program),definitions:{random_bits:{label:'bits',params:{count:{type:'integer',label:'count'}}},awgn:{label:'noise',params:{esn0_db:{type:'number',label:'SNR'}}}},busy:false};
  const context={window:{},document:{createElement:tag=>new Element(tag)},console};vm.runInNewContext(source,context);
  let ui,job=async()=>({rows:[],summaries:[],completed:0,total:0,complete:true,latency_reference:'frame'}),request=async()=>({}),lastJob=null;
  const core={root:new Element(),byId,esc:value=>String(value??''),clone,get:()=>current,status(){},download(){},api:async(_,payload)=>({program:clone(payload.program),token:'compiled'}),setBusy(value){current.busy=value;ui?.buttons(value);},setProgram(value){current.program=clone(value);ui.replaceProgram();}};
  ui=context.window.createCommunicationExperiments(core,{meta:()=>meta,persist(){},request:(...args)=>request(...args),runJob:(kind,payload)=>{lastJob={kind,payload};return job(kind,payload);}});ui.render();byId('cmBatchMode').value='link';
  return {ui,byId,program,get:()=>current,meta:()=>meta,setMeta:value=>{meta=value;},setJob:value=>{job=value;},setRequest:value=>{request=value;},lastJob:()=>lastJob};
}
async function main(){
  let failed=0;
  async function test(name,run){try{await run();console.log('PASS '+name);}catch(error){failed++;console.error('FAIL '+name+': '+error.stack);}}
  await test('queued projects retain independent captured parameters',async()=>{const f=fixture();await f.byId('cmBatchAdd').onclick();f.get().program.blocks[1].params.esn0_db=-8;assert.equal(f.meta().experiments.queue[0].program.blocks[1].params.esn0_db,10);});
  await test('saved snapshot joins the queue without replacing the current chain',async()=>{const f=fixture();f.byId('cmProjectList').value='snapshot-id';f.byId('cmProjectVersions').value='2';const saved=JSON.parse(JSON.stringify(f.program));saved.blocks[1].params.esn0_db=25;let requested;f.setRequest(async(action,payload)=>{requested={action,payload};return {version:2,document:{name:'Saved',program:saved}};});await f.byId('cmBatchSnapshot').onclick();assert.equal(requested.action,'project-load');assert.equal(requested.payload.version,2);assert.equal(f.get().program.blocks[1].params.esn0_db,10);assert.equal(f.meta().experiments.queue[0].program.blocks[1].params.esn0_db,25);});
  await test('experiment queue locks editing and keeps stop available',async()=>{const f=fixture();await f.byId('cmBatchAdd').onclick();let release;f.setJob(()=>new Promise(resolve=>release=resolve));const running=f.byId('cmBatchRun').onclick();assert.equal(f.get().busy,true);assert.equal(f.byId('cmBatchAdd').disabled,true);assert.equal(f.byId('cmExperimentStop').disabled,false);assert.equal(f.lastJob().kind,'batch');release({rows:[],summaries:[],completed:0,total:3,complete:false,latency_reference:'frame'});await running;assert.equal(f.get().busy,false);assert.equal(f.meta().experiments.batchResult.complete,false);});
  await test('editing a chain clears classroom acceptance while retaining queue evidence',()=>{const f=fixture();f.meta().experiments.taskResult={score:100,stages:[],passed:true};f.meta().experiments.batchResult={rows:[],summaries:[],complete:true,completed:3,total:3};f.ui.invalidate();assert.equal(f.meta().experiments.taskResult,null);assert.equal(f.meta().experiments.batchResult.complete,true);assert.equal(f.byId('cmTaskResults').innerHTML,'');});
  await test('switching projects renders that project queue and search results',()=>{const f=fixture();f.setMeta({name:'New',experiments:{tasks:[],queue:[{name:'Loaded project',program:f.program}],searchResult:{selected:{snr_db:12,ber:0},points:[],resolution_db:2}}});f.ui.render();assert.match(f.byId('cmBatchQueue').innerHTML,/Loaded project/);assert.match(f.byId('cmTargetResults').innerHTML,/12 dB/);assert.equal(f.byId('cmTargetApply').disabled,false);});
  if(failed)process.exitCode=1;
}
main().catch(error=>{console.error(error);process.exitCode=1;});
