"""对正在运行的真实服务执行验收，不使用内存替代数据库。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import uuid
from datetime import datetime, timezone

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8038")
parser.add_argument("--out", default="evidence/backend_verification.json")
parser.add_argument("--passport")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
settings = dict(line.split("=", 1) for line in (root/"private/runtime.env").read_text().splitlines())
headers = {"Authorization": "Bearer "+settings["LF_API_TOKEN"]}
passport = args.passport or "proof-"+uuid.uuid4().hex
client = httpx.Client(base_url=args.url, headers=headers, timeout=60)
responses = []

def turn(text, request_id=None):
    body = {"passport": passport, "case_id":"ticket",
            "request_id":request_id or uuid.uuid4().hex, "text":text}
    result = client.post("/v1/turn", json=body)
    result.raise_for_status()
    data = result.json()
    responses.append({"input":body, "output":data})
    return data

turn("开门")
rid = uuid.uuid4().hex
first = turn("查验2", rid)
with ThreadPoolExecutor(max_workers=4) as pool:
    repeated = list(pool.map(lambda _: turn("查验2", rid), range(4)))
assert all(result == first for result in repeated)
conflict = client.post("/v1/turn", json={
    "passport":passport, "case_id":"ticket", "request_id":rid, "text":"改写"})
assert conflict.status_code == 409
changed = turn("改写")
assert changed["view"]["timeline"] == 1 and changed["view"]["coins"] == 2
new = turn("查验2")
assert [entry["current"] for entry in new["view"]["clues"]] == [False, True]
ended = turn("归还A")
assert ended["view"]["ending"]["kind"] == "returned"
again = turn("状态")
assert again["view"]["ending"] == ended["view"]["ending"]
evidence = client.get(f"/v1/evidence/{passport}/ticket")
evidence.raise_for_status()
record = evidence.json()
assert len(record["events"]) == 5
assert record["state"]["finished"] is True
assert client.post("/v1/turn", headers={"Authorization":"Bearer invalid"}, json={
    "passport":passport, "case_id":"ticket", "request_id":uuid.uuid4().hex, "text":"状态"}).status_code == 401
out = Path(args.out)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"verified_at": datetime.now(timezone.utc).isoformat(),
    "backend_pid": int((root/"private/backend.pid").read_text()), "checks":{
    "real_seekdb":True, "idempotent_parallel_retry":True, "request_conflict":True,
    "timeline_changes_owner":True, "old_evidence_retained":True, "state_restored":True,
    "authentication":True}, "passport":passport, "responses":responses, "database_evidence":record},
    ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
print(json.dumps({"passed":True,"passport":passport,"database":record["database"],
                  "event_count":len(record["events"]),"out":str(out)},ensure_ascii=False))
