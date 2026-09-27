/* Optimistic, serial preference writes. Input never waits for disk or a poll.
   A fresh read can retire an overlay only if that write had already settled
   when the read STARTED. Late reads and superseded failures cannot undo intent. */
'use strict';
window.NXPreferences = (() => {
  function create({read, project, write, changed=()=>{}, failed=()=>{}, settled=()=>{}}) {
    const entries=new Map();
    let revision=0, draining=false, scheduled=false;
    function set(key,value) {
      const old=entries.get(key);
      entries.set(key,{value,confirmed:old?old.confirmed:read(key),revision:++revision,status:'queued'});
      project(key,value);changed();
      if(!scheduled&&!draining){scheduled=true;queueMicrotask(drain);}
    }
    async function drain() {
      scheduled=false;if(draining)return;draining=true;
      try {
        for (;;) {
          const next=[...entries].find(([,e])=>e.status==='queued');if(!next)break;
          const [key,entry]=next,{value,revision:version}=entry;entry.status='writing';
          try {
            const result=await write(key,value);
            if(result?.ok===false)throw new Error(result.error||result.err||'设置未保存');
            const latest=entries.get(key);
            if(!latest)continue;
            latest.confirmed=value;
            if(latest.revision===version)latest.status='settled';
          } catch(error) {
            const latest=entries.get(key);
            // A later click is still queued. Do not roll it back or show a stale error.
            if(latest?.revision===version){latest.value=latest.confirmed;latest.status='settled';project(key,latest.value);failed(error,key);}
          }
          changed();
        }
      } finally {draining=false;settled();}
    }
    function readTicket() {
      return new Map([...entries].filter(([,e])=>e.status==='settled').map(([key,e])=>[key,e.revision]));
    }
    function reconcile(target,ticket) {
      for(const [key,e] of entries) {
        if(e.status==='settled'&&ticket?.get(key)===e.revision)entries.delete(key);
        else project(key,e.value,target);
      }
    }
    return {set,readTicket,reconcile,pending:()=>draining||scheduled||[...entries.values()].some(e=>e.status!=='settled')};
  }
  return {create};
})();
