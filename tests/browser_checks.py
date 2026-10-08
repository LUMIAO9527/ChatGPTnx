"""Offline DOM/layout regressions in an installed Chromium/Edge browser."""
from __future__ import annotations
import argparse
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT_ID = 'nx-check-results'

HARNESS = r'''<script>
const nxReportHarnessError=message=>{if(document.querySelector('#nx-check-results'))return;const pre=document.createElement('pre');pre.id='nx-check-results';pre.textContent=btoa(unescape(encodeURIComponent(JSON.stringify([...(window.__nxChecks||[]),{name:'harness/runtime',passed:false,details:String(message)}]))));document.body.appendChild(pre);};
window.addEventListener('error',event=>nxReportHarnessError(event.error?.stack||event.message));
window.addEventListener('unhandledrejection',event=>nxReportHarnessError(event.reason?.stack||event.reason));
(async()=>{
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const out=window.__nxChecks=[];
  const check=(name,passed,details='')=>out.push({name,passed:!!passed,details});
  const box=target=>(typeof target==='string'?document.querySelector(target):target).getBoundingClientRect();
  const scenario=async name=>{window.NXDemo.scenario(name);await window.nxShown();await wait(100);};
  const stableScrollRegion=region=>{
    const width=region.clientWidth,scroll=region.scrollTop,spacer=document.createElement('div');
    spacer.style.cssText='height:2000px;min-height:2000px;flex:none;pointer-events:none';
    region.appendChild(spacer);region.scrollTop=region.scrollHeight;
    const result=[region.clientWidth===width,region.scrollHeight>region.clientHeight,region.scrollTop>0,
      getComputedStyle(region).scrollbarWidth==='none'];
    spacer.remove();region.scrollTop=scroll;
    return result;
  };
  await wait(150);
  const liveRule=[...document.styleSheets[0].cssRules].find(rule=>rule.selectorText==='body:not(.demo) #app');
  const rootStyle=getComputedStyle(document.documentElement);
  check('design/window-and-surface-radius-r16',rootStyle.getPropertyValue('--radius-ui').trim()==='16px'&&rootStyle.getPropertyValue('--window-r').trim()==='16px',
        [rootStyle.getPropertyValue('--radius-ui'),rootStyle.getPropertyValue('--window-r')]);
  check('window/live-frame-has-no-shadow',liveRule?.style.boxShadow==='none'&&!liveRule?.style.margin,liveRule?.style.boxShadow||'missing');
  check('window/native-config-matches-css',window.NX_CONFIG.radius===16,window.NX_CONFIG.radius);
  const currentCardStyle=getComputedStyle(document.querySelector('.current-card'));
  const rowStyle=getComputedStyle(document.querySelector('.account-list .row'));
  const badgeStyle=getComputedStyle(document.querySelector('.badge'));
  check('design/surface-and-control-radius-hierarchy',currentCardStyle.borderRadius==='16px'&&rowStyle.borderRadius==='12px',
        [currentCardStyle.borderRadius,rowStyle.borderRadius]);
  check('design/pills-remain-functional',badgeStyle.borderRadius==='999px',badgeStyle.borderRadius);
  check('design/type-height-and-shadow-scales',rootStyle.getPropertyValue('--font-body').trim()==='11px'&&rootStyle.getPropertyValue('--height-control').trim()==='36px'&&rootStyle.getPropertyValue('--shadow-hover').trim()!==rootStyle.getPropertyValue('--shadow-floating').trim(),
        [rootStyle.getPropertyValue('--font-body'),rootStyle.getPropertyValue('--height-control')]);
  check('home/compact-size',app.clientWidth===372&&app.clientHeight===520,[app.clientWidth,app.clientHeight]);
  let list=document.querySelector('.account-list');
  check('home/three-accounts-fit',list.querySelectorAll('.row').length===3&&list.scrollHeight-list.clientHeight<=1,
        [list.querySelectorAll('.row').length,list.scrollHeight,list.clientHeight]);
  const homeScroll=stableScrollRegion(list);
  check('home/account-list-scroll-keeps-width',homeScroll.every(Boolean),homeScroll);
  const listBox=box('.account-list'),rowBox=box('.account-list .row');
  check('home/row-shadow-has-real-gutter',rowBox.left-listBox.left>=7&&listBox.right-rowBox.right>=7,
        [rowBox.left-listBox.left,listBox.right-rowBox.right]);
  const sectionLink=box('.section-link');
  check('home/section-hover-aligns-with-account-rows',Math.abs(sectionLink.left-rowBox.left)<1&&Math.abs(sectionLink.right-rowBox.right)<1&&getComputedStyle(document.querySelector('.section-link')).borderRadius===getComputedStyle(list.querySelector('.row')).borderRadius&&sectionLink.height>=38,
        [sectionLink.left,rowBox.left,sectionLink.right,rowBox.right,sectionLink.height]);
  let footer=document.querySelector('.footer.slim');
  check('home/footer-two-whole-actions',!!footer.querySelector('.refresh-status[data-action="refresh"]')&&!!footer.querySelector('[data-action="add"]')&&footer.querySelector('.refresh-status').textContent.trim().length>0);
  check('home/footer-compact',footer.offsetHeight<=40,footer.offsetHeight);
  check('home/add-button-near-panel-bottom',box('#app').bottom-box('.footer.slim .add').bottom<=8,
        box('#app').bottom-box('.footer.slim .add').bottom);
  for(const [name,count] of [['three-accounts',1],['four-accounts',2]]){
    await scenario(name);
    list=document.querySelector('.account-list');footer=document.querySelector('.footer.slim');
    const rows=[...list.querySelectorAll('.row')],head=box('.section-link');
    const positions=rows.map(row=>box(row));
    check(`home/${name}-rows-start-at-top`,rows.length===count&&
          positions.every((row,i)=>row.height>=50&&row.height<=55&&
            (i===0?row.top-head.bottom<=10:Math.abs(row.top-positions[i-1].bottom-4)<=1))&&
          box(footer).top-positions.at(-1).bottom>20,
          positions.map(row=>[row.top,row.height]));
  }
  await scenario('default');
  await scenario('week-exhausted-auto-off');
  check('home/weekly-limit-shows-disabled-auto-relay',document.querySelector('.notice[data-action="settings"]')?.textContent.includes('自动接力未开启'));
  await scenario('default');

  const homeCardBox=box('.current-card'),homeRelayBox=box('.relay');
  const homeAvatarLeft=box('.current-card .avatar').left-homeCardBox.left;
  const homeQuotaTop=box('.current-card .quota-bars').top-homeCardBox.top;
  document.querySelector('.current-identity').click();await wait(70);
  let resetRow=document.querySelector('.reset-summary');
  const detail=document.querySelector('.detail-body');
  const overviewBox=box('.detail-overview'),actionsBox=box('.detail-actions');
  check('full/detail-keeps-home-frame',app.clientWidth===372&&app.clientHeight===520,
        [app.clientWidth,app.clientHeight]);
  check('detail/overview-reuses-home-card-layout',document.querySelector('.detail-overview.current-card')&&
        Math.abs(overviewBox.left-homeCardBox.left)<=1&&Math.abs(overviewBox.right-homeCardBox.right)<=1&&
        Math.abs(overviewBox.top-homeCardBox.top)<=1&&
        Math.abs(overviewBox.height-homeCardBox.height)<=1&&
        Math.abs(box('.detail-overview .avatar').left-overviewBox.left-homeAvatarLeft)<=1&&
        Math.abs(box('.detail-overview .quota-bars').top-overviewBox.top-homeQuotaTop)<=1,
        [overviewBox.left,homeCardBox.left,overviewBox.top,homeCardBox.top,overviewBox.height,homeCardBox.height,
         box('.detail-overview .avatar').left-overviewBox.left,homeAvatarLeft,
         box('.detail-overview .quota-bars').top-overviewBox.top,homeQuotaTop]);
  check('detail/actions-align-with-home-relay',Math.abs(actionsBox.top-homeRelayBox.top)<=1&&
        Math.abs(actionsBox.left-homeRelayBox.left)<=1&&Math.abs(actionsBox.right-homeRelayBox.right)<=1,
        [actionsBox.top,homeRelayBox.top,actionsBox.left,homeRelayBox.left,actionsBox.right,homeRelayBox.right]);
  check('detail/top-four-rows-keep-original-order',box('.detail-profile').top<box('.detail-overview .quota-bars').top&&
        box('.detail-overview .quota-bars').bottom<box('.detail-actions').top&&
        box('.detail-actions').bottom<box('.detail-body .link-row').top&&
        box('.detail-body .link-row').bottom<box('.account-editor summary').top);
  check('detail/quota-actions-have-breathing-room',box('.detail-actions').top-box('.detail-overview .quota-bars').bottom>=11,
        [box('.detail-overview .quota-bars').bottom,box('.detail-actions').top]);
  check('detail/nickname-keeps-standard-row-height',Math.abs(box('.account-editor summary').height-box(resetRow).height)<=1&&
        detail.querySelector('.account-editor summary').textContent.includes('昵称与会员期限')&&box(resetRow).top>box('.account-editor summary').bottom,
        [box('.account-editor summary').height,box(resetRow).height]);
  check('detail/member-date-moves-to-bottom',/^\d{4}\/\d{2}\/\d{2} 到期$/.test(document.querySelector('.detail-expiry-note')?.textContent||'')&&
        box('.detail-expiry-note').top>=box('.danger-row').bottom&&
        box('.detail-footer').bottom-box('.detail-expiry-note').bottom>=12&&
        Math.abs((box('.detail-expiry-note').left+box('.detail-expiry-note').right)/2-(box('.detail-body').left+box('.detail-body').right)/2)<=1,
        [document.querySelector('.detail-expiry-note')?.textContent,box('.detail-expiry-note').top,box('.danger-row').bottom,box('.detail-body').bottom]);
  check('detail/banked-count-separate-from-credits',resetRow?.textContent.includes('2 次')&&!detail.querySelector('.detail-compact [data-action="billing"]'));
  check('detail/collapsed-fits-without-scrolling',detail.scrollHeight-detail.clientHeight<=1,[detail.scrollHeight,detail.clientHeight]);
  const detailWidth=detail.clientWidth,compactWidth=box('.detail-compact').width;
  resetRow.click();await wait(50);
  check('detail/banked-expands-individual-expiries',document.querySelectorAll('.reset-credit').length===2&&
        document.querySelectorAll('.reset-credit strong').length===2&&
        [...document.querySelectorAll('.reset-credit')].every(row=>box(row).height<=42&&row.textContent.includes('2026/'))&&
        document.querySelector('.reset-summary')?.getAttribute('aria-expanded')==='true');
  document.querySelector('.account-editor summary').click();await wait(50);
  check('detail/opening-editor-closes-reset',document.querySelector('.account-editor details').open&&!document.querySelector('.reset-credit-details'));
  document.querySelector('.reset-summary').click();await wait(50);
  check('detail/opening-reset-closes-editor',!document.querySelector('.account-editor details').open&&!!document.querySelector('.reset-credit-details'));
  check('detail/expanded-keeps-quota-clear',box('.detail-overview .quota-bars').bottom+11<=box('.detail-actions').top,
        [box('.detail-overview .quota-bars').bottom,box('.detail-actions').top]);
  const expandedDetail=document.querySelector('.detail-body');
  check('detail/expansion-keeps-panel-width',expandedDetail.clientWidth===detailWidth&&
        Math.abs(box('.detail-compact').width-compactWidth)<=1&&getComputedStyle(expandedDetail).scrollbarWidth==='none',
        [detailWidth,expandedDetail.clientWidth,compactWidth,box('.detail-compact').width]);
  const initialScroll=expandedDetail.scrollTop;
  expandedDetail.scrollTop=expandedDetail.scrollHeight;
  check('detail/expanded-remains-scrollable',expandedDetail.scrollHeight<=expandedDetail.clientHeight+1||expandedDetail.scrollTop>initialScroll,
        [expandedDetail.scrollHeight,expandedDetail.clientHeight,expandedDetail.scrollTop]);
  expandedDetail.scrollTop=initialScroll;
  check('detail/expanded-card-does-not-overlap-archive',box('.detail-body').bottom<=box('.detail-footer').top+.5 && getComputedStyle(expandedDetail).overflowY==='auto',
        [box('.detail-reset').bottom,box('.danger-row').top]);
  await window.nxShown();await wait(70);
  check('detail/banked-expansion-survives-refresh',document.querySelectorAll('.reset-credit').length===2&&
        document.querySelector('.detail-body').scrollWidth<=document.querySelector('.detail-body').clientWidth+1);
  document.querySelector('[data-action="back"]').click();await wait(50);
  document.querySelector('[data-action="quota-overview"]').click();await wait(50);
  document.querySelector('[data-action="detail"][data-email="work-02@example.com"]').click();await wait(50);
  resetRow=document.querySelector('.reset-summary');
  check('detail/known-zero-is-explicit',resetRow?.textContent.includes('0 次'));
  resetRow.click();await wait(40);
  check('detail/zero-has-empty-detail',document.querySelector('.reset-credit-details')?.textContent.includes('暂无可用'));
  document.querySelector('[data-action="back"]').click();await wait(40);
  document.querySelector('[data-action="detail"][data-email="studio@example.com"]').click();await wait(40);
  const richDetail=document.querySelector('.detail-body');
  check('detail/collapsed-fits-with-credits',richDetail.scrollHeight-richDetail.clientHeight<=1&&richDetail.textContent.includes('Credits'),
        [richDetail.scrollHeight,richDetail.clientHeight]);
  document.querySelector('[data-action="back"]').click();await wait(40);
  document.querySelector('[data-action="back"]').click();await wait(40);
  await scenario('detail-dense');
  document.querySelector('.current-identity').click();await wait(40);
  if(document.querySelector('.reset-summary')?.getAttribute('aria-expanded')==='true')document.querySelector('.reset-summary').click();await wait(40);
  const denseDetail=document.querySelector('.detail-body');
  check('detail/collapsed-dense-account-fits',denseDetail.scrollHeight-denseDetail.clientHeight<=1&&
        denseDetail.textContent.includes('Credits')&&denseDetail.querySelectorAll('.quota-bars > div').length===2,
        [denseDetail.scrollHeight,denseDetail.clientHeight]);
  document.querySelector('[data-action="back"]').click();await wait(40);
  await scenario('detail-dense-other');
  document.querySelector('[data-action="quota-overview"]').click();await wait(40);
  document.querySelector('[data-action="detail"][data-email="work-01@example.com"]').click();await wait(40);
  const otherDetail=document.querySelector('.detail-body');
  check('detail/other-account-four-original-rows-and-all-data-fit',otherDetail.scrollHeight-otherDetail.clientHeight<=1&&
        otherDetail.querySelector('.detail-actions:not(.is-current)')?.querySelectorAll('button').length===2&&
        box('.detail-profile').top<box('.quota-bars').top&&box('.quota-bars').top<box('.detail-actions').top&&
        box('.detail-actions').top<box('.link-row').top&&box('.link-row').top<box('.account-editor summary').top&&
        box('.detail-actions').top-box('.quota-bars').bottom>=11&&
        otherDetail.textContent.includes('Credits'),[otherDetail.scrollHeight,otherDetail.clientHeight]);
  document.querySelector('[data-action="back"]').click();await wait(40);
  document.querySelector('[data-action="back"]').click();await wait(40);
  await scenario('default');
  document.querySelector('.current-identity').click();await wait(40);
  document.querySelector('.account-editor summary').click();await wait(40);
  check('edit/expiration-field-directly-visible',!!document.querySelector('#manual-date')&&document.querySelector('#manual-date').offsetParent!==null);
  document.querySelector('#manual-date').value='2030-10-13';
  document.querySelector('[data-action="save-expiry"]').click();await wait(70);
  document.querySelector('.account-editor summary').click();await wait(20);
  check('detail/nickname-edit-controls-bottom-date',document.querySelector('.detail-expiry-note')?.textContent==='2030/10/13 到期'&&
        Math.abs(box('.account-editor summary').height-box('.reset-summary').height)<=1,
        document.querySelector('.detail-expiry-note')?.textContent);
  document.querySelector('[data-action="back"]').click();await wait(40);
  await scenario('default');
  document.querySelector('.row[data-email="remote@example.com"]').click();await wait(40);
  const failedDetail=document.querySelector('.detail-body');
  check('detail/quota-failure-keeps-layout',!!failedDetail.querySelector('.quota-failure')&&
        box('.detail-actions').top-box('.quota-failure').bottom>=11&&
        failedDetail.scrollWidth<=failedDetail.clientWidth+1,
        [box('.quota-failure').bottom,box('.detail-actions').top,failedDetail.scrollWidth,failedDetail.clientWidth]);
  document.querySelector('[data-action="back"]').click();await wait(40);
  await scenario('banked-partial');
  document.querySelector('.current-identity').click();await wait(40);
  if(document.querySelector('.reset-summary')?.getAttribute('aria-expanded')!=='true')document.querySelector('.reset-summary').click();await wait(40);
  check('detail/partial-list-keeps-authoritative-count',document.querySelector('.reset-summary')?.textContent.includes('2 次')&&
        document.querySelectorAll('.reset-credit').length===1&&document.querySelector('.reset-credit-details')?.textContent.includes('另有 1 次'));
  document.querySelector('[data-action="back"]').click();await wait(40);
  await scenario('banked-unknown');
  document.querySelector('.current-identity').click();await wait(40);
  if(document.querySelector('.reset-summary')?.getAttribute('aria-expanded')!=='true')document.querySelector('.reset-summary').click();await wait(40);
  check('detail/unknown-is-not-zero',document.querySelector('.reset-summary')?.textContent.includes('暂不可用')&&
        !document.querySelector('.reset-credit-details')?.textContent.includes('0 次')&&document.querySelectorAll('.reset-credit').length===0);
  document.querySelector('[data-action="back"]').click();await wait(40);
  await scenario('default');

  document.querySelector('[data-action="usage-all"]').click();await wait(120);
  check('full/usage-keeps-home-frame',app.clientWidth===372&&app.clientHeight===520,
        [app.clientWidth,app.clientHeight]);
  const usageTotal=()=>document.querySelector('.usage-total')?.getAttribute('aria-label');
  const usageRows=()=>[...document.querySelectorAll('.account-usage-row .usage-number')].map(n=>n.textContent);
  const firstRangeTotal=usageTotal(),firstRangeRows=usageRows();
  check('usage/filter-above-cumulative-total',document.querySelectorAll('.usage-filter [data-action="usage-period"]').length===4&&box('.usage-filter').bottom<box('.usage-total').top&&document.querySelector('.usage-hero .eyebrow')?.textContent==='累计 Tokens',
        [document.querySelectorAll('.usage-filter button').length,box('.usage-filter').bottom,box('.usage-total').top]);
  document.querySelector('[data-action="usage-period"][data-value="7"]').click();await wait(70);
  check('usage/seven-days-updates-total-rows-and-chart',usageTotal()!==firstRangeTotal&&JSON.stringify(usageRows())!==JSON.stringify(firstRangeRows)&&document.querySelectorAll('.usage-trend .trend-bar').length===7,
        [firstRangeTotal,usageTotal(),document.querySelectorAll('.usage-trend .trend-bar').length]);
  check('usage/today-is-visible-with-coverage',document.querySelector('.usage-chart-heading span')?.textContent.includes('今日')&&!!document.querySelector('.trend-bar.today'),document.querySelector('.usage-chart-heading span')?.textContent);
  document.querySelector('[data-action="usage-period"][data-value="180"]').click();await wait(70);
  check('usage/180-days-groups-to-sixty-bars',document.querySelectorAll('.usage-trend .trend-bar').length===60&&document.querySelector('.usage-chart-heading').textContent.includes('每 3 天一组'),
        [document.querySelectorAll('.usage-trend .trend-bar').length,document.querySelector('.usage-chart-heading').textContent]);
  document.querySelector('[data-action="usage-period"][data-value="all"]').click();await wait(70);
  const allBars=[...document.querySelectorAll('.usage-trend .trend-bar')];
  check('usage/all-keeps-lifetime-total-and-uses-monthly-bars',usageTotal()!==firstRangeTotal&&allBars.length>=1&&document.querySelector('.usage-chart-heading')?.textContent.includes('月度用量按月')&&!document.querySelector('.usage-partial'),
        [usageTotal(),firstRangeTotal,allBars.length,document.querySelector('.usage-chart-heading')?.textContent]);
  check('usage/monthly-tooltip-uses-compact-token-unit',allBars.some(bar=>/\d+(?:\.\d{2})?[万亿] Tokens/.test(bar.getAttribute('aria-label')||''))&&!allBars.some(bar=>(bar.getAttribute('aria-label')||'').includes('— Tokens')),
        allBars.map(bar=>bar.getAttribute('aria-label')));
  const statsAccountEmail=document.querySelector('.account-usage-row').dataset.email;
  document.querySelector('.account-usage-row').click();await wait(70);
  document.querySelector('[data-action="usage-period"][data-value="30"]').click();await wait(70);
  const statsAccount=NXDemo.state().accounts.find(a=>a.email===statsAccountEmail);
  const statsUsage=await NXDemo.call('read_usage',statsAccountEmail);
  const selectedUsage=NXMath.aggregate([statsAccount],{[statsAccountEmail]:statsUsage},30);
  const selectedPeak=selectedUsage.daily.reduce((max,d)=>BigInt(d.tokens)>max?BigInt(d.tokens):max,0n);
  const selectedMean=selectedUsage.daily.reduce((sum,d)=>sum+BigInt(d.tokens),0n)/BigInt(selectedUsage.daily.length);
  const metricText=document.querySelector('.metrics-row')?.textContent||'';
  check('usage/account-window-stats-follow-selection',metricText.includes('单日峰值'+NXMath.compactText(selectedPeak))&&metricText.includes('日均用量'+NXMath.compactText(selectedMean)),metricText);
  document.querySelector('[data-action="back"]').click();await wait(50);

  await scenario('archived');
  document.querySelector('[data-action="usage-all"]').click();await wait(100);
  const archivedRow=document.querySelector('.account-usage-row[data-email="archived@example.com"]');
  check('usage/archived-history-keeps-plan-and-subtle-style',!!archivedRow&&archivedRow.classList.contains('archived')&&
        archivedRow.querySelector('strong')?.textContent.includes('已归档')&&archivedRow.querySelector('small')?.textContent.trim()==='Plus'&&
        archivedRow.querySelector('.usage-number')?.textContent.includes('万'));
  archivedRow?.click();await wait(70);
  check('usage/archived-detail-is-read-only',document.querySelector('.usage-top .badge')?.textContent==='Plus'&&
        document.querySelector('.usage-top .identity-title strong')?.textContent.includes('已归档')&&
        !document.querySelector('[data-action="usage-refresh"]')&&document.querySelector('.usage-total')?.textContent.includes('万'));
  document.querySelector('[data-action="back"]').click();await wait(40);

  await scenario('error-home');
  list=document.querySelector('.account-list');footer=document.querySelector('.footer.slim');
  const lb=box('.account-list'),fb=box('.footer.slim'),background=getComputedStyle(footer).backgroundColor;
  check('home/notice-list-stops-before-footer',lb.bottom<=fb.top+.5,[lb.bottom,fb.top]);
  check('home/footer-is-opaque',background!=='rgba(0, 0, 0, 0)',background);
  check('home/notice-fourth-account-scrolls',list.scrollHeight>list.clientHeight,[list.scrollHeight,list.clientHeight]);

  document.querySelector('[data-action="quota-overview"]').click();await wait(80);
  check('quota-overview/all-accounts-and-resets',document.querySelectorAll('.quota-overview-row').length===window.NXDemo.state().accounts.length&&document.querySelectorAll('.quota-overview-window [data-reset]').length>=2,
        [document.querySelectorAll('.quota-overview-row').length,window.NXDemo.state().accounts.length]);
  const quotaRow=box('.quota-overview-row'),quotaWindow=document.querySelector('.quota-overview-window');
  check('quota-overview/reset-follows-percentage-on-one-line',quotaRow.height<=64&&Math.abs(box(quotaWindow.querySelector('strong')).top-box(quotaWindow.querySelector('small')).top)<=4&&box(quotaWindow.querySelector('small')).left>box(quotaWindow.querySelector('strong')).right,
        [quotaRow.height,box(quotaWindow.querySelector('strong')).top,box(quotaWindow.querySelector('small')).top]);
  check('quota-overview/two-compact-sort-controls',document.querySelectorAll('.quota-metric button').length===2&&document.querySelectorAll('.quota-scope button').length===3,
        [document.querySelectorAll('.quota-metric button').length,document.querySelectorAll('.quota-scope button').length]);
  check('quota-overview/sort-labels',document.querySelector('.quota-metric').textContent.includes('额度')&&document.querySelector('.quota-metric').textContent.includes('时间')&&document.querySelector('.quota-scope').textContent.includes('接力'),
        document.querySelector('.quota-overview-toolbar').textContent);
  document.querySelector('[data-action="quota-metric"][data-value="time"]').click();await wait(40);
  const timeRows=[...document.querySelectorAll('.quota-overview-row')],timeValues=timeRows.map(row=>Number(row.querySelector('[data-duration="300"]')?.dataset.reset||Number.MAX_SAFE_INTEGER));
  check('quota-overview/5h-time-is-soonest-first',timeValues.every((v,i)=>i===0||timeValues[i-1]<=v),timeValues);
  check('quota-overview/sticky-toolbar-is-opaque',getComputedStyle(document.querySelector('.quota-overview-toolbar')).backgroundColor!=='rgba(0, 0, 0, 0)',getComputedStyle(document.querySelector('.quota-overview-toolbar')).backgroundColor);
  check('quota-overview/toolbar-moved-up-and-no-caption',box('.quota-overview-toolbar').top-box('.sheet-head').bottom<=8&&!document.querySelector('.quota-overview-toolbar p'),
        [box('.quota-overview-toolbar').top-box('.sheet-head').bottom,!!document.querySelector('.quota-overview-toolbar p')]);
  document.querySelector('[data-action="back"]').click();await wait(50);

  await scenario('relay-continuity');
  check('relay/one-percent-is-not-next',document.querySelector('[data-action="relay"]').textContent.includes('充足账号'),document.querySelector('[data-action="relay"]').textContent);
  document.querySelector('[data-action="quota-overview"]').click();await wait(80);
  document.querySelector('[data-action="quota-metric"][data-value="quota"]').click();await wait(40);
  document.querySelector('[data-action="quota-scope"][data-value="relay"]').click();await wait(40);
  const continuityOrder=[...document.querySelectorAll('.quota-overview-row .identity-title strong')].map(node=>node.textContent.trim());
  check('quota-overview/relay-max-uptime-order',continuityOrder.join('|')==='充足账号|稳定 49|稳定 37|当前 Pro|应急账号|不可用账号',continuityOrder);
  document.querySelector('[data-action="back"]').click();await wait(50);

  await scenario('many');
  document.querySelector('[data-action="quota-overview"]').click();await wait(80);
  const manyRows=[...document.querySelectorAll('.quota-overview-row')];
  const quotaScroll=stableScrollRegion(document.querySelector('.quota-overview-body'));
  check('quota-overview/scroll-keeps-width',quotaScroll.every(Boolean),quotaScroll);
  check('quota-overview/many-accounts-fit-without-horizontal-overflow',manyRows.length>8&&manyRows.every(row=>row.scrollWidth<=row.clientWidth+1&&box(row).height<=64),
        [manyRows.length,...manyRows.map(row=>[row.scrollWidth,row.clientWidth,box(row).height])]);
  document.querySelector('[data-action="back"]').click();await wait(50);

  await scenario('default');window.nxShown();await wait(80);
  document.querySelector('[data-action="settings"]').click();await wait(80);
  check('full/settings-keeps-home-frame',app.clientWidth===372&&app.clientHeight===520,
        [app.clientWidth,app.clientHeight]);
  const settingsScroll=stableScrollRegion(document.querySelector('.settings-body'));
  check('settings/scroll-keeps-width',settingsScroll.every(Boolean),settingsScroll);
  const settingsText=document.querySelector('.settings-body').textContent;
  check('settings/index-orders-system-relay-accounts',settingsText.indexOf('系统')<settingsText.indexOf('接力与接续')&&settingsText.indexOf('接力与接续')<settingsText.indexOf('账号快捷键'),settingsText);
  check('settings/single-panel-no-mode-entry',!document.querySelector('[data-key="panel_mode"]'));
  check('settings/index-not-overloaded',!!document.querySelector('[data-key="auto_relay"]')&&!document.querySelector('[data-action="automation"]')&&!!document.querySelector('[data-disclosure="notifications"]'));
  check('settings/system-order',settingsText.indexOf('开机自启')<settingsText.indexOf('外观'),settingsText);
  check('settings/grouped-without-row-descriptions',document.querySelectorAll('.settings-section').length===3&&document.querySelectorAll('.settings-list > .toggle-line small,.settings-list > .setting-choice small').length===0);
  check('settings/index-keeps-width',document.querySelector('.settings-body').scrollWidth===document.querySelector('.settings-body').clientWidth);
  check('settings/compact-row-and-switch-heights',[...document.querySelectorAll('.settings-list > *')].every(row=>box(row).height<=44)&&[...document.querySelectorAll('.settings-list .switch')].every(control=>box(control).height===24));
  check('settings/detail-style-independent-rows',document.querySelectorAll('.settings-list').length===3&&[...document.querySelectorAll('.settings-list > *')].every(row=>getComputedStyle(row).borderRadius==='12px'&&getComputedStyle(row).backgroundColor!=='rgba(0, 0, 0, 0)'));
  check('settings/auto-relay',!!document.querySelector('[data-key="auto_relay"]'));
  check('settings/continuation-switch-and-message',!!document.querySelector('[data-key="task_continuation"]')&&!!document.querySelector('[data-action="resume-details"]')&&!!document.querySelector('[data-disclosure="message"]'));
  check('settings/auto-relay-account-entry',!!document.querySelector('[data-disclosure="relay"]'));
  check('settings/automation-keeps-width',document.querySelector('.settings-body').scrollWidth===document.querySelector('.settings-body').clientWidth);
  const settingsCard=box('.settings-list');
  document.querySelector('[data-disclosure="relay"] > summary').click();await wait(70);
  const firstAuto=window.NXDemo.state().relay_email;
  const relayAccountCount=window.NXDemo.state().accounts.length;
  check('settings/relay-account-list',document.querySelectorAll('.relay-account-row .switch').length===relayAccountCount&&
        document.querySelector('[data-disclosure="relay"] .disclosure-meta')?.textContent===`${relayAccountCount}/${relayAccountCount}`);
  check('settings/relay-account-style-aligns',box('.relay-account-list').left>=settingsCard.left&&
        box('.relay-account-list').right<=settingsCard.right&&
        document.querySelector('[data-disclosure="relay"]').open&&
        [...document.querySelectorAll('.relay-account-row .switch')].every(control=>box(control).height===24));
  document.querySelector('[data-action="auto-relay-account"][data-email="work-01@example.com"]').click();await wait(70);
  check('settings/excluding-current-stops-auto-only',window.NXDemo.state().auto_relay_email===null&&
        window.NXDemo.state().relay_email===firstAuto&&document.querySelector('[data-disclosure="relay"] .disclosure-meta')?.textContent===`${relayAccountCount-1}/${relayAccountCount}`);
  document.querySelector('[data-action="auto-relay-account"][data-email="work-01@example.com"]').click();await wait(70);
  document.querySelector(`[data-action="auto-relay-account"][data-email="${firstAuto}"]`).click();await wait(70);
  check('settings/excluding-target-preserves-manual-suggestion',window.NXDemo.state().auto_relay_email!==firstAuto&&
        window.NXDemo.state().relay_email===firstAuto&&window.NXDemo.state().settings.auto_relay_excluded.includes(firstAuto));
  document.querySelector('[data-disclosure="relay"] > summary').click();await wait(70);
  document.querySelector('[data-disclosure="hotkeys"] > summary').click();await wait(70);
  check('settings/hotkeys-use-grouped-list',document.querySelectorAll('.hotkey-row').length===relayAccountCount&&
        document.querySelector('[data-disclosure="hotkeys"]').open);
  document.querySelector('[data-disclosure="message"] > summary').click();await wait(70);
  check('settings/message-has-labelled-limit-not-long-note',document.querySelector('#resume-message')?.value==='继续'&&!!document.querySelector('label[for="resume-message"]')&&document.querySelector('[data-disclosure="message"]').open&&!document.querySelector('.sheet-body .note'));
  document.querySelector('#resume-message').value='请接着完成上个任务';
  document.querySelector('[data-action="save-resume-message"]').click();await wait(90);
  check('settings/custom-message-persists',window.NXDemo.state().settings.resume_message==='请接着完成上个任务'&&!!document.querySelector('.settings-body'));
  document.querySelector('[data-action="back"]').click();await wait(80);

  await scenario('resume-progress');
  const progress=document.querySelector('.resume-notice');
  check('resume/progress-banner-links-to-details',progress?.textContent.includes('任务接续中 1/3')&&progress.dataset.action==='resume-details');
  progress.click();await wait(100);
  check('full/resume-keeps-home-frame',app.clientWidth===372&&app.clientHeight===520,
        [app.clientWidth,app.clientHeight]);
  check('resume/reopens-collapsed',document.querySelectorAll('.resume-task').length===0);
  document.querySelector('.resume-summary').click();await wait(50);
  check('resume/details-show-original-tasks',document.querySelectorAll('.resume-task').length===3&&document.querySelector('.resume-body')?.textContent.includes('研究任务 B'));
  check('resume/title-has-regular-emphasis',getComputedStyle(document.querySelector('.resume-task-copy strong')).fontWeight==='500');
  check('resume/each-task-stays-compact', [...document.querySelectorAll('.resume-task')].every(row=>box(row).height<=42)&&
        [...document.querySelectorAll('.resume-summary')].every(row=>box(row).height<=42));
  check('resume/success-needs-no-visible-status',!document.querySelector('.resume-task')?.querySelector('.resume-progress')&&
        !document.querySelector('.resume-task')?.querySelector('.resume-task-copy small')&&document.querySelector('.resume-task')?.getAttribute('aria-label')?.includes('成功'));
  check('resume/in-progress-zero-is-not-failure-red',!document.querySelector('.resume-task .resume-zero'));
  const resumeScroll=stableScrollRegion(document.querySelector('.resume-body'));
  check('resume/scroll-keeps-width',resumeScroll.every(Boolean),resumeScroll);
  document.querySelector('[data-action="back"]').click();await wait(80);
  await scenario('resume-waiting');
  const waitingNotice=document.querySelector('.resume-notice');
  check('resume/waiting-account-banner',waitingNotice?.textContent.includes('等待可用接力账号 0/2'));
  waitingNotice.click();await wait(100);
  check('resume/waiting-reopens-collapsed',document.querySelectorAll('.resume-task').length===0);
  document.querySelector('.resume-summary').click();await wait(50);
  check('resume/waiting-task-rows-and-dismissible-expansion',document.querySelectorAll('.resume-task').length===2&&
        [...document.querySelectorAll('.resume-task .resume-progress')].every(n=>n.textContent==='等待中'));
  check('resume/waiting-shows-nearest-reset-time',document.querySelector('.resume-summary')?.textContent.includes('预计'));
  document.querySelector('.resume-summary').click();await wait(50);
  check('resume/waiting-group-collapses',document.querySelectorAll('.resume-task').length===0);
  document.querySelector('[data-action="back"]').click();await wait(60);
  check('resume/viewing-waiting-does-not-clear-banner',!!document.querySelector('.resume-notice'));
  await scenario('resume-failed');
  const failure=document.querySelector('.resume-notice');
  check('resume/failure-banner-is-visible',failure?.textContent.includes('任务接续失败 1/3'));
  failure.click();await wait(100);
  document.querySelector('.resume-summary').click();await wait(50);
  check('resume/viewing-clears-banner-and-keeps-history',!window.NXDemo.state().resume&&document.querySelectorAll('.resume-task').length===3);
  check('resume/failure-shows-only-muted-red-reason',[...document.querySelectorAll('.resume-task')].some(row=>{
    const reason=row.querySelector('.resume-failure-reason');
    return reason?.textContent.includes('无法确认原任务页面')&&!row.querySelector('.resume-progress')&&
      getComputedStyle(reason).color!==getComputedStyle(row.querySelector('strong')).color;
  }));
  document.querySelector('[data-action="back"]').click();await wait(80);
  await scenario('resume-history');
  document.querySelector('[data-action="settings"]').click();await wait(60);
  document.querySelector('[data-action="resume-details"]').click();await wait(80);
  check('resume/history-groups-and-collapses',document.querySelector('.resume-body')?.textContent.includes('今天')&&document.querySelector('.resume-body')?.textContent.includes('近 7 天')&&document.querySelectorAll('.resume-summary').length===3&&document.querySelectorAll('.resume-task').length===0);
  document.querySelector('[data-action="resume-toggle"][data-value="history-old"]').click();await wait(40);
  check('resume/history-expands-with-readable-reason',document.querySelectorAll('.resume-task').length===1&&!document.querySelector('.resume-body')?.textContent.includes('switch_not_completed'));
  document.querySelector('[data-action="resume-toggle"][data-value="history-old"]').click();await wait(40);
  check('resume/history-recollapses',document.querySelectorAll('.resume-task').length===0);
  document.querySelector('[data-action="resume-toggle"][data-value="history-draft"]').click();await wait(40);
  check('resume/bridge-preflight-failure-and-explicit-retry',document.querySelector('.resume-body')?.textContent.includes('桌面桥接不可用')&&!!document.querySelector('[data-action="retry-resume-task"]'));
  document.querySelector('[data-action="retry-resume-task"]').click();await wait(70);
  check('resume/preflight-retry-keeps-original-session',window.NXDemo.state().resume?.phase==='resuming'&&!document.querySelector('[data-action="retry-resume-task"]'));
  await scenario('default');

  window.NXDemo.scenario('relay-week-priority');await window.nxShown();await wait(80);
  document.querySelector('[data-action="relay"]').click();await wait(80);
  check('relay/no-rule-ui',!document.querySelector('.relay-rule-mark')&&!document.querySelector('#sheet').textContent.includes('先看周剩余'),document.querySelector('#sheet').textContent);

  await scenario('adding-home');
  document.querySelector('[data-action="add"]').click();await wait(120);
  const hint=document.querySelector('.status-bar.flow-status')?.textContent||'';
  check('add/repeat-hint-inside-compact-box',hint.trim().length>0&&document.querySelector('.status-bar.flow-status').offsetHeight===38,
        [hint,document.querySelector('.status-bar.flow-status')?.offsetHeight]);
  check('add/no-snapshot-preservation-copy',!document.querySelector('#sheet').textContent.includes('现有账号与快照会保留'));

  // Shared controls retain their persisted choices across navigation.
  await scenario('default');
  document.querySelector('[data-action="settings"]').click();await wait(60);
  const selected=key=>document.querySelector(`[data-key="${key}"][aria-pressed="true"]`)?.dataset.value;
  const groupsValid=()=>[...document.querySelectorAll('.segmented')].filter(n=>n.offsetParent!==null).every(group=>group.getAttribute('role')==='group'&&group.getAttribute('aria-label')&&group.querySelectorAll('[aria-pressed="true"]').length===1);
  check('settings/full-groups-have-one-accessible-selection',groupsValid());
  check('settings/opens-all-collapsed',[...document.querySelectorAll('.settings-body details')].every(d=>!d.open));
  document.querySelector('[data-disclosure="appearance"] > summary').click();await wait(30);
  document.querySelector('[data-disclosure="notifications"] > summary').click();await wait(70);
  check('settings/opening-notifications-closes-appearance',!document.querySelector('[data-disclosure="appearance"]').open&&document.querySelector('[data-disclosure="notifications"]').open);
  document.querySelector('[data-key="notify_low"]').click();await wait(70);
  check('settings/fixed-low-threshold-and-reset-expiry-toggle',!document.querySelector('[data-key="notify_low_threshold"]')&&!!document.querySelector('[data-key="notify_reset_expiry"]')&&window.NXDemo.state().settings.notify_reset_expiry===true);
  document.querySelector('[data-disclosure="notifications"] > summary').click();await wait(70);
  if(!document.querySelector('[data-disclosure="appearance"]').open)document.querySelector('[data-disclosure="appearance"] > summary').click();
  document.querySelector('[data-key="appearance"][data-value="light"]').click();await wait(70);
  check('appearance/explicit-light-palette',document.documentElement.dataset.appearance==='light'&&getComputedStyle(app).backgroundColor==='rgb(255, 255, 255)'&&selected('appearance')==='light');
  document.querySelector('[data-key="appearance"][data-value="dark"]').click();await wait(70);
  check('appearance/explicit-dark-palette',document.documentElement.dataset.appearance==='dark'&&getComputedStyle(app).backgroundColor==='rgb(29, 29, 29)'&&selected('appearance')==='dark');
  document.querySelector('[data-key="appearance"][data-value="system"]').click();await wait(70);
  check('appearance/system-palette',document.documentElement.dataset.appearance===(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light')&&selected('appearance')==='system');
  document.querySelector('[data-key="auto_relay"]').click();await wait(70);
  document.querySelector('[data-action="back"]').click();await wait(40);
  document.querySelector('[data-action="settings"]').click();await wait(60);
  check('settings/navigation-retains-values',window.NXDemo.state().settings.auto_relay===true&&window.NXDemo.state().settings.appearance==='system');
  check('settings/reopens-all-collapsed',[...document.querySelectorAll('.settings-body details')].every(d=>!d.open));
  await scenario('default');window.nxShown();await wait(80);
  document.querySelector('[data-action="relay"]').click();await wait(60);
  const execute=document.querySelector('[data-action="execute-switch"]'),target=execute.dataset.email;
  execute.click();await wait(1800);
  check('switch/confirmation-completes',window.NXDemo.state().current===target&&document.querySelector('#sheet').hidden);

  const openNextDetail=()=>window.NXPreview.open(new URLSearchParams('open=detail&email=work-02@example.com'));
  await scenario('default');await openNextDetail();await wait(80);
  let pick=document.querySelector('.detail-actions .primary'),switchButton=document.querySelector('.detail-actions .secondary');
  check('detail/primary-sets-next-secondary-switches',pick.dataset.action==='pick'&&pick.textContent==='设为下一棒'&&switchButton.dataset.action==='switch'&&switchButton.textContent.includes('切换到此账号')&&box(pick).width>box(switchButton).width);
  check('detail/next-and-switch-icons-match-their-actions',pick.querySelector('path').getAttribute('d')===document.querySelector('.relay-label path').getAttribute('d')&&switchButton.querySelector('path').getAttribute('d')===document.querySelector('.relay-arrow path').getAttribute('d'));
  pick.click();await wait(150);
  check('detail/normal-next-can-be-cancelled',window.NXDemo.state().settings.relay_pick==='work-02@example.com'&&document.querySelector('.detail-actions .primary').textContent.startsWith('取消下一棒'));
  document.querySelector('.detail-actions .primary').click();await wait(150);
  check('detail/cancel-next-clears-selection',window.NXDemo.state().settings.relay_pick===null&&document.querySelector('.detail-actions .primary').textContent.startsWith('设为下一棒'));
  await scenario('relay-exhausted');await openNextDetail();await wait(80);
  pick=document.querySelector('.detail-actions .primary');
  check('detail/zero-quota-offers-recovery-relay',pick.textContent.startsWith('恢复后接力')&&window.NXDemo.state().current==='work-01@example.com');
  const before=box(pick);pick.click();await wait(150);
  pick=document.querySelector('.detail-actions .primary');
  check('detail/recovery-relay-is-cancellable-with-same-geometry',pick.textContent.startsWith('取消等待')&&pick.getAttribute('aria-pressed')==='true'&&window.NXDemo.state().relay_wait?.email==='work-02@example.com'&&Math.abs(box(pick).width-before.width)<1&&Math.abs(box(pick).height-before.height)<1);
  pick.click();await wait(150);window.NXDemo.simulate('restore-quota');await window.NXPreview.refresh();await wait(1600);
  check('detail/cancelled-recovery-does-not-switch',window.NXDemo.state().current==='work-01@example.com'&&!window.NXDemo.state().relay_wait&&!window.NXDemo.state().operation);
  await scenario('relay-waiting');window.NXDemo.simulate('restore-quota');await window.NXPreview.refresh();await wait(1600);await window.NXPreview.refresh();
  check('detail/verified-recovery-runs-once',window.NXDemo.state().current==='work-02@example.com'&&!window.NXDemo.state().relay_wait&&!window.NXDemo.state().operation);

  const math=window.NXMath,stamp=new Date(2026,8,22,12).getTime()/1000;
  const accounts=[{email:'a@example.com',identity_key:'a',activity_key:'one'},{email:'b@example.com',identity_key:'b',activity_key:'one'},{email:'c@example.com',identity_key:'c'}];
  const usage=(key,total,buckets=[])=>({ok:true,source:'account/usage/read',identity_key:key,summary:{lifetimeTokens:total},dailyUsageBuckets:buckets});
  const cache={'a@example.com':usage('a','9007199254740993123',[{startDate:'2026-09-22',tokens:'0'}]),'b@example.com':usage('b','99')};
  const total=math.aggregate(accounts,cache,7,stamp);
  check('math/exact-integer-and-identity-deduplication',total.total_tokens==='9007199254740993123'&&total.unique_accounts===2&&total.rows[1].status==='duplicate');
  check('math/missing-is-distinct-from-zero',!total.total_complete&&total.rows[2].tokens===null&&total.daily.length===1&&total.daily[0].tokens==='0'&&!total.daily[0].complete);
  check('math/invalid-token-values-stay-unknown',[null,-1,1.5,true,'1e6','-1',Number.MAX_SAFE_INTEGER+1].every(value=>math.count(value)===null));
  const dailyGroups=math.trendGroups(total).groups;
  check('math/trend-preserves-missing-and-known-zero',dailyGroups.length===7&&dailyGroups.at(-1).recorded===1&&dailyGroups.at(-1).tokens===0n&&dailyGroups[0].recorded===0);
  const monthly=math.trendGroups({period:{start:'2026-01-31',end:'2026-03-01',span_days:30},daily:[{date:'2026-01-31',tokens:'3',complete:true},{date:'2026-03-01',tokens:'4',complete:false}]},true).groups;
  check('math/months-retain-calendar-length-and-coverage',monthly.map(g=>g.length).join(',')==='1,28,1'&&monthly[0].tokens===3n&&monthly[1].recorded===0&&monthly[2].complete===0);

  const pre=document.createElement('pre');pre.id='nx-check-results';
  pre.textContent=btoa(unescape(encodeURIComponent(JSON.stringify(out))));document.body.appendChild(pre);
})();
</script>'''


def main(browser: Path, output: Path) -> int:
    import sys
    sys.path.insert(0, str(ROOT / 'tools'))
    from browser_session import browser_session, demo_html
    source = demo_html()
    with browser_session(browser) as engine:
        page = engine.new_page(viewport={'width': 900, 'height': 800})
        page.set_content(source.replace('</body>', HARNESS + '</body>'))
        page.wait_for_selector('#' + RESULT_ID, state='attached', timeout=60000)
        encoded = page.locator('#' + RESULT_ID).inner_text()
    checks = json.loads(base64.b64decode(encoded).decode('utf-8'))
    failed = [item for item in checks if not item['passed']]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"{browser.stem} UI checks: {len(checks)-len(failed)}/{len(checks)}")
    for item in failed:
        print(f"FAIL {item['name']}: {item['details']}")
    return int(bool(failed))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / '_wip' / 'build' / 'browser-results.json')
    args = parser.parse_args()
    raise SystemExit(main(args.browser.resolve(), args.output.resolve()))
