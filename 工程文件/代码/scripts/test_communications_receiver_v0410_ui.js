/* Verify measured trace selection, result ownership, export and busy lifecycle. */
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../web/communication-receiver-v0410.js'),'utf8');
function fixture(){
  const elements=new Map();let downloaded;
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.value='';this.disabled=false;this.clientWidth=800;this.children=[];}
    set innerHTML(html){this.html=html;for(const match of html.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)){if(!elements.has(match[2]))elements.set(match[2],new Element(match[1]));}if(this.tagName==='SELECT')this.value=/<option value="([^"]*)"/.exec(html)?.[1]||'';}
    get innerHTML(){return this.html||'';}append(v){this.children.push(v);}querySelectorAll(){return [...elements.values()].filter(e=>['SELECT','INPUT','BUTTON'].includes(e.tagName));}
    getContext(){return new Proxy({},{get:()=>()=>{}});}
  }
  const byId=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const state={busy:false,result:null,definitions:{rx_mlse:{label:'MLSE'},rx_music:{label:'MUSIC'},tdl_channel:{label:'TDL'}}},meta={};
  const context={window:{devicePixelRatio:1,addEventListener(){}},document:{createElement:tag=>new Element(tag)}};vm.runInNewContext(source,context);
  const ui=context.window.createCommunicationReceiverV0410({byId,esc:String,get:()=>state,download:(name,value)=>{downloaded={name,value};}},{meta:()=>meta});
  return {ui,byId,state,meta,downloaded:()=>downloaded};
}
let failures=0;
function test(name,run){try{run();console.log('PASS '+name);}catch(error){failures++;console.error('FAIL '+name+': '+error.stack);}}
test('MLSE controls inspect actual per-step metrics and survivor states',()=>{
  const f=fixture(),value={training_symbols:128,estimated_noise_variance:.02,channel_estimate:{i:[1,.5],q:[0,.2]},mlse:{state_count:2,branch_count:4,metric_evaluations:80,sequence_metric:1.2,metric_history:[[0,3],[2,0]],predecessors:[[0,0],[1,0]],survivor_states:[0,1],input_indices:[0,1],initial_state:0,steps:20,trace_steps:2}};
  f.ui.onResult({advanced:{wireless:{rx_mlse:value}}});assert.equal(f.byId('cmReceiver410View').value,'metrics');assert.match(f.byId('cmReceiver410Caption').textContent,/80 次距离计算/);
  f.byId('cmReceiver410Step').value='1';f.byId('cmReceiver410Step').oninput();assert.match(f.byId('cmReceiver410Caption').textContent,/步骤 2/);assert.match(f.byId('cmReceiver410Table').innerHTML,/<td>1<\/td><td>0<\/td><td>0<\/td><td>●/);
  for(const view of ['path','taps']){f.byId('cmReceiver410View').value=view;assert.doesNotThrow(()=>f.byId('cmReceiver410View').onchange());}
  f.byId('cmReceiver410Export').onclick();assert.deepEqual(JSON.parse(f.downloaded().value),{kind:'rx_mlse',value});
});
test('MUSIC target and automatic beam charts use the supplied receive observation',()=>{
  const f=fixture(),music={angles:[-30,0,17.5,30],spectrum_db:[-5,-20,0,-18],estimated_angles:[-30,17.5],target_angle:17.5,target_index:1,pilot_coefficients:{i:[.01,1],q:[.02,.1]},eigenvalues:[.01,.02,1,9],subarray_length:4,source_count:2,snapshots:1024};
  const result={advanced:{wireless:{rx_music_mvdr:{music,beam_pattern:{angles:[-30,0,17.5,30],db:[[-45,-8,0,-10]]},rejection_db:31}}}};f.state.result=result;f.ui.render();
  assert.match(f.byId('cmReceiver410Caption').textContent,/17.500°/);assert.match(f.byId('cmReceiver410Table').innerHTML,/<td>17.500<\/td><td>1<\/td><td>0.10000<\/td><td>●/);
  for(const view of ['eigenvalues','beam']){f.byId('cmReceiver410View').value=view;assert.doesNotThrow(()=>f.byId('cmReceiver410View').onchange());}
  assert.match(f.byId('cmReceiver410Caption').textContent,/31 dB/);f.ui.buttons(true);assert.equal(f.byId('cmReceiver410Export').disabled,true);f.ui.buttons(false);assert.equal(f.byId('cmReceiver410Export').disabled,false);
});
test('TDL frame trajectories retain sample indices and reset on replacement',()=>{
  const f=fixture(),value={profile:'TDL-A',delays_ns:[0,100],delays_samples:[0,.3],powers_db:[0,-3],powers:[.666,.334],measured_path_power:[.7,.3],rms_delay_ns:47,doppler_hz:5,interpolation:'17 点 Kaiser 窗 sinc',filter_delay_samples:8,guard_samples:16,sample_indices:[1000,1010],path_gains:{i:[[1,.1],[.8,.2]],q:[[0,.2],[.1,.3]]},processed_samples:1200};
  f.ui.onResult({advanced:{wireless:{tdl_channel:value}}});assert.match(f.byId('cmReceiver410Caption').textContent,/TDL-A.*47 ns/);f.byId('cmReceiver410View').value='fading';f.byId('cmReceiver410Path').value='1';f.byId('cmReceiver410Path').onchange();assert.match(f.byId('cmReceiver410Caption').textContent,/路径 2.*1200 点/);
  f.byId('cmReceiver410Export').onclick();assert.deepEqual(JSON.parse(f.downloaded().value).value.sample_indices,[1000,1010]);f.ui.replaceProgram();assert.equal(f.byId('cmReceiver410Stage').innerHTML,'');assert.equal(f.byId('cmReceiver410Export').disabled,true);assert.equal(f.byId('cmReceiver410Table').innerHTML,'');
});
if(failures)process.exitCode=1;
