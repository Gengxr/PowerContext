"""导出已在 Dify 实际操作的档案；需另外保存 Dify UI 追踪，不能单靠本脚本证明端到端运行。"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--passport",required=True)
parser.add_argument("--url",default="http://127.0.0.1:8038")
parser.add_argument("--out",default="evidence/dify_seekdb_evidence.json")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
settings = dict(line.split("=",1) for line in (root/"private/runtime.env").read_text().splitlines())
with httpx.Client(base_url=args.url,headers={"Authorization":"Bearer "+settings["LF_API_TOKEN"]},timeout=30) as client:
    reply = client.get(f"/v1/evidence/{args.passport}/ticket")
    reply.raise_for_status()
    record = reply.json()
assert record["state"]["timeline"]==1 and record["state"]["coins"]==1
assert record["state"]["finished"] and record["state"]["ending"]["kind"]=="returned"
assert len(record["events"])==5
report = {"verified_at":datetime.now(timezone.utc).isoformat(),"passport":args.passport,
          "expected_commands":["开门","查验2","改写","查验2","归还A"],"database_evidence":record}
out = Path(args.out)
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"passed":True,"event_count":len(record["events"]),"database":record["database"]},ensure_ascii=False))
