/* Exact usage totals and trend buckets; no DOM or bridge dependencies. */
'use strict';
window.NXMath = (() => {
  const SOURCE='account/usage/read';
  const count=value=>typeof value==='bigint'&&value>=0n?value:typeof value==='number'&&Number.isSafeInteger(value)&&value>=0?BigInt(value):typeof value==='string'&&/^\d+$/.test(value)?BigInt(value):null;
  const localIso=ms=>{const d=new Date(ms),pad=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;};
  const shiftIso=(value,days)=>{const[y,m,d]=value.split('-').map(Number);return new Date(Date.UTC(y,m-1,d+days)).toISOString().slice(0,10);};
  function aggregate(accounts,cache,days=30,now=Math.floor(Date.now()/1000)){
    if(![7,30,90,180,'all'].includes(days))days=30;
    const end=localIso(now*1000),fixedStart=days==='all'?null:shiftIso(end,1-days);
    const seen=new Set(),eligible=[],rows=[];
    for(const a of accounts){
      const key=a.identity_key||'email:'+a.email.toLowerCase(),activityKey=a.activity_key||key;
      const duplicate=seen.has(activityKey);seen.add(activityKey);
      const u=cache[a.email],valid=!!(u&&u.ok===true&&u.source===SOURCE),bound=!u||u.identity_key===key;
      const tokens=valid?count(u.summary?.lifetimeTokens):null;
      const status=duplicate?'duplicate':!bound?'identity_changed':u&&!valid?'unavailable':!u?'pending':tokens===null?'missing_total':'ready';
      rows.push({email:a.email,alias:a.alias||'',plan:a.plan,archived:!!a.archived,identity_key:key,activity_key:activityKey,status,fetched_at:u?.fetched_at||null,tokens:tokens===null?null:String(tokens),included:status==='ready',usage:u||null});
      if(!duplicate&&bound&&valid)eligible.push(u);
    }
    const observed=eligible.flatMap(u=>(u.dailyUsageBuckets||[]).filter(b=>b.startDate<=end).map(b=>b.startDate));
    const start=fixedStart||(observed.length?observed.reduce((a,b)=>a<b?a:b):null);
    for(const row of rows){
      const valid=row.usage?.ok===true&&row.usage.source===SOURCE&&!['duplicate','identity_changed','unavailable','pending'].includes(row.status);
      const buckets=valid&&start?(row.usage.dailyUsageBuckets||[]).filter(b=>b.startDate>=start&&b.startDate<=end&&count(b.tokens)!==null):[];
      row.period_tokens=buckets.length?String(buckets.reduce((sum,b)=>sum+count(b.tokens),0n)):null;
      row.period_days=buckets.length;
    }
    const unique=seen.size,dates=new Map();
    for(const u of eligible)for(const b of u.dailyUsageBuckets||[]){const value=count(b.tokens);if(!start||b.startDate<start||b.startDate>end||value===null)continue;const d=dates.get(b.startDate)||{tokens:0n,accounts:0};d.tokens+=value;d.accounts++;dates.set(b.startDate,d);}
    const daily=[...dates].sort(([a],[b])=>a.localeCompare(b)).map(([date,d])=>({date,tokens:String(d.tokens),accounts:d.accounts,complete:d.accounts===unique}));
    const included=rows.filter(r=>r.included),total=included.length?included.reduce((sum,row)=>sum+BigInt(row.tokens),0n):null;
    const span=start?Math.round((Date.parse(end+'T00:00:00Z')-Date.parse(start+'T00:00:00Z'))/86400000)+1:0;
    return{ok:true,source:SOURCE,scope:'chatgpt_account_activity',total_tokens:total===null?null:String(total),included_accounts:included.length,unique_accounts:unique,total_complete:!!unique&&included.length===unique,rows,daily,period:{days,start,end,span_days:span,complete:days!=='all'&&!!unique&&daily.length===days&&daily.every(d=>d.complete),recorded_tokens:daily.length?String(daily.reduce((sum,d)=>sum+BigInt(d.tokens),0n)):null},oldest_fetched_at:included.length?Math.min(...included.map(r=>r.fetched_at)):null,newest_fetched_at:included.length?Math.max(...included.map(r=>r.fetched_at)):null,generated_at:now};
  }
  function compact(value){const n=count(value);if(n===null)return{main:'—',unit:''};for(const[size,unit]of[[100000000n,'亿'],[10000n,'万']])if(n>=size){const h=(n*100n+size/2n)/size;return{main:`${h/100n}.${String(h%100n).padStart(2,'0')}`,unit};}return{main:String(n),unit:''};}
  const compactText=value=>{const v=compact(value);return v.main+v.unit;};
  const exact=value=>count(value)===null?'—':count(value).toLocaleString('en-US');
  function trendGroups(u, lifetime=false) {
    // Fixed ranges stay within 60 bars; lifetime history uses natural calendar months.
    const span=u.period.span_days||0, chartStart=u.period.start?Date.parse(u.period.start+'T00:00:00Z'):null;
    let groups=[],groupLabel='每日',chartStartLabel=u.period.start,chartEndLabel=u.period.end;
    if(lifetime&&chartStart!==null){
      const endDate=Date.parse(u.period.end+'T00:00:00Z'),firstDate=new Date(chartStart),lastDate=new Date(endDate);
      const firstMonth=Date.UTC(firstDate.getUTCFullYear(),firstDate.getUTCMonth(),1),lastMonth=Date.UTC(lastDate.getUTCFullYear(),lastDate.getUTCMonth(),1),index=new Map();
      for(let cursor=firstMonth;cursor<=lastMonth;){
        const month=new Date(cursor).toISOString().slice(0,7),next=Date.UTC(new Date(cursor).getUTCFullYear(),new Date(cursor).getUTCMonth()+1,1);
        const first=Math.max(chartStart,cursor),last=Math.min(endDate,next-86400000),length=Math.round((last-first)/86400000)+1;
        index.set(month,groups.length);groups.push({tokens:0n,recorded:0,complete:0,first:new Date(first).toISOString().slice(0,10),last:new Date(last).toISOString().slice(0,10),length,label:month});cursor=next;
      }
      for(const d of u.daily){const group=groups[index.get(d.date.slice(0,7))];if(!group)continue;group.tokens+=count(d.tokens);group.recorded++;if(d.complete)group.complete++;}
      groupLabel='按月';chartStartLabel=u.period.start.slice(0,7);chartEndLabel=u.period.end.slice(0,7);
    }else if(chartStart!==null){
      const groupDays=Math.max(1,Math.ceil(span/60));groupLabel=groupDays===1?'每日':`每 ${groupDays} 天一组`;
      groups=Array.from({length:Math.ceil(span/groupDays)},(_,i)=>{const first=new Date(chartStart+i*groupDays*86400000).toISOString().slice(0,10),last=new Date(chartStart+Math.min(span-1,(i+1)*groupDays-1)*86400000).toISOString().slice(0,10);return{tokens:0n,recorded:0,complete:0,first,last,length:Math.min(groupDays,span-i*groupDays)};});
      for(const d of u.daily){const group=groups[Math.floor((Date.parse(d.date+'T00:00:00Z')-chartStart)/86400000/groupDays)];if(!group)continue;group.tokens+=count(d.tokens);group.recorded++;if(d.complete)group.complete++;}
    }
    return {groups, groupLabel, chartStartLabel, chartEndLabel};
  }
  return {aggregate, compact, compactText, exact, count, trendGroups};
})();
