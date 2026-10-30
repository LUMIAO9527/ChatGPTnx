/* Native blur is authoritative; HTML alone never claims a desktop backdrop. */
'use strict';
window.NXMaterial = (() => {
  const root = document.documentElement;
  const reduced = window.matchMedia('(prefers-reduced-transparency: reduce)');
  const contrast = window.matchMedia('(forced-colors: active)');
  let nativeMode = 'solid', preferred = 'glass';
  function apply() {
    const enabled = preferred === 'glass' && nativeMode !== 'solid' && !reduced.matches && !contrast.matches;
    root.dataset.material = enabled ? 'glass' : 'solid';
    root.dataset.backdrop = enabled ? nativeMode : 'solid';
  }
  function native(mode) {
    nativeMode = ['acrylic', 'blur', 'preview'].includes(mode) ? mode : 'solid';
    apply();
  }
  function preference(value) {
    const next=value === 'solid' ? 'solid' : 'glass',changed=next!==preferred;
    preferred=next;apply();
    if(changed)window.dispatchEvent(new CustomEvent('nxmaterialpreference',{detail:{material:preferred}}));
  }
  reduced.addEventListener('change', apply); contrast.addEventListener('change', apply);
  window.nxNativeBackdrop = native;
  if (window.NX_CONFIG.demo) {
    const query = new URLSearchParams(window.NX_PREVIEW_QUERY ?? location.search);
    root.dataset.materialPreview = query.get('backdrop') || 'dawn';
    nativeMode = 'preview'; preferred = query.get('material') === 'solid' ? 'solid' : 'glass';
  }
  apply();
  return { native, preference, preferred: () => preferred, mode: () => root.dataset.material };
})();
