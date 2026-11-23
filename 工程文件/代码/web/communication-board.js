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
  const roles = ['tx','rx'];
  const roleName = {tx:'发送端', rx:'接收端'};
  const builds = {tx:null, rx:null};
  let devicePane = false;
  const paired = () => get().program?.blocks.some(b => b.kind === 'uart_link');
  const choice = (role = '') => ({language:field(role+'Language').value, board:field(role+'Target').value});
  const target = () => paired() ? {targets:{tx:choice('tx'), rx:choice('rx')}} : choice();
  const isCpp = () => choice().language === 'cpp';
  const isEsp = board => board === 'esp32s3';
  const statusName = {ok:'通过', timeout:'接收超时', crc_error:'CRC 错误', sequence_error:'序号不匹配',
    length_error:'有效位数不匹配', frame_error:'帧头错误'};
  const pins = board => isEsp(board) ? ['GPIO17','GPIO18'] : ['GP0','GP1'];
  function setupHint(c) {
    if (isEsp(c.board)) return c.language === 'cpp' ? '从 ESP-IDF 终端启动工作台。选择 USB 转 UART 端口写入 BIN。' :
      '安装 ESP32_GENERIC_S3 解释器后，通过固件控制台对应的 USB 串口上传 main.py。';
    return c.language === 'cpp' ? '按住 BOOTSEL 接入 USB，选择启动盘写入 UF2，再选择运行态串口。' :
      '首次安装时按住 BOOTSEL 接入 USB，将本板的 MicroPython UF2 复制到 RPI-RP2 盘。';
  }
  const cardFor = id => id === 'graph' ? root.querySelector('.cm-scratch-parallel') :
    [...byId('cmProgram').querySelectorAll('[data-cm-id]')].find(el => el.dataset.cmId === id);
  const device = (role = '') => inventory?.devices.find(d => d.id === field(role+'Device').value);
  function accepts(d, board) {
    if (!d) return false;
    if (d.kind === 'bootsel') return !isEsp(board);
    return d.kind === 'serial' && (!d.family || d.family === (isEsp(board) ? 'esp32s3' : 'pico'));
  }
  function writable(d, c, firmware) {
    return accepts(d, c.board) && (c.language === 'cpp' ?
      firmware && d.kind === (isEsp(c.board) ? 'serial' : 'bootsel') : d.kind === 'serial');
  }
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
    field('Generate').disabled = locked || pending;
    const pair = paired();
    field('SingleTargets').hidden = field('SingleDevice').hidden = pair;
    field('PairTargets').hidden = !pair;
    field('Build').hidden = pair || !isCpp();
    field('Deploy').hidden = pair;
    field('Build').disabled = locked || !local || !generated || pair;
    field('Deploy').disabled = locked || !local || !generated || !writable(device(), choice(), build);
    field('Deploy').textContent = isCpp() ? '烧录固件' : '上传程序';
    field('Firmware').hidden = pair || !build;
    field('CppSetup').hidden = pair || !isCpp();
    field('MicroSetup').hidden = pair || isCpp();
    field('CppHint').textContent = field('MicroHint').textContent = setupHint(choice());
    field('FirmwareHelp').href = 'https://micropython.org/download/' +
      ({pico:'RPI_PICO',pico_w:'RPI_PICO_W',esp32s3:'ESP32_GENERIC_S3'}[choice().board]) + '/';
    field('Measure').textContent = pair ? '运行双板实验' : '运行并回读';
    const ready = role => device(role)?.kind === 'serial' && accepts(device(role), choice(role).board);
    field('Measure').disabled = locked || !local || !generated || (pair ?
      !roles.every(ready) || device('tx')?.id === device('rx')?.id : !ready(''));
    if (pair) for (const role of roles) {
      const c = choice(role), cpp = c.language === 'cpp';
      for (const name of ['Target','Language','Device']) field(role+name).disabled = locked;
      field(role+'DevicePane').hidden = !devicePane;
      field(role+'Export').hidden = devicePane;
      field(role+'Export').disabled = locked || !generated;
      field(role+'Build').hidden = !cpp;
      field(role+'Build').disabled = locked || !local || !generated;
      field(role+'Deploy').disabled = locked || !local || !generated || !writable(device(role), c, builds[role]);
      field(role+'Deploy').textContent = cpp ? '烧录固件' : '上传程序';
      field(role+'Firmware').hidden = !builds[role];
      field(role+'Setup').textContent = setupHint(c);
    }
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
    const frame = measured?.frame;
    field('Frame').hidden = !frame;
    if (frame) {
      const check = frame.crc_ok === null ? '待完整收帧' : frame.crc_ok ? '通过' : '错误';
      const seq = frame.rx_sequence != null && frame.rx_sequence !== frame.sequence ? '  收到帧 '+frame.rx_sequence : '';
      const checksum = frame.crc16 == null ? '' : '  0x'+frame.crc16.toString(16).toUpperCase().padStart(4,'0');
      field('Frame').innerHTML = '<strong>帧 ' + esc(String(frame.sequence)+seq) + '  ' + esc(statusName[frame.status]) +
        '  CRC ' + check + esc(checksum) + '</strong><p>发送  ' + esc(sampleText(frame.sent, false)) +
        '</p><p>接收  ' + (frame.received ? esc(sampleText(frame.received, false)) : '本帧未交付') + '</p>';
    }
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
    const role = currentFile.split('/')[0], ep = generated.endpoints?.[role];
    const map = ep ? ep.source_map : generated.source_map;
    const path = ep ? currentFile.slice(role.length+1) : currentFile;
    const ranges = Object.entries(map).filter(([,r]) => r.file === path);
    const owners = new Map();
    for (const [id,r] of ranges) for (let n = r.start; n <= r.end; n++) owners.set(n,id);
    field('File').value = currentFile;
    field('Code').innerHTML = generated.files[currentFile].split('\n').map((line,i) => {
      const id = owners.get(i + 1);
      const attrs = id ? ' data-board-block="' + esc(id) + '" role="button" tabindex="' +
        (map[id].start === i + 1 ? '0' : '-1') + '" title="定位 ' + esc(nameFor(id)) + '"' : '';
      return '<div class="cm-board-line"' + attrs + '><span aria-hidden="true">' + (i + 1) +
        '</span><code>' + esc(line || ' ') + '</code></div>';
    }).join('');
  }
  function selectSource(scroll, follow = true) {
    if (!generated) return;
    const id = get().selectedId, role = currentFile.split('/')[0];
    const inRole = generated.endpoints?.[role]?.source_map[id];
    const range = inRole ? {file:role+'/'+inRole.file} : generated.source_map[id];
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
      if (generated.endpoints) {
        field('Wiring').textContent = '发送端 '+pins(choice('tx').board)[0]+'（TX）接接收端 '+pins(choice('rx').board)[1]+
          '（RX），两板 GND 相连。两路 USB 分别连接电脑。';
      } else if (generated.experiment === 'uart') {
        const [tx,rx] = pins(choice().board);
        field('Wiring').textContent = '用跳线连接 '+tx+'（TX）与 '+rx+'（RX）。USB 用于部署和回读结果。';
      } else {
        field('Wiring').textContent = '用数据线连接 USB。' + (generated.experiment === 'qpsk' ? 'QPSK 的 I/Q 分量' : 'BPSK 符号') + '在板内计算。';
      }
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
    builds.tx = builds.rx = null;
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
    devicePane = toDevices;
    buttons();
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
  field('Target').onchange = changedTarget;
  function changedTarget() { if (inventory) fillDevices(); render(); }
  for (const role of roles) {
    field(role+'Target').onchange = changedTarget;
    field(role+'Language').onchange = render;
    field(role+'Device').onchange = deviceChanged;
    field(role+'Build').onclick = () => compileBoard(role);
    field(role+'Deploy').onclick = () => deployBoard(role);
    field(role+'Export').onclick = () => exportProject(role);
  }
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
    const id = ++refreshId;
    try {
      const value = await request('devices', {});
      if (id !== refreshId) return;
      inventory = value;
      fillDevices();
      const labels = {sdk:'Pico SDK', esp_idf:'ESP-IDF', cmake:'CMake', ninja:'Ninja', compiler:'Arm 编译器', mpremote:'mpremote', serial:'pyserial'};
      field('Tools').textContent = '已就绪工具  ' + (Object.keys(labels).filter(k => inventory.tools[k]).map(k => labels[k]).join(' / ') || '无');
    } catch (error) {
      if (id !== refreshId) return;
      inventory = null;
      for (const role of ['', ...roles]) field(role+'Device').innerHTML = '<option value="">设备列表读取失败</option>';
      field('Tools').textContent = error.message;
    }
    deviceChanged();
  }
  function fillDevices() {
    for (const role of ['', ...roles]) {
      const select = field(role+'Device'), previous = select.value;
      const available = inventory.devices.filter(d => accepts(d, choice(role).board));
      select.innerHTML = '<option value="">'+(available.length ? '请选择设备' : '未发现对应设备')+'</option>'+
        available.map(d => '<option value="'+esc(d.id)+'">'+esc(d.label)+'</option>').join('');
      if (available.some(d => d.id === previous)) select.value = previous;
    }
  }
  function deviceChanged() {
    if (measured && (paired() ? roles.some(role => measured.device_ids?.[role] !== device(role)?.id) : measured.device_id !== device()?.id)) {
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
  const rolePayload = role => role ? {...payload(), role} : payload();
  function exportProject(role) {
    return operation('正在打包源码…', async () => {
      const blob = await request('export', rolePayload(role), true);
      const item = generated.endpoints?.[role] || generated;
      const parts = item.endpoints ? ['dual-uart'] : [item.experiment,item.board,item.language];
      core.download([...parts,role || '',(item.artifact_id || '').slice(0,8)].filter(Boolean).join('-')+'.zip', blob, 'application/zip');
      status('源码工程已导出');
    });
  }
  field('Export').onclick = () => exportProject('');
  function compileBoard(role) {
    return operation('正在编译'+(roleName[role] || '开发板')+'固件…', async () => {
      const result = await request('build', rolePayload(role));
      if (role) builds[role] = result; else build = result;
      const link = field(role+'Firmware');
      link.href = '/api/board/firmware/'+encodeURIComponent(result.build_id);
      link.download = result.filename;
      link.textContent = isEsp(choice(role).board) ? '下载 BIN' : '下载 UF2';
      status((roleName[role] || '')+'固件编译通过  '+result.size+' 字节');
    });
  }
  field('Build').onclick = () => compileBoard('');
  function deployBoard(role) {
    const selected = device(role);
    if (!selected || field(role+'Deploy').disabled) return;
    const verb = choice(role).language === 'cpp' ? '写入固件并替换当前程序' : '上传并替换 main.py';
    if (!window.confirm('向 '+(roleName[role] || '')+' '+selected.label+' '+verb+'？')) return;
    return operation('正在向 '+selected.label+' 写入程序…', async () => {
      await request('deploy', {...rolePayload(role), device_id:selected.id, build_id:(role ? builds[role] : build)?.build_id});
      measured = null;
      showMeasurement();
      status('程序已写入  刷新并选择运行态串口');
      await refresh();
    });
  }
  field('Deploy').onclick = () => deployBoard('');
  field('Measure').onclick = () => operation('正在等待板端回读…', async () => {
    measured = null;
    showMeasurement();
    const ids = paired() ? {device_ids:{tx:device('tx').id, rx:device('rx').id}} : {device_id:device().id};
    measured = await request('run', {...payload(), ...ids});
    showMeasurement();
    const message = measured.status === 'ok' ?
      (measured.matches_reference ? '板端实测完成  各节点与电脑参考一致' : '板端实测完成  请对照节点数据') :
      'UART '+(statusName[measured.status] || measured.status)+'  已记录丢帧';
    status(message);
  });
  field('ResultSave').onclick = () => {
    if (measured) core.download('开发板实测.json', JSON.stringify(measured,null,2), 'application/json');
  };
  return {render, invalidate, buttons};
};
