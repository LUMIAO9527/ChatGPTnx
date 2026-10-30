"""Long quota countdowns must remain separated at the native panel size."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from browser_session import browser_session, demo_html

SCRIPT = r"""() => {
 const issues=[]; const rect=n=>n.getBoundingClientRect();
 const overlap=(a,b)=>a.left<b.right-.5&&b.left<a.right-.5&&a.top<b.bottom-.5&&b.top<a.bottom-.5;
 for(const head of document.querySelectorAll('.quota-bar-head')){
  if(!head.getBoundingClientRect().width)continue;
  const label=head.querySelector('.quota-label'), reset=head.querySelector('.reset'), value=head.querySelector('b');
  if(overlap(rect(label),rect(value)))issues.push('quota label/percentage overlap');
  if(rect(reset).right>rect(head).right+.5)issues.push('countdown outside column');
  const track=head.nextElementSibling;
  if(rect(track).top<rect(reset).bottom-.5)issues.push('countdown/track overlap');
  const card=head.closest('.current-card');
  if(card&&rect(track).bottom>rect(card).bottom-5)issues.push('track outside card');
 }
 for(const row of document.querySelectorAll('.quota-overview-window')){
  const nodes=[...row.children];
  if(!rect(row).width)continue;
  for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++)if(overlap(rect(nodes[i]),rect(nodes[j])))issues.push('overview overlap');
  if(nodes.some(n=>rect(n).right>rect(row).right+.5))issues.push('overview overflow');
 }
 const app=document.querySelector('#app');
 if(app.scrollWidth>app.clientWidth)issues.push('panel horizontal overflow');
 return issues;
}"""

def main():
 output=Path(sys.argv[1]); output.mkdir(parents=True,exist_ok=True)
 results=[]
 with browser_session(Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')) as browser:
  for appearance in ('light','dark'):
   for material in ('glass','solid'):
    for count in (1,2):
     for used in (0,.1,100):
      source=demo_html(f'appearance={appearance}&material={material}')
      fixture=f"seed();state.accounts.forEach(a=>{{a.ok=true;a.windows=a.windows.slice(0,{count});a.windows.forEach(w=>{{w.used={used};w.resets_at=sec()+6*86400+23*3600+17*60;}});}});\n  const params"
      source=source.replace('seed();\n  const params',fixture)
      context=browser.new_context(viewport={'width':640,'height':700},device_scale_factor=1.75,reduced_motion='reduce')
      page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
      page.set_content(source);page.wait_for_function('window.NX_CASE_READY')
      for view in ('home','detail','quota-overview','usage'):
       if view=='home':page.evaluate('NXPreview.home()')
       else:page.evaluate('(view)=>NXPreview.open(new URLSearchParams("open="+view))',view)
       page.wait_for_timeout(70)
       issues=page.evaluate(SCRIPT)+errors
       results.append(dict(appearance=appearance,material=material,count=count,used=used,view=view,issues=issues))
       if appearance=='light' and material=='glass' and count==2 and used==0 and view=='home':
        page.locator('#app').screenshot(path=str(output/'home-fixed.png'))
      context.close()
 (output/'quota-layout.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 failed=[r for r in results if r['issues']]
 print(f'Quota layout: {len(results)-len(failed)}/{len(results)} scenes passed')
 for item in failed:print(item)
 return bool(failed)
if __name__=='__main__':raise SystemExit(main())
