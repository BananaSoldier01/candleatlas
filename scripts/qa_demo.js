// Run only in an isolated browser pointed at a --demo server.
async page => {
 const origin=new URL(page.url()).origin,checks={},errors=[],consoleErrors=[],writes=[],external=[];
 const runtime=await (await page.request.get(origin+'/api/runtime')).json();if(runtime.mode!=='demo'||!runtime.read_only)throw Error('Only an isolated --demo server is permitted');
 const assert=(key,x)=>{checks[key]=!!x;if(!x)throw Error(key)};
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});
 await page.route('**/*',async route=>{const r=route.request(),url=new URL(r.url());if(url.origin!==origin){external.push(url.href);return route.abort()}if(!['GET','HEAD'].includes(r.method())){writes.push(url.href);return route.abort()}return route.continue()});
 await page.setViewportSize({width:1440,height:1050});await page.goto(origin+'/#watch');await page.reload();
 await page.waitForFunction(()=>document.querySelector('#demo-banner')&&document.querySelectorAll('[data-desk-stock]').length===3);
 assert('three_synthetic_stocks_are_available',await page.locator('[data-desk-stock]').count()===3);
 assert('banner_is_clear',(await page.locator('#demo-banner').textContent()).includes('非真实行情'));
 assert('banner_does_not_overlap_app',await page.evaluate(()=>document.querySelector('#demo-banner').getBoundingClientRect().bottom<=document.querySelector('header').getBoundingClientRect().top+1));
 assert('source_is_labeled_synthetic',(await page.locator('.statusline').textContent()).includes('合成行情'));
 assert('batch_mutation_is_disabled',await page.locator('#batch-run').isDisabled());
 await page.screenshot({path:'output/playwright/public-demo-workbench.png'});
 await page.locator('[data-desk-action="chart"]').click();await page.waitForFunction(()=>!!document.querySelector('#price-chart svg'));
 assert('real_chart_code_runs_on_synthetic_prices',await page.locator('#price-chart svg').count()>0);
 assert('rsi_and_macd_panels_are_present',await page.locator('#price-indicator-summary').isVisible());
 assert('analysis_is_not_automatically_run',writes.length===0);
 await page.locator('[data-view="analysis"]').click();
 await page.waitForFunction(()=>!!document.querySelector('.technical-assessment')&&document.querySelectorAll('[data-delta-metric]').length>0);
 assert('technical_assessment_is_visible',await page.locator('.technical-assessment').isVisible());
 assert('report_comparison_has_rows',await page.locator('[data-delta-metric]').count()>0);
 assert('technical_mutation_is_disabled',await page.locator('#analyze-technical').isDisabled());
 assert('ai_mutation_is_disabled',await page.locator('#analyze-ai').isDisabled());
 assert('report_material_is_marked_synthetic',(await page.locator('.analysis-limitations').textContent()).includes('程序合成'));
 await page.screenshot({path:'output/playwright/public-demo-analysis.png'});
 await page.locator('[data-page="guide"]').click();
 await page.locator('[data-guide-term="rsi"]').first().click();await page.waitForFunction(()=>!!document.querySelector('#guide-lab svg'));
 assert('beginner_guide_and_rsi_lab_work',await page.locator('#guide-lab svg').count()>0);
 await page.locator('#guide-source-real').click();await page.waitForFunction(()=>document.querySelector('#guide-real-status')?.textContent.includes('合成示例'));
 assert('watchlist_source_does_not_claim_real_quotes',(await page.locator('#guide-source-real').textContent()).includes('合成行情'));
 assert('watchlist_learning_uses_synthetic_stock',(await page.locator('#guide-real-status').textContent()).includes('合成示例'));
 const before=await page.locator('#guide-real-day').inputValue();await page.locator('#guide-real-prev').click();
 assert('learning_date_can_be_changed',await page.locator('#guide-real-day').inputValue()!==before);
 const checkGuideLabels=async view=>{
  const day=await page.locator('#guide-real-day').inputValue();
  for(const id of ['ohlc','ma','return','rsi','macd']){
   await page.locator(`.guide-lab-switch [data-guide-term="${id}"]`).click();
   await page.waitForSelector('#guide-real-day');
   assert(`${view}_${id}_heading_is_synthetic`,(await page.locator('.guide-lab-heading .eyebrow').textContent()).includes('示例自选 · 合成行情'));
   assert(`${view}_${id}_chart_does_not_claim_real_quotes`,!(await page.locator('#guide-lab-chart svg').getAttribute('aria-label')).includes('真实行情'));
   assert(`${view}_${id}_date_is_preserved`,await page.locator('#guide-real-day').inputValue()===day);
   if(id==='ohlc')assert(`${view}_ohlc_readonly_note_is_synthetic`,(await page.locator('#guide-lab-controls').textContent()).includes('合成四价只读'));
  }
  await page.locator('#guide-source-sample').click();
  assert(`${view}_sample_heading_remains_synthetic`,(await page.locator('.guide-lab-heading .eyebrow').textContent()).trim()==='动手试一试 · 合成行情');
  await page.locator('#guide-source-real').click();
  await page.waitForFunction(()=>document.querySelector('.guide-lab-heading .eyebrow')?.textContent.includes('示例自选 · 合成行情'));
  assert(`${view}_return_to_watchlist_keeps_date`,await page.locator('#guide-real-day').inputValue()===day);
 };
 await checkGuideLabels('desktop');
 await page.screenshot({path:'output/playwright/public-demo-guide.png'});
 await page.setViewportSize({width:390,height:844});
 await page.waitForFunction(()=>document.querySelector('#demo-banner').getBoundingClientRect().bottom<=document.querySelector('header').getBoundingClientRect().top+1);
 assert('mobile_has_no_horizontal_page_overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1&&document.querySelector('main').scrollWidth<=document.querySelector('main').clientWidth+1));
 assert('mobile_banner_stays_above_app',await page.evaluate(()=>document.querySelector('#demo-banner').getBoundingClientRect().bottom<=document.querySelector('header').getBoundingClientRect().top+1));
 await checkGuideLabels('mobile');
 await page.locator('#guide-lab').scrollIntoViewIfNeeded();
 await page.screenshot({path:'output/playwright/public-demo-mobile.png'});
 await page.locator('[data-page="settings"]').click();
 assert('credential_entry_is_disabled',await page.locator('#model-key').isDisabled());
 assert('model_connect_test_is_disabled',await page.locator('#test-model').isDisabled());
 // Stub only runtime metadata to check live labels; the server still serves synthetic data.
 await page.route('**/api/runtime',route=>route.fulfill({json:{mode:'live',read_only:false,synthetic:false}}));
 await page.goto(origin+'/#guide');await page.reload();await page.waitForSelector('#guide-source-real');
 assert('live_runtime_does_not_add_demo_banner',await page.locator('#demo-banner').count()===0);
 assert('live_source_label_is_unchanged',(await page.locator('#guide-source-real').textContent()).includes('我的自选 · 真实行情'));
 await page.locator('#guide-source-real').click();await page.waitForSelector('#guide-real-day');
 for(const id of ['ohlc','ma','return','rsi','macd']){
  await page.locator(`.guide-lab-switch [data-guide-term="${id}"]`).click();
  assert(`live_${id}_heading_is_unchanged`,(await page.locator('.guide-lab-heading .eyebrow').textContent()).trim()==='动手试一试 · 真实行情');
  if(['ohlc','ma','return'].includes(id))assert(`live_${id}_chart_label_is_unchanged`,(await page.locator('#guide-lab-chart svg').getAttribute('aria-label')).includes('真实行情'));
 }
 await page.unroute('**/api/runtime');
 assert('no_javascript_errors',errors.length===0);assert('no_console_errors',consoleErrors.length===0);assert('no_ui_write_requests',writes.length===0);assert('no_external_browser_requests',external.length===0);
 return {status:'PASS',checks,total:Object.keys(checks).length,errors,consoleErrors,writes,external};
}
