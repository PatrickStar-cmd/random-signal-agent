/* Lifecycle regression against the production learning UI, without DOM packages. */
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../web/communication-learning.js'),'utf8');

function fixture(){
  const elements=new Map();
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.value='';this.dataset={};this.style={};this.disabled=false;this.hidden=false;this.max='0';this.children=[];this.classList={add(){},remove(){},toggle(){}};this.nodes=new Map();}
    set innerHTML(value){this.html=value;for(const m of value.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)){if(!elements.has(m[2])){const e=new Element(m[1]);e.id=m[2];elements.set(e.id,e);}const e=elements.get(m[2]),v=/\bvalue="([^"]*)"/.exec(m[0]);if(v)e.value=v[1];}if(this.tagName==='SELECT'){const valueMatch=/<option value="([^"]*)"/.exec(value);this.value=valueMatch?valueMatch[1]:'';}}
    get innerHTML(){return this.html||'';}
    append(...nodes){this.children.push(...nodes);} prepend(...nodes){this.children.unshift(...nodes);} insertBefore(node){this.append(node);} setAttribute(key,value){this[key]=String(value);} addEventListener(){} dispatchEvent(event){this.lastEvent=event;} remove(){} close(){} click(){return this.onclick?.();}
    querySelector(selector){if(!this.nodes.has(selector))this.nodes.set(selector,new Element());return this.nodes.get(selector);}
    querySelectorAll(selector){return selector==='button,input,select,textarea'?[...elements.values()]:[];}
    closest(){if(!this.parent)this.parent=new Element();return this.parent;}
    getContext(){return new Proxy({},{get:()=>()=>{}});}
  }
  const byId=id=>{if(!elements.has(id)){const e=new Element();e.id=id;elements.set(id,e);}return elements.get(id);};
  const program={seed:42,symbol_rate:1000,sample_rate:8000,sample_count:32,blocks:[{id:'source',kind:'random_bits',params:{count:32}},{id:'noise',kind:'awgn',params:{esn0_db:10}}]};
  let meta={name:'test',learning:{variables:{},bindings:{}}},getState={program,definitions:{random_bits:{label:'bits',params:{count:{type:'integer',label:'count'}}},awgn:{label:'noise',params:{esn0_db:{type:'number',label:'SNR'}}}},catalog:{learning:{challenges:[{id:'first',name:'First',objective:'one',steps:[],goals:[]},{id:'second',name:'Second',objective:'two',steps:[],goals:[]}]},presets:{}},busy:false,result:null,selectedId:null};
  const root=new Element(),context={window:{addEventListener(){}},document:{activeElement:null,createElement:tag=>new Element(tag)},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},devicePixelRatio:1,setInterval,clearInterval,Date,console};
  vm.runInNewContext(source,context);
  const clone=x=>JSON.parse(JSON.stringify(x));let request=async(action,payload)=>({program:payload.program,variables:{}}),ui;
  const core={root,byId,esc:value=>String(value??''),clone,get:()=>getState,status(){},download(){},setProgram(p){getState.program=p;ui.replaceProgram();},mutate(fn){fn();},setBusy(value){getState.busy=value;ui?.buttons(value);},api:async(_,payload)=>({program:payload.program,token:'build'})};
  ui=context.window.createCommunicationLearning(core,{meta:()=>meta,persist(){},layout:{showAnalysis(){}},request:(...args)=>request(...args),runJob:async()=>({points:[],x_values:[0],y_values:[0],completed_points:0,total_points:1}),documentValue(){}});
  ui.render();
  return {ui,byId,get:()=>getState,meta:()=>meta,setMeta:value=>{meta=value;},setRequest:value=>{request=value;}};
}

