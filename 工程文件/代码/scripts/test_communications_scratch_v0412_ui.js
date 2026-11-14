const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const M=require('../web/communication-graph-model-v0411.js');
let serial=0;
const uid=()=>`copy-${++serial}`;
const block=(id,kind='gain')=>({id,kind,params:{gain:1}});
function graph(){
  const g={schema:1,globals:{seed:42},prefix:[block('source','random_bits'),block('channel','awgn')],
    branches:['rx1','rx2'].map(id=>({id,name:id,blocks:[block('a','rx_isac_ofdm'),block('b'),block('c')]})),
    tail:[block('demod','demod_qpsk'),block('sink','sink')],merge:{domain:'symbols',inputs:['rx1','rx2'],mode:'select',select:0,weights:[.5,.5]},
    analyses:[{id:'cfar1',kind:'analysis_cfar2d',source:'rx1/a',params:{pfa:.001}}],layout:{}};
  g.edges=M.connections(g);return g;
}
let failures=0;
function test(name,fn){try{fn();console.log('PASS '+name);}catch(e){failures++;console.error('FAIL '+name,e.stack);}}
test('a selected segment moves in one canonical operation and one snapshot restores it',()=>{
  const g=graph(),before=M.clone(g);M.reorder(g,['rx1/a','rx1/b'],'rx1',3,{uid});
  assert.deepEqual(M.lane(g,'rx1').map(b=>b.id),['c','a','b']);assert.deepEqual(g.edges,M.connections(g));
  Object.assign(g,before);assert.deepEqual(M.lane(g,'rx1').map(b=>b.id),['a','b','c']);assert.deepEqual(g,graph());
});
test('Ctrl drag copies with independent parameter objects and fresh IDs',()=>{
  const g=graph(),keys=M.reorder(g,['rx1/a','rx1/b'],'rx2',1,{copy:true,uid});
  assert.equal(new Set(M.lane(g,'rx2').map(b=>b.id)).size,5);assert.equal(keys.length,2);
  M.lane(g,'rx2')[1].params.gain=9;assert.equal(M.lane(g,'rx1')[0].params.gain,1);
  assert.equal(g.analyses[0].source,'rx1/a');assert.deepEqual(g.edges,M.connections(g));
});
test('moving between lanes remaps CFAR sources and resolves repeated imported IDs',()=>{
  const g=graph();g.layout=M.arrange(g);const keys=M.reorder(g,['rx1/a','rx2/a'],'shared',2,{uid});
  assert.equal(new Set(g.prefix.map(b=>b.id)).size,4);assert.equal(new Set(keys).size,2);
  assert.equal(g.analyses[0].source,keys[0]);assert(g.edges.some(e=>e.to==='cfar1'&&e.from===keys[0]&&e.output==='power'));
  assert.equal(g.layout['rx1/a'],undefined);assert.equal(g.layout['rx2/a'],undefined);assert(Object.keys(g.layout).every(key=>M.nodes(g).some(n=>n.key===key)));
});
test('deleting selected receivers preserves lane connections and removes dependent analysis',()=>{
  const g=graph();M.remove(g,['rx1/a','rx1/b']);assert.deepEqual(M.lane(g,'rx1').map(b=>b.id),['c']);
  assert.equal(g.analyses.length,0);assert.deepEqual(g.edges,M.connections(g));
  assert.throws(()=>M.remove(g,['rx1/c']),/至少一个/);assert.throws(()=>M.remove(g,['tail/sink']),/信宿/);
});
test('sink remains last and each parallel slot keeps an executable sequence',()=>{
  const g=graph();assert.throws(()=>M.reorder(g,['tail/sink'],'rx1',0,{uid}),/信宿/);
  assert.throws(()=>M.reorder(g,['rx1/a','rx1/b','rx1/c'],'rx2',0,{uid}),/至少一个/);
  M.reorder(g,['rx1/b'],'tail',100,{uid});assert.equal(g.tail.at(-1).kind,'sink');
});
test('linear segment copy and move keep order, unique IDs and final sink',()=>{
  const p={blocks:[block('a'),block('b'),block('c'),block('sink','sink')]};
  M.editBlocks(p,['b','c'],0,{uid});assert.deepEqual(p.blocks.map(b=>b.id),['b','c','a','sink']);
  const ids=M.editBlocks(p,['b','c'],100,{copy:true,uid});assert.equal(ids.length,2);assert.equal(p.blocks.at(-1).kind,'sink');
  assert.equal(new Set(p.blocks.map(b=>b.id)).size,p.blocks.length);p.blocks[3].params.gain=8;assert.equal(p.blocks[0].params.gain,1);
});
test('view metadata and auto-arrange preserve numerical graph identity',()=>{
  const g=graph(),key=M.numericKey(g),document={graph:g,scratch:{zoom:1,notes:{},groups:[],collapsed:{}}};
  g.layout=M.arrange(g);document.scratch.zoom=.7;document.scratch.notes['rx1/a']='接收观测';
  document.scratch.groups.push({id:'group1',name:'均衡器',keys:['rx1/b','rx1/c']});document.scratch.collapsed.group1=true;
  assert.equal(M.numericKey(g),key);assert.deepEqual(JSON.parse(JSON.stringify(document)).scratch,document.scratch);
});
test('conversion and projection retain tools with exact valid observation scopes',()=>{
  const g=graph(),tools=[{id:'probe',kind:'probe',source:'linear/a'},{id:'reference',kind:'reference',source:'linear/demod',reference:'linear/source'},{id:'metrics',kind:'metrics',metrics:['merged.ber']}];
  const converted=M.remapTools(tools,g,'rx1');assert.equal(converted[0].source,'rx1/a');assert.equal(converted[1].source,'tail/demod');assert.equal(converted[1].reference,'shared/source');
  assert.deepEqual(M.remapTools(converted,g,'rx1',false),tools);
  converted.push({id:'other',kind:'probe',source:'rx2/b'},{id:'condition',kind:'assertion',metric:'rx1.ber',operator:'<=',value:.1});
  const projected=M.remapTools(converted,g,'rx1',false);assert.equal(projected.find(t=>t.id==='other'),undefined);assert.equal(projected.find(t=>t.id==='condition').metric,'merged.ber');
});
test('production dragover accepts palette copies and graph move or Ctrl copy',()=>{
  const source=fs.readFileSync(__dirname+'/../web/communication-graph-v0411.js','utf8'),handler=source.split('\n').find(line=>line.includes("byId('cmGraphStage').ondragover=")),stage={};let cleared=0;
  vm.runInNewContext(handler,{byId:()=>stage,get:()=>({busy:false}),dropTarget:()=>({id:'shared',card:null}),clearDrop:()=>cleared++});
  for(const [type,ctrlKey,allowed,expected] of [['application/x-ocean-communication',false,'copy','copy'],['application/x-ocean-graph',false,'copyMove','move'],['application/x-ocean-graph',true,'copyMove','copy']]){
    let accepted=false;const e={ctrlKey,dataTransfer:{types:[type],effectAllowed:allowed,dropEffect:'none'},preventDefault(){accepted=true;},stopPropagation(){}};stage.ondragover(e);
    assert.equal(accepted,true);assert.equal(e.dataTransfer.dropEffect,expected);assert(allowed.toLowerCase().includes(expected));
  }
  assert.equal(cleared,3);
});
if(failures)process.exitCode=1;
