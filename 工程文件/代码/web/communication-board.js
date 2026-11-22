/* Keep hardware operations tied to the exact generated program and selected USB device. */
window.createCommunicationBoard = function (core, ctx) {
  'use strict';
  const {root, byId, get, esc} = core;
  const panel = byId('cmBoardPanel');
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.id = 'cmBoardOpen';
  toggle.textContent = '🔌 开发板';
  toggle.setAttribute('aria-controls', panel.id);
  toggle.setAttribute('aria-expanded', 'false');
  byId('cmRun').after(toggle);

  const field = id => byId('cmBoard' + id);
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  let generated = null, build = null, measured = null, inventory = null;
  let generation = 0, refreshId = 0, timer = 0, signature = '', working = false, pending = false;
  let issueIds = [], currentFile = '', probeId = '';
  const target = () => ({language: field('Language').value, board: field('Target').value});
  const isCpp = () => target().language === 'cpp';
  const cardFor = id => id === 'graph' ? root.querySelector('.cm-scratch-parallel') :
    [...byId('cmProgram').querySelectorAll('[data-cm-id]')].find(el => el.dataset.cmId === id);
  const device = () => inventory?.devices.find(d => d.id === field('Device').value);
  const status = message => {field('Status').textContent = message;};
  const nameFor = id => get().definitions[get().program?.blocks.find(b => b.id === id)?.kind]?.label || id;

  function payload() {
    const {document_schema, name, program, graph, tools} = ctx.documentValue();
    return {document: {document_schema, name, program, graph, tools}, ...target()};
  }
  async function request(action, data, binary = false) {
    const response = await fetch('/api/communications/board-' + action, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
    });
    if (!response.ok) {
      const info = await response.json();
      const error = new Error(info.error || '开发板请求失败（HTTP ' + response.status + '）');
      error.blockIds = info.block_ids || [];
      throw error;
    }
    return binary ? response.blob() : response.json();
  }
  function issues(ids) {
    issueIds = ids;
    root.querySelectorAll('.cm-board-issue').forEach(el => el.classList.remove('cm-board-issue'));
    for (const id of ids) cardFor(id)?.classList.add('cm-board-issue');
    field('Issues').innerHTML = ids.map(id => '<button type="button" data-board-issue="' + esc(id) + '">定位 ' +
      esc(id === 'graph' ? '并行接收' : nameFor(id)) + '</button>').join('');
  }
  function report(error) {
    status(error.message);
    issues(ctx.meta().graph && !generated ? ['graph'] : (error.blockIds || []));
  }
  function buttons() {
    const locked = working || get().busy;
    toggle.disabled = locked;
    for (const id of ['Language','Target','Load','Preset','File','Generate','Device','Refresh']) field(id).disabled = locked;
    field('Refresh').disabled = locked || !local;
    field('Export').disabled = locked || !generated;
    field('Build').hidden = !isCpp();
    field('Build').disabled = locked || !local || !generated;
    field('Deploy').disabled = locked || !generated || !local ||
      (isCpp() ? !build || device()?.kind !== 'bootsel' : device()?.kind !== 'serial');
    field('Measure').disabled = locked || !generated || !local || device()?.kind !== 'serial';
    field('Generate').disabled = locked || pending;
    field('Deploy').textContent = isCpp() ? '烧录固件' : '上传程序';
    field('Firmware').hidden = !build;
    field('CppSetup').hidden = !isCpp();
    field('MicroSetup').hidden = isCpp();
    field('FirmwareHelp').href = target().board === 'pico' ?
      'https://micropython.org/download/RPI_PICO/' : 'https://micropython.org/download/RPI_PICO_W/';
  }
  function sampleText(samples, iq) {
    const limit = iq ? 8 : 64;
    const shown = samples.slice(0, limit);
    const text = iq ? shown.map(([i,q]) => '(' + i.toFixed(4) + ', ' + q.toFixed(4) + ')').join(' ') : shown.join(' ');
    return samples.length > limit ? text + ' …（共 ' + samples.length + ' 个）' : text;
  }
  function drawSymbols(reference, actual, index) {
    const x = i => 100 + i * 73, y = q => 87 - q * 73;
    const dots = (samples, color, radius, fill) => {
      const seen = new Set();
      return samples.map(([i,q]) => {
        const key = x(i).toFixed(1) + ',' + y(q).toFixed(1);
        if (seen.has(key)) return '';
        seen.add(key);
        return '<circle cx="' + x(i) + '" cy="' + y(q) + '" r="' + radius + '" stroke="' + color + '" stroke-width="2" fill="' + fill + '"/>';
      }).join('');
    };
    field('Scatter').innerHTML = '<path d="M12 87H188 M100 9V165" fill="none" stroke="#a0b9cc"/><text x="184" y="82">I</text><text x="106" y="15">Q</text>' +
      dots(reference, '#7455ad', 4, 'none') + dots(actual || [], '#19796f', 2, '#19796f') +
      dots([reference[index]], '#c57429', 7, 'none') +
      '<text x="12" y="180" xml:space="preserve">紫圈 电脑参考' + (actual ? '  绿点 板端' : '') + '  橙圈 当前符号</text>';
  }
  function decodedText(bits) {
    const bytes = new Uint8Array(bits.length / 8);
    bits.forEach((bit, index) => {bytes[index >> 3] |= bit << (7 - index % 8);});
    return new TextDecoder('utf-8', {ignoreBOM:true}).decode(bytes);
  }
  function inspectNode(step, index, result, previous) {
    const values = result?.nodes[step.id];
    if (!values) return measured ? '本次未收到样本' : '待板端实测';
    if (step.format === 'iq') {
      const [i,q] = values[index];
      return 'I = ' + i.toFixed(6) + '  Q = ' + q.toFixed(6) + '  判决比特 ' + Number(i < 0) + Number(q < 0);
    }
    if (step.kind === 'hamming_decode') {
      const word = previous && result.nodes[previous.id]?.slice(7 * index, 7 * index + 7);
      const syndrome = result.syndromes?.[step.id]?.[index];
      if (!word || syndrome === undefined) return '等待码字回读';
      const data = values.slice(4 * index, 4 * index + 4);
      return '收到 ' + word.join('') + '  综合征 ' + syndrome + (syndrome ? '  纠正第 ' + syndrome + ' 位' : '  原样通过') + '  数据 ' + data.join('');
    }
    if (step.kind === 'bit_flip') {
      const start = (step.codeword - 1) * 7;
      return '码字 ' + step.codeword + '  第 ' + step.position + ' 位  ' +
        result.nodes[previous.id].slice(start, start + 7).join('') + ' → ' + values.slice(start, start + 7).join('');
    }
    return decodedText(values);
  }
  function probe() {
    const id = get().selectedId, step = generated?.steps.find(s => s.id === id);
    field('Probe').hidden = !step;
    if (!step) return;
    field('NodeTitle').textContent = step.label + ' 输出';
    const reference = generated.expected.nodes[id], iq = step.format === 'iq';
    field('Expected').textContent = sampleText(reference, iq);
    const actual = measured?.nodes[id];
    field('Actual').textContent = actual?.length ? sampleText(actual, iq) : measured ? '本次未收到样本' : '待板端实测';
    const sources = get().program.blocks.filter(b => get().definitions[b.kind]?.category === 'source');
    const text = step.kind === 'text' || (step.kind === 'sink' && sources.length > 0 && sources.every(b => b.kind === 'text'));
    const hamming = step.kind === 'hamming_decode';
    const count = hamming ? generated.expected.syndromes[id].length : iq ? reference.length : 1;
    if (probeId !== id) field('Index').value = 1;
    probeId = id;
    const index = Math.max(1, Math.min(count, Math.trunc(Number(field('Index').value)) || 1)) - 1;
    field('Index').max = count;
    field('Index').value = index + 1;
    field('Symbols').hidden = !iq;
    if (iq) drawSymbols(reference, actual, index);
    field('IndexLabel').hidden = !(iq || hamming);
    field('IndexName').textContent = (hamming ? '码字序号' : '符号序号') + '（共 ' + count + '）';
    field('Observation').hidden = !(iq || hamming || text || step.kind === 'bit_flip');
    if (!field('Observation').hidden) {
      const previous = generated.steps[generated.steps.indexOf(step) - 1];
      field('ObservationTitle').textContent = '电脑参考  ' + (iq ? '星座坐标' : hamming ? '译码过程' : text ? 'UTF-8 文字' : '软件注错');
      field('ReferenceDetail').textContent = inspectNode(step, index, generated.expected, previous);
      field('MeasuredDetail').textContent = inspectNode(step, index, measured, previous);
    }
  }
  field('Index').onchange = probe;
  function showMeasurement() {
    field('Result').hidden = !measured;
    if (measured) {
      const m = measured.metrics;
      const metrics = [
        ['收到帧数', m.received_frames + ' / ' + m.expected_frames],
        ['丢帧数', String(m.lost_frames)],
        ['误比特 / 比较位数', m.compared_bits ? m.bit_errors + ' / ' + m.compared_bits : '无可比较数据'],
        ['误码率 BER', m.compared_bits ? (100 * m.ber).toPrecision(4) + '%' : '无可比较数据']
      ];
      field('Metrics').innerHTML = metrics.map(([k,v]) => '<div><dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd></div>').join('');
    }
    probe();
  }
  function showFile() {
    const ranges = Object.entries(generated.source_map).filter(([,r]) => r.file === currentFile);
    const owners = new Map();
    for (const [id,r] of ranges) for (let n = r.start; n <= r.end; n++) owners.set(n,id);
    field('File').value = currentFile;
    field('Code').innerHTML = generated.files[currentFile].split('\n').map((line,i) => {
      const id = owners.get(i + 1);
      const attrs = id ? ' data-board-block="' + esc(id) + '" role="button" tabindex="' +
        (generated.source_map[id].start === i + 1 ? '0' : '-1') + '" title="定位 ' + esc(nameFor(id)) + '"' : '';
      return '<div class="cm-board-line"' + attrs + '><span aria-hidden="true">' + (i + 1) +
        '</span><code>' + esc(line || ' ') + '</code></div>';
    }).join('');
  }
  function selectSource(scroll, follow = true) {
    if (!generated) return;
    const id = get().selectedId, range = generated.source_map[id];
    if (follow && range && range.file !== currentFile) {currentFile = range.file; showFile();}
    let first;
    for (const el of field('Code').querySelectorAll('[data-board-block]')) {
      const on = el.dataset.boardBlock === id;
      el.classList.toggle('selected', on);
      if (on && !first) first = el;
    }
    if (first && scroll) field('Code').scrollTop = Math.max(0, first.offsetTop - field('Code').clientHeight / 3);
    probe();
  }
  function locate(id) {
    const card = cardFor(id);
    if (!card) return;
    if (id !== 'graph') {
      const group = card.closest('.cm-group');
      if (group) group.open = true;
      core.selectBlock(id);
    }
    card.scrollIntoView({block:'nearest', inline:'nearest'});
  }
  field('Issues').onclick = e => {const el = e.target.closest('[data-board-issue]'); if (el) locate(el.dataset.boardIssue);};
  field('Code').onclick = e => {const el = e.target.closest('[data-board-block]'); if (el) locate(el.dataset.boardBlock);};
  field('Code').onkeydown = e => {
    if (['Enter',' '].includes(e.key) && e.target.dataset.boardBlock) {e.preventDefault(); locate(e.target.dataset.boardBlock);}
  };
  field('File').onchange = () => {currentFile = field('File').value; showFile(); selectSource(false, false);};
  root.addEventListener('cm-select', () => {if (!panel.hidden) selectSource(true);});
  async function generate() {
    clearProject();
    const id = ++generation;
    pending = true;
    status('正在生成源码…');
    buttons();
    try {
      const value = await request('generate', payload());
      if (id !== generation) return;
      generated = value;
      issues([]);
      currentFile = generated.entry_file;
      field('File').innerHTML = Object.keys(generated.files).map(file =>
        '<option value="' + esc(file) + '">' + esc(file) + '</option>').join('');
      field('Source').hidden = false;
      showFile();
      selectSource(true);
      field('Wiring').textContent = generated.experiment === 'uart' ?
        '用跳线连接 GP0（TX）与 GP1（RX）。USB 用于部署和回读结果。' :
        '用数据线连接 USB。' + (generated.experiment === 'qpsk' ? 'QPSK 的 I/Q 分量' : 'BPSK 符号') + '在板内计算，各积木输出经 USB 回传。';
      const hostTools = generated.host_tools?.length;
      status('已生成 ' + generated.steps.length + ' 块积木的源码' +
        (hostTools ? '  ' + hostTools + ' 个分析工具在电脑端运行' : ''));
    } catch (error) {
      if (id === generation) report(error);
    } finally {
      if (id === generation) {pending = false; buttons();}
    }
  }
  function clearProject() {
    clearTimeout(timer);
    generation++;
    pending = false;
    generated = build = measured = null;
    probeId = '';
    field('Source').hidden = true;
    field('Firmware').removeAttribute('href');
    field('Wiring').textContent = '';
    issues([]);
    showMeasurement();
    buttons();
  }
  function render() {
    if (panel.hidden) return;
    const g = ctx.meta().graph;
    const next = JSON.stringify([target(), get().program, !!g, ctx.meta().tools]);
    if (signature !== next) {
      signature = next;
      clearProject();
      status('正在检查当前积木链路…');
      timer = setTimeout(generate, 250);
    } else if (issueIds.length) {
      for (const id of issueIds) cardFor(id)?.classList.add('cm-board-issue');
    }
  }
  function invalidate() {if (!panel.hidden) render(); else if (generated || pending) {signature = ''; clearProject();}}
  function switchPane(toDevices) {
    field('CodePane').hidden = toDevices;
    field('DevicePane').hidden = !toDevices;
    field('CodeTab').setAttribute('aria-pressed', String(!toDevices));
    field('DeviceTab').setAttribute('aria-pressed', String(toDevices));
    if (toDevices && !inventory) refresh();
  }
  function togglePanel(open) {
    panel.hidden = !open;
    root.classList.toggle('cm-board-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    if (open) {
      if (root.dataset.mobilePane !== 'chain') root.querySelector('[data-mobile="chain"]')?.click();
      render();
      if (matchMedia('(max-width:1000px)').matches) panel.scrollIntoView({block:'start'});
    } else {
      clearTimeout(timer);
      if (!generated) signature = '';
      toggle.focus();
    }
  }
  toggle.onclick = () => togglePanel(panel.hidden);
  field('Close').onclick = () => togglePanel(false);
  field('Language').onchange = render;
  field('Target').onchange = render;
  field('CodeTab').onclick = () => switchPane(false);
  field('DeviceTab').onclick = () => switchPane(true);
  field('Load').onclick = async () => {
    const preset = byId('cmPreset');
    preset.value = field('Preset').value;
    await preset.onchange({target:preset});
    render();
  };
  field('Generate').onclick = generate;
  async function refresh() {
    if (!local) {
      field('Tools').textContent = '在连接开发板的电脑上打开本地工作台即可访问 USB。';
      return;
    }
    const id = ++refreshId, previous = field('Device').value;
    try {
      const value = await request('devices', {});
      if (id !== refreshId) return;
      inventory = value;
      field('Device').innerHTML = '<option value="">' + (inventory.devices.length ? '请选择设备' : '未发现 Pico 设备') +
        '</option>' + inventory.devices.map(d => '<option value="' + esc(d.id) + '">' + esc(d.label) + '</option>').join('');
      if (inventory.devices.some(d => d.id === previous)) field('Device').value = previous;
      const labels = {sdk:'Pico SDK', cmake:'CMake', ninja:'Ninja', compiler:'Arm 编译器', mpremote:'mpremote', serial:'pyserial'};
      field('Tools').textContent = '已就绪工具  ' + (Object.keys(labels).filter(k => inventory.tools[k]).map(k => labels[k]).join(' / ') || '无');
    } catch (error) {
      if (id !== refreshId) return;
      inventory = null;
      field('Device').innerHTML = '<option value="">设备列表读取失败</option>';
      field('Tools').textContent = error.message;
    }
    deviceChanged();
  }
  function deviceChanged() {
    if (measured && measured.device_id !== device()?.id) {
      measured = null;
      showMeasurement();
      status('已切换设备  运行并回读可查看本设备的结果');
    }
    buttons();
  }
  field('Device').onchange = deviceChanged;
  field('Refresh').onclick = refresh;
  async function operation(label, action) {
    if (working || get().busy || !generated) return;
    working = true;
    core.setBusy(true);
    status(label);
    try {await action();}
    catch (error) {report(error);}
    finally {working = false; core.setBusy(false); buttons();}
  }
  field('Export').onclick = () => operation('正在打包源码…', async () => {
    const blob = await request('export', payload(), true);
    core.download([generated.experiment, generated.board, generated.language, generated.artifact_id.slice(0,8)].join('-') + '.zip', blob, 'application/zip');
    status('源码工程已导出');
  });
  field('Build').onclick = () => operation('正在编译 Pico 固件…', async () => {
    build = await request('build', payload());
    field('Firmware').href = '/api/board/firmware/' + encodeURIComponent(build.build_id);
    field('Firmware').download = build.filename;
    status('固件编译通过  ' + build.size + ' 字节');
  });
  field('Deploy').onclick = () => {
    const selected = device();
    if (!selected || field('Deploy').disabled) return;
    const verb = isCpp() ? '写入固件并替换当前程序' : '上传并替换 main.py';
    if (!window.confirm('向 ' + selected.label + ' ' + verb + '？')) return;
    return operation('正在向 ' + selected.label + ' 写入程序…', async () => {
      await request('deploy', {...payload(), device_id:selected.id, build_id:build?.build_id});
      measured = null;
      showMeasurement();
      status('程序已写入  刷新并选择串口以运行测量');
      await refresh();
    });
  };
  field('Measure').onclick = () => operation('正在等待板端回读…', async () => {
    measured = null;
    showMeasurement();
    measured = await request('run', {...payload(), device_id:device().id});
    showMeasurement();
    const message = measured.status === 'timeout' ? 'UART 接收超时  已记录丢帧' :
      measured.matches_reference ? '板端实测完成  各节点与电脑参考一致' : '板端实测完成  请对照节点数据';
    status(message + '  ' + (device()?.label || measured.device_id));
  });
  field('ResultSave').onclick = () => {
    if (measured) core.download('开发板实测.json', JSON.stringify(measured,null,2), 'application/json');
  };
  return {render, invalidate, buttons};
};
