/* Canonical graph operations shared by the editor and its structural tests. */
(function(root){
  'use strict';
  const clone=v=>JSON.parse(JSON.stringify(v));
  function lanes(g){return [['shared',g.prefix],...g.branches.map(b=>[b.id,b.blocks]),['tail',g.tail]];}
  function projection(g,id){return {schema:1,...clone(g.globals),blocks:clone([...g.prefix,...g.branches.find(b=>b.id===id).blocks,...g.tail])};}
  function nodes(g){return [...lanes(g).flatMap(([lane,blocks])=>blocks.map(b=>({key:lane+'/'+b.id,lane,...b}))),{key:'merge',lane:'merge',kind:'branch_merge'},...g.analyses.map(a=>({...a,key:a.id,lane:'analysis'}))];}
  function connections(g){
    const edges=[],add=(from,to,input='in',output='out')=>edges.push({from,to,input,output});
    for(const [lane,blocks] of lanes(g))for(let i=1;i<blocks.length;i++)add(lane+'/'+blocks[i-1].id,lane+'/'+blocks[i].id);
    for(const b of g.branches)add('shared/'+g.prefix.at(-1).id,b.id+'/'+b.blocks[0].id);
    g.merge.inputs.forEach((id,i)=>{const b=g.branches.find(b=>b.id===id);add(id+'/'+b.blocks.at(-1).id,'merge','ab'[i]);});
    add('merge','tail/'+g.tail[0].id);
    for(const a of g.analyses)add(a.source,a.id,'in','power');
    return edges;
  }
  function arrange(g){
    const layout={},columns=Math.max(2,g.branches.length),width=Math.max(900,columns*245),prefixCols=Math.floor(width/225);
    g.prefix.forEach((b,i)=>layout['shared/'+b.id]={x:20+i%prefixCols*225,y:35+Math.floor(i/prefixCols)*120});
    const start=60+Math.ceil(g.prefix.length/prefixCols)*120;
    g.branches.forEach((b,i)=>b.blocks.forEach((n,j)=>layout[b.id+'/'+n.id]={x:Math.round((i+.5)*width/columns-102),y:start+j*120}));
    const bottom=start+Math.max(...g.branches.map(b=>b.blocks.length))*120;
    layout.merge={x:Math.round(width/2-105),y:bottom+20};
    g.tail.forEach((b,i)=>layout['tail/'+b.id]={x:layout.merge.x,y:bottom+150+i*120});
    g.analyses.forEach((a,i)=>layout[a.id]={x:Math.max(20,width-220),y:bottom+150+i*120});
    return layout;
  }
  function numericKey(g){const value=clone(g);delete value.layout;return JSON.stringify(value);}
  function absorb(g,program,active,definitions){
    const split=program.blocks.findIndex(b=>['demodulator','rx_converter'].includes(definitions[b.kind].category));
    const demod=program.blocks.findIndex(b=>/^(soft_|demod_)/.test(b.kind));
    if(split<1||demod<split)throw Error('保留共享信道、接收处理及数字解调器后即可同步可视接线。');
    const end=demod+(g.merge.domain==='llr'?1:0);
    if(end<=split)throw Error('复符号汇合前需要接收处理积木。');
    const previous=nodes(g).map(n=>n.key).join('|');
    g.prefix=clone(program.blocks.slice(0,split));g.branches.find(b=>b.id===active).blocks=clone(program.blocks.slice(split,end));g.tail=clone(program.blocks.slice(end));
    for(const key of ['seed','sample_rate','sample_count','symbol_rate'])g.globals[key]=program[key];
    const current=nodes(g),keys=new Set(current.map(n=>n.key));
    if(previous!==current.map(n=>n.key).join('|')){
      g.analyses=g.analyses.filter(a=>keys.has(a.source));g.edges=connections(g);
      for(const key of Object.keys(g.layout))if(!keys.has(key))delete g.layout[key];
    }
    return g;
  }
  function connect(g,edge){
    if(edge.from===edge.to)throw Error('请选择两个不同积木的端口。');
    const from=nodes(g).find(n=>n.key===edge.from),to=nodes(g).find(n=>n.key===edge.to);
    if(!from||!to)throw Error('请选择工程内的积木。');
    if(edge.output==='power'&&(from.kind!=='rx_isac_ofdm'||to.kind!=='analysis_cfar2d'))throw Error('功率分析端口连接 CFAR 输入。');
    if(edge.output==='out'&&to.kind==='analysis_cfar2d')throw Error('CFAR 使用通感接收器的功率分析端口。');
    if(to.kind==='branch_merge'&&!['a','b'].includes(edge.input))throw Error('请选择汇合 A 或 B 输入。');
    if(to.kind!=='branch_merge'&&edge.input!=='in')throw Error('普通积木使用主输入端口。');
    if(to.kind==='branch_merge'){
      if(!g.branches.some(b=>b.id===from.lane))throw Error('汇合输入选择接收分支的输出。');
      const index=edge.input==='a'?0:1,other=1-index;
      if(g.merge.inputs[other]===from.lane)throw Error('汇合 A、B 选择两条不同分支。');
      g.merge.inputs[index]=from.lane;
    }
    g.edges=g.edges.filter(e=>!(e.to===edge.to&&e.input===edge.input));g.edges.push(clone(edge));
    if(to.kind==='analysis_cfar2d')g.analyses.find(a=>a.id===to.key).source=from.key;
  }
  const api={clone,lanes,projection,nodes,connections,arrange,numericKey,absorb,connect};
  root.CommunicationGraphModel=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
