/* Select measured figures, annotate, preview and export an ocean-style report. */
window.createCommunicationReport = function (core, ctx) {
  'use strict';
  const {root, byId, esc} = core;
  const dialog = document.createElement('dialog');
  dialog.id = 'cmReportDialog'; dialog.className = 'cm-replace-dialog cm-report-editor';
  dialog.innerHTML = `<h3>📄 编排通信实验报告</h3><p class="cm-learn-hint">选择已运行的实验素材，填写图注和结论，再预览与导出。</p><div id="cmReportMaterials" class="cm-report-materials"></div><label class="cm-report-conclusion">📝 实验结论<textarea id="cmReportConclusion" rows="4" maxlength="8000" placeholder="记录现象、比较结果和参数选择"></textarea></label><div class="cm-experience-row"><button id="cmReportRefresh" type="button">🔎 更新预览</button><button id="cmReportDownload" type="button">📥 下载 PDF</button><button id="cmReportClose" type="button">关闭</button></div><p id="cmReportStatus" role="status"></p><div id="cmReportPreview"></div>`;
  root.append(dialog);
  let available = [], busy = false;
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
    return `<svg viewBox="0 0 580 245" role="img" aria-label="${esc(item.title)}"><rect x="45" y="30" width="500" height="170" fill="none" stroke="#c5d5e6"/>${lines}<text x="2" y="36">${format(ymax)}</text><text x="2" y="204">${format(ymin)}</text><text x="45" y="228">${format(xmin)}</text><text x="510" y="228">${format(xmax)}</text></svg><p class="cm-learn-hint">${item.series.map(s => esc(s.name)).join(' · ')}</p>`;
  }
  function capture() {
    const s = state(); s.materials = available.filter(item => byId('cmReportPick-' + item.id).checked).map(item => item.id);
    s.captions = Object.fromEntries(available.map(item => [item.id, byId('cmReportCaption-' + item.id).value]));
    s.conclusion = byId('cmReportConclusion').value; ctx.persist();
  }
  function preview(value) {
    byId('cmReportPreview').innerHTML = value.summary.map(text => `<p>${esc(text)}</p>`).join('') + value.selected_materials.map(item => `<article class="cm-report-figure"><h4>${esc(item.title)}</h4>${figure(item)}${item.headers.length ? `<div class="cm-learn-scroll"><table><thead><tr>${item.headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${item.rows.slice(0, 12).map(row => `<tr>${row.map(v => `<td>${esc(format(v))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : ''}<p>${esc(item.note)}</p><p>${esc(item.caption || '')}</p></article>`).join('') + (value.conclusion ? `<h4>实验结论</h4><p class="cm-report-prose">${esc(value.conclusion)}</p>` : '');
  }
  async function action(fn) {
    if (busy) return; busy = true; buttons(true);
    try { await fn(); } catch (error) { byId('cmReportStatus').textContent = error.message; }
    finally { busy = false; buttons(false); }
  }
  async function open() {
    return action(async () => {
      const value = await ctx.request('report-preview', {document: ctx.documentValue()}); available = value.materials;
      const s = state(), picked = s.materials || available.map(item => item.id);
      byId('cmReportMaterials').innerHTML = available.length ? available.map(item => `<article><label class="cm-inline"><input type="checkbox" id="cmReportPick-${esc(item.id)}" ${picked.includes(item.id) ? 'checked' : ''}>${esc(item.title)}</label><label>图注<textarea rows="2" id="cmReportCaption-${esc(item.id)}" maxlength="1200">${esc(s.captions?.[item.id] || '')}</textarea></label></article>`).join('') : '<p>运行批量、空间通信或教学实验后，可在这里选择对应素材。</p>';
      byId('cmReportConclusion').value = s.conclusion || ''; preview(value); byId('cmReportStatus').textContent = '预览中的图表与 PDF 使用同一组实测数据。'; dialog.showModal();
    });
  }
  byId('cmReportRefresh').onclick = () => action(async () => { capture(); preview(await ctx.request('report-preview', {document: ctx.documentValue()})); });
  byId('cmReportDownload').onclick = () => action(async () => {
    capture(); const response = await fetch('/api/communications/report-pdf', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({session_id: ctx.session(), document: ctx.documentValue()})});
    if (!response.ok) throw Error((await response.json()).error || '报告生成失败。');
    const url = URL.createObjectURL(await response.blob()), link = document.createElement('a'); link.href = url; link.download = 'communication-experiment.pdf'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
    byId('cmReportStatus').textContent = 'PDF 已生成，图注与结论已保存到工程。';
  });
  byId('cmReportClose').onclick = () => { capture(); dialog.close(); };
  dialog.addEventListener('cancel', capture);
  function buttons(value) { dialog.querySelectorAll('button,input,textarea').forEach(element => element.disabled = value); }
  return {open, buttons, figure};
};
