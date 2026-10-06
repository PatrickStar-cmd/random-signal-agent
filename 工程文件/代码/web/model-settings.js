/* Keys remain in the password input until applied; no browser storage or task queue. */
(() => {
  let providers=[],saved=null,busy=false;
  const tell=(text,error=false)=>{$('modelStatus').textContent=text;$('modelStatus').classList.toggle('studio-error',error)};
  async function api(action,configuration){
    const response=await fetch('/api/model/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,...(configuration?{configuration}:{})})});
    const data=await response.json();if(!response.ok)throw Error(data.error||'模型配置请求失败');return data;
  }
  function show(configuration){
    saved=configuration;$('modelProvider').value=configuration.provider||'custom';$('modelBase').value=configuration.base_url||'';
    $('modelId').value=configuration.model||'';$('modelTimeout').value=configuration.timeout||45;
    $('modelTokenParameter').value=configuration.token_parameter||'max_tokens';$('modelTemperature').value=configuration.send_temperature?'yes':'no';
    $('modelRemember').checked=!!configuration.remember;$('modelKey').value='';$('modelChoice').innerHTML='<option value="">读取列表或手动填写模型 ID</option>';
    $('modelBadge').textContent=configuration.configured?configuration.model:'本地工具链';
    $('modelKey').placeholder=configuration.has_key&&configuration.source==='session'?'已有同地址 Key；留空沿用':'输入此服务的 API Key';presetLink();
  }
  function presetLink(){const p=providers.find(p=>p.id===$('modelProvider').value);$('modelBase').readOnly=!!p&&p.id!=='custom';$('modelKeyLink').hidden=!p?.key_url;if(p?.key_url)$('modelKeyLink').href=p.key_url}
  function configuration(){return {provider:$('modelProvider').value,base_url:$('modelBase').value.trim(),model:$('modelId').value.trim(),api_key:$('modelKey').value,
    timeout:+$('modelTimeout').value,remember:$('modelRemember').checked,enabled:true,token_parameter:$('modelTokenParameter').value,send_temperature:$('modelTemperature').value==='yes'}}
  async function action(fn){
    if(busy)return;busy=true;document.querySelectorAll('#modelPanel input,#modelPanel select,#modelPanel button').forEach(e=>e.disabled=true);
    try{await fn()}catch(e){tell(e.message,true)}finally{busy=false;document.querySelectorAll('#modelPanel input,#modelPanel select,#modelPanel button').forEach(e=>e.disabled=false)}
  }
  $('modelProvider').onchange=()=>{
    const p=providers.find(p=>p.id===$('modelProvider').value);if(!p)return;
    $('modelBase').value=p.base_url;$('modelTokenParameter').value=p.token_parameter;$('modelTemperature').value=p.send_temperature?'yes':'no';
    $('modelKey').value='';$('modelId').value='';$('modelChoice').innerHTML='<option value="">先读取模型列表，或手动填写</option>';presetLink();tell('已选择服务，请填写该服务的 Key 并读取模型列表。');
  };
  $('modelChoice').onchange=()=>{if($('modelChoice').value)$('modelId').value=$('modelChoice').value};
  $('modelBase').oninput=()=>{$('modelChoice').innerHTML='<option value="">地址已改变，请重新读取模型列表</option>';tell('地址已改变，请使用此地址对应的 Key。')};
  $('modelList').onclick=()=>action(async()=>{
    tell('正在读取可用模型…');const data=await api('models',configuration());
    $('modelChoice').innerHTML='<option value="">选择可用模型</option>'+data.models.map(id=>`<option value="${escapeHtml(id)}">${escapeHtml(id)}</option>`).join('');
    if(data.models.includes($('modelId').value))$('modelChoice').value=$('modelId').value;
    else if(data.models.length){$('modelChoice').value=data.models[0];$('modelId').value=data.models[0]}
    tell(`已读取 ${data.models.length} 个模型${data.truncated?'（列表已截断）':''}。列表可能包含非对话模型，请测试后使用。`);
  });
  async function save(test){
    if(!$('modelForm').reportValidity())return;
    const draft=configuration();await action(async()=>{
      if(test){tell('正在测试所选模型…');await api('test',draft)}
      tell('正在应用配置…');const data=await api('save',draft);show(data.settings);
      tell((test?'文本对话测试通过，':'已应用，尚未验证连接；')+'当前会话已使用 '+data.settings.model+'。'+(data.settings.remember?'重启后保留。':'服务重启后需重新配置。'));
    });
  }
  $('modelForm').onsubmit=e=>{e.preventDefault();save(true)};$('modelSave').onclick=()=>save(false);
  $('modelDisable').onclick=()=>action(async()=>{show((await api('disable')).settings);tell('已切回本地工具链；保存的 Key 保留，可重新应用。')});
  $('modelClear').onclick=()=>{if(!window.confirm('移除当前会话的模型配置和 Key？随后恢复服务的环境变量默认配置。'))return;action(async()=>{show((await api('clear')).settings);tell('当前会话配置与 Key 已移除，已恢复服务默认设置。')})};
  fetch('/api/model/settings?session_id='+encodeURIComponent(sessionId)).then(async r=>{const data=await r.json();if(!r.ok)throw Error(data.error);providers=data.providers;
    $('modelProvider').innerHTML=providers.map(p=>`<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`).join('');show(data.settings);
    if(data.settings.configured)tell('当前使用 '+data.settings.model+'（'+(data.settings.source==='environment'?'服务默认配置':data.settings.remember?'已记住配置':'服务内存配置')+'）。');
  }).catch(e=>tell(e.message,true));
})();
