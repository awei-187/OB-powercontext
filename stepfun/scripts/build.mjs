import { build } from 'esbuild';
import { mkdir, copyFile, readdir } from 'node:fs/promises';
await mkdir('public/assets',{recursive:true}); await mkdir('public/runtime',{recursive:true});
for(const name of await readdir('node_modules/onnxruntime-web/dist')) if(/ort-wasm.*\.(wasm|mjs)$/.test(name)) await copyFile('node_modules/onnxruntime-web/dist/'+name,'public/runtime/'+name);
await build({entryPoints:['src/app.mjs','src/embed-worker.mjs'],outdir:'public/assets',bundle:true,format:'esm',platform:'browser',target:'chrome120',minify:false});
console.log('Built local browser assets; all inference runs in the browser worker.');
