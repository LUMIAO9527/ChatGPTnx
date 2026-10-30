"""Isolated Windows material preview. Only synthetic demo data is loaded."""
from __future__ import annotations
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

FROZEN = bool(getattr(sys, 'frozen', False))
ROOT = Path(sys._MEIPASS) if FROZEN else Path(__file__).resolve().parents[1]
TASK = Path(sys.executable).resolve().parent if FROZEN else ROOT / '_wip' / 'glass-preview'
RUNTIME = TASK / 'runtime' / 'glass-preview'
RUNTIME.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(RUNTIME)
tempfile.tempdir = str(RUNTIME)
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
from nx.window_material import WindowMaterial, edge_color
from nx.window_corners import WindowCorners
from nx.win_compat import window_dpi
from nx.design import PANEL_CONFIG


def inspect_outline(hwnd):
    from ctypes import wintypes as wt
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    gdi.DeleteObject.argtypes = [wt.HGDIOBJ]
    bounds = wt.RECT()
    if not user.GetWindowRect(hwnd, ctypes.byref(bounds)):
        raise OSError('Cannot measure preview outline')
    radius = round(PANEL_CONFIG['radius'] * window_dpi(hwnd) / 96)
    user.GetWindowRgn.argtypes = [wt.HWND,wt.HRGN]
    user.GetWindowRgn.restype = ctypes.c_int
    gdi.CreateRectRgn.argtypes = [ctypes.c_int]*4
    gdi.CreateRectRgn.restype = wt.HRGN
    gdi.PtInRegion.argtypes = [wt.HRGN,ctypes.c_int,ctypes.c_int]
    gdi.PtInRegion.restype = wt.BOOL
    query = gdi.CreateRectRgn(0,0,0,0)
    try:
        kind=user.GetWindowRgn(hwnd,query)
        return {'radius_css':PANEL_CONFIG['radius'],'radius_physical':radius,'region_kind':kind,
                'quarter_radius_outside':not bool(gdi.PtInRegion(query,radius//4,radius//4)),
                'center_inside':bool(gdi.PtInRegion(query,(bounds.right-bounds.left)//2,(bounds.bottom-bounds.top)//2))}
    finally:
        gdi.DeleteObject(query)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=('auto', 'blur', 'solid'), default='auto')
    parser.add_argument('--appearance', choices=('light', 'dark'), default='light')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--close-after-check', action='store_true')
    parser.add_argument('--edge-test', action='store_true')
    parser.add_argument('--report', type=Path, default=TASK/'evidence'/'native-preview.json')
    args = parser.parse_args()
    import webview
    from webview.platforms.winforms import BrowserView
    from System import Action
    material = WindowMaterial(resources=ROOT if FROZEN else ROOT/'_wip/build/resources')
    corners = WindowCorners()
    state = {'appearance': args.appearance, 'backend': args.backend, 'mode': 'solid'}
    lock = threading.Lock()
    diagnostics = {}
    def write_report(extra=None):
        with lock:
            diagnostics.update(extra or {})
            value = {'os_build': sys.getwindowsversion().build, 'synthetic_data_only': True,
                     'window': {'width':312, 'height':458}, **state, **diagnostics}
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    def publish():
        preview.evaluate_js('window.nxNativeBackdrop(' + json.dumps(state['mode']) + ')')
        board.evaluate_js('document.getElementById("mode").textContent=' + json.dumps(
            {'acrylic':'Windows 原生磨砂', 'blur':'高斯模糊', 'solid':'纯色'}[state['mode']]))
        write_report()
    def configure(show=False):
        form = BrowserView.instances[preview.uid]
        hwnd = int(form.Handle.ToInt64())
        from ctypes import wintypes as wt
        user = ctypes.windll.user32
        user.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
        user.SetWindowPos.restype = wt.BOOL
        dpi = window_dpi(hwnd)
        if not user.SetWindowPos(hwnd, None, 0, 0, round(312*dpi/96), round(458*dpi/96), 0x16):
            raise OSError('Cannot size preview panel')
        state['mode'] = material.apply(form, hwnd, dark=state['appearance']=='dark',
                                       backend=state['backend'])
        state['backdrop_clip'] = material.outline
        state['native_error'] = material.last_error
        color=edge_color(state['appearance']=='dark') if state['mode']!='solid' else ((29,29,29) if state['appearance']=='dark' else (255,255,255))
        corners.apply(hwnd,round(PANEL_CONFIG['radius']*dpi/96),color)
        state['outline_check'] = inspect_outline(hwnd)
        state['outline_check']['alpha_edges'] = len(corners.windows)
        state['radius'] = PANEL_CONFIG['radius']
        state['dpi'] = dpi
        if show:
            board_form = BrowserView.instances.get(board.uid)
            if board_form:
                board_form.Show()
            def move(*_): corners.move()
            def closed(*_): corners.close()
            form.LocationChanged += move
            form.VisibleChanged += move
            form.HandleDestroyed += closed
            form.Show()
            form.Activate()
            corners.move(visible=True)
    def dispatch(show=False):
        form = BrowserView.instances.get(preview.uid)
        if form:
            form.Invoke(Action(lambda: configure(show)))
    class Bridge:
        def configure(self, appearance, backend):
            if appearance not in ('light','dark') or backend not in ('auto','blur','solid'):
                return False
            state['appearance'],state['backend']=appearance,backend
            dispatch()
            preview.evaluate_js('window.NXPreview.appearance(' + json.dumps(appearance) + ')')
            preview.evaluate_js('window.NXPreview.material(' + json.dumps('solid' if backend=='solid' else 'glass') + ')')
            publish()
            return True
        def appearance(self, appearance, preference='glass'):
            if appearance not in ('light','dark') or preference not in ('glass','solid'):
                return False
            backend='solid' if preference=='solid' else ('blur' if state['backend']=='blur' else 'auto')
            if appearance==state['appearance'] and backend==state['backend']:
                return False
            state['appearance']=appearance
            state['backend']=backend
            dispatch()
            publish()
            return True
        def close(self):
            preview.destroy()
            board.destroy()
        def material_state(self):
            return {key:state.get(key) for key in ('appearance','backend','mode','native_error','backdrop_clip')}
    if FROZEN:
        html = (ROOT/'demo.html').read_text(encoding='utf-8')
    else:
        from build import panel
        html = panel(demo=True)
    html = html.replace('class="demo"', 'class="live"', 1)
    query = '?appearance='+args.appearance+'&material='+('solid' if args.backend=='solid' else 'glass')
    html = html.replace('window.NX_CONFIG=', 'window.NX_PREVIEW_QUERY='+json.dumps(query)+';window.NX_CONFIG=', 1)
    observer = """<script>window.addEventListener('pywebviewready',()=>{
      const sync=()=>{window.NX_NATIVE_SYNC=window.pywebview.api.appearance(document.documentElement.dataset.appearance,window.NXMaterial.preferred());};
      window.addEventListener('nxmaterialpreference',sync);
      new MutationObserver(sync)
        .observe(document.documentElement,{attributes:true,attributeFilter:['data-appearance']});
      sync();
    });</script>"""
    html = html.replace('</body>', observer+'</body>')
    board_html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
      *{box-sizing:border-box}body{margin:0;height:100vh;color:#223047;font:14px/1.8 'Segoe UI','Microsoft YaHei UI',sans-serif;background:radial-gradient(ellipse at 20% 10%,#9ec8eb,transparent 55%),radial-gradient(ellipse at 85% 80%,#c4aee8,transparent 50%),radial-gradient(ellipse at 15% 90%,#e7aa92,transparent 60%),#b8cddd}main{padding:55px;width:425px}h1{font-size:29px;line-height:1.4;font-weight:600}p{color:#4f6077}button{border:1px solid #ffffff70;border-radius:9px;background:#ffffff60;color:inherit;font:inherit;padding:6px 13px;margin:3px;cursor:pointer}.actions{margin:24px 0}small{font-size:11px;color:#4f6077}.line{position:absolute;left:46%;right:20px;top:310px;height:28px;background:#f4c9a7}.line.two{top:370px;background:#819fba}.status{font-size:12px;margin-top:25px}</style>
      <div class="line"></div><div class="line two"></div><main><small>CHATGPTNX / WINDOWS PREVIEW</small><h1>真实的桌面模糊。</h1><p>右侧是独立窗口。移动它，可以看到后方的色带透过玻璃改变。</p><div class="actions"><button onclick="change('light',null)">浅色</button><button onclick="change('dark',null)">深色</button><br><button onclick="change(null,'auto')">磨砂</button><button onclick="change(null,'blur')">高斯模糊</button><button onclick="change(null,'solid')">纯色</button></div><div class="status" id="mode">正在准备…</div><p><small>面板采用合成数据，可体验页面和转场。所有操作均留在预览中。</small></p><button onclick="window.pywebview.api.close()">关闭预览</button></main><script>let appearance='light',backend='auto';function change(a,b){appearance=a||appearance;backend=b||backend;window.pywebview.api.configure(appearance,backend)}</script></html>'''
    width, height = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
    if args.edge_test:
        board_html=board_html.replace('</style>','body{background:repeating-conic-gradient(#163d72 0% 25%,#f1bd67 0% 50%) 0 0/10px 10px}main{background:#e9eef4f0}</style>')
    x, y = max(20,(width-1000)//2), max(20,(height-650)//2)
    bridge = Bridge()
    board = webview.create_window('ChatGPTnx · 玻璃背景对照', html=board_html, js_api=bridge,
                                  width=1000, height=650, x=x, y=y, resizable=False)
    preview = webview.create_window('ChatGPTnx · 玻璃预览', html=html, js_api=bridge,
                                    width=312, height=458, x=x+580, y=y+100,
                                    frameless=True, easy_drag=False, shadow=False,
                                    hidden=True, resizable=False, background_color='#ffffff')
    def ready():
        try:
            preview.events.loaded.wait(30)
            dispatch(True)
            publish()
            if args.check:
                results = []
                for appearance in ('light','dark'):
                    for backend in ('auto','blur','solid'):
                        bridge.configure(appearance, backend)
                        result = preview.evaluate_js("({material:document.documentElement.dataset.material,backdrop:document.documentElement.dataset.backdrop,appearance:document.documentElement.dataset.appearance,width:document.getElementById('app').clientWidth,height:document.getElementById('app').clientHeight,logo:getComputedStyle(document.querySelector('.mark')).color,footer:getComputedStyle(document.querySelector('.footer')).backgroundColor})")
                        results.append({'requested':backend, 'native':state['mode'], **result})
                bridge.configure(args.appearance,args.backend)
                write_report({'checks':results})
                source=(ROOT/'glass_render_checks.js' if FROZEN else ROOT/'tests/glass_render_checks.js').read_text(encoding='utf-8')
                preview.evaluate_js(source)
                finished=threading.Event()
                rendered={}
                def checked(value):
                    rendered.update(value if isinstance(value,dict) else {'error':str(value)})
                    finished.set()
                preview.evaluate_js('window.nxCheckGlassRendering()',callback=checked)
                if not finished.wait(40):
                    raise TimeoutError('Glass rendering checks did not finish')
                write_report({'render_checks':rendered})
                switched={}
                finished.clear()
                def checked_switches(value):
                    switched.update(value if isinstance(value,dict) else {'error':str(value)})
                    finished.set()
                preview.evaluate_js('window.nxCheckNativeMaterialSwitching()',callback=checked_switches)
                if not finished.wait(20):
                    raise TimeoutError('Native material switching did not finish')
                write_report({'material_switches':switched})
                if args.close_after_check:
                    preview.destroy()
                    board.destroy()
        except Exception as error:
            import traceback
            write_report({'error':type(error).__name__, 'details':str(error), 'trace':traceback.format_exc()})
            if args.close_after_check:
                preview.destroy()
                board.destroy()
    board.events.closed += lambda: preview.destroy()
    webview.start(ready, gui='edgechromium', private_mode=True, storage_path=str(RUNTIME/'webview'))


if __name__ == '__main__':
    main()
