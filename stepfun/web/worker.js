import {pipeline,env} from '@huggingface/transformers';
env.allowLocalModels=false;
export const MODEL='Xenova/all-MiniLM-L6-v2',REV='751bff37182d3f1213fa05d7196b954e230abad9';
let pipe,key,actual;
self.onmessage=async({data:d})=>{try{
const wanted=d.dtype+':'+d.forceWasm;
let loadMs=0,fallback='';
if(key!==wanted){if(pipe)await pipe.dispose();pipe=null;const t=performance.now();
let device='wasm';
if(!d.forceWasm&&self.navigator.gpu){const a=await navigator.gpu.requestAdapter();if(a&&(d.dtype!=='fp16'||a.features.has('shader-f16')))device='webgpu';}
const opts={revision:REV,dtype:d.dtype,device,progress_callback:p=>postMessage({progress:p})};
try{pipe=await pipeline('feature-extraction',MODEL,opts);}
catch(e){if(device==='wasm')throw e;fallback=e.message;device='wasm';pipe=await pipeline('feature-extraction',MODEL,{...opts,device});}
actual=device;key=wanted;loadMs=performance.now()-t;}
const t=performance.now();let vectors=[];
for(let i=0;i<d.texts.length;i+=d.batch){const x=await pipe(d.texts.slice(i,i+d.batch),{pooling:'mean',normalize:true});vectors.push(...x.tolist());postMessage({fraction:Math.min(i+d.batch,d.texts.length)/d.texts.length});}
postMessage({id:d.id,vectors,backend:actual,dtype:d.dtype,loadMs,embedMs:performance.now()-t,fallback});
}catch(e){postMessage({id:d.id,error:e.message});}};
