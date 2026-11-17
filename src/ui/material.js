/* Native blur is authoritative; HTML alone never claims a desktop backdrop. */
'use strict';
window.NXMaterial = (() => {
  const root = document.documentElement;
  const reduced = window.matchMedia('(prefers-reduced-transparency: reduce)');
  const contrast = window.matchMedia('(forced-colors: active)');
  let nativeMode = 'solid', preferred = 'glass', nativeOutline;
  function apply() {
    const enabled = preferred === 'glass' && nativeMode !== 'solid' && !reduced.matches && !contrast.matches;
    root.dataset.material = enabled ? 'glass' : 'solid';
    root.dataset.backdrop = enabled ? nativeMode : 'solid';
  }
  function fitNativePanel() {
    // WebView2 can composite a few extra device pixels at fractional scales.
    // Use the client area measured for the native backdrop. The WebView scale
    // may update after the host sends its geometry.
    for (const dimension of ['width', 'height']) {
      const value = nativeOutline?.[dimension];
      const property = '--native-panel-' + dimension;
      if (Number.isFinite(value) && value > 0) {
        root.style.setProperty(property, (value / window.devicePixelRatio) + 'px');
      } else {
        root.style.removeProperty(property);
      }
    }
  }
  function native(mode, outline) {
    nativeMode = ['acrylic', 'blur', 'preview'].includes(mode) ? mode : 'solid';
    nativeOutline = outline;
    fitNativePanel();
    apply();
  }
  function preference(value) {
    const next=value === 'solid' ? 'solid' : 'glass',changed=next!==preferred;
    preferred=next;apply();
    if(changed)window.dispatchEvent(new CustomEvent('nxmaterialpreference',{detail:{material:preferred}}));
  }
  reduced.addEventListener('change', apply); contrast.addEventListener('change', apply);
  window.addEventListener('resize', fitNativePanel);
  window.nxNativeBackdrop = native;
  if (window.NX_CONFIG.demo) {
    const query = new URLSearchParams(window.NX_PREVIEW_QUERY ?? location.search);
    root.dataset.materialPreview = query.get('backdrop') || 'dawn';
    nativeMode = 'preview'; preferred = query.get('material') === 'solid' ? 'solid' : 'glass';
  }
  apply();
  return { native, preference, preferred: () => preferred, mode: () => root.dataset.material };
})();