async function main(){
  const failures=[];
  async function test(name,run){try{await run();console.log('PASS '+name);}catch(error){failures.push(name);console.error('FAIL '+name+': '+error.message);}}
  await test('restoring a project uses its own algorithm evidence',()=>{
    const f=fixture();f.byId('cmAlgorithm').value='huffman';
    f.get().result={advanced:{learning:[{kind:'huffman',codes:[{symbol:'OLD',code:'0',count:1}]}]}};f.ui.onResult(f.get().result);
    f.setMeta({name:'loaded',learning:{variables:{},bindings:{},tab:'algorithm',explanation:{algorithm:'huffman',codes:[{symbol:'NEW',code:'0',count:2}]}}});f.get().result=null;f.ui.render();
    assert.match(f.byId('cmAlgorithmDetails').innerHTML,/NEW/);assert.doesNotMatch(f.byId('cmAlgorithmDetails').innerHTML,/OLD/);
  });
  await test('changing a challenge removes the previous completion',()=>{
    const f=fixture();f.meta().learning.check={passed:true,checks:[]};f.ui.render();f.byId('cmLesson').value='second';f.byId('cmLesson').onchange();
    assert.doesNotMatch(f.byId('cmLessonResult').innerHTML,/实验目标已完成/);
  });
  await test('editing a chain invalidates its measured teaching evidence',()=>{
    const f=fixture(),saved=f.meta().learning;
    saved.explanation={algorithm:'wireless',data:{rx_mrc:{branch_power:[1,2]}}};saved.check={passed:true,checks:[]};saved.protocolResult={};saved.amcResult={};
    f.ui.invalidate();
    for(const key of ['explanation','check','protocolResult','amcResult'])assert.equal(saved[key],null,key);
  });
  await test('a scan locks the workbench while parameter resolution is pending',async()=>{
    const f=fixture();let release;f.byId('cmVariableText').value='Rs = 1000';f.meta().learning.bindings={symbol_rate:'Rs'};
    f.setRequest(()=>new Promise(resolve=>{release=resolve;}));f.byId('cmScanX').value='blocks.noise.esn0_db';f.byId('cmScanY').value='seed';f.byId('cmScanXValues').value='0';f.byId('cmScanYValues').value='1';f.byId('cmScanFrames').value='1';
    const pending=f.byId('cmScanRun').onclick();const locked=f.get().busy;release({program:f.get().program,variables:{Rs:1000}});await pending;
    assert.equal(locked,true);assert.equal(f.get().busy,false);
  });
  await test('protocol controls follow the selected physical chain',()=>{
    const f=fixture();f.byId('cmProtocolPHY').value='program';f.byId('cmProtocolMode').value='arq';f.byId('cmProtocolMode').onchange();
    assert.equal(f.byId('cmProtocolRate').closest('label').hidden,true);assert.equal(f.byId('cmProtocolSNR').closest('label').hidden,true);
    f.byId('cmProtocolMode').value='amc';f.byId('cmProtocolMode').onchange();assert.equal(f.byId('cmProtocolSNR').closest('label').hidden,false);assert.equal(f.byId('cmProtocolNoise').closest('label').hidden,false);
    f.byId('cmProtocolPHY').value='reference';f.byId('cmProtocolPHY').onchange();assert.equal(f.byId('cmProtocolRate').closest('label').hidden,false);assert.equal(f.byId('cmProtocolNoise').closest('label').hidden,true);
  });
  await test('IR switches to a rate-matched budget and preserves Chase full-mother option',()=>{
    const f=fixture();f.byId('cmHARQBudget').value='1';f.byId('cmProtocolMode').value='ir_harq';f.byId('cmProtocolMode').onchange();
    assert.equal(f.byId('cmHARQBudget').value,'2');assert.equal(f.byId('cmHARQBudget').closest('label').hidden,false);assert.equal(f.byId('cmProtocolCompare').hidden,false);
    f.byId('cmProtocolMode').value='harq';f.byId('cmHARQBudget').value='1';f.byId('cmProtocolMode').onchange();assert.equal(f.byId('cmHARQBudget').value,'1');
    f.byId('cmProtocolMode').value='amc';f.byId('cmProtocolMode').onchange();assert.equal(f.byId('cmProtocolCompare').hidden,true);
  });
  if(failures.length)process.exitCode=1;
}
main().catch(error=>{console.error(error);process.exitCode=1;});
