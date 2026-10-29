'use strict';
// 变化列着色：只有可比的价格类（close / change1 / change20）使用红涨绿跌。
(function(root){
  function hiddenDirection(row){
    return !!(row&&(row.hide_direction||row.display==='hidden_direction'||row.direction==='not_comparable'||row.direction==='window_sensitive'));
  }
  function deltaToneClass(row){
    const item=row||{};
    if(hiddenDirection(item))return 'delta-na';
    if(item.metric_class==='price'&&item.direction==='up')return 'quote-up';
    if(item.metric_class==='price'&&item.direction==='down')return 'quote-down';
    return '';
  }
  const api={deltaToneClass,hiddenDirection};
  root.DeltaDisplay=api;
  if(typeof module==='object'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
