import {fork} from 'node:child_process';import {readFile,writeFile} from 'node:fs/promises';import {quality} from '../src/core.mjs';import {variants} from '../server/retrieval.mjs';
const saved=JSON.parse(await readFile('test-results/retrieval-quality/baseline-v1/test-results/benchmark.json')),kb=saved.runs.find(r=>r.config.dtype==='fp16').kb.id;
const input=process.env.QUERY_INSTRUCTION==='none'?'query-vectors-no-instruction.json':'query-vectors.json';
const vectors=JSON.parse(await readFile('test-results/retrieval-quality/'+input)),f=JSON.parse(await readFile('data/fixture.json'));
const child=fork(new URL('../server/db-worker.mjs',import.meta.url),[],{stdio:['ignore','ignore','ignore','ipc'],windowsHide:true});
let seq=0;const pending=new Map();child.on('message',m=>{const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error)):p.resolve(m.result);});
const call=(type,...args)=>new Promise((resolve,reject)=>{pending.set(++seq,{resolve,reject});child.send({id:seq,type,args});});
const timer=setTimeout(()=>{child.kill();process.exitCode=1;},120000),runs=[];
try {
  for(const [strategy,config]of Object.entries(variants)){
    const run={strategy,config,queries:[]};runs.push(run);
    for(const q of f.queries){const v=vectors.queries.find(v=>v.id===q.id);try{
      const r=await call('search',kb,{query:q.text,profile:v.profile,embedding:v.vectors[0],topK:5,strategy});
      run.queries.push({id:q.id,text:q.text,ids:r.results.ids[0],lexicalQuery:r.lexicalQuery,searchMs:r.searchMs,...quality(r.results.ids[0],q.relevance)});
    }catch(e){run.error=e.message;break;}}
    if(!run.error)run.summary={recall:run.queries.reduce((s,q)=>s+q.recall,0)/12,ndcg:run.queries.reduce((s,q)=>s+q.ndcg,0)/12};
    console.log(strategy,run.summary||run.error);
  }
  await writeFile('test-results/retrieval-quality/'+(process.env.QUERY_INSTRUCTION==='none'?'variants-no-instruction.json':'variants.json'),JSON.stringify({note:'Exploratory DB-only comparison using fresh browser-generated FP16 vectors; not end-to-end timing',input,kb,runs},null,2));
}finally{clearTimeout(timer);child.kill();}
