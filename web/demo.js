'use strict';
(async()=>{
 try{
  const r=await fetch('/api/runtime'),runtime=await r.json();if(runtime.mode!=='demo')return;
  document.body.classList.add('demo-mode');document.title='观市 · 合成演示';
  const banner=document.createElement('div');banner.id='demo-banner';banner.className='demo-banner';banner.setAttribute('role','note');banner.innerHTML='<strong>合成演示 · 只读</strong>全部价格、日期和记录为程序合成，非真实行情。不联网、不读取密钥、不调用AI。部分功能没有演示样本时会明确留空。';
  document.body.prepend(banner);const resize=()=>document.documentElement.style.setProperty('--demo-banner-height',banner.getBoundingClientRect().height+'px');new ResizeObserver(resize).observe(banner);resize();const source=document.querySelector('.statusline>span');if(source)source.textContent='合成行情 · 无网络连接';const caption=document.querySelector('.brand-caption>span');if(caption)caption.textContent='合成演示';
  const footer=document.querySelector('footer');if(footer)footer.textContent='程序合成示例 · 非真实行情 · 不保存操作 · 不联网';
  const selectors=['#analyze-technical','#analyze-ai','#batch-run','#batch-cancel','#batch-retry','#sync-day','#import-watch','#observe-stock','#save-model','#test-model','#model-key','#model-url','#model-name','#model-clear','[data-archive]','[data-observe]','[data-desk-action="note"]','#watch-form button[type="submit"]','[data-workspace="settings"] input','[data-workspace="settings"] button[type="submit"]'];
  function disable(){
   const real=document.getElementById('guide-source-real');
   if(real&&real.textContent!=='示例自选 · 合成行情')real.textContent='示例自选 · 合成行情';
   if(real?.getAttribute('aria-pressed')==='true'){
    for(const [selector,text] of [
     ['.guide-data-source .guide-small','程序合成日K · 按正式指标口径计算 · 非真实行情'],
     ['.guide-lab-heading .eyebrow','动手试一试 · 示例自选 · 合成行情'],
    ]){
     const node=document.querySelector(selector);if(node&&node.textContent!==text)node.textContent=text;
    }
    const note=document.querySelector('#guide-lab-controls .guide-small');
    if(note?.textContent.startsWith('真实四价只读'))note.textContent=note.textContent.replace('真实四价只读','合成四价只读');
    const chart=document.querySelector('#guide-lab-chart svg'),label=chart?.getAttribute('aria-label');
    if(label?.includes('真实行情'))chart.setAttribute('aria-label',label.replaceAll('真实行情','合成行情'));
   }
   for(const n of document.querySelectorAll(selectors.join(','))){if(!n.disabled)n.disabled=true;if(!n.hasAttribute('data-demo-disabled')){n.setAttribute('data-demo-disabled','');n.title='演示模式只读，不提交或保存';}}
  }
  new MutationObserver(disable).observe(document.body,{subtree:true,childList:true});disable();
 }catch{ /* Live mode still uses its normal error reporting. */ }
})();
