"""在重启独立后端后，验证同一档案及事件从 seekdb 恢复。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8038")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
before = json.loads((root/"evidence/backend_verification.json").read_text(encoding="utf-8"))
settings = dict(line.split("=", 1) for line in (root/"private/runtime.env").read_text().splitlines())
pid = int((root/"private/backend.pid").read_text())
assert pid != before["backend_pid"], "必须先重启后端，不能把同进程查询当成重启恢复"
client = httpx.Client(base_url=args.url, headers={"Authorization":"Bearer "+settings["LF_API_TOKEN"]}, timeout=60)
passport = before["passport"]
reply = client.post("/v1/turn", json={"passport":passport,"case_id":"ticket",
    "request_id":uuid.uuid4().hex,"text":"状态"})
reply.raise_for_status()
after = client.get(f"/v1/evidence/{passport}/ticket")
after.raise_for_status()
record = after.json()
assert record == before["database_evidence"]
assert reply.json()["view"]["ending"]["kind"] == "returned"
report = {"verified_at":datetime.now(timezone.utc).isoformat(),"passed":True,
    "passport":passport,"before_pid":before["backend_pid"],"after_pid":pid,
    "state_and_events_identical":True,"event_count":len(record["events"]),
    "database":record["database"],"restored_output":reply.json(),
    "state_sha256":hashlib.sha256(json.dumps(record["state"],sort_keys=True).encode()).hexdigest()}
(root/"evidence/restart_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({key:report[key] for key in ("passed","before_pid","after_pid","event_count","database")},ensure_ascii=False))
