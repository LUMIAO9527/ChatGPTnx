/* Local async/DOM coordination. No API calls and no product decisions. */
'use strict';
window.NXRuntime = (() => {
  function readEpoch() {
    let revision = 0;
    return {ticket: () => revision, invalidate: () => ++revision,
            current: ticket => ticket === revision};
  }
  function coalescedRefresh(read) {
    let flight = null, trailing = false;
    return (requireFresh = false) => {
      if (flight) { trailing ||= requireFresh === true; return flight; }
      flight = Promise.resolve().then(async () => {
        do { trailing = false; await read(); } while (trailing);
      }).finally(() => { flight = null; });
      return flight;
    };
  }
  const focusKey = node => node?.dataset?.action ? {...node.dataset} : node?.matches?.('summary')&&node.parentElement?.dataset?.disclosure ? {disclosure:node.parentElement.dataset.disclosure} : null;
  function restoreFocus(root, key) {
    if (!key) return;
    if(key.disclosure){[...root.querySelectorAll('[data-disclosure]')].find(n=>n.dataset.disclosure===key.disclosure)?.querySelector('summary')?.focus({preventScroll:true});return;}
    [...root.querySelectorAll('[data-action]')].find(node =>
      Object.entries(key).every(([k, v]) => node.dataset[k] === v)
    )?.focus({preventScroll: true});
  }
  const scrollRegions = ['.sheet-body', '.account-list', '.onboarding-main'];
  const captureScroll = root => scrollRegions.map(selector =>
    [selector, root.querySelector(selector)?.scrollTop || 0]);
  function restoreScroll(root, positions) {
    for (const [selector, top] of positions || []) {
      const node = root.querySelector(selector);
      if (node) node.scrollTop = top;
    }
  }
  return {readEpoch, coalescedRefresh, focusKey, restoreFocus, captureScroll, restoreScroll};
})();
