/* Exercise board selection, source mapping and real-device result handling with controlled USB responses. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../web/communication-board.js'), 'utf8');

function fixture(hostname = 'localhost') {
  const fields = new Map(), cards = new Map(), events = new Map(), calls = [];
  class Element {
    constructor() {
      this.dataset = {}; this.value = ''; this.hidden = false; this.disabled = false;
      this.rows = []; this.attrs = {}; this.classes = new Set();
      this.classList = {add:k=>this.classes.add(k), remove:k=>this.classes.delete(k),
        toggle:(k,on)=>on?this.classes.add(k):this.classes.delete(k)};
    }
    set id(v) {this._id=v;fields.set(v,this);}
    get id() {return this._id;}
    set innerHTML(html) {
      this.html=html;
      this.rows = [...html.matchAll(/data-board-block="([^"]+)"/g)].map(m=>{
        const el=new Element();el.dataset.boardBlock=m[1];return el;
      });
      if (html.includes('<option')) this.value=/<option value="([^"]*)"/.exec(html)[1];
    }
    get innerHTML(){return this.html || '';}
    after() {}
    closest(){return null;}
    focus() {}
    scrollIntoView(){this.located=true;}
    setAttribute(k,v){this.attrs[k]=v;}
    removeAttribute(k){delete this.attrs[k];}
    querySelector(){return null;}
    querySelectorAll(selector){return selector==='[data-cm-id]'?[...cards.values()]:selector==='[data-board-block]'?this.rows:[];}
    addEventListener(name,fn){events.set(name,fn);}
  }
  function byId(id) {if(!fields.has(id)){const el=new Element();el.id=id;}return fields.get(id);}
  const field = name=>byId('cmBoard'+name);
  field('Panel').hidden=true;field('Language').value='cpp';field('Target').value='pico';
  const root=new Element(); root.dataset.mobilePane='chain';
  const state={selectedId:'s',program:{blocks:[{id:'s',kind:'source'},{id:'z',kind:'sink'}]},busy:false,
    definitions:{source:{label:'信源'},sink:{label:'信宿'}}};
  for(const b of state.program.blocks){const e=new Element();e.dataset.cmId=b.id;cards.set(b.id,e);}
  const sample=(board,language)=>({language,board,experiment:'uart',entry_file:'main',files:{main:'input\noutput',notes:'readme'},
    source_map:{s:{file:'main',start:1,end:1},z:{file:'main',start:2,end:2}},
    steps:[{id:'s',label:'信源'},{id:'z',label:'信宿'}],expected:{nodes:{s:[1,0],z:[1,0]}}});
  let response=async(name,body)=>{
    if(name==='generate')return sample(body.board,body.language);
    if(name==='devices')return {devices:[{id:'serial:A',kind:'serial',label:'COM8'},{id:'bootsel:B',kind:'bootsel',label:'RPI-RP2'}],tools:{serial:true}};
    if(name==='build')return {build_id:'fw-1',filename:'board.uf2',size:1024};
    if(name==='deploy')return {status:'written'};
    if(name==='run')return {device_id:body.device_id,status:'timeout',nodes:{s:[1,0]},metrics:{compared_bits:0,ber:null,bit_errors:0,received_frames:0,expected_frames:1,lost_frames:1}};
  };
  let confirmation=true, ui;
  const runtime={window:{confirm:()=>confirmation},location:{hostname},TextDecoder,document:{createElement:()=>new Element()},
    matchMedia:()=>({matches:false}),setTimeout:()=>1,clearTimeout(){},
    fetch:async(url,options)=>{
      const name=url.split('/board-')[1],body=JSON.parse(options.body);calls.push({name,body});
      const data=await response(name,body);
      return {ok:!data.error, status:data.error?400:200, json:async()=>data};
    }};
  vm.runInNewContext(source,runtime);
  const core={root,byId,get:()=>state,esc:v=>String(v),setBusy(v){state.busy=v;ui.buttons();},
    selectBlock(id){state.selectedId=id;events.get('cm-select')();}};
  ui=runtime.window.createCommunicationBoard(core,{meta:()=>({}),documentValue:()=>({document_schema:2,program:state.program})});
  byId('cmBoardOpen').onclick();
  return {field,ui,state,calls,cards,sample,core,generate:()=>field('Generate').onclick(),
    setResponse:v=>response=v,allow:v=>confirmation=v};
}
test('block selection and source rows link both ways and alternate files remain selectable',async()=>{
  const f=fixture();await f.generate();
  assert.equal(f.field('NodeTitle').textContent,'信源 输出');
  const rows=f.field('Code').rows;assert.equal(rows[0].classes.has('selected'),true);
  f.field('Code').onclick({target:{closest:()=>rows[1]}});
  assert.equal(f.state.selectedId,'z');assert.equal(f.cards.get('z').located,true);
  assert.equal(rows[1].classes.has('selected'),true);
  f.field('File').value='notes';f.field('File').onchange();assert.match(f.field('Code').innerHTML,/readme/);
  f.core.selectBlock('s');assert.equal(f.field('File').value,'main');
});
test('new targets supersede pending source requests and failed nodes are located',async()=>{
  const f=fixture();let release;
  f.setResponse(()=>new Promise(resolve=>release=resolve));const first=f.generate();
  f.field('Target').value='pico_w';f.field('Language').value='micropython';f.ui.render();
  f.setResponse(async()=>({error:'调整该积木',block_ids:['s']}));await f.generate();
  release(f.sample('pico','cpp'));await first;
  assert.equal(f.field('Source').hidden,true);assert.equal(f.field('Status').textContent,'调整该积木');
  assert.match(f.field('Issues').innerHTML,/定位 信源/);assert.equal(f.cards.get('s').classes.has('cm-board-issue'),true);
  assert.equal(f.calls.at(-1).body.language,'micropython');assert.equal(f.calls.at(-1).body.board,'pico_w');
});
test('C++ uses a selected boot drive and matching build then measures through a serial port',async()=>{
  const f=fixture();await f.generate();await f.field('Refresh').onclick();
  f.field('Device').value='bootsel:B';f.field('Device').onchange();assert.equal(f.field('Deploy').disabled,true);
  await f.field('Build').onclick();assert.equal(f.field('Deploy').disabled,false);
  assert.match(f.field('Firmware').href,/fw-1$/);assert.equal(f.field('Measure').disabled,true);
  f.allow(false);await f.field('Deploy').onclick();assert.equal(f.calls.some(c=>c.name==='deploy'),false);
  f.allow(true);await f.field('Deploy').onclick();
  assert.equal(f.calls.find(c=>c.name==='deploy').body.build_id,'fw-1');
  f.field('Device').value='serial:A';f.field('Device').onchange();
  assert.equal(f.field('Deploy').disabled,true);assert.equal(f.field('Measure').disabled,false);
  await f.field('Measure').onclick();
  assert.match(f.field('Status').textContent,/超时/);assert.match(f.field('Metrics').innerHTML,/无可比较数据/);
  assert.equal(f.field('Actual').textContent,'1 0');
  f.core.selectBlock('z');assert.equal(f.field('Actual').textContent,'本次未收到样本');
  f.field('Device').value='bootsel:B';f.field('Device').onchange();
  assert.equal(f.field('Result').hidden,true);assert.equal(f.field('Actual').textContent,'待板端实测');
});
test('MicroPython selects the right interpreter and changing project clears measurements and firmware',async()=>{
  const f=fixture();await f.generate();await f.field('Refresh').onclick();await f.field('Build').onclick();
  f.field('Language').value='micropython';f.field('Target').value='pico_w';f.ui.render();
  assert.equal(f.field('Firmware').hidden,true);await f.generate();
  f.field('Device').value='serial:A';f.field('Device').onchange();
  assert.equal(f.field('Build').hidden,true);assert.match(f.field('FirmwareHelp').href,/RPI_PICO_W\//);
  assert.equal(f.field('Deploy').textContent,'上传程序');assert.equal(f.field('Deploy').disabled,false);
  await f.field('Measure').onclick();assert.equal(f.field('Result').hidden,false);
  f.state.program.blocks[0].params={pattern:'01'};f.ui.invalidate();
  assert.equal(f.field('Result').hidden,true);assert.equal(f.field('Source').hidden,true);
});
test('remote users can generate and download code while device calls stay local',async()=>{
  const f=fixture('example.test');await f.generate();await f.field('Refresh').onclick();
  assert.equal(f.calls.some(c=>c.name==='devices'),false);assert.equal(f.field('Build').disabled,true);
  assert.equal(f.field('Export').disabled,false);assert.match(f.field('Tools').textContent,/本地工作台/);
});
test('an unsuccessful regeneration discards the previous source and firmware',async()=>{
  const f=fixture();await f.generate();await f.field('Build').onclick();
  f.setResponse(async()=>({error:'无法生成当前工程'}));await f.generate();
  assert.equal(f.field('Source').hidden,true);assert.equal(f.field('Export').disabled,true);
  assert.equal(f.field('Firmware').hidden,true);assert.equal(f.field('Build').disabled,true);
});

test('QPSK keeps both axes and shows the chosen symbol before and after a measurement',async()=>{
  const f=fixture();
  const s=Math.SQRT1_2;
  const base=f.sample('pico','cpp');
  const iq=[[s,s],[s,-s],[-s,-s],[-s,s]];
  base.steps[0]={id:'s',kind:'mod_qpsk',label:'QPSK 调制',format:'iq'};
  base.experiment='qpsk';base.expected.nodes.s=iq;
  f.setResponse(async name=>name==='generate'?base:
    name==='devices'?{devices:[{id:'serial:A',kind:'serial',label:'COM8'}],tools:{}}:
    {device_id:'serial:A',nodes:{s:iq,z:[1,0]},status:'ok',matches_reference:true,
      metrics:{compared_bits:2,bit_errors:0,ber:0,received_frames:1,lost_frames:0,expected_frames:1}});
  await f.generate();
  f.field('Index').value=4;f.field('Index').onchange();
  assert.equal(f.field('Symbols').hidden,false);
  assert.match(f.field('ReferenceDetail').textContent,/I = -0.707107  Q = 0.707107  判决比特 10/);
  assert.equal(f.field('MeasuredDetail').textContent,'待板端实测');
  await f.field('Refresh').onclick();f.field('Device').value='serial:A';f.field('Device').onchange();
  await f.field('Measure').onclick();
  assert.match(f.field('MeasuredDetail').textContent,/判决比特 10/);
  assert.match(f.field('Scatter').innerHTML,/绿点 板端/);
});

test('Hamming displays the received codeword, syndrome and recovered data',async()=>{
  const f=fixture(),base=f.sample('pico','cpp');
  base.steps[1]={id:'z',kind:'hamming_decode',label:'Hamming 译码',format:'bits'};
  base.expected={nodes:{s:[0,1,1,0,1,1,1],z:[1,0,1,1]},syndromes:{z:[5]}};
  f.setResponse(async()=>base);await f.generate();f.core.selectBlock('z');
  assert.match(f.field('ReferenceDetail').textContent,/收到 0110111  综合征 5  纠正第 5 位  数据 1011/);
});

test('UTF-8 text is decoded from the selected node bits including the sink',async()=>{
  const f=fixture(),base=f.sample('pico','cpp');
  const bits=Array.from(Buffer.from('你好，Pico'),byte=>byte.toString(2).padStart(8,'0')).join('').split('').map(Number);
  f.state.program.blocks[0].kind='text';f.state.definitions.text={category:'source',label:'文本信源'};
  base.steps[0].kind='text';base.steps[1].kind='sink';base.expected.nodes={s:bits,z:bits};
  f.setResponse(async()=>base);await f.generate();f.core.selectBlock('z');
  assert.equal(f.field('ReferenceDetail').textContent,'你好，Pico');
  assert.equal(f.field('MeasuredDetail').textContent,'待板端实测');
});

test('dual deployment binds each build to its own role and compares the reported UART frame', async()=>{
  const f=fixture(), base=f.sample('pico','cpp');
  f.state.program.blocks.splice(1,0,{id:'link',kind:'uart_link'});
  for(const [role,name] of [['tx','pico'],['rx','esp32s3']]){
    f.field(role+'Target').value=name;
    f.field(role+'Language').value='cpp';
  }
  const ep={source_map:{},files:{}};
  const pair={...base, experiment:'link', endpoints:{tx:ep,rx:ep}};
  const ports=[{id:'B',family:'pico',kind:'bootsel',label:'BOOTSEL'},
    {id:'P',family:'pico',kind:'serial',label:'P USB'},
    {id:'E',family:'esp32s3',kind:'serial',label:'E USB'}];
  f.setResponse(async(name,body)=>{
    if(name==='generate')return pair;
    if(name==='devices')return {tools:{esp_idf:true},devices:ports};
    if(name==='build')return {build_id:body.role,filename:'board.bin',size:123};
    if(name==='deploy')return {status:'written'};
    return {status:'crc_error',device_ids:body.device_ids,nodes:{},matches_reference:false,
      frame:{sequence:5,rx_sequence:5,crc_ok:false,crc16:0x1111,sent:[1,0],received:[0,0],status:'crc_error'},
      metrics:{received_frames:0,expected_frames:1,lost_frames:1,compared_bits:0,bit_errors:0,ber:null}};
  });
  await f.generate();
  assert.equal(f.field('SingleTargets').hidden,true);
  assert.equal(f.calls.at(-1).body.targets.rx.board,'esp32s3');
  await f.field('Refresh').onclick();
  f.field('rxDevice').value='E';f.field('rxDevice').onchange();
  await f.field('rxBuild').onclick(); await f.field('rxDeploy').onclick();
  const write=f.calls.find(c=>c.name==='deploy').body;
  assert.equal(write.role,'rx');assert.equal(write.device_id,'E');assert.equal(write.build_id,'rx');
  assert.equal(f.field('txDeploy').disabled,true);
  f.field('txDevice').value='P';f.field('txDevice').onchange();
  assert.equal(f.field('Measure').disabled,false);await f.field('Measure').onclick();
  assert.match(f.field('Frame').innerHTML,/CRC 错误  0x1111/);
  assert.match(f.field('Frame').innerHTML,/接收  0 0/);
  f.field('rxTarget').value='pico';f.field('rxTarget').onchange();
  assert.equal(f.field('Result').hidden,true);
  f.field('rxDevice').value='P';f.field('rxDevice').onchange();await f.generate();
  assert.equal(f.field('Measure').disabled,true);
});
