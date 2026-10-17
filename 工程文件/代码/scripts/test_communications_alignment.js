/* Numerical checks for the same alignment helper used by the browser. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..'),context={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(root,'web/communication-analysis.js'),'utf8'),context);
const align=context.window.communicationAlign;
let seed=17;const random=()=>{seed=(Math.imul(1664525,seed)+1013904223)>>>0;return seed/2**32-.5};
const a={i:Array.from({length:512},random),q:Array.from({length:512},random),domain:'复符号',unit:'s',sample_rate:1000,offset:0};
for(const lag of [-45,-7,0,12,80]){
  const make=v=>Array.from({length:512},(_,i)=>v[i-lag]??0);
  const b={...a,i:make(a.i),q:make(a.q)},out=align(a,b,true);
  assert.equal(out.lag,lag);assert.ok(out.score>.99);
  assert.ok(out.a.i.every((v,i)=>Math.abs(v-out.b.i[i])<1e-12));
}
const same=align(a,{...a},false);assert.equal(same.lag,0);
const constant={...a,i:Array(128).fill(1),q:Array(128).fill(0)};assert.equal(align(constant,constant,true).lag,0);
const resampled={...a,sample_rate:2000,i:a.i.flatMap(v=>[v,v]),q:a.q.flatMap(v=>[v,v])};
const out=align(a,resampled,false);assert.ok(out.a.i.every((v,i)=>v===out.b.i[i]));
const log=path.join(root,'logs/communications-rf/alignment.log');fs.mkdirSync(path.dirname(log),{recursive:true});fs.writeFileSync(log,'PASS: signed lags, complex samples, constant input, disabled alignment and unequal sample rates.\n');console.log(fs.readFileSync(log,'utf8'));
