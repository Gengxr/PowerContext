import {docs,queries} from './data.js';
const $=id=>document.getElementById(id),worker=new Worker(new URL('./worker.js',import.meta.url),{type:'module'});
let seq=0,pending=new Map(),logs=[],busy=false;
worker.onmessage=({data:d})=>{if(d.progress)$('status').textContent='模型加载：'+(d.progress.file||'')+' '+Math.round(d.progress.progress||0)+'%';if(d.fraction)$('progress').value=d.fraction;if(d.id){const p=pending.get(d.id);pending.delete(d.id);d.error?p.reject(Error(d.error)):p.resolve(d);}};
function embed(texts,dtype=$('dtype').value,forceWasm=$('wasm').checked,batch=8){return new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});worker.postMessage({id,texts,dtype,forceWasm,batch});});}
async function api(route,body){const r=await fetch('/api/'+route,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const x=await r.json();if(!r.ok)throw Error(x.error);return x;}
function collection(){const kb=$('kb').value;if(!/^[a-z0-9_]{1,35}$/.test(kb))throw Error('知识库名称限小写英文、数字、下划线');return 'kb_'+kb+'_'+$('dtype').value;}
async function refresh(){const x=await api('collections');$('saved').replaceChildren(new Option('选择已有知识库',''),...x.collections.map(n=>new Option(n,n)));}
$('saved').onchange=()=>{const n=$('saved').value;if(!n)return;const p=n.lastIndexOf('_');$('kb').value=n.slice(3,p);$('dtype').value=n.slice(p+1);$('results').replaceChildren();};
async function guard(fn){if(busy)return;busy=true;document.querySelectorAll('button,input,select').forEach(e=>e.disabled=true);try{await fn();}catch(e){$('status').textContent='操作失败：'+e.message;}finally{busy=false;document.querySelectorAll('button,input,select').forEach(e=>e.disabled=false);}}
function backend(x){$('backend').textContent='当前后端：'+x.backend.toUpperCase()+' / '+x.dtype+(x.fallback?'（WebGPU 失败后降级）':'');}
async function ingest(rows,c=collection(),dtype=$('dtype').value,wasm=$('wasm').checked,batch=8){const e=await embed(rows.map(r=>r[1]),dtype,wasm,batch);backend(e);const db=await api('import',{collection:c,ids:rows.map(r=>r[0]),documents:rows.map(r=>r[1]),embeddings:e.vectors});return {...e,vectors:undefined,...db,batch,collection:c};}
$('sample').onclick=()=>guard(async()=>{logs.push(await ingest(docs));await refresh();$('status').textContent='样例已写入并刷新索引。';});
$('import').onclick=()=>guard(async()=>{const rows=[];for(const f of $('files').files){const text=await f.text();for(let i=0;i<text.length;i+=800)rows.push([f.name+':'+i,text.slice(i,i+800)]);}if(!rows.length)throw Error('请选择非空文本文件');logs.push(await ingest(rows));await refresh();$('status').textContent='已导入 '+rows.length+' 个分块，索引刷新完成。';});
async function search(text,c,dtype,wasm){const t=performance.now(),e=await embed([text],dtype,wasm,1);backend(e);const db=await api('search',{collection:c,text,embedding:e.vectors[0]});return {...db,queryEmbedMs:e.embedMs,loadMs:e.loadMs,endToEndMs:performance.now()-t,backend:e.backend};}
$('search').onsubmit=e=>{e.preventDefault();guard(async()=>{const r=await search($('query').value,collection(),$('dtype').value,$('wasm').checked);$('results').replaceChildren();(r.results.documents?.[0]||[]).forEach((text,i)=>{const a=document.createElement('article');a.textContent=(i+1)+'. '+r.results.ids[0][i]+'\n'+text;$('results').append(a);});logs.push(r);$('metrics').textContent=JSON.stringify({...r,results:undefined},null,2);});};
$('bench').onclick=()=>guard(async()=>{
const report={time:new Date().toISOString(),browser:navigator.userAgent,hardwareConcurrency:navigator.hardwareConcurrency,model:'Xenova/all-MiniLM-L6-v2',revision:'751bff37182d3f1213fa05d7196b954e230abad9',corpus:docs,queries,runs:[],bytes:{}};
for(const [dtype,file] of [['fp32','model.onnx'],['q8','model_quantized.onnx'],['fp16','model_fp16.onnx']]){const r=await fetch('https://huggingface.co/'+report.model+'/resolve/'+report.revision+'/onnx/'+file);if(!r.ok)throw Error('模型体积测量失败');report.bytes[dtype]=(await r.arrayBuffer()).byteLength;}
const session=Date.now().toString(36);
for(const [dtype,wasm,batch] of [['fp32',true,1],['q8',true,1],['q8',true,8],['fp16',false,8]]){
const c='kb_bench_'+session+'_'+dtype+'_'+batch;
for(let repetition=0;repetition<3;repetition++){
const ingestion=await ingest(docs,c,dtype,wasm,batch);let hits=0,raw=[];
for(const [q,id] of queries){const result=await search(q,c,dtype,wasm);if(result.results.ids[0].includes(id))hits++;raw.push({query:q,expected:id,...result});}
report.runs.push({dtype,requestedBackend:wasm?'wasm':'webgpu',actualBackend:ingestion.backend,batch,repetition,ingestion,recallAt5:hits/queries.length,queries:raw});
$('metrics').textContent=JSON.stringify(report,null,2);}}
const median=a=>[...a].sort((a,b)=>a-b)[Math.floor(a.length/2)];
report.summary=Object.values(Object.groupBy(report.runs,r=>r.dtype+'_'+r.batch)).map(rs=>({dtype:rs[0].dtype,batch:rs[0].batch,backend:rs[0].actualBackend,bytes:report.bytes[rs[0].dtype],compression:report.bytes.fp32/report.bytes[rs[0].dtype],recallAt5:median(rs.map(r=>r.recallAt5)),warmDocumentsPerSecond:median(rs.slice(1).map(r=>1000*docs.length/r.ingestion.embedMs)),warmSearchMs:median(rs.slice(1).flatMap(r=>r.queries.map(q=>q.searchMs))),warmEndToEndMs:median(rs.slice(1).flatMap(r=>r.queries.map(q=>q.endToEndMs)))}));
logs.push(report);$('metrics').textContent=JSON.stringify(report.summary,null,2);$('status').textContent='实验结束。请导出原始日志；若实际后端是 WASM，不能当作 WebGPU 实测。';await refresh();
});
$('export').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(logs,null,2)],{type:'application/json'}));a.download='stepfun-results.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
refresh().catch(e=>$('status').textContent=e.message);
