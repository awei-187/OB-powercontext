import { pipeline, env } from '@huggingface/transformers';
env.allowRemoteModels=false;
env.allowLocalModels=true;
env.localModelPath='/models/';
env.useBrowserCache=true;
env.backends.onnx.wasm.wasmPaths='/runtime/';
env.backends.onnx.wasm.numThreads=2;
env.backends.onnx.wasm.proxy=false;
let extractor, state, spec;
const emit = value => postMessage({event:'status',value});
function check(output) {
  const vectors=output.tolist();
  if (!vectors.length || vectors.some(v=>v.length!==512 || v.some(x=>!Number.isFinite(x)))) throw Error('Invalid model output');
  return vectors;
}
async function make(device,dtype) {
  const t=performance.now();
  extractor=await pipeline('feature-extraction',spec.repo,{device,dtype,local_files_only:true,
    progress_callback:p=>emit({phase:'loading',backend:device,dtype,file:p.file,progress:p.progress,status:p.status})});
  const sessionLoadMs=performance.now()-t;
  const warm=performance.now();
  check(await extractor(['浏览器本地模型预热'],{pooling:'cls',normalize:true,truncation:true,max_length:256}));
  let adapter=null;
  if(device==='webgpu') {
    // This is ORT's actual inference device after a real model run, not a separate capability probe.
    const gpuDevice=await env.backends.onnx.webgpu.device;
    await gpuDevice.queue.onSubmittedWorkDone();
    const info=gpuDevice.adapterInfo ?? env.backends.onnx.webgpu.adapter?.info;
    adapter=info?{vendor:info.vendor,architecture:info.architecture,device:info.device,description:info.description}: {description:'Runtime did not expose adapter details'};
  }
  return {backend:device,dtype,adapter,sessionLoadMs,warmupMs:performance.now()-warm};
}
async function load(p) {
  const started=performance.now(); spec=p.spec;
  let actual, fallbackReason=null;
  if(p.backend!=='wasm') {
    try {
      if(!navigator.gpu) throw Error('WebGPU API unavailable');
      const adapter=await navigator.gpu.requestAdapter({powerPreference:'high-performance'});
      if(!adapter) throw Error('No WebGPU adapter');
      if(p.dtype==='fp16' && !adapter.features.has('shader-f16')) throw Error('shader-f16 unavailable');
      env.backends.onnx.webgpu.adapter=adapter;
      actual=await make('webgpu',p.dtype);
    } catch(e) {
      fallbackReason=String(e.message || e); emit({phase:'fallback',reason:fallbackReason});
      if(extractor) { await extractor.dispose().catch(()=>{}); extractor=null; }
    }
  } else fallbackReason='用户选择 WASM / 固定降级验证';
  if(!actual) actual=await make('wasm',p.dtype==='fp16'?'fp32':p.dtype);
  state={phase:'ready',...actual,requestedDtype:p.dtype,fallbackReason,readyMs:performance.now()-started,
    runtime:'Transformers.js 3.8.1 / ORT Web 1.22.0-dev.20250409-89f8206ba4',
    profile:{repo:spec.repo,revision:spec.revision,dtype:actual.dtype,dimension:512,pooling:'cls',normalize:true,maxTokens:256},
    resources:performance.getEntriesByType('resource').filter(x=>x.name.includes('/models/')).map(x=>({url:x.name,ms:x.duration,bytes:x.decodedBodySize,transferBytes:x.transferSize}))};
  emit(state); return state;
}
let queue=Promise.resolve();
self.onmessage=({data:{id,type,payload}})=>{
  queue=queue.then(async()=>{
    try {
      if(type==='load') return postMessage({id,result:await load(payload)});
      if(!extractor || !state) throw Error('模型尚未加载');
      if(type==='embed') {
        const t=performance.now();
        const texts=payload.texts.map(t=>payload.query?spec.queryPrefix+t:t);
        const vectors=check(await extractor(texts,{pooling:'cls',normalize:true,truncation:true,max_length:256}));
        postMessage({id,result:{vectors,ms:performance.now()-t,profile:state.profile}});
      }
    } catch(e) { postMessage({id,error:String(e.message || e)}); }
  });
};
