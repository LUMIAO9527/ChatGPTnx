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
  const nodeKey = node => {
    if (node.nodeType !== 1) return '';
    const data = node.dataset || {};
    return node.id ? 'id:' + node.id : data.motionIdentity ? 'identity:' + data.motionIdentity :
      data.email ? 'account:' + data.email + ':' + (data.action || '') :
      data.disclosure ? 'disclosure:' + data.disclosure :
      data.action ? 'action:' + data.action + ':' + (data.key || data.value || '') : '';
  };
  const compatible = (a, b) => a.nodeType === b.nodeType && a.nodeName === b.nodeName &&
    a.namespaceURI === b.namespaceURI && nodeKey(a) === nodeKey(b);
  function patchChildren(root, incoming) {
    const previous = [...root.childNodes], unused = new Set(previous);
    let cursor = root.firstChild;
    for (const next of [...incoming.childNodes]) {
      const node = cursor && unused.has(cursor) && compatible(cursor, next) ? cursor :
        previous.find(old => unused.has(old) && compatible(old, next));
      if (!node) {
        root.insertBefore(next, cursor); continue;
      }
      unused.delete(node);
      if (node !== cursor) root.insertBefore(node, cursor);
      if (node.nodeType === 1) {
        // Editing fields already survive refreshes in app.js. Preserve their
        // composition, caret and validation state, as well as the actual node.
        if (!node.matches('.field')) {
          for (const attr of [...node.attributes]) {
            if (attr.name === 'style' && node.__nxMotionOwned) continue;
            if (!next.hasAttribute(attr.name)) node.removeAttribute(attr.name);
          }
          for (const attr of [...next.attributes]) {
            if (attr.name === 'style' && node.__nxMotionOwned) continue;
            if (node.getAttribute(attr.name) !== attr.value) node.setAttribute(attr.name, attr.value);
          }
          patchChildren(node, next);
        }
      } else if (node.nodeValue !== next.nodeValue) node.nodeValue = next.nodeValue;
      cursor = node.nextSibling;
    }
    for (const node of unused) node.remove();
  }
  function patchHTML(root, html) {
    const template = root.ownerDocument.createElement('template');
    template.innerHTML = html;
    patchChildren(root, template.content);
  }
  return {readEpoch, coalescedRefresh, focusKey, restoreFocus, captureScroll, restoreScroll, patchHTML};
})();
