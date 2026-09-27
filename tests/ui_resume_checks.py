"""Real browser checks with synthetic data; no desktop account operations."""
import argparse
from pathlib import Path
from ui_final_checks import CASES, add, main

CASES.clear()
add('resume/exclusive-active-and-history', 'open=resume&scenario=resume-progress', """
const call=NXDemo.call, base=await call('get_resume_details');
const mixed=[base[0],{...base[0],id:'today',phase:'done'},
  {...base[0],id:'old',phase:'failed',updated_at:base[0].updated_at-172800}];
NXDemo.call=(m,...args)=>m==='get_resume_details'?structuredClone(mixed):call(m,...args);
await NXPreview.refresh();
for(const id of ['today','old','demo-resume','today','demo-resume']){
  $('[data-action=resume-toggle][data-value="'+id+'"]').click();
  await NXPreview.refresh();
  const open=$$('[data-action=resume-toggle][aria-expanded=true]');
  if(open.length!==1||open[0].dataset.value!==id||$$('.resume-tasks').length!==1)return false;
}
$('[data-action=resume-toggle][data-value="demo-resume"]').click();
return $$('[aria-expanded=true]').length===0&&$$('.resume-tasks').length===0;
""")
add('error/no-separate-page', 'open=error', "return NXPreview.info().page==='home'&&!document.body.textContent.includes('操作需要查看');")
add('error/inline-message', '', """
const call=NXDemo.call;
NXDemo.call=async(m,...args)=>{const result=await call(m,...args);
  if(m==='get_data')result.last_error={id:'synthetic-error',message:'无法确定接续目标窗口'};
  return result;};
await NXPreview.refresh();
return NXPreview.info().page==='home'&&document.body.textContent.includes('无法确定接续目标窗口')&&!$('[data-action=error]');
""")

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    raise SystemExit(main(args.browser,args.output))
