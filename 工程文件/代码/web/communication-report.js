/* Select measured figures, annotate, preview and export an ocean-style report. */
window.createCommunicationReport = function (core, ctx) {
  'use strict';
  const {root, byId, esc} = core;
  const dialog = document.createElement('dialog');
  dialog.id = 'cmReportDialog'; dialog.className = 'cm-replace-dialog cm-report-editor';
  dialog.innerHTML = `<h3>📄 编排通信实验报告</h3><p class="cm-learn-hint">选择已运行的实验素材，填写图注和结论，再预览与导出。</p><div id="cmReportMaterials" class="cm-report-materials"></div><label class="cm-report-conclusion">📝 实验结论<textarea id="cmReportConclusion" rows="4" maxlength="8000" placeholder="记录现象、比较结果和参数选择"></textarea></label><div class="cm-experience-row"><button id="cmReportRefresh" type="button">🔎 更新预览</button><button id="cmReportDownload" type="button">📥 下载 PDF</button><button id="cmReportClose" type="button">关闭</button></div><p id="cmReportStatus" role="status"></p><div id="cmReportPreview"></div>`;
  root.append(dialog);
  let available = [], busy = false, pdfUrl = null;
  const state = () => ctx.meta().report || (ctx.meta().report = {captions: {}, conclusion: ''});
  const format = value => typeof value === 'number' ? Number(value.toPrecision(4)) : value ?? '—';
  function figure(item) {
    const colors = ['#477ac7', '#9673c8', '#339a94', '#bd8a39'];
    const h = item.heatmap;
    if (h) {
      const values = h.values.flat().filter(Number.isFinite), lo = Math.min(...values), hi = Math.max(...values), rows = h.values.length, cols = h.values[0].length;
      const cells = h.values.map((row, y) => row.map((value, x) => {
        const z = value == null ? 0 : (value - lo) / Math.max(hi - lo, 1e-12);
        return `<rect x="${40 + x * 500 / cols}" y="${20 + y * 180 / rows}" width="${500 / cols + .2}" height="${180 / rows + .2}" fill="hsl(210 55% ${95 - 45 * z}%)"><title>${esc(`x=${h.x[x]}, y=${h.y[y]}, 值=${format(value)}`)}</title></rect>`;
      }).join('')).join('');
      return `<svg viewBox="0 0 580 245" role="img" aria-label="${esc(item.title)}">${cells}<text x="40" y="228">${esc(`X: ${h.x[0]} → ${h.x.at(-1)}；Y: ${h.y[0]} → ${h.y.at(-1)}；值: ${format(lo)} → ${format(hi)}`)}</text></svg>`;
    }
    if (!item.series.length) return '';
    const xs = item.series.flatMap(s => s.x).filter(Number.isFinite), ys = item.series.flatMap(s => [...s.y, ...(s.interval || []).flat()]).filter(Number.isFinite);
    if (!xs.length || !ys.length) return '';
    let xmin = Math.min(...xs), xmax = Math.max(...xs);
    const ymin = Math.min(0, ...ys), ymax = Math.max(...ys);
    if(xmin===xmax){xmin-=.5;xmax+=.5;}
    const px = x => 45 + (x - xmin) / Math.max(xmax - xmin, 1e-12) * 500, py = y => 200 - (y - ymin) / Math.max(ymax - ymin, 1e-12) * 170;
    const lines = item.series.map((s, i) => `<polyline points="${s.x.map((x, j) => s.y[j] == null ? '' : `${px(x)},${py(s.y[j])}`).join(' ')}" fill="none" stroke="${colors[i % 4]}" stroke-width="2"/>${s.interval ? s.interval.map((pair, j) => `<line x1="${px(s.x[j])}" x2="${px(s.x[j])}" y1="${py(pair[0])}" y2="${py(pair[1])}" stroke="${colors[i % 4]}"/><circle cx="${px(s.x[j])}" cy="${py(s.y[j])}" r="3" fill="${colors[i % 4]}"/>`).join('') : ''}`).join('');
    return `<svg viewBox="0 0 580 245" role="img" aria-label="${esc(item.title)}"><rect x="45" y="30" width="500" height="170" fill="none" stroke="#c5d5e6"/>${lines}<text x="2" y="36">${format(ymax)}</text><text x="2" y="204">${format(ymin)}</text><text x="45" y="228">${format(xmin)}</text><text x="510" y="228">${format(xmax)}</text></svg><p class="cm-learn-hint">${item.series.map(s => esc(s.name)).join('   ')}</p>`;
  }
  function capture() {
    const s = state(); s.materials = available.filter(item => byId('cmReportPick-' + item.id).checked).map(item => item.id);
    s.captions = Object.fromEntries(available.map(item => [item.id, byId('cmReportCaption-' + item.id).value]));
    s.conclusion = byId('cmReportConclusion').value; ctx.persist();
  }
  function materialCards() {
    const s=state(),picked=s.materials||available.map(item=>item.id);
    byId('cmReportMaterials').innerHTML=available.length?available.map(item=>`<article><label class="cm-inline"><input type="checkbox" id="cmReportPick-${esc(item.id)}" ${picked.includes(item.id)?'checked':''}>${esc(item.title)}</label><div><button type="button" data-report-up="${esc(item.id)}" aria-label="上移 ${esc(item.title)}">↑ 上移</button><button type="button" data-report-down="${esc(item.id)}" aria-label="下移 ${esc(item.title)}">↓ 下移</button></div><label>图注<textarea rows="2" id="cmReportCaption-${esc(item.id)}" maxlength="1200">${esc(s.captions?.[item.id]||'')}</textarea></label></article>`).join(''):'<p>运行实验后可选择实测素材。</p>';
  }
  async function preview() {
    const response=await fetch('/api/communications/report-pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:ctx.session(),document:ctx.documentValue()})});
    if(!response.ok)throw Error((await response.json()).error||'报告生成失败。');
    if(pdfUrl)URL.revokeObjectURL(pdfUrl);
    pdfUrl=URL.createObjectURL(await response.blob());
    byId('cmReportPreview').innerHTML=`<iframe title="最终 PDF 报告预览" src="${pdfUrl}" style="width:100%;height:65vh;border:2px solid #7899b2;border-radius:12px"></iframe>`;
    byId('cmReportStatus').textContent='当前预览为最终 PDF，图注和素材顺序已保存。';
  }
  async function action(fn) {
    if (busy) return; busy = true; buttons(true);
    try { await fn(); } catch (error) { byId('cmReportStatus').textContent = error.message; }
    finally { busy = false; buttons(false); }
  }
  async function open() {
    return action(async () => {
      const value = await ctx.request('report-preview', {document: ctx.documentValue()}); available = value.materials;
      const s=state(),order=s.materials||available.map(item=>item.id);
      available.sort((a,b)=>(order.includes(a.id)?order.indexOf(a.id):1000)-(order.includes(b.id)?order.indexOf(b.id):1000));
      materialCards();byId('cmReportConclusion').value=s.conclusion||'';dialog.showModal();await preview();
    });
  }
  byId('cmReportRefresh').onclick = () => action(async () => { capture(); await preview(); });
  byId('cmReportDownload').onclick=()=>action(async()=>{
    capture();await preview();const link=document.createElement('a');link.href=pdfUrl;link.download='communication-experiment.pdf';link.click();
    byId('cmReportStatus').textContent='已下载预览中的最终 PDF。';
  });
  byId('cmReportMaterials').onclick=e=>{const button=e.target.closest('[data-report-up],[data-report-down]');if(!button||busy)return;capture();const id=button.dataset.reportUp||button.dataset.reportDown,index=available.findIndex(v=>v.id===id),next=index+(button.dataset.reportUp?-1:1);if(next<0||next>=available.length)return;[available[index],available[next]]=[available[next],available[index]];materialCards();capture();};
  byId('cmReportClose').onclick = () => { capture(); dialog.close(); };
  dialog.addEventListener('cancel', capture);
  function buttons(value) { dialog.querySelectorAll('button,input,textarea').forEach(element => element.disabled = value); }
  return {open, buttons, figure};
};
