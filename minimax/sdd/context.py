"""Task-scoped retrieval through real embedded seekdb; no external embeddings."""
import hashlib
import json
from pathlib import Path
import pyseekdb
from .state import state

def sha(data):
    return hashlib.sha256(data).hexdigest()

def read_manifest(source):
    return json.loads((source / "manifest.json").read_text(encoding="utf-8"))

def collection(runtime):
    # Linux native seekdb stores engineering documents, not SQLite.
    runtime.mkdir(parents=True, exist_ok=True)
    client = pyseekdb.Client(path=str((runtime / "seekdb").resolve()))
    return client, client.get_or_create_collection(
        "engineering", configuration=pyseekdb.HNSWConfiguration(dimension=2),
        embedding_function=None)

def ingest(source, runtime):
    manifest = read_manifest(source)
    records = []
    for entry in manifest["sources"]:
        path = (source / entry["path"]).resolve()
        if not path.is_relative_to(source.resolve()) or not path.is_file():
            raise ValueError("Source path must be an existing file inside sample root")
        content = path.read_text(encoding="utf-8")
        records.append({**entry, "content": content, "sha256": sha(content.encode()),
                        "task": manifest["task"]})
    client, docs = collection(runtime)
    # Delete obsolete task documents on every reimport, so stale specs cannot survive.
    docs.delete(where={"task": manifest["task"]})
    docs.upsert(ids=[manifest["task"] + ":" + r["id"] for r in records],
                documents=[r["content"] for r in records],
                embeddings=[[1.0, 0.0] for _ in records],
                metadatas=[{k:v for k,v in r.items() if k != "content"} for r in records])
    return {"operation":"seekdb.upsert", "task":manifest["task"],
            "sources":[{k:v for k,v in r.items() if k!="content"} for r in records]}

def context(source, runtime):
    manifest = read_manifest(source)
    client, docs = collection(runtime)
    query = {"where":{"task":manifest["task"]}, "include":["documents","metadatas"]}
    rows = docs.get(**query)
    records = []
    for key, text, meta in zip(rows["ids"], rows["documents"], rows["metadatas"]):
        path = (source / meta["path"]).resolve()
        if not path.is_relative_to(source.resolve()) or not path.is_file():
            raise ValueError("Missing source: " + meta["path"])
        if sha(path.read_text(encoding="utf-8").encode()) != meta["sha256"]:
            raise ValueError("Source changed; run ingest before context: " + meta["path"])
        records.append({**meta, "content":text, "database_id":key,
                        "locator":str(path), "lines":[1,len(text.splitlines())]})
    if {r["id"] for r in records} != {r["id"] for r in manifest["sources"]}:
        raise ValueError("Incomplete database context; run ingest")
    previous = state(runtime / "powercontext.sqlite", manifest["task"])
    return {"task":manifest["task"], "objective":manifest["objective"], "sources":records,
            "database_query":query, "previous":previous,
            "next_action": "review_previous_results" if previous["state"] else "implement_and_test"}
