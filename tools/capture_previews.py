"""Capture every catalog state in both palettes, plus full-content views for scrolling pages.

The source UI is unmodified for viewport images. Full-content images deliberately
extend only the height and are labeled as such; they are not native window sizes.
"""
import argparse
import json
import hashlib
import struct
from pathlib import Path
from browser_session import ROOT,browser_session,demo_html
from screen_catalog import CASES
from build import CONFIG,APP_VERSION,ui_source_digest

METRICS=r'''() => {
 const app=document.querySelector('#app'),sheet=document.querySelector('#sheet:not([hidden])'),root=sheet||document.querySelector('#home');
 const visible=n=>n.getBoundingClientRect().width>0&&n.getBoundingClientRect().height>0;
 const scrollables=[...root.querySelectorAll('.sheet-body,.account-list,.onboarding-main')].filter(visible);
 const overflow=[root,...scrollables].filter(n=>n.scrollWidth>n.clientWidth+2).map(n=>({class:n.className,id:n.id,width:n.clientWidth,content:n.scrollWidth}));
 const quotas=[...document.querySelectorAll('.choice-quotas,.roster-quotas')].filter(visible).filter(n=>{const r=n.getBoundingClientRect(),b=n.closest('button')?.getBoundingClientRect();return n.scrollWidth>n.clientWidth+1||b&&(r.right>b.right+1||r.left<b.left-1);}).map(n=>n.textContent);
 return {width:app.clientWidth,height:app.clientHeight,title:sheet?.querySelector('h2')?.textContent||null,page:window.NXPreview.info().page,horizontalOverflow:overflow,clippedQuotas:quotas,
   scroll:scrollables.map(n=>({selector:n.classList.contains('sheet-body')?'.sheet-body':n.classList.contains('account-list')?'.account-list':n.classList.contains('onboarding-main')?'.onboarding-main':'.onboarding-main',extra:Math.max(0,n.scrollHeight-n.clientHeight),height:n.clientHeight}))};
}'''

def verify_png_size(image: bytes, width: int, height: int) -> None:
 if image[:8] != b'\x89PNG\r\n\x1a\n' or len(image)<24:
  raise ValueError('Invalid preview PNG')
 actual=struct.unpack('>II',image[16:24])
 if actual!=(width,height):raise ValueError(f'PNG geometry mismatch: {actual}, expected {(width,height)}')

def main(browser,output,appearance='both',only=None,resume=False):
 output.mkdir(parents=True,exist_ok=True)
 digest=ui_source_digest()
 report=json.loads((output/'matrix.json').read_text(encoding='utf-8')) if resume and (output/'matrix.json').exists() else {'native':False,'cases':[]}
 if report.get('source_sha256',digest)!=digest:raise RuntimeError('UI sources changed: recapture into an empty directory')
 report.update(version=APP_VERSION,source_sha256=digest)
 size=[372,520]
 view_width=max(520,size[0]+80);view_height=max(700,size[1]+80)
 palettes=['light','dark'] if appearance=='both' else [appearance]
 selected=[c for c in CASES if not only or c['id'] in only]
 for palette in palettes:
  done={r['id'] for r in report['cases'] if r['appearance']==palette and r['passed']}
  selected=[c for c in CASES if (not only or c['id'] in only) and (not resume or c['id'] not in done)]
  (output/palette).mkdir(exist_ok=True)
  for offset in range(0,len(selected),20):
   with browser_session(browser) as engine:
    report['engine']=engine.version
    for case in selected[offset:offset+20]:
     context=engine.new_context(viewport={'width':view_width,'height':view_height},device_scale_factor=1,color_scheme=palette,reduced_motion='reduce')
     page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
     row={'id':case['id'],'name':case['id'],'appearance':palette,'label':case['label'],'group':case['group']}
     try:
      query=case['query']+'&case='+case['id']+'&appearance='+palette
      page.set_content(demo_html(query))
      page.wait_for_function('window.NX_CASE_READY || window.NX_CASE_ERROR',timeout=9000)
      if page.evaluate('window.NX_CASE_ERROR||null'):errors.append(page.evaluate('window.NX_CASE_ERROR'))
      for step in case['steps']:
       if step.get('hover'):page.locator(step['hover']).first.hover()
      metrics=page.evaluate(METRICS);row.update(metrics)
      if metrics['page']!=case['expected']:errors.append(f"Expected {case['expected']}, got {metrics['page']}")
      if metrics['horizontalOverflow'] or metrics['clippedQuotas']:errors.append('Horizontal overflow or clipped quotas')
      if (metrics['width'],metrics['height']) not in tuple(tuple(v) for v in CONFIG['sizes'].values())+(tuple(size),):errors.append('Unexpected panel geometry')
      image=f"{palette}/{case['id']}.png";png=page.locator('#app').screenshot(path=str(output/image),animations='disabled');verify_png_size(png,metrics['width'],metrics['height']);row['image']=image
      extra=max([r['extra'] for r in metrics['scroll']]+[0])
      if extra>2:
       height=metrics['height']+extra+3
       # Scroll-only preview: same width, all rows; explicit full-content artifact.
       page.set_viewport_size({'width':view_width,'height':height+90})
       page.add_style_tag(content=f'#app{{height:{height}px!important}} .status-dock,.status-runway{{display:none!important}}')
       page.evaluate('height=>{const app=document.querySelector("#app");app.style.height=height+"px";document.querySelectorAll(".sheet-body,.account-list,.onboarding-main").forEach(n=>n.scrollTop=0);}',height)
       full=f"{palette}/{case['id']}--full.png";png=page.locator('#app').screenshot(path=str(output/full),animations='disabled');verify_png_size(png,metrics['width'],height);row['fullImage']=full;row['fullHeight']=height
       remaining=page.evaluate(METRICS)['scroll']
       if any(item['extra']>2 for item in remaining):errors.append('Full-content preview still scrolls')
     except Exception as error:errors.append(str(error))
     finally:
      row['passed']=not errors;row['errors']=errors;report['cases']=[r for r in report['cases'] if (r['id'],r['appearance'])!=(case['id'],palette)];report['cases'].append(row);context.close()
      (output/'matrix.json.tmp').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');(output/'matrix.json.tmp').replace(output/'matrix.json')
 failed=[r for r in report['cases'] if not r['passed']]
 print(f"Capture: {len(report['cases'])-len(failed)}/{len(report['cases'])} passed")
 for r in failed:print(r['appearance'],r['id'],r['errors'])
 return int(bool(failed))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--browser',required=True,type=Path);p.add_argument('--output',type=Path,default=ROOT/'docs/previews');p.add_argument('--appearance',choices=['light','dark','both'],default='both');p.add_argument('--only',nargs='+');p.add_argument('--resume',action='store_true');a=p.parse_args()
 raise SystemExit(main(a.browser.resolve(),a.output.resolve(),a.appearance,a.only,a.resume))
