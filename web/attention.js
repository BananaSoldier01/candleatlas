'use strict';
(() => {
  let version=0;
  function render(data){
    $('attention-body').innerHTML=window.LabelRules?LabelRules.cardHTML(data):'';
  }
  async function load(){
    const host=$('attention-body');if(!host)return;
    if(!state.date){host.textContent='等待观察日';return;}
    const token=++version;host.textContent='正在读取本机自选…';
    try{
      const data=await api('workbench',{date:state.date});
      if(token!==version)return;
      render(data);
    }catch(e){if(token===version)host.textContent=window.LabelRules?LabelRules.loadError:'自选完成度读取失败，市场概览其余部分不受影响。';}
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-open-desk]');if(!button)return;
    document.dispatchEvent(new CustomEvent('open-desk-stock',{detail:button.dataset.openDesk}));
  });
  document.addEventListener('day-selected',load);
  if(state.date)load();
})();
