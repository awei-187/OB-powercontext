import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import {call,close} from './db-service.mjs';
const spec=JSON.parse(await readFile('model-manifest.json'));
const port=Number(process.env.PORT || 4317), root=path.resolve('public');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript','.mjs':'text/javascript','.css':'text/css','.json':'application/json','.wasm':'application/wasm','.onnx':'application/octet-stream','.txt':'text/plain; charset=utf-8'};
function json(res,status,data) { res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'}); res.end(JSON.stringify(data)); }
async function body(req) {
  if (!req.headers['content-type']?.startsWith('application/json')) throw Error('JSON required');
  const chunks=[]; let size=0;
  for await (const chunk of req) { size+=chunk.length; if(size>2*1024*1024) throw Error('请求超过 2 MiB'); chunks.push(chunk); }
  return JSON.parse(Buffer.concat(chunks).toString());
}
const server=http.createServer(async(req,res)=>{
  res.setHeader('Cross-Origin-Opener-Policy','same-origin'); res.setHeader('Cross-Origin-Embedder-Policy','require-corp');
  res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'");
  try {
    if (req.headers.host !== `127.0.0.1:${port}` && req.headers.host !== `localhost:${port}`) return json(res,403,{error:'Local host required'});
    if(req.method==='POST' && req.headers.origin && ![`http://127.0.0.1:${port}`,`http://localhost:${port}`].includes(req.headers.origin)) return json(res,403,{error:'Origin rejected'});
    const url=new URL(req.url,`http://127.0.0.1:${port}`), p=url.pathname;
    if(p.startsWith('/api/')) {
      if(p==='/api/model' && req.method==='GET') return json(res,200,spec);
      if(p==='/api/fixture' && req.method==='GET') return json(res,200,JSON.parse(await readFile('data/fixture.json')));
      const data=req.method==='POST'?await body(req):{};
      const result=await (async()=>{
        if(p==='/api/health') return call('health');
        if(p==='/api/kbs' && req.method==='GET') return call('list');
        if(p==='/api/kbs' && req.method==='POST') return call('create',data.name,data.dtype,data.retrieval??'quality-v2');
        const m=p.match(/^\/api\/kbs\/(kb_[a-f0-9]{32})\/(ingest|refresh|search|optimize)$/);
        if(m && req.method==='POST') return call(m[2],m[1],data);
        throw Error('Unknown endpoint');
      })();
      return json(res,200,result);
    }
    if(req.method!=='GET') return json(res,405,{error:'Method not allowed'});
    const file=path.resolve(root,'.'+decodeURIComponent(p==='/'?'/index.html':p));
    if(!file.startsWith(root+path.sep)) return json(res,403,{error:'Forbidden'});
    const s=await stat(file); if(!s.isFile()) throw Error('Not found');
    const content=await readFile(file);
    res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream','Content-Length':s.size,
      'Cache-Control':p.startsWith('/models/')||p.startsWith('/runtime/')?'public, max-age=31536000, immutable':'no-cache'});
    res.end(content);
  } catch(e) { console.error(e.message); json(res,req.url.startsWith('/api/')?400:404,{error:e.message}); }
});
server.listen(port,'127.0.0.1',()=>console.log(`StepFun http://127.0.0.1:${port}`));
for (const sig of ['SIGTERM','SIGINT']) process.on(sig,()=>{close();server.close(()=>process.exit());});
