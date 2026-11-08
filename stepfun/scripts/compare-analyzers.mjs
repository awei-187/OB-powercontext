import {fork} from 'node:child_process';import {readFile,writeFile} from 'node:fs/promises';import {quality} from '../src/core.mjs';
const saved=JSON.parse(await readFile('test-results/retrieval-quality/baseline-v1/test-results/benchmark.json')),kb=saved.runs.find(r=>r.config.dtype==='fp16').kb.id;
const vectors=JSON.parse(await readFile('test-results/retrieval-quality/query-vectors.json')),f=JSON.parse(await readFile('data/fixture.json'));
const child=fork(new URL('../server/db-worker.mjs',import.meta.url),[],{stdio:['ignore','ignore','ignore','ipc'],windowsHide:true});
let seq=0;const pending=new Map();child.on('message',m=>{const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error)):p.resolve(m.result);});
const call=(type,...args)=>new Promise((resolve,reject)=>{pending.set(++seq,{resolve,reject});child.send({id:seq,type,args});});
const timer=setTimeout(()=>{child.kill();process.exitCode=1;},120000),runs=[];
try{
  const collections=[{id:kb,analyzer:'ik-smart'}];
  for(const analyzer of ['ik-max-word','ngram'])collections.push(await call('cloneWithAnalyzer',kb,analyzer));
  for(const c of collections)for(const strategy of ['baseline-v1','score-75','clean-score-75']){
    const run={...c,strategy,queries:[]};runs.push(run);
    for(const q of f.queries){const v=vectors.queries.find(v=>v.id===q.id);const r=await call('search',c.id,{query:q.text,profile:v.profile,embedding:v.vectors[0],topK:5,strategy});
      run.queries.push({id:q.id,text:q.text,ids:r.results.ids[0],lexicalQuery:r.lexicalQuery,searchMs:r.searchMs,...quality(r.results.ids[0],q.relevance)});
    }
    run.summary={recall:run.queries.reduce((s,q)=>s+q.recall,0)/12,ndcg:run.queries.reduce((s,q)=>s+q.ndcg,0)/12};console.log(c.analyzer,strategy,run.summary);
  }
  await writeFile('test-results/retrieval-quality/analyzers.json',JSON.stringify({note:'Document text, IDs, metadata and browser-generated vectors copied unchanged into separate experimental collections',collections,runs},null,2));
} finally {clearTimeout(timer);child.kill();}
