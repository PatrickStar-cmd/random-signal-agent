/* Production delivery/report UI lifecycle and final-PDF preview acceptance. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const clone=v=>JSON.parse(JSON.stringify(v));
function fixture(module='delivery'){
  const elements=new Map(),downloads=[],revoked=[],requests=[];
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.value='';this.children=[];this.disabled=false;this.dataset={};this.checked=false;}
    set innerHTML(text){this.html=text;for(const match of text.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)){const node=byId(match[2]);node.tagName=match[1].toUpperCase();node.checked=/\bchecked\b/.test(match[0]);if(node.tagName==='TEXTAREA')node.value=text.slice(match.index+match[0].length).split('</textarea>')[0];}if(this.tagName==='SELECT')this.value=/<option value="([^"]*)"/.exec(text)?.[1]||'';}
    get innerHTML(){return this.html||'';} append(...nodes){this.children.push(...nodes);}
    querySelectorAll(){return [...elements.values()];} addEventListener(){} showModal(){this.open=true;}close(){this.open=false;}
    click(){if(this.tagName==='A')downloads.push({href:this.href,name:this.download});return this.onclick?.();}
  }
  const byId=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  let meta={},doc={document_schema:2,name:'实验',program:{seed:42,blocks:[]}},job=async()=>({passed:true,completed:3,total:3,rows:[]}),run=null;
  let request=async(action,payload)=>action==='delivery-courses'?[]:action==='workbench-build'?{token:'actual-built-token'}:{};
  const context={window:{},document:{createElement:tag=>new Element(tag)},console,Blob,Uint8Array,atob,btoa,setTimeout:()=>0,
    URL:{createObjectURL:()=>`blob:pdf-${requests.length}`,revokeObjectURL:url=>revoked.push(url)},
    fetch:async(url,options)=>{requests.push({url,payload:JSON.parse(options.body)});return {ok:true,blob:async()=>new Blob(['%PDF final bytes'])};}};
  vm.runInNewContext(fs.readFileSync(__dirname+'/../web/communication-'+(module==='delivery'?'delivery-v0412':'report')+'.js','utf8'),context);
  let globallyBusy=false;const core={root:new Element(),byId,clone,esc:v=>String(v??''),get:()=>({busy:globallyBusy}),setBusy:v=>globallyBusy=v};
  const ctx={meta:()=>meta,persist(){},session:()=> 'test-session',request:(...args)=>request(...args),documentValue:()=>clone({...doc,...meta}),
    restoreDocument:async value=>{doc=clone(value);meta=clone(value);},runDocument:async value=>{run=clone(value);},runJob:(...args)=>job(...args)};
  const ui=context.window[module==='delivery'?'createCommunicationDeliveryV0412':'createCommunicationReport'](core,ctx);
  return {ui,byId,meta:()=>meta,doc:()=>doc,run:()=>run,busy:()=>globallyBusy,requests,downloads,revoked,setMeta:value=>meta=value,setRequest:fn=>request=fn,setJob:fn=>job=fn};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const lesson={id:'digital',title:'数字实验',objective:'目标',prediction:'预测',steps:['运行'],observations:['BER'],conclusion:'结论',challenge:'挑战',metric:'ber',operator:'<=',threshold:.1,seeds:[42,1042,2042]};
async function main(){let failed=0;async function test(name,fn){try{await fn();console.log('PASS '+name);}catch(error){failed++;console.error('FAIL '+name,error.stack);}}
  await test('course acceptance builds complete graph then runs all seeds while controls are locked',async()=>{
    const f=fixture();await settle();f.setMeta({graph:{globals:{seed:42},edges:[{from:'shared/a',to:'rx/b'}]},delivery:{lesson,records:[],answers:{},courseResult:{passed:true,completed:3,total:3,rows:[]}}});f.ui.render();
    let release,payload;f.setJob(async(kind,value)=>{assert.equal(kind,'workbench-task');payload=clone(value);return new Promise(resolve=>release=resolve);});
    const pending=f.byId('cmDeliveryCheck').onclick();await settle();assert.equal(f.byId('cmDeliveryRecord').disabled,true);assert.equal(f.busy(),true);
    assert.equal(payload.token,'actual-built-token');assert.equal(payload.document.graph.edges.length,1);assert.equal(payload.document.delivery.courseResult,undefined);assert.deepEqual(payload.settings.seeds,[42,1042,2042]);
    release({passed:true,completed:3,total:3,rows:[{seed:42,frame:0,tools:[{kind:'assertion',metric:'ber',value:.012,samples:1000,passed:true}]}]});await pending;
    assert.match(f.byId('cmDeliveryCourseResult').innerHTML,/<td>0.012<\/td>/);assert.equal(f.byId('cmDeliveryRecord').disabled,false);
  });
  await test('named record replay restores complete graph, exact seed, answers and baseline history',async()=>{
    const f=fixture();await settle();const saved={document_schema:2,name:'保存工程',program:{seed:1007,blocks:[]},graph:{globals:{seed:1007},edges:[{from:'x',to:'y'}]},delivery:{answers:{conclusion:'保存结论'}}};
    f.setMeta({delivery:{records:[{id:'baseline',name:'命名基线',seed:1007,document_data:'compressed'}],baseline:'baseline'}});f.setRequest(async(action,payload)=>{assert.equal(action,'delivery-restore');assert.equal(payload.record.id,'baseline');return {document:clone(saved)}});f.ui.render();await f.byId('cmDeliveryReplay').onclick();
    assert.equal(f.run().graph.globals.seed,1007);assert.equal(f.run().graph.edges[0].to,'y');assert.equal(f.meta().delivery.records.length,1);assert.equal(f.meta().delivery.answers.conclusion,'保存结论');assert.equal(f.meta().delivery.baseline,'baseline');
  });
  await test('course answers persist and editing clears prior acceptance',async()=>{
    const f=fixture();await settle();f.setMeta({delivery:{lesson,records:[],answers:{},courseResult:{passed:true,completed:3,total:3,rows:[]}}});f.ui.render();
    f.byId('cmDeliveryPrediction').value='预测更低误码';f.byId('cmDeliveryPrediction').onchange();f.ui.render();assert.equal(f.meta().delivery.answers.prediction,'预测更低误码');f.ui.invalidate();assert.equal(f.meta().delivery.courseResult,undefined);assert.equal(f.byId('cmDeliveryCourseResult').innerHTML,'');
  });
  await test('report preview uses final PDF and persisted material order and captions',async()=>{
    const f=fixture('report');f.setMeta({report:{materials:['b','a'],captions:{b:'真实图注'},conclusion:'实际结论'}});f.setRequest(async()=>({materials:[{id:'a',title:'A'},{id:'b',title:'B'}]}));await f.ui.open();
    assert(f.byId('cmReportMaterials').innerHTML.indexOf('cmReportPick-b')<f.byId('cmReportMaterials').innerHTML.indexOf('cmReportPick-a'));
    assert.match(f.byId('cmReportPreview').innerHTML,/<iframe/);assert.equal(f.requests[0].url,'/api/communications/report-pdf');assert.equal(f.requests[0].payload.session_id,'test-session');
    f.byId('cmReportMaterials').onclick({target:{closest:()=>({dataset:{reportDown:'b'}})}});assert.deepEqual(clone(f.meta().report.materials),['a','b']);assert.equal(f.meta().report.captions.b,'真实图注');
    await f.byId('cmReportDownload').onclick();assert.deepEqual(f.requests.at(-1).payload.document.report.materials,['a','b']);assert.equal(f.downloads[0].href,'blob:pdf-2');assert.equal(f.revoked[0],'blob:pdf-1');
  });
  if(failed)process.exitCode=1;
}
main().catch(error=>{console.error(error);process.exitCode=1;});
