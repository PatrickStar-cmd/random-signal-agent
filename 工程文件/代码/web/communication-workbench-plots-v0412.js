/* Small SVG views use the same measured summaries as the result table. */
window.communicationWorkbenchPlot=function(result,metric,parameters=[]){
  const axes=result.settings?.axes||[],rows=(result.summaries||[]).filter(r=>Number.isFinite(r.metrics?.[metric]));
  if(!axes.length||!rows.length)return '';
  const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=v=>Number(v.toPrecision(4)),label=path=>parameters.find(p=>p.path===path)?.label||path;
  return [...new Set(rows.map(r=>r.document_index))].map(index=>{
    const data=rows.filter(r=>r.document_index===index),x=axes[0],y=axes[1],values=data.map(r=>r.metrics[metric]),lo=Math.min(...values),hi=Math.max(...values);
    let shapes='',xtitle=label(x.path),ytitle=y?label(y.path):metric;
    if(y){
      const xs=[...new Set(x.values)],ys=[...new Set(y.values)],cw=480/xs.length,ch=230/ys.length;
      data.forEach(r=>{const xi=xs.indexOf(r.parameters[x.path]),yi=ys.indexOf(r.parameters[y.path]),v=r.metrics[metric],t=(v-lo)/(hi-lo||1);shapes+=`<rect x="${90+xi*cw}" y="${35+yi*ch}" width="${cw}" height="${ch}" fill="hsl(${190+65*t},58%,${88-35*t}%)" stroke="#fff"><title>${esc(xtitle)} ${r.parameters[x.path]} ${esc(ytitle)} ${r.parameters[y.path]} ${esc(metric)} ${fmt(v)}</title></rect><text x="${90+(xi+.5)*cw}" y="${40+(yi+.5)*ch}" text-anchor="middle">${fmt(v)}</text>`;});
      xs.forEach((v,i)=>shapes+=`<text x="${90+(i+.5)*cw}" y="285" text-anchor="middle">${esc(v)}</text>`);
      ys.forEach((v,i)=>shapes+=`<text x="80" y="${40+(i+.5)*ch}" text-anchor="end">${esc(v)}</text>`);
    }else{
      const xs=x.values.map(Number),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(0,lo),ymax=hi===ymin?ymin+1:hi*1.1,px=v=>90+480*(v-xmin)/(xmax-xmin||1),py=v=>265-230*(v-ymin)/(ymax-ymin);
      for(let i=0;i<=4;i++){const v=ymin+(ymax-ymin)*i/4,yy=py(v);shapes+=`<path d="M90 ${yy}H570" stroke="#cedde7"/><text x="80" y="${yy+4}" text-anchor="end">${fmt(v)}</text>`;}
      const sorted=data.slice().sort((a,b)=>a.parameters[x.path]-b.parameters[x.path]);
      shapes+=`<polyline fill="none" stroke="#6c57b4" stroke-width="3" points="${sorted.map(r=>`${px(r.parameters[x.path])},${py(r.metrics[metric])}`).join(' ')}"/>`;
      sorted.forEach(r=>shapes+=`<circle cx="${px(r.parameters[x.path])}" cy="${py(r.metrics[metric])}" r="5" fill="#259d9a"><title>${esc(xtitle)} ${r.parameters[x.path]} ${esc(metric)} ${fmt(r.metrics[metric])}</title></circle>`);
      [...new Set(xs)].forEach(v=>shapes+=`<text x="${px(v)}" y="285" text-anchor="middle">${esc(v)}</text>`);
    }
    return `<figure class="cm-workbench-plot"><figcaption>${esc(data[0].name)} ${esc(metric)} ${y?'参数热图':'参数曲线'}</figcaption><svg viewBox="0 0 650 340" role="img" aria-label="${esc(metric)} ${y?'二维参数热图':'参数曲线'}"><g fill="#25465c" font-family="sans-serif" font-size="11">${shapes}<text x="325" y="317" text-anchor="middle">${esc(xtitle)}</text><text x="20" y="150" text-anchor="middle" transform="rotate(-90 20 150)">${esc(ytitle)}</text></g></svg></figure>`;
  }).join('');
};
