/* Demo-only driver. Uses real navigation/actions; never linked to panel.html. */
'use strict';
(() => {
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const params=new URLSearchParams(window.NX_PREVIEW_QUERY??location.search);
  const id=window.NX_PREVIEW_CASE||params.get('case');
  const selected=(window.NX_CATALOG||[]).find(c=>c.id===id);
  const report=(type,extra={})=>{if(parent!==window)parent.postMessage({source:'chatgptnx-preview',type,...extra},'*');};
  async function applyStep(step) {
    if(step.simulate){window.NXDemo.simulate(step.simulate);await window.NXPreview.refresh();await wait(step.wait??80);return;}
    const target=step.click||step.fill||step.hover||step.scroll;
    let node;
    for(let attempt=0;attempt<40;attempt++){
      node=document.querySelector(target);
      if(node && !node.disabled)break;
      await wait(50);
    }
    if(!node||node.disabled)throw new Error('演示步骤找不到可用控件：'+target);
    if(step.click)node.click();
    if(step.fill){node.value=step.value;node.dispatchEvent(new Event('input',{bubbles:true}));}
    if(step.scroll)node.scrollTop=step.top==='bottom'?node.scrollHeight:(step.top||0);
    if(step.hover){node.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));}
    await wait(step.wait??120);
  }
  window.NX_CASE_READY=false;
  window.NX_CASE_PROMISE=(async()=>{
    await window.NXPreviewReady;
    for(const step of selected?.steps||[])await applyStep(step);
    await wait(40);
    window.NX_CASE_READY=true;report('ready',{id,info:window.NXPreview.info()});
  })().catch(error=>{window.NX_CASE_ERROR=String(error.message||error);report('error',{message:window.NX_CASE_ERROR});});
  window.addEventListener('message',async event=>{
    if(event.source!==parent||event.data?.source!=='chatgptnx-explorer')return;
    const {command,value}=event.data;
    try{
      if(command==='appearance')await window.NXPreview.appearance(value);
      else if(command==='simulate'){window.NXDemo.simulate(value);await window.NXPreview.refresh();}
      report('state',{info:window.NXPreview.info()});
    }catch(error){report('error',{message:String(error.message||error)});}
  });
})();
