"""对真实 PowerContext Server 的接口冒烟验证（开发期使用，输出留证据）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.powercontext_client import PowerContextClient

ROOT = Path(__file__).resolve().parent.parent
c = PowerContextClient("http://127.0.0.1:18080", audit_path=ROOT / "runtime" / "smoke-audit.jsonl")

print("ready:", c.health_ready()["status"])

scope = c.create_scope(title="smoke-test-scope", summary="接口冒烟", idempotency_key="smoke-test-v1")
sid = scope["scope_id"]
print("scope:", sid)

again = c.create_scope(title="smoke-test-scope", summary="接口冒烟", idempotency_key="smoke-test-v1")
print("idempotent same scope:", again["scope_id"] == sid)

rec = c.remember(sid, "knowledge-point", json.dumps({"type": "knowledge-point", "title": "矩阵乘法"}, ensure_ascii=False), reason="smoke")
print("remember record:", json.dumps(rec, ensure_ascii=False)[:300])
aid = rec["artifact"]["artifact_id"]

items = c.list_all_atomic_memories(sid, kind="knowledge-point", states=["active"])
print("list count:", len(items))

rev, etag = c.get_artifact(sid, aid)
print("get revision:", rev["revision"], "etag:", etag)
new_rev = c.replace_atomic_memory(sid, aid, "knowledge-point",
                                  json.dumps({"type": "knowledge-point", "title": "矩阵乘法", "mastery": 2}, ensure_ascii=False),
                                  if_match=etag)
print("replace new revision:", new_rev["revision"])
state = c.get_atomic_state(sid, aid)
print("state after replace:", state["state"], "state_version:", state["state_version"])

src = c.capture_content_source(sid, "smoke-source-1", "复习证据：矩阵乘法 已掌握", metadata={"origin": "smoke"})
print("source status:", src.get("status"), "source:", json.dumps(src.get("source"), ensure_ascii=False)[:200])

sr = c.search_memory(sid, "矩阵乘法", limit=5)
print("search hits:", len(sr.get("hits", [])))

prep = c.prepare_context(sid, "矩阵乘法", max_bytes=2000)
print("prepare status:", prep.get("status"))

c.forget_atomic_memory(sid, state["artifact"], state["state_version"])
items2 = c.list_all_atomic_memories(sid, kind="knowledge-point", states=["active"])
print("after forget active count:", len(items2))

scopes = c.list_scopes(query="smoke-test", query_field="title")
print("scope query hits:", [s["title"] for s in scopes["items"]])
print("SMOKE OK")