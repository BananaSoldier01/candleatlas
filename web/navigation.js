'use strict';
(() => {
  function switchPanel(type,value){
    for(const panel of document.querySelectorAll(`[data-${type}-panel]`))panel.hidden=panel.dataset[type+'Panel']!==value;
    for(const button of document.querySelectorAll(`[data-${type}-view]`)){
      const active=button.dataset[type+'View']===value;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));
    }
    if(type==='market')document.dispatchEvent(new CustomEvent('market-view',{detail:value}));
    requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));
  }
  $('market-views').addEventListener('click',e=>{const b=e.target.closest('[data-market-view]');if(b)switchPanel('market',b.dataset.marketView);});
  $('board-views').addEventListener('click',e=>{const b=e.target.closest('[data-board-view]');if(b)switchPanel('board',b.dataset.boardView);});
  document.addEventListener('board-view',e=>switchPanel('board',e.detail));
  document.addEventListener('click',e=>{
    const route=e.target.closest('[data-route]');if(route){showWorkspace(route.dataset.route);if(route.dataset.route==='stocks')$('search-query').focus();}
    const board=e.target.closest('[data-show-board]');if(board){showWorkspace('boards');switchPanel('board',board.dataset.showBoard);}
    const ranking=e.target.closest('[data-open-rank]');if(ranking){showWorkspace('market');switchPanel('market','rankings');document.dispatchEvent(new CustomEvent('open-ranking',{detail:ranking.dataset.openRank}));}
    const day=e.target.closest('[data-observe-day]');if(day){$('date').value=day.dataset.observeDay;$('date').dispatchEvent(new Event('change'));}
  });
  let origin='market';
  document.addEventListener('research-origin',e=>{
    if(!pages[e.detail])return;origin=e.detail;$('stock-back').hidden=false;$('stock-back').textContent='← 返回'+pages[origin][0];
  });
  $('stock-back').addEventListener('click',()=>showWorkspace(origin));
  function resume(){
    if(!watchLoaded)return;
    const rows=observations.filter(o=>o.active).slice(0,3);
    $('home-watch').innerHTML=rows.length?rows.map(o=>`<div class="resume-item">${stockLink(o)}<small>${esc(o.date)}</small><p>${esc(o.note)}</p></div>`).join(''):'<div class="resume-empty"><strong>把关注留在这里</strong><p>从榜单或线索选择股票，记录关注理由，下次打开就能继续跟踪。</p><button class="text-action" data-route="themes">寻找线索 →</button></div>';
  }
  document.addEventListener('records-updated',resume);resume();
})();
