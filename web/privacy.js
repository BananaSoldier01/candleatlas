'use strict';
(function(factory){
  const api=factory();
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.Privacy=api;
  if(typeof document!=='undefined'){
    let storage;
    try{storage=window.localStorage;}catch(e){storage={getItem(){throw e;},setItem(){throw e;}};}
    api.bind(document,storage);
  }
})(function(){
  const KEY='guanshi.privacy.v1';
  const PLACEHOLDER='已隐藏 · 点击显示';
  function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function maskNote(text,on){
    const value=text==null?'':String(text);
    if(!on||value==='')return value;
    return PLACEHOLDER;
  }
  function readPref(storage){
    try{return storage.getItem(KEY)==='1';}
    catch(e){return false;}
  }
  function writePref(storage,on){
    try{storage.setItem(KEY,on?'1':'0');return true;}
    catch(e){return false;}
  }
  function privateHTML(text,className,on){
    const raw=text==null?'':String(text);
    const hidden=!!on&&raw!=='';
    const shown=maskNote(raw,!!on);
    const cls=[className,'private-text'].filter(Boolean).join(' ');
    const interactive=hidden?' tabindex="0" role="button" aria-pressed="false"':'';
    return `<p class="${cls}"${interactive} data-private="${esc(raw)}">${esc(shown)}</p>`;
  }
  function toggleNote(el){
    if(!el||!document.body.classList.contains('privacy-on'))return;
    if(el.matches('textarea,input')){el.classList.add('private-revealed');return;}
    if(el.getAttribute('role')!=='button'||el.dataset.private==null||el.dataset.private==='')return;
    const open=el.getAttribute('aria-pressed')==='true';
    if(open){
      el.textContent=maskNote(el.dataset.private,true);
      el.setAttribute('aria-pressed','false');
      el.classList.remove('private-revealed');
    }else{
      el.textContent=el.dataset.private;
      el.setAttribute('aria-pressed','true');
      el.classList.add('private-revealed');
    }
  }
  function bind(doc,storage){
    const button=doc.getElementById('privacy-toggle');
    if(!button||!doc.body)return;
    const paint=on=>{
      doc.body.classList.toggle('privacy-on',!!on);
      button.setAttribute('aria-pressed',on?'true':'false');
      if(on)doc.querySelectorAll('.private-revealed').forEach(el=>el.classList.remove('private-revealed'));
    };
    paint(readPref(storage));
    button.addEventListener('click',()=>{
      const next=button.getAttribute('aria-pressed')!=='true';
      writePref(storage,next);
      paint(readPref(storage));
      doc.dispatchEvent(new Event('privacy-changed'));
    });
    doc.addEventListener('click',event=>{
      const el=event.target.closest&&event.target.closest('.private-text');
      if(el)toggleNote(el);
    });
    doc.addEventListener('keydown',event=>{
      if(event.key!=='Enter'&&event.key!==' ')return;
      const el=event.target.closest&&event.target.closest('.private-text');
      if(!el||el.matches('textarea,input'))return;
      event.preventDefault();
      toggleNote(el);
    });
    doc.addEventListener('focusin',event=>{
      const el=event.target;
      if(el.matches&&el.matches('textarea.private-text, input.private-text'))toggleNote(el);
    });
  }
  return {KEY,PLACEHOLDER,maskNote,readPref,writePref,privateHTML,bind};
});
