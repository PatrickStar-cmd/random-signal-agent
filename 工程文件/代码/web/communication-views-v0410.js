/* Keep related instruments one click away without stacking long empty panels. */
window.createCommunicationViewsV0410=function(core,ctx){
  'use strict';
  const {byId,esc}=core,groups={};
  function group(name,entries){
    const pane=byId('cmPane-'+name),nav=document.createElement('nav');nav.className='cm-learning-nav cm-instrument-nav';nav.setAttribute('aria-label',name==='spatial'?'空间与自主接收仪器':name==='rf'?'射频与物理层仪器':'教学与实验分析工具');
    nav.innerHTML=entries.map(([id,label])=>`<button type="button" data-instrument="${id}">${esc(label)}</button>`).join('');pane.prepend(nav);
    groups[name]={entries,nav};
    nav.onclick=e=>{const id=e.target.closest('[data-instrument]')?.dataset.instrument;if(id){select(name,id);ctx.persist();}};
  }
  function select(name,id){
    const g=groups[name];if(!g.entries.some(e=>e[0]===id))id=g.entries[0][0];
    for(const [key,,element] of g.entries)element.hidden=key!==id;
    g.nav.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.instrument===id)));
    (ctx.meta().analysisSections||(ctx.meta().analysisSections={}))[name]=id;
    requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));
  }
  group('spatial',[
    ['space','🛰️ 空间与子工程',byId('cmSpaceStage').closest('section.cm-spatial')],
    ['receiver','🐬 自主接收',byId('cmReceiver410Panel')],
    ['flow','🔱 汇合与通感',byId('cmFlow410Panel')]]);
  group('rf',[
    ['measure','📶 射频测量',byId('cmRFPanel')],['waveform','🌊 波形与同步',byId('cmWaveformPanel')],
    ['framing','📦 物理帧与迭代',byId('cmFramingV0410')]]);
  group('learning',[
    ['lesson','🎓 业务与教学',byId('cmLesson').closest('section.cm-learning')],
    ['experiment','🧭 教学任务与编排',byId('cmExperimentStop').closest('section.cm-learning')],
    ['analysis','🔬 自主分析与优化',byId('cmV410Inspect').closest('section.cm-v410')]]);
  function render(){for(const name of Object.keys(groups))select(name,ctx.meta().analysisSections?.[name]);}
  function onResult(result){
    const w=result?.advanced?.wireless||{};
    if(w.rx_isac_ofdm)select('spatial','flow');else if(w.rx_mlse||w.rx_music||w.tdl_channel)select('spatial','receiver');
    if(w.rx_self_frame||result?.advanced?.codecs?.some(c=>c.kind==='turbo_decode'))select('rf','framing');
  }
  core.root.addEventListener('cm-protocol-result',e=>{if(e.detail?.events?.some(v=>v.mother_indices))select('rf','framing');});
  render();return {render,onResult,buttons(){},invalidate(){}};
};
