/* Frame, Turbo and IR measurements retain ownership through UI lifecycle. */
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../web/communication-framing-v0410.js'),'utf8');
function fixture(){
  const elements=new Map();let download;
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.value='';this.disabled=false;this.clientWidth=320;this.children=[];this.handlers={};}
    set innerHTML(html){this.html=html;for(const match of html.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)){if(!elements.has(match[2]))elements.set(match[2],new Element(match[1]));const e=elements.get(match[2]),v=/\bvalue="([^"]*)"/.exec(match[0]);if(v)e.value=v[1];}if(this.tagName==='SELECT')this.value=/<option value="([^"]*)"/.exec(html)?.[1]||'';}
    get innerHTML(){return this.html||'';}append(v){this.children.push(v);}querySelectorAll(){return [...elements.values()].filter(e=>['SELECT','INPUT','BUTTON'].includes(e.tagName));}
    addEventListener(type,fn){this.handlers[type]=fn;}getContext(){return new Proxy({},{get:()=>()=>{}});}
  }
  const byId=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const state={busy:false,result:null},meta={},root=new Element();const context={window:{addEventListener(){}},devicePixelRatio:1,document:{createElement:tag=>new Element(tag)}};
  vm.runInNewContext(source,context);const ui=context.window.createCommunicationFramingV0410({root,byId,esc:String,get:()=>state,download:(name,value)=>{download={name,value};}},{meta:()=>meta});
  return {ui,byId,state,meta,root,download:()=>download};
}
let failures=0;function test(name,fn){try{fn();console.log('PASS '+name);}catch(e){failures++;console.error('FAIL '+name+': '+e.stack);}}
test('protected receive headers use observed positions and capture failure',()=>{
  const f=fixture(),value={kind:'self_frame_rx',total_bits:16,received_bits:8,accepted_packets:1,complete_payload:false,frames:[{sequence:0,start_sample:23,end_sample:450,payload_bits:8,offset_bits:0,mcs_name:'BPSK',header_crc_pass:true,payload_crc_pass:false},{sequence:1,start_sample:490,end_sample:909,payload_bits:8,offset_bits:8,mcs_name:'QPSK',header_crc_pass:true,payload_crc_pass:true}]};
  f.ui.onResult({advanced:{wireless:{rx_self_frame:value}}});assert.match(f.byId('cmFramingTable').innerHTML,/<td>23<\/td>/);assert.match(f.byId('cmFramingTable').innerHTML,/校验失败/);assert.match(f.byId('cmFramingCaption').textContent,/来自接收波形/);
  f.byId('cmFramingExport').onclick();assert.deepEqual(JSON.parse(f.download().value)[0].value,value);f.ui.buttons(true);assert.equal(f.byId('cmFramingExport').disabled,true);f.ui.invalidate();assert.equal(f.byId('cmFramingTable').innerHTML,'');
});
test('Turbo step controls and saved project restore own actual traces',()=>{
  const f=fixture(),value={kind:'turbo_decode',algorithm:'Log-MAP',iterations:2,block_size:32,codewords:1,learning:{kind:'turbo',history:[{iteration:1,prior:[0,0],extrinsic:[2,-3],posterior:[4,-6],changed_bits:2,mean_abs_posterior:5},{iteration:2,prior:[1,-1],extrinsic:[4,-5],posterior:[7,-9],changed_bits:0,mean_abs_posterior:8}]}};
  f.meta.result={advanced:{codecs:[value]}};f.ui.render();assert.equal(f.byId('cmFramingView').value,'turbo');f.byId('cmFramingNext').onclick();assert.match(f.byId('cmFramingCaption').textContent,/第 2 \/ 2 轮/);assert.match(f.byId('cmFramingTable').innerHTML,/<td>7<\/td>/);
  f.meta.result=null;f.ui.replaceProgram();assert.equal(f.byId('cmFramingStage').innerHTML,'');
});
test('protocol event shows real RV and mother-buffer coverage',()=>{
  const f=fixture(),result={config:{mode:'ir_harq'},events:[{packet:0,attempt:1,rv:0,coded_bits:6,mother_bits:8,mother_indices:[0,1,2,4,5,6],mother_coverage:.75,llr_buffer:[2,3,-1,0,4,-2,1,0],symbols:3,accumulated_tx_energy:3,tx_energy:3,crc_pass:false}]};
  f.root.handlers['cm-protocol-result']({detail:result});assert.equal(f.byId('cmFramingView').value,'harq');assert.match(f.byId('cmFramingCaption').textContent,/RV 0/);assert.match(f.byId('cmFramingTable').innerHTML,/75%/);
  f.byId('cmFramingExport').onclick();assert.deepEqual(JSON.parse(f.download().value)[0].value.events[0].llr_buffer,result.events[0].llr_buffer);
});
if(failures)process.exitCode=1;
