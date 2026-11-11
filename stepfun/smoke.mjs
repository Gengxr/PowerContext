// Database transport smoke test ONLY. Synthetic vectors are not model evidence.
import fs from 'node:fs/promises';
const started=new Date().toISOString();
const api=async(p,body)=>{const r=await fetch('http://localhost:3070/api/'+p,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const x=await r.json();if(!r.ok)throw Error(x.error);return x;};
const v=Array(384).fill(0);v[0]=1;
const collection='kb_smoke_'+Date.now();
const inserted=await api('import',{collection,ids:['smoke'],documents:['seekdb database transport smoke test'],embeddings:[v]});
const found=await api('search',{collection,text:'seekdb',embedding:v});
if(!found.results.ids[0].includes('smoke'))throw Error('Fresh document not found');
await fs.mkdir('results',{recursive:true});
await fs.writeFile('results/validation.json',JSON.stringify({started,kind:'synthetic database transport only, NOT browser inference or performance evidence',node:process.version,collection,inserted,found},null,2));
console.log('PASS: seekdb-js upsert, refresh_index and database hybridSearch');
