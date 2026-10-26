/* Actual waveform instrument lifecycle and result ownership. */
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../web/communication-waveform.js'),'utf8');
function fixture(){
  const elements=new Map();let download;
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.value='';this.disabled=false;this.clientWidth=700;this.children=[];}
    set innerHTML(html){this.html=html;for(const m of html.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)){if(!elements.has(m[2]))elements.set(m[2],new Element(m[1]));}if(this.tagName==='SELECT')this.value=/<option value="([^"]*)"/.exec(html)?.[1]||'';}
    get innerHTML(){return this.html||'';}append(v){this.children.push(v)}addEventListener(){}getContext(){return new Proxy({},{get:()=>()=>{}})}
  }
  const byId=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
  const state={busy:false,definitions:{rx_burst_sync:{label:'同步'},tx_dpd_fit:{label:'逆模型'},tx_memory_pa:{label:'功放'}}};
  const context={window:{addEventListener(){}},document:{createElement:tag=>new Element(tag)},devicePixelRatio:1};vm.runInNewContext(source,context);
  const ui=context.window.createCommunicationWaveform({byId,esc:String,get:()=>state,download:(name,value)=>{download={name,value}}},{});
  return {ui,byId,state,download:()=>download};
}
let failures=0;
function test(name,run){try{run();console.log('PASS '+name)}catch(error){failures++;console.error('FAIL '+name+': '+error.stack)}}
test('synchronization view displays measured estimates and exports the current result',()=>{
  const f=fixture();f.ui.onResult({advanced:{wireless:{rx_burst_sync:{detected:true,offsets:[0,1,2],timing_metric:[0,.1,1],correlation:[0,.1,.8],start_sample:2,frequency_hz:37,clock_ppm:350,marker_error:.001,marker_positions:[2,1100],payload_samples:970,method:'Schmidl–Cox'}}}});
  assert.equal(f.byId('cmWaveformView').value,'sync');assert.match(f.byId('cmWaveformCaption').textContent,/37 Hz.*350 ppm/);
  f.byId('cmWaveformExport').onclick();assert.equal(JSON.parse(f.download().value)[0].value.frequency_hz,37);
});
test('Polar path view uses the decoder history and clears old results on invalidation',()=>{
  const f=fixture();f.ui.onResult({advanced:{codecs:[{kind:'polar_decode',n:128,k:64,list_size:8,codewords:2,failed_codewords:0,seconds:.03,learning:{kind:'polar',history:[{bit:0,frozen:true,path_metrics:[.1]},{bit:1,frozen:false,path_metrics:[.2,.6]}]}}]}});
  assert.equal(f.byId('cmWaveformView').value,'polar');assert.match(f.byId('cmWaveformCaption').textContent,/CRC 通过 2\/2/);assert.match(f.byId('cmWaveformTable').innerHTML,/冻结位/);
  f.ui.invalidate();assert.equal(f.byId('cmWaveformStage').innerHTML,'');assert.equal(f.byId('cmWaveformExport').disabled,true);
});
test('DPD coefficient and PA plots share actual measured arrays',()=>{
  const f=fixture();f.ui.onResult({advanced:{wireless:{tx_dpd_fit:{fit_error:.01,coefficients_i:[1,.2],coefficients_q:[0,.01]},tx_memory_pa:{input_amplitude:[0,1,2],output_amplitude:[0,.9,1.5],output_phase_deg:[0,1,4]}}}});
  f.byId('cmWaveformStage').value='tx_dpd_fit';f.byId('cmWaveformStage').onchange();assert.equal(f.byId('cmWaveformView').value,'coefficients');assert.match(f.byId('cmWaveformCaption').textContent,/0.010000/);
  f.byId('cmWaveformStage').value='tx_memory_pa';f.byId('cmWaveformStage').onchange();assert.equal(f.byId('cmWaveformView').value,'amplitude');f.byId('cmWaveformView').value='phase';assert.doesNotThrow(()=>f.byId('cmWaveformView').onchange());
  f.ui.buttons(true);assert.equal(f.byId('cmWaveformExport').disabled,true);
});
if(failures)process.exitCode=1;
