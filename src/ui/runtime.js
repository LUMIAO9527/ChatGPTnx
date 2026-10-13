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
  const scrollRegions = ['.sheet-body', '.account-list', '.onboarding-main', '.update-notes-body'];
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
  function patchChildren(root, incoming, preserveFields) {
    // A moving live avatar keeps an inert layout slot beside it. This is not
    // product markup: preserve it during refresh, and reconcile the real node.
    const previous = [...root.childNodes].filter(node => !node.__nxMotionPlaceholder&&!node.__nxMotionRetained), unused = new Set(previous);
    const nextContent = node => { while (node?.__nxMotionPlaceholder||node?.__nxMotionRetained) node = node.nextSibling; return node; };
    const reusable = (old, next) => compatible(old, next) &&
      (preserveFields || !old.matches?.('.field'));
    let cursor = nextContent(root.firstChild);
    for (const next of [...incoming.childNodes]) {
      const node = cursor && unused.has(cursor) && reusable(cursor, next) ? cursor :
        previous.find(old => unused.has(old) && reusable(old, next));
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
            if (attr.name === 'style' && (node.__nxMotionOwned||node.__nxDisclosureOwned)) continue;
            if(attr.name==='open'&&node.__nxDisclosureIntent!==undefined)continue;
            if(attr.name==='hidden'&&node.__nxDisclosureOwned)continue;
            if (!next.hasAttribute(attr.name)) node.removeAttribute(attr.name);
          }
          for (const attr of [...next.attributes]) {
            if (attr.name === 'style' && (node.__nxMotionOwned||node.__nxDisclosureOwned)) continue;
            if(attr.name==='open'&&node.__nxDisclosureIntent!==undefined)continue;
            if(attr.name==='hidden'&&node.__nxDisclosureOwned)continue;
            if (node.getAttribute(attr.name) !== attr.value) node.setAttribute(attr.name, attr.value);
          }
          patchChildren(node, next, preserveFields);
        }
      } else if (node.nodeValue !== next.nodeValue) node.nodeValue = next.nodeValue;
      cursor = nextContent(node.nextSibling);
    }
    for (const node of unused) node.remove();
  }
  function patchHTML(root, html, {preserveFields = true} = {}) {
    const template = root.ownerDocument.createElement('template');
    template.innerHTML = html;
    // The action's surface and its content have separate motion roles. Normalize
    // every primary control here so all views share one structure, including
    // plain text labels, icons, loading feedback and the wide relay button.
    for (const button of template.content.querySelectorAll('button')) {
      if (!button.matches('.primary') && !button.matches('.relay')) continue;
      const copy = root.ownerDocument.createElement('span');
      copy.setAttribute('class','control-content');
      while (button.firstChild) copy.appendChild(button.firstChild);
      button.appendChild(copy);
    }
    patchChildren(root, template.content, preserveFields);
    window.NXDisclosure?.afterPatch(root);
  }
  return {readEpoch, coalescedRefresh, focusKey, restoreFocus, captureScroll, restoreScroll, patchHTML};
})();
