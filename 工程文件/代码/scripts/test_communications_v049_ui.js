/* Reuse the v048 DOM fixture while exercising the production v049 panel. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let fixtureSource=fs.readFileSync(__dirname+'/test_communications_experiments_ui.js','utf8').split('async function main(){')[0];
fixtureSource=fixtureSource.replace('setProgram(value){current.program=clone(value);ui.replaceProgram();}',"restoreResult(built,value){current.compiled=built;current.result=value;},setProgram(value){if(current.busy)return;current.program=clone(value);ui.replaceProgram();}");
const context={require,__dirname,console};vm.runInNewContext(fixtureSource,context);
const fixture=context.fixture,clone=v=>JSON.parse(JSON.stringify(v));
function layoutIntegration(){
  const elements=new Map();let root;
  class Node{
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.className='';this.hidden=false;this.parentElement=null;this.classList={add:name=>this.className+=' '+name};}
    set id(value){this._id=value;elements.set(value,this)}get id(){return this._id}
    append(...nodes){for(const node of nodes){if(node.parentElement)node.parentElement.children=node.parentElement.children.filter(v=>v!==node);node.parentElement=this;this.children.push(node)}}
    before(node){const parent=this.parentElement;if(!parent)return;if(node.parentElement)node.parentElement.children=node.parentElement.children.filter(v=>v!==node);parent.children.splice(parent.children.indexOf(this),0,node);node.parentElement=parent;}
    setAttribute(key,value){if(key==='class')this.className=value;else this[key]=value;}
    get firstElementChild(){return this.children[0]}get lastElementChild(){return this.children.at(-1)}
    matches(selector){return selector.startsWith('.')?this.className.split(/\s+/).includes(selector.slice(1)):this.tagName.toLowerCase()===selector;}
    closest(selector){for(let e=this;e;e=e.parentElement)if(e.matches(selector))return e;return null;}
    querySelectorAll(selector){return this.children.flatMap(e=>[...(e.matches(selector)?[e]:[]),...e.querySelectorAll(selector)])}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null}
    set innerHTML(html){this.children=[];const stack=[this];for(const match of html.matchAll(/<(\/)?([\w-]+)([^>]*)>/g)){if(match[1]){if(stack.length>1)stack.pop();continue;}const e=new Node(match[2]);for(const a of match[3].matchAll(/([\w-]+)="([^"]*)"/g))e.setAttribute(a[1],a[2]);stack.at(-1).append(e);if(!['input','br','hr','img'].includes(match[2]))stack.push(e);}}
  }
  root=new Node('section');const byId=id=>{if(!elements.has(id)){const label=new Node('label'),e=new Node('input');e.id=id;label.append(e);root.append(label)}return elements.get(id)};
  const projectbar=new Node('div');projectbar.className='cm-project-bar';root.append(projectbar);
  const settings=new Node('details');settings.className='cm-settings';settings.innerHTML='<summary>参数</summary>';root.append(settings);
  const sandbox={document:{createElement:tag=>new Node(tag)},window:{},byId,root,matchMedia:()=>({matches:false}),core:{root,byId,esc:v=>v,get:()=>({})}};
  const experience=fs.readFileSync(__dirname+'/../web/communication-experience.js','utf8');
  const project=experience.slice(experience.indexOf('  const projectPanel='),experience.indexOf("  const paletteTools="));
  const execution=experience.slice(experience.indexOf('  const executionPanel='),experience.indexOf('  const rf='));
  vm.createContext(sandbox);vm.runInContext(project+execution,sandbox);
  const layout=fs.readFileSync(__dirname+'/../web/communication-layout.js','utf8');
  vm.runInContext(layout.slice(0,layout.indexOf('  const mobile='))+'};window.createCommunicationLayout(core);',sandbox);
  const controls=elements.get('cmExecutionTools'),debug=root.querySelector('.cm-debug-menu');
  assert.ok(debug&&controls.closest('.cm-debug-menu')===debug);
  assert.equal(root.querySelector('.cm-projects').hidden,true);
  for(const id of ['cmBreakpointRun','cmJobResume']){assert.ok(elements.get(id));for(let e=elements.get(id);e;e=e.parentElement)assert.equal(e.hidden,false,id+' remains outside the hidden project panel');}
}
function batch(p){return {programs:[p,clone(p)],names:['基线','优化'],settings:{},mode:'link',completed:4,total:4,complete:true,latency_reference:'帧时长',
  summaries:[{program_index:0,name:'基线',runs:2,ber:.1,ber_interval:[.05,.2]},{program_index:1,name:'优化',runs:2,ber:.02,ber_interval:[.005,.06]}],
  rows:[0,1].flatMap(i=>[42,143].map((seed,j)=>({program_index:i,name:i?'优化':'基线',seed,base_seed:j?142:42,frame:j+1,runtime_seconds:.01,metrics:{ber:i?.02:.1,bit_errors:i?2:10,bit_count:100,net_bit_rate:1000+i*100,frame_duration_seconds:.1-i*.01}})))};}
function submission(p){return {submission_schema:1,student:'同学甲',notes:'初始记录',program:clone(p),active_stage:0,attempts:[],stages:[null,null],hint_events:[],task:{title:'阶段任务',objective:'观察并改善传输',initial_program:clone(p),editable:['blocks.noise.esn0_db'],seeds:[42],stages:[{name:'观察误码',hint:'观察星座',weight:1,goals:[{metric:'ber',operator:'<=',value:.1}]},{name:'可靠传输',hint:'调整信道',weight:1,goals:[{metric:'ber',operator:'<=',value:0}]}]}};}
async function main(){let failed=0;async function test(name,fn){try{await fn();console.log('PASS '+name)}catch(e){failed++;console.error('FAIL '+name+' '+e.stack)}}
  await test('production layout moves breakpoint and resume tools into the visible debug menu',layoutIntegration);
  await test('batch controls survive rerender and project roundtrip',()=>{const f=fixture(),panel=f.byId('cmPane-learning').children[0];f.byId('cmBatchSeeds').value='13,29';panel.oninput({target:f.byId('cmBatchSeeds')});f.byId('cmTargetStep').value='.5';panel.oninput({target:f.byId('cmTargetStep')});f.setMeta(clone(f.meta()));f.byId('cmBatchSeeds').value='42';f.ui.render();assert.equal(f.byId('cmBatchSeeds').value,'13,29');assert.equal(f.byId('cmTargetStep').value,'.5');});
  await test('all statistical views show measured groups and paired differences',()=>{const f=fixture();f.meta().experiments.batchResult=batch(f.program);f.ui.render();for(const value of ['ber','throughput','latency','paired']){f.byId('cmBatchPlot').value=value;f.byId('cmBatchPlot').onchange();assert.match(f.byId('cmBatchChart').innerHTML,/<svg/);assert.match(f.byId('cmBatchChart').innerHTML,/优化/);}assert.match(f.byId('cmBatchChart').innerHTML,/当前方案/);assert.match(f.byId('cmBatchResults').innerHTML,/data-batch-replay="3"/);});
  await test('row replay restores exact seed while busy and keeps queue evidence',async()=>{const f=fixture(),r=batch(f.program);f.meta().experiments.batchResult=r;f.setJob(async(kind,payload)=>{assert.equal(kind,'batch-replay');assert.equal(payload.program.seed,143);return {metrics:{ber:.02,bit_errors:2}}});await f.byId('cmBatchResults').onclick({target:{closest:()=>({dataset:{batchReplay:'3'}})}});await new Promise(resolve=>setImmediate(resolve));assert.equal(f.get().program.seed,143);assert.equal(f.get().result.metrics.bit_errors,2);assert.equal(f.meta().experiments.batchResult.rows.length,4);});
  await test('resumed jobs return to the matching experiment view',()=>{const f=fixture();f.ui.acceptResumed('batch',batch(f.program));assert.equal(f.meta().experiments.batchResult.complete,true);assert.match(f.byId('cmBatchResults').innerHTML,/优化/);f.ui.acceptResumed('target-search',{selected:{snr_db:9,ber:0},points:[],resolution_db:1});assert.match(f.byId('cmTargetResults').innerHTML,/9 dB/);});
  await test('student hints and earlier stage snapshots survive later editing',()=>{const f=fixture(),s=submission(f.program);const first={stage:0,number:1,time:'2026-10-26T00:00:00Z',program:clone(f.program),passed:true,trials:[{seed:42,checks:[{metric:'ber',operator:'<=',target:.1,actual:.01,passed:true}]}]};s.attempts.push(first);s.stages[0]=clone(first);s.active_stage=1;f.meta().experiments.submission=s;f.meta().experiments.studentMode=true;f.ui.render();f.byId('cmStudentHint').onclick();assert.equal(s.hint_events[0].stage,1);assert.match(f.byId('cmStudentHintText').textContent,/调整信道/);f.get().program.blocks[1].params.esn0_db=27;f.ui.invalidate();assert.equal(s.program.blocks[1].params.esn0_db,27);assert.equal(s.stages[0].program.blocks[1].params.esn0_db,10);});
  await test('student submission sends active stage and stores independent returned work',async()=>{const f=fixture(),s=submission(f.program);f.meta().experiments.submission=s;f.ui.render();const next=clone(s);next.active_stage=1;next.stages[0]={stage:0,number:1,time:'2026-10-26T00:00:00Z',program:clone(f.program),trials:[],passed:true};next.attempts.push(next.stages[0]);f.setJob(async(kind,payload)=>{assert.equal(kind,'classroom-stage');assert.equal(payload.stage,0);return {submission:next,attempt:next.stages[0],score:50}});await f.byId('cmStudentCheck').onclick();assert.equal(f.meta().experiments.submission.active_stage,1);assert.equal(f.meta().experiments.submission.attempts.length,1);});
  await test('switching saved student work preserves the previous assignment',async()=>{const f=fixture(),current=submission(f.program),older=submission(f.program);older.task.title='另一个任务';older.program.blocks[1].params.esn0_db=24;f.meta().experiments.submission=current;f.meta().experiments.submissions=[older];f.ui.render();f.byId('cmStudentArchive').value='0';await f.byId('cmStudentRestore').onclick();assert.equal(f.meta().experiments.submission.task.title,'另一个任务');assert.equal(f.meta().experiments.submissions[0].task.title,'阶段任务');assert.equal(f.get().program.blocks[1].params.esn0_db,24);});
  if(failed)process.exitCode=1;
}
main().catch(e=>{console.error(e);process.exitCode=1});
