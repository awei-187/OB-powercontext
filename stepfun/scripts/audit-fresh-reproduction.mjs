import {fork} from 'node:child_process';import {readFile,writeFile} from 'node:fs/promises';
const before=JSON.parse(await readFile('test-results/retrieval-quality/final/comparison.json')),fresh=JSON.parse(await readFile('test-results/retrieval-quality/fresh-reproduction/comparison.json'));
const vectors=JSON.parse(await readFile('test-results/retrieval-quality/query-vectors.json')),q=vectors.queries.find(q=>q.id==='q-room');
const child=fork(new URL('../server/db-worker.mjs',import.meta.url),[],{stdio:['ignore','ignore','ignore','ipc'],windowsHide:true});
let seq=0;const pending=new Map();child.on('message',m=>{const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error)):p.resolve(m.result);});
const call=(type,...args)=>new Promise((resolve,reject)=>{pending.set(++seq,{resolve,reject});child.send({id:seq,type,args});});
const timer=setTimeout(()=>{child.kill();process.exitCode=1;},60000);
try{
  const a=before.cases[0].kb,b=fresh.baselineKb;
  const drift=await call('auditVectorDrift',a,b),results=[];
  for(const id of [a,b])results.push({id,...await call('search',id,{query:q.text,embedding:q.vectors[0],profile:q.profile,topK:10,strategy:'baseline-v1'})});
  const division=await call('auditDivisionPrecision');
  await writeFile('test-results/retrieval-quality/fresh-audit.json',JSON.stringify({drift,division,results},null,2));
  console.log(drift,division,results.map(r=>({id:r.id,ids:r.results.ids[0],scores:r.results.distances[0]})));
}finally{clearTimeout(timer);child.kill();}
