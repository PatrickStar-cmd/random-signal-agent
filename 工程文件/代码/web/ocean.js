/* View navigation keeps the existing controls and experiment state mounted. */
(() => {
  const views = Array.from(document.querySelectorAll('[data-view]'));
  const links = Array.from(document.querySelectorAll('[data-view-link]'));
  const targets = {workspace: 'layoutRoot', templates: 'workbenchPanel', data: 'dataPanel', comparison: 'comparisonPanel', diagnostics: 'diagnosticPanel', settings: 'modelPanel'};
  function show(name, focus = false) {
    if (!(name in targets)) name = 'workspace';
    const current = views.find(v => v.dataset.view === name);
    views.forEach(v => { v.hidden = v !== current; });
    document.querySelectorAll('.workflow-nav a').forEach(a => {
      if (a.dataset.viewLink === name) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    const target = document.getElementById(targets[name]);
    if (target?.tagName === 'DETAILS') target.open = true;
    if (focus) {
      current.tabIndex = -1;
      current.focus({preventScroll: true});
      window.scrollTo({top: 0, behavior: 'instant'});
    }
    // Canvas backing sizes must be refreshed after revealing a hidden view.
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  }
  function fromHash() {
    const id = location.hash.slice(1);
    return Object.keys(targets).find(name => targets[name] === id) ||
      document.getElementById(id)?.closest('[data-view]')?.dataset.view || 'workspace';
  }
  function navigate(name) {
    if (!(name in targets)) return;
    const hash = `#${targets[name]}`;
    if (location.hash !== hash) history.pushState(null, '', hash);
    show(name, true);
  }
  links.forEach(a => a.addEventListener('click', event => {
    event.preventDefault();
    navigate(a.dataset.viewLink);
  }));
  window.addEventListener('workspace-navigate', event => navigate(event.detail));
  window.addEventListener('popstate', () => show(fromHash(), true));
  window.addEventListener('hashchange', () => show(fromHash(), true));
  document.querySelector('.skip-link').addEventListener('click', () => show('workspace'));
  const quick = document.createElement('div');
  quick.className = 'ocean-quick';
  quick.setAttribute('aria-label', '对话示例');
  for (const [label, prompt] of [['从示例开始', '采集 8 秒 200Hz 主频 8Hz 的随机信号并分析'], ['诊断信号', '诊断信号'], ['了解功率谱', '解释功率谱密度的含义']]) {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = label;
    button.onclick = () => { $('messageInput').value = prompt; $('messageInput').focus(); };
    quick.append(button);
  }
  $('messages').after(quick);
  show(fromHash());
})();
