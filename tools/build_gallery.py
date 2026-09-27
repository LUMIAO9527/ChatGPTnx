"""A searchable, self-contained visual inventory with full-resolution/scroll previews."""
import argparse,base64,json,hashlib
from pathlib import Path
from screen_catalog import CASES,NATIVE_SURFACES
from build import APP_VERSION,ui_source_digest
from build_explorer import js
ROOT=Path(__file__).resolve().parents[1]

TEMPLATE=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'"><title>ChatGPTnx __VERSION__ · 全界面样式索引</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f3f5;color:#202329;font:13px/1.6 'Segoe UI','Microsoft YaHei UI',sans-serif}header{background:#fff;padding:26px 32px;border-bottom:1px solid #ddd}h1{font-size:26px;margin:0 0 6px;letter-spacing:-.6px}p{margin:4px 0;color:#626a75}header strong{color:#202329}nav{display:flex;gap:10px;padding:16px 32px;position:sticky;top:0;background:#f2f3f5ed;backdrop-filter:blur(12px);z-index:5;align-items:center;flex-wrap:wrap}input,select,button{font:inherit;border:1px solid #d9dde3;border-radius:9px;background:#fff;color:inherit;padding:9px 12px}input{width:280px}button{cursor:pointer}button:hover{background:#e8ebee}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #48617f;outline-offset:2px}#count{margin-left:auto;color:#626a75;font-size:12px}main{padding:0 32px 40px;display:grid;grid-template-columns:repeat(auto-fill,minmax(365px,1fr));gap:18px}article{padding:16px;background:#fff;border:1px solid #e0e3e7;border-radius:14px;min-width:0;align-self:start}article h2{font-size:15px;margin:0 0 3px}.meta{font-size:10px;color:#7b8189;overflow-wrap:anywhere;margin-bottom:12px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}.pair button{padding:0;border:0;background:none;border-radius:12px;overflow:hidden;line-height:0}.pair img{width:100%;height:auto;border-radius:12px;vertical-align:top;border:1px solid #e2e3e5}.palette{font-size:10px;color:#7b8189;text-align:center;line-height:2.5}.foot{margin-top:10px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}.foot button{font-size:10px;padding:5px 8px}.pill{border-radius:20px;font-size:10px;padding:3px 8px;background:#eff1f4}.group-label{font-size:10px;letter-spacing:.3px;color:#858b94;margin-bottom:5px}dialog{border:0;border-radius:14px;padding:0;max-width:calc(100vw - 28px);max-height:calc(100vh - 28px);background:#eceef1;color:#222;overflow:auto;box-shadow:0 20px 100px #0004}dialog::backdrop{background:#111b}dialog .bar{position:sticky;top:0;display:flex;align-items:center;justify-content:space-between;gap:24px;background:#fff;padding:14px 18px;z-index:2}dialog h2{font-size:15px;margin:0}dialog .images{padding:24px;display:flex;align-items:flex-start;justify-content:center;gap:20px;flex-wrap:wrap}dialog figure{margin:0}dialog img{display:block;width:auto;max-width:100%;height:auto;border-radius:16px}dialog figcaption{font-size:11px;text-align:center;margin:8px 0;color:#666}#native{padding:0 32px 36px}#native h2{font-size:17px}#native p{font-size:12px;max-width:1000px}@media(max-width:600px){header{padding:20px}nav{padding:12px}main{padding:0 12px 30px;grid-template-columns:1fr}#count{margin:0}input{width:100%}dialog .images{padding:14px}h1{font-size:22px}}
</style></head><body><header><h1>ChatGPTnx · 全界面样式索引</h1><p><strong>__VERSION__</strong> · __COUNT__ 个具名页面 / 状态 · 浅色 + 深色 · __IMAGES__ 张实际渲染截图</p><p>点击缩略图查看原尺寸。标有“可滚动”的页面另附完整内容长图，避免只展示首屏。全部截图使用真实组件与合成数据。</p></header><nav><input id="search" type="search" placeholder="搜索页面、状态、路由" aria-label="搜索全部截图"><select id="group" aria-label="选择页面分组"><option value="">全部分组</option></select><label><input id="scrollOnly" type="checkbox" style="width:auto"> 仅看可滚动页</label><span id="count"></span></nav><main id="cards"></main><section id="native"><h2>原生 Windows 界面</h2><p>本页覆盖源码内全部 HTML 页面路由以及目录中列出的状态。托盘、系统通知、权限弹窗、外部 ChatGPT 窗口不由这些组件绘制，不能把浏览器截图冒充它们的实测结果。</p><div id="nativeRows"></div></section><dialog id="viewer" aria-labelledby="viewerTitle"><div class="bar"><div><h2 id="viewerTitle"></h2><p id="viewerNote"></p></div><button id="close">关闭 ×</button></div><div class="images" id="images"></div></dialog><script>
const items=__ITEMS__,native=__NATIVE__,$=s=>document.querySelector(s);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function render(){const q=$('#search').value.trim().toLowerCase(),g=$('#group').value,scroll=$('#scrollOnly').checked;const rows=items.filter(c=>(!g||c.group===g)&&(!scroll||c.light.fullImage)&&[c.group,c.label,c.id,c.route].join(' ').toLowerCase().includes(q));$('#count').textContent=rows.length+' / '+items.length+' 个页面与状态';$('#cards').innerHTML=rows.map(c=>`<article><div class="group-label">${esc(c.group)}</div><h2>${esc(c.label)}</h2><div class="meta">${esc(c.id)} · ${esc(c.route)}</div><div class="pair">${['light','dark'].map(t=>`<div><button data-id="${c.id}" data-mode="pair" aria-label="查看 ${esc(c.label)} 原尺寸"><img src="${c[t].image}" loading="lazy" alt="${esc(c.label)} · ${t==='light'?'浅色':'深色'}"></button><div class="palette">${t==='light'?'浅色':'深色'} · ${c[t].width} × ${c[t].height}</div></div>`).join('')}</div><div class="foot"><span class="pill">${c.light.fullImage?'可滚动':'首屏内容'}</span>${c.light.fullImage?`<button data-id="${c.id}" data-mode="full">查看展开内容全览</button>`:''}<button data-id="${c.id}" data-mode="pair">原尺寸对照</button></div></article>`).join('');}
function open(id,mode){const c=items.find(x=>x.id===id);$('#viewerTitle').textContent=c.label;$('#viewerNote').textContent=mode==='full'?'完整内容长图：仅延展内容高度并隐藏悬浮层，不表示原生窗口会变高；悬浮状态请看原尺寸截图。':'原尺寸截图：浅色与深色使用同一布局。';$('#images').innerHTML=['light','dark'].map(t=>`<figure><img src="${mode==='full'?c[t].fullImage:c[t].image}" alt="${esc(c.label)}"><figcaption>${t==='light'?'浅色':'深色'} · ${mode==='full'?'完整内容':c[t].width+' × '+c[t].height}</figcaption></figure>`).join('');$('#viewer').showModal();}
$('#search').addEventListener('input',render);$('#group').addEventListener('change',render);$('#scrollOnly').addEventListener('change',render);document.addEventListener('click',e=>{const b=e.target.closest('[data-id]');if(b)open(b.dataset.id,b.dataset.mode);});$('#close').onclick=()=>$('#viewer').close();$('#viewer').addEventListener('click',e=>{if(e.target===$('#viewer'))$('#viewer').close();});
[...new Set(items.map(c=>c.group))].forEach(g=>{const o=document.createElement('option');o.value=g;o.textContent=g;$('#group').append(o);});$('#nativeRows').innerHTML=native.map(n=>`<p><strong>${esc(n.surface)}</strong>：${esc(n.verification)}</p>`).join('');render();
</script></body></html>'''

def build_gallery(output:Path):
    folder=ROOT/'docs/previews'
    report=json.loads((folder/'matrix.json').read_text(encoding='utf-8'))
    digest=ui_source_digest()
    if report.get('version')!=APP_VERSION or report.get('source_sha256')!=digest:
        raise RuntimeError('Screenshots do not match current UI sources; capture again')
    indexed={(r['id'],r['appearance']):r for r in report['cases']}
    records=[];nimages=0
    for case in CASES:
        item={k:case[k] for k in ('id','label','group','route','expected')}
        for palette in ('light','dark'):
            row=indexed.get((case['id'],palette))
            if not row or not row['passed']:raise RuntimeError(f'Missing or failed screenshot: {case["id"]}/{palette}')
            image={key:row[key] for key in ('width','height','page')}
            if row.get('fullImage'):image['fullHeight']=row['fullHeight']
            for key in ('image','fullImage'):
                if row.get(key):
                    path=(folder/row[key]).resolve()
                    if not path.is_relative_to(folder.resolve()):raise ValueError('Unsafe preview path')
                    image[key]='data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode('ascii');nimages+=1
            item[palette]=image
        records.append(item)
    html=TEMPLATE.replace('__VERSION__',APP_VERSION).replace('__COUNT__',str(len(CASES))).replace('__IMAGES__',str(nimages)).replace('__ITEMS__',js(records)).replace('__NATIVE__',js(NATIVE_SURFACES))
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(html,encoding='utf-8')
    # Human-readable and machine-readable inventory use the same source of truth.
    lines=[f'# 全界面与状态清单 · {APP_VERSION}','',f'{len(CASES)} 个具名页面 / 状态；每项浅色、深色各一张。共 {nimages} 张 PNG，包含可滚动页面的完整内容长图。','',
           '打开 `ui-explorer.html` 操作真实界面组件；打开 `ui-gallery.html` 搜索、放大和对照全部截图。浏览器截图使用合成数据，不替代 Windows 本机验收。','']
    group=None
    for case in CASES:
        if group!=case['group']:
            group=case['group'];lines.extend(['## '+group,'','| 状态 | ID | 入口路由 → 截图路由 | 内容 |','| --- | --- | --- | --- |'])
        row=indexed[(case['id'],'light')]
        lines.append(f"| {case['label']} | `{case['id']}` | `{case['route']}` → `{case['expected']}` | {'首屏 + 完整内容长图' if row.get('fullImage') else '首屏'} |")
    lines.extend(['','## 不以 HTML 截图代替的原生表面',''])
    for n in NATIVE_SURFACES:lines.append(f"**{n['surface']}**（`{n['source']}`）：{n['verification']}\n")
    (ROOT/'docs/SCREEN_MAP.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (ROOT/'docs/screen-catalog.json').write_text(json.dumps({'cases':CASES,'native':NATIVE_SURFACES},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Gallery: {len(records)} states, {nimages} PNGs, {output.stat().st_size:,} bytes')
    return len(records),nimages

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'docs/ui-gallery.html');build_gallery(p.parse_args().output.resolve())
