'use strict';
(() => {
  let busy=false, configured=false, managed=false;
  function render(){
    $('key-status').textContent=configured?'已配置':'尚未配置';
    $('api-key').disabled=busy||managed;
    $('save-key').disabled=busy||managed;
    $('test-key').disabled=busy||!configured;
  }
  async function read(){
    try{const d=await api('settings');configured=d.configured;managed=d.managed;render();if(managed)$('key-help').textContent='当前由启动环境提供 Key。如需在页面修改，请先移除启动环境中的配置。';}
    catch(e){$('settings-message').textContent=e.message;}
  }
  async function send(path,body){
    const response=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await response.json();if(!response.ok)throw new Error(d.error||'操作失败');return d;
  }
  $('settings-form').addEventListener('submit',async e=>{
    e.preventDefault();if(busy)return;
    if(!$('api-key').value.trim()){$('settings-message').textContent='请输入新的 API Key；已有配置未改变。';return;}
    busy=true;render();$('settings-message').textContent='正在保存…';
    try{const d=await send('settings',{key:$('api-key').value});$('api-key').value='';configured=d.configured;managed=d.managed;$('settings-message').textContent=d.message;}
    catch(e){$('settings-message').textContent=e.message;}
    finally{busy=false;render();}
  });
  $('test-key').addEventListener('click',async()=>{
    if(busy)return;busy=true;render();$('settings-message').textContent='正在测试已保存的 Key…';
    try{$('settings-message').textContent=(await send('settings/test',{})).message;}
    catch(e){$('settings-message').textContent=e.message;}
    finally{busy=false;render();}
  });
  read();
})();
