import path from 'node:path';
import {writeFile,mkdir} from 'node:fs/promises';
process.env.SEEKDB_BINDINGS_CACHE_DIR = path.resolve('.cache/bindings');
const { SeekdbClient } = await import('seekdb');
const db = new SeekdbClient({ path: path.resolve('.data/seekdb'), database: 'test' });
const evidence={startedAt:new Date().toISOString()};
try {
  evidence.version=await db.execute('SELECT VERSION() AS version');
  const c = await db.getOrCreateCollection({name: 'binding_probe', configuration: {dimension: 3, distance: 'cosine'}, embeddingFunction: null});
  await c.upsert({ids:['a','b'], documents:['浏览器本地向量检索 seekdb','苹果水果'], embeddings:[[1,0,0],[0,1,0]], metadatas:[{source:'probe'},{source:'probe'}]});
  await db.execute('CALL dbms_index_manager.refresh()');
  evidence.hybrid=await c.hybridSearch({query:{whereDocument:{$contains:'浏览器'}},knn:{queryEmbeddings:[[1,0,0]],nResults:2},rank:{rrf:{rankConstant:60}},nResults:2});
} catch(e) { evidence.error=e.message;process.exitCode=1; }
await db.close();
await mkdir('test-results',{recursive:true});
await writeFile('test-results/db-probe.json',JSON.stringify(evidence,null,2));
// Windows native library changes stdout descriptors and keeps native threads alive. Evidence goes to a file.
process.send?.({exitCode:process.exitCode||0});
