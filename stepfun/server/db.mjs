import path from 'node:path';
import { appendFile, mkdir, readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import {lexicalQuery,variants,scoreFusionSql,defaultStrategy} from './retrieval.mjs';
process.env.SEEKDB_BINDINGS_CACHE_DIR ??= path.resolve('.cache/bindings');
const { SeekdbClient } = await import('seekdb');
export const spec = JSON.parse(await readFile('model-manifest.json'));
const resultDir=process.env.RESULT_DIR||'test-results';
export const db = new SeekdbClient(process.env.SEEKDB_HOST ? {
  host: process.env.SEEKDB_HOST, port: Number(process.env.SEEKDB_PORT || 2881),
  user: process.env.SEEKDB_USER || 'root', password: process.env.SEEKDB_PASSWORD || '',
  database: process.env.SEEKDB_DATABASE || 'test', queryTimeout: 60000,
} : { path: path.resolve(process.env.SEEKDB_PATH || '.data/seekdb'), database: 'test' });
export const mode = process.env.SEEKDB_HOST ? 'server' : 'Windows embedded native binding';
// A single SDK connection uses @search_parm. Serialize whole operations, including GET_SQL + execution.
let tail = Promise.resolve();
export function serial(fn) { const p = tail.then(fn); tail = p.catch(() => {}); return p; }
export async function ensureServerConnection() {
  if (mode !== 'server') return;
  let lastError;
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      await db.execute('SELECT 1');
      return;
    } catch (error) {
      lastError = error;
      // seekdb-js 1.4.0 retains a mysql2 connection after the Server restarts. Close only
      // the SDK connection, then reconnect with the same server configuration before any
      // read or mutation. Docker's host-port forwarding can trail the internal healthcheck,
      // so use bounded backoff for this read-only preflight; the business request runs once.
      await db.close().catch(() => {});
      if (attempt < 4) await new Promise(resolve => setTimeout(resolve, 250 * (attempt + 1)));
    }
  }
  throw lastError;
}
let initialized = false;
export async function init() {
  if (initialized) return;
  await mkdir('.data', { recursive: true });
  await db.execute(`CREATE TABLE IF NOT EXISTS stepfun_kbs (
    id VARCHAR(64) PRIMARY KEY, name VARCHAR(128), dtype VARCHAR(16), dirty INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)`);
  initialized = true;
}
export function profile(dtype) {
  if (!['fp32','fp16','q8'].includes(dtype)) throw Error('Invalid precision');
  return { repo: spec.repo, revision: spec.revision, dtype, dimension:512, pooling:'cls', normalize:true, maxTokens:256 };
}
export function validateProfile(p, dtype) {
  if (!p || !Object.entries(profile(dtype)).every(([key,value])=>p[key]===value)) throw Error('模型配置与知识库不一致，请加载对应精度');
}
export async function kb(id) {
  if (!/^kb_[a-f0-9]{32}$/.test(id || '')) throw Error('Invalid knowledge base');
  const rows = await db.execute('SELECT * FROM stepfun_kbs WHERE id = ?', [id]);
  if (!rows?.length) throw Error('Knowledge base not found');
  return rows[0];
}
export async function collection(id) { return db.getCollection({ name:id, embeddingFunction:null }); }
export async function list() {
  const rows = await db.execute('SELECT * FROM stepfun_kbs ORDER BY created_at, id');
  for (const r of rows) {const c=await collection(r.id);r.count=Number(await c.count());r.retrieval=defaultStrategy(c);}
  return rows;
}
export async function create(name, dtype,retrieval='quality-v2') {
  profile(dtype);
  if(!['baseline-v1','quality-v2'].includes(retrieval))throw Error('Unknown index preset');
  if (typeof name !== 'string' || !name.trim() || name.length > 100) throw Error('请输入 1–100 字的知识库名称');
  const id = 'kb_' + randomUUID().replaceAll('-', '');
  await db.createCollection({name:id, configuration:{hnsw:{dimension:512,distance:'cosine'},fulltextConfig:{analyzer:'ik',properties:{ik_mode:retrieval==='baseline-v1'?'smart':'max_word'}}},embeddingFunction:null});
  await db.execute('INSERT INTO stepfun_kbs (id,name,dtype) VALUES (?,?,?)', [id,name.trim(),dtype]);
  return {id,name:name.trim(),dtype,dirty:0,count:0,retrieval};
}
export function vector(v) {
  if (!Array.isArray(v) || v.length !== 512 || !v.every(x => typeof x === 'number' && Number.isFinite(x))) throw Error('必须提供浏览器生成的 512 维有限向量');
  const norm = Math.sqrt(v.reduce((s,x) => s+x*x, 0));
  if (Math.abs(norm - 1) > 0.02) throw Error('Vector must be L2 normalized');
  return v;
}
export async function ingest(id, payload) {
  const k = await kb(id); validateProfile(payload.profile, k.dtype);
  const docs = payload.documents;
  if (!Array.isArray(docs) || !docs.length || docs.length > 32) throw Error('批次需为 1–32 段');
  for (const d of docs) {
    if (typeof d.id !== 'string' || !/^[a-zA-Z0-9_-]{1,128}$/.test(d.id) || typeof d.text !== 'string' || !d.text.trim() || d.text.length > 2000) throw Error('Invalid document');
    if (typeof d.source !== 'string' || d.source.length > 200) throw Error('Invalid source');
    vector(d.embedding);
  }
  await db.execute('UPDATE stepfun_kbs SET dirty=1 WHERE id=?',[id]);
  const t = performance.now();
  await (await collection(id)).upsert({ids:docs.map(d=>d.id), documents:docs.map(d=>d.text), embeddings:docs.map(d=>d.embedding),
    metadatas:docs.map(d=>({source:d.source,chunk:d.chunk ?? 0,model:spec.repo,revision:spec.revision,dtype:k.dtype}))});
  return {count:Number(await (await collection(id)).count()),writeMs:performance.now()-t,dirty:1};
}
export async function refresh(id) {
  await kb(id);
  const t=performance.now();
  // Direct call is intentional: SDK refresh_index silently skips unknown versions.
  await db.execute('CALL dbms_index_manager.refresh()');
  await db.execute('UPDATE stepfun_kbs SET dirty=0 WHERE id=?',[id]);
  return {refreshMs:performance.now()-t,dirty:0};
}
export async function search(id, p) {
  const k=await kb(id); validateProfile(p.profile,k.dtype); vector(p.embedding);
  if (Number(k.dirty)) throw Error('知识库有待刷新写入，请先刷新索引');
  if (typeof p.query !== 'string' || !p.query.trim() || p.query.length > 300) throw Error('请输入 1–300 字查询');
  const topK = Math.trunc(Math.max(1,Math.min(20,Number(p.topK)||5)));
  const c=await collection(id);
  const strategy=p.strategy || defaultStrategy(c);
  if(!Object.hasOwn(variants,strategy))throw Error('Unknown retrieval strategy');
  const config=variants[strategy];
  const lexical=config.clean?lexicalQuery(p.query):p.query;
  const internal=db._delegate._internal,originalExecute=internal.execute,trace=[];
  internal.execute=async function(sql,params) {
    const result=await originalExecute.call(this,sql,params);
    trace.push({sql,params,generatedSql:sql.includes('DBMS_HYBRID_SEARCH.GET_SQL')?result?.[0]?.query_sql:undefined});
    return result;
  };
  const t=performance.now();
  let results;
  try {
    if(config.denseWeight!==undefined){
      const sql=scoreFusionSql('`c$v2$'+c.collectionId+'`',config),params=[JSON.stringify(p.embedding),lexical,lexical,topK];
      let rows;
      if(mode==='server'){
        // seekdb-js 1.4.0 Connection.execute treats only SELECT/SHOW/DESC prefixes as row queries.
        // quality-v2 intentionally starts with WITH, so use the SDK-owned mysql2 connection and
        // keep the exact parameterized CTE inside seekdb rather than rewriting or client-fusing it.
        await internal.execute('SELECT 1');
        [rows]=await internal.connectionManager.getRawConnection().query(sql,params);
        trace.push({sql,params,transport:'seekdb-js 1.4.0 server raw query for WITH row result'});
      }else rows=await db.execute(sql,params);
      results={ids:[rows.map(r=>r._id.toString())],documents:[rows.map(r=>r.document)],metadatas:[rows.map(r=>typeof r.metadata==='string'?JSON.parse(r.metadata):r.metadata)],distances:[rows.map(r=>Number(r._score))]};
    }else results=await c.hybridSearch({query:{whereDocument:{$contains:lexical}},
    knn:{queryEmbeddings:[p.embedding],nResults:Math.max(config.candidates,topK)},
    rank:{rrf:{rankWindowSize:60,rankConstant:config.rankConstant}},nResults:topK,include:['documents','metadatas']});
  } finally {internal.execute=originalExecute;}
  const searchMs=performance.now()-t;
  await mkdir(resultDir,{recursive:true});
  await appendFile(path.join(resultDir,'hybrid-sql.jsonl'),JSON.stringify({at:new Date().toISOString(),kb:id,query:p.query,strategy,lexicalQuery:lexical,trace})+'\n');
  return {results,searchMs,strategy,lexicalQuery:lexical,engine:config.denseWeight!==undefined?'seekdb SQL: vector + fulltext → normalized score fusion':'seekdb DBMS_HYBRID_SEARCH.GET_SQL → database RRF SQL'};
}
// Read-only diagnostics for the local verification script; not exposed as an HTTP endpoint.
export async function inspect(id) {
  const k=await kb(id),c=await collection(id);
  return {kb:k,count:Number(await c.count()),stored:await c.get({ids:['index-0','incremental-mars'],include:['documents','metadatas','embeddings']}),
    schema:await db.execute('SHOW CREATE TABLE `c$v2$'+c.collectionId+'`')};
}
// Offline diagnostic command (IPC only): compare the actual database retrieval channels.
export async function diagnose(id,p) {
  const k=await kb(id);validateProfile(p.profile,k.dtype);vector(p.embedding);
  const c=await collection(id),table='`c$v2$'+c.collectionId+'`';
  const options={queryEmbeddings:[p.embedding],distance:'cosine',include:['documents','distances']};
  const exact=await c.query({...options,nResults:100,approximate:false});
  const approximate=await c.query({...options,nResults:20,approximate:true});
  const fts=await db.execute(`SELECT _id,document,MATCH(document) AGAINST (? IN NATURAL LANGUAGE MODE) AS score FROM ${table}
    WHERE MATCH(document) AGAINST (? IN NATURAL LANGUAGE MODE) ORDER BY score DESC,_id LIMIT 100`,[p.query,p.query]);
  const hybrid=await search(id,p);
  return {count:Number(await c.count()),exact,approximate,fts:fts.map(r=>({...r,_id:r._id.toString()})),hybrid};
}
// IPC experiment helper: copy already browser-computed vectors unchanged, varying only the FTS analyzer.
export async function cloneWithAnalyzer(id,analyzer,name) {
  if(!['ik-max-word','ngram'].includes(analyzer))throw Error('Unsupported experimental analyzer');
  const original=await kb(id),source=await collection(id),count=Number(await source.count());
  if(Number(original.dirty))throw Error('请先完成原知识库索引刷新');
  const target='kb_'+randomUUID().replaceAll('-',''),fulltextConfig=analyzer==='ngram'?{analyzer:'ngram',properties:{ngram_token_size:2}}:{analyzer:'ik',properties:{ik_mode:'max_word'}};
  const c=await db.createCollection({name:target,configuration:{hnsw:{dimension:512,distance:'cosine'},fulltextConfig},embeddingFunction:null});
  try {
    for(let offset=0;offset<count;offset+=100){
      const all=await source.get({limit:100,offset,include:['documents','metadatas','embeddings']});
      for(let i=0;i<all.ids.length;i+=20)await c.upsert({ids:all.ids.slice(i,i+20),documents:all.documents.slice(i,i+20),metadatas:all.metadatas.slice(i,i+20),embeddings:all.embeddings.slice(i,i+20)});
    }
    if(Number(await c.count())!==count)throw Error('索引副本条数校验失败');
    await db.execute('CALL dbms_index_manager.refresh()');
    const displayName=name||'检索诊断-'+analyzer;
    // Publish only a complete, refreshed copy. A failed copy never appears as an available KB.
    await db.execute('INSERT INTO stepfun_kbs (id,name,dtype,dirty) VALUES (?,?,?,0)',[target,displayName,original.dtype]);
    return {id:target,name:displayName,dtype:original.dtype,dirty:0,analyzer,count,retrieval:defaultStrategy(c),originalId:id};
  }catch(e){await db.deleteCollection(target).catch(()=>{});throw e;}
}
export async function optimize(id) {
  const original=await kb(id);
  return cloneWithAnalyzer(id,'ik-max-word',original.name.slice(0,90)+'（优化索引）');
}
export async function verifyEquivalent(a,b) {
  const ca=await collection(a),cb=await collection(b),count=Number(await ca.count());
  if(Number(await cb.count())!==count)throw Error('Document counts differ');
  for(let offset=0;offset<count;offset+=100){
    const rows=await ca.get({limit:100,offset,include:['documents','metadatas','embeddings']});
    const other=await cb.get({ids:rows.ids,include:['documents','metadatas','embeddings']});
    const lookup=new Map(other.ids.map((id,i)=>[id,i]));
    for(let i=0;i<rows.ids.length;i++){
      const j=lookup.get(rows.ids[i]);
      if(j===undefined || rows.documents[i]!==other.documents[j] || JSON.stringify(rows.metadatas[i])!==JSON.stringify(other.metadatas[j]) || JSON.stringify(rows.embeddings[i])!==JSON.stringify(other.embeddings[j]))throw Error('Stored document/vector changed');
    }
  }
  return {count,identicalIds:true,identicalText:true,identicalMetadata:true,identicalVectors:true};
}
// Offline numerical audit only; this compares stored browser outputs, it does not create embeddings.
export async function auditVectorDrift(a,b) {
  const ca=await collection(a),cb=await collection(b),x=await ca.get({limit:1000,include:['documents','metadatas','embeddings']}),y=await cb.get({limit:1000,include:['documents','metadatas','embeddings']});
  const lookup=new Map(y.ids.map((id,i)=>[id,i]));let changed=0,max=0,minCosine=1;
  for(let i=0;i<x.ids.length;i++){
    const j=lookup.get(x.ids[i]);if(j===undefined||x.documents[i]!==y.documents[j])throw Error('Different corpus');
    const v=x.embeddings[i],w=y.embeddings[j];let dot=0,nv=0,nw=0;
    for(let k=0;k<v.length;k++){const d=Math.abs(v[k]-w[k]);if(d!==0)changed++;max=Math.max(max,d);dot+=v[k]*w[k];nv+=v[k]*v[k];nw+=w[k]*w[k];}
    minCosine=Math.min(minCosine,dot/Math.sqrt(nv*nw));
  }
  return {documents:x.ids.length,changedComponents:changed,maxAbsoluteDifference:max,minCosine};
}
export async function auditDivisionPrecision() {
  return db.execute('SELECT @@div_precision_increment AS division_digits,1/61 AS rrf_rank1,1/80 AS rrf_rank20');
}
