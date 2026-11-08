import {fork} from 'node:child_process';import {readFile,writeFile} from 'node:fs/promises';import {quality} from '../src/core.mjs';
const saved=JSON.parse(await readFile('test-results/benchmark.json')),kb=saved.runs.find(r=>r.config.dtype==='fp16').kb.id;
const vectors=JSON.parse(await readFile('test-results/retrieval-quality/query-vectors.json')),f=JSON.parse(await readFile('data/fixture.json'));
const child=fork(new URL('../server/db-worker.mjs',import.meta.url),[],{stdio:['ignore','ignore','ignore','ipc'],windowsHide:true});
let seq=0;const pending=new Map();
child.on('message',m=>{const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error)):p.resolve(m.result);});
const call=(type,...args)=>new Promise((resolve,reject)=>{pending.set(++seq,{resolve,reject});child.send({id:seq,type,args});});
const timer=setTimeout(()=>{child.kill();process.exitCode=1;},60000);
try{
  const rows=[];
  for(const q of f.queries){
    const v=vectors.queries.find(v=>v.id===q.id),r=await call('diagnose',kb,{query:q.text,profile:v.profile,embedding:v.vectors[0],topK:5});
    const exact=r.exact.ids[0],approx=r.approximate.ids[0],fts=r.fts.map(x=>x._id),hybrid=r.hybrid.results.ids[0];
    const metrics={exact:quality(exact,q.relevance),approximate:quality(approx,q.relevance),fts:quality(fts,q.relevance),hybrid:quality(hybrid,q.relevance)};
    rows.push({queryId:q.id,query:q.text,metrics,relevantRanks:Object.keys(q.relevance).map(id=>({id,vectorRank:exact.indexOf(id)+1,approxRank:approx.indexOf(id)+1,ftsRank:fts.indexOf(id)+1})),...r});
    console.log(q.id,JSON.stringify(metrics),exact.slice(0,5),fts.slice(0,5));
  }
  await writeFile('test-results/retrieval-quality/diagnosis.json',JSON.stringify({kb,model:vectors.state,rows},null,2));
} finally {clearTimeout(timer);child.kill();}
