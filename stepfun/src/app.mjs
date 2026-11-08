import {splitText,docId} from './core.mjs';
const $=id=>document.getElementById(id);
let worker, seq=0, state, kbs=[], metrics=[], busy=false;
let pending=new Map();
export async function api(url,data) {
  const r=await fetch('/api'+url,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result=await r.json(); if(!r.ok) throw Error(result.error); return result;
}
function record(kind,value) {metrics.push({at:new Date().toISOString(),kind,...value}); $('metrics').textContent=JSON.stringify(metrics.slice(-8),null,2);}
function status(s) {
  if(s.phase==='ready') $('modelStatus').textContent=`已完成真实模型预热 · ${s.backend.toUpperCase()} · ${s.dtype.toUpperCase()}\n${JSON.stringify(s.adapter||{})}\n${s.fallbackReason?'降级原因：'+s.fallbackReason:''}\n加载 ${s.sessionLoadMs.toFixed(0)} ms / 预热 ${s.warmupMs.toFixed(0)} ms`;
  else $('modelStatus').textContent=JSON.stringify(s);
  $('progress').value=s.phase==='ready'?100:Number(s.progress||0);
}
function rpc(type,payload) {return new Promise((resolve,reject)=>{const id=++seq; pending.set(id,{resolve,reject}); worker.postMessage({id,type,payload});});}
export async function loadModel(dtype=$('dtype').value,backend=$('backend').value) {
  if(worker) worker.terminate();
  for(const p of pending.values()) p.reject(Error('模型已重新加载')); pending.clear(); state=null;
  worker=new Worker('/assets/embed-worker.js',{type:'module'});
  worker.onmessage=({data})=>{
    if(data.event==='status') return status(data.value);
    const p=pending.get(data.id); if(p) {pending.delete(data.id);data.error?p.reject(Error(data.error)):p.resolve(data.result);}
  };
  worker.onerror=e=>{for(const p of pending.values())p.reject(Error(e.message));pending.clear();};
  state=await rpc('load',{dtype,backend,spec:await api('/model')});
  record('model',state); return state;
}
function current() {const k=kbs.find(x=>x.id===$('kb').value); if(!k) throw Error('请先新建知识库'); return k;}
function ready(k=current()) {if(!state) throw Error('请先加载模型');if(k.dtype!==state.dtype) throw Error(`当前知识库需要 ${k.dtype}，请选择对应精度并加载模型`);return k;}
export async function reloadKbs(selected) {
  kbs=await api('/kbs'); $('kb').replaceChildren(...kbs.map(k=>new Option(`${k.name} · ${k.dtype} · ${k.count} 段${k.retrieval==='quality-v2'?' · 已优化':''}${Number(k.dirty)?' · 待刷新':''}`,k.id)));
  if(kbs.some(k=>k.id===selected)) $('kb').value=selected;
  if(kbs.length) $('dtype').value=current().dtype;
  saveSelection(); return kbs;
}
function saveSelection() {if($('kb').value)localStorage.setItem('stepfun.kb',$('kb').value);$('results').replaceChildren();}
export async function createKb(name=$('kbName').value) {
  if(!state) throw Error('请先加载模型');const k=await api('/kbs',{name,dtype:state.dtype});await reloadKbs(k.id);return k;
}
export async function importDocs(documents,batchSize=Number($('batch').value)) {
  const k=ready(), profile=state.profile, total=documents.length;
  if(total>1000) throw Error('单次最多 1000 段，请分批导入');
  let embedMs=0,writeMs=0; const start=performance.now();
  for(let i=0;i<total;i+=batchSize) {
    const batch=documents.slice(i,i+batchSize), result=await rpc('embed',{texts:batch.map(d=>d.text)});embedMs+=result.ms;
    const docs=await Promise.all(batch.map(async(d,j)=>({...d,id:d.id||await docId(d),embedding:result.vectors[j]})));
    const r=await api(`/kbs/${k.id}/ingest`,{profile,documents:docs});writeMs+=r.writeMs;
    $('notice').textContent=`向量化并写入 ${Math.min(i+batchSize,total)} / ${total} 段`;
  }
  const {refreshMs}=await api(`/kbs/${k.id}/refresh`,{});
  const result={kb:k.id,documents:total,batchSize,embeddingMs:embedMs,writeMs,refreshMs,totalMs:performance.now()-start,backend:state.backend,dtype:state.dtype};
  record('import',result);await reloadKbs(k.id);return result;
}
export async function query(text=$('query').value,topK=5,strategy) {
  const k=ready(),start=performance.now();
  const e=await rpc('embed',{texts:[text],query:true});
  const db=await api(`/kbs/${k.id}/search`,{query:text,embedding:e.vectors[0],profile:e.profile,topK,strategy});
  $('results').replaceChildren();
  db.results.ids[0].forEach((id,i)=>{
    const article=document.createElement('article'),title=document.createElement('h3'),pre=document.createElement('p');
    title.textContent=`${i+1}. ${db.results.metadatas?.[0]?.[i]?.source||id}`;
    pre.textContent=db.results.documents?.[0]?.[i]||''; article.append(title,pre);$('results').append(article);
  });
  // Include DOM update and a rendering opportunity in end-to-end timing.
  await new Promise(requestAnimationFrame);
  const value={query:text,queryEmbeddingMs:e.ms,searchMs:db.searchMs,endToEndMs:performance.now()-start,ids:db.results.ids[0],strategy:db.strategy,engine:db.engine};record('query',value);return value;
}
async function run(fn) {
  if(busy)return;busy=true;
  document.querySelectorAll('button,input,select,textarea').forEach(x=>x.disabled=true);
  try {await fn();$('notice').textContent='操作完成';}catch(e){$('notice').textContent=e.message;console.error(e);}
  finally {busy=false;document.querySelectorAll('button,input,select,textarea').forEach(x=>x.disabled=false);}
}
$('load').onclick=()=>run(()=>loadModel());
$('create').onclick=()=>run(()=>createKb());
$('kb').onchange=()=>{saveSelection();$('dtype').value=current().dtype;};
$('refresh').onclick=()=>run(async()=>{const k=current();record('refresh',await api(`/kbs/${k.id}/refresh`,{}));await reloadKbs(k.id);});
$('optimize').onclick=()=>run(async()=>{const k=current(),t=performance.now();const result=await api(`/kbs/${k.id}/optimize`,{});await reloadKbs(result.id);record('optimize',{...result,ms:performance.now()-t});});
$('import').onclick=()=>run(async()=>{
  let docs=[];for(const f of $('files').files) {if(f.size>2*1024*1024) throw Error('每个文本文件最多 2 MiB，请拆分后导入');docs.push(...splitText(await f.text(),f.name));}
  if($('text').value.trim()) docs.push(...splitText($('text').value,'粘贴文本'));
  if(!docs.length) throw Error('请粘贴文本或选择 UTF-8 文本文件');await importDocs(docs);
});
$('fixture').onclick=()=>run(async()=>{const f=await api('/fixture');await importDocs(f.documents);});
$('search').onclick=()=>run(()=>query());
$('query').onkeydown=e=>{if(e.key==='Enter')run(()=>query());};
$('export').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify({userAgent:navigator.userAgent,state,metrics},null,2)],{type:'application/json'}));a.download='stepfun-metrics.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
// Browser automation calls the exact same load/import/search functions used by the UI.
window.stepfunTest={loadModel,createKb,importDocs,query,reloadKbs,api,embed:texts=>rpc('embed',{texts}),select:id=>{$('kb').value=id;saveSelection();},getState:()=>state,getMetrics:()=>metrics};
api('/health').then(async health=>{
  $('dbStatus').textContent=`seekdb 已连接 · ${health.mode} · ${JSON.stringify(health.version)}`;
  await reloadKbs(localStorage.getItem('stepfun.kb'));
}).catch(e=>{$('dbStatus').textContent='数据库未就绪：'+e.message;});
