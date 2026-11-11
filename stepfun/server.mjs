import express from 'express';
import {SeekdbClient} from 'seekdb';
import path from 'node:path';
import os from 'node:os';
const client=new SeekdbClient(process.env.SEEKDB_HOST?{host:process.env.SEEKDB_HOST,port:Number(process.env.SEEKDB_PORT||2881),user:process.env.SEEKDB_USER||'root',password:process.env.SEEKDB_PASSWORD||'',database:'test'}:{path:process.env.SEEKDB_PATH||path.join(os.homedir(),'.stepfun-seekdb'),database:'test'});
const app=express();app.use(express.json({limit:'12mb'}));
let queue=Promise.resolve();
const run=fn=>(req,res)=>{const work=queue.then(()=>fn(req));queue=work.catch(()=>{});work.then(x=>res.json(x)).catch(e=>res.status(400).json({error:e.message}));};
function name(s){if(!/^kb_[a-z0-9_]{1,60}$/.test(s))throw Error('Invalid collection');return s;}
function vectors(v){if(!Array.isArray(v)||!v.length||v.some(x=>!Array.isArray(x)||x.length!==384||x.some(n=>!Number.isFinite(n))))throw Error('Expected browser-generated 384-dimensional vectors');}
async function col(n){return client.getOrCreateCollection({name:name(n),configuration:{dimension:384,distance:'cosine'},embeddingFunction:null});}
app.get('/api/collections',run(async()=>({collections:(await client.listCollections()).map(x=>typeof x==='string'?x:x.name).filter(x=>x.startsWith('kb_'))})));
app.post('/api/import',run(async r=>{
const {collection,ids,documents,embeddings}=r.body;vectors(embeddings);
if(!Array.isArray(documents)||documents.length>500||ids?.length!==documents.length||embeddings.length!==documents.length||documents.some(d=>typeof d!=='string'||d.length>20000)||ids.some(d=>typeof d!=='string'))throw Error('Invalid import');
const c=await col(collection),t=performance.now();
await c.upsert({ids,documents,embeddings,metadatas:ids.map(id=>({source:id}))});
const written=performance.now();await c.refresh_index();
return {count:await c.count(),writeMs:written-t,refreshMs:performance.now()-written};
}));
app.post('/api/search',run(async r=>{
const {collection,text,embedding}=r.body;vectors([embedding]);
if(typeof text!=='string'||!text.trim()||text.length>2000)throw Error('Invalid query');
const c=await client.getCollection({name:name(collection),embeddingFunction:null}),t=performance.now();
const results=await c.hybridSearch({query:{whereDocument:{$contains:text},nResults:20},knn:{queryEmbeddings:[embedding],nResults:20},rank:{rrf:{}},nResults:5});
return {results,searchMs:performance.now()-t};
}));
app.use(express.static('dist'));app.listen(3070,'127.0.0.1',()=>console.log('http://localhost:3070'));
