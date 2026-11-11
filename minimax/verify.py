"""Reproducible evidence runner. 'reference' is explicitly NOT MiniMax evidence."""
import argparse
import difflib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parent

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def command(args, log, env=None):
    result=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,timeout=180)
    record={"command":args,"exit_code":result.returncode,
            "stdout":result.stdout,"stderr":result.stderr,
            "time_utc":datetime.now(timezone.utc).isoformat()}
    write(log,record)
    return record

def module(cmd,source,runtime,log,extra=()):
    args=[sys.executable,"-m","sdd",cmd,"--source",str(source),"--runtime",str(runtime),*extra]
    record=command(args,log)
    if record["exit_code"]!=0:
        raise RuntimeError("Context subprocess failed; see "+str(log))
    # Some seekdb builds print lifecycle messages before/after the JSON.
    text=record["stdout"]
    decoder=json.JSONDecoder()
    for pos,char in enumerate(text):
        if char=="{":
            try:
                result,_=decoder.raw_decode(text[pos:])
                if isinstance(result,dict) and ("task" in result or "operation" in result):
                    return result
            except json.JSONDecodeError:
                pass
    raise RuntimeError("No context JSON in subprocess output")

def tests(source,code,suite,log):
    # Same exact tests for before/after; no credential environment in test subprocess.
    env={k:v for k,v in os.environ.items() if k in ("PATH","HOME","LANG","SYSTEMROOT")}
    env["TICKET_MODULE"]=str(code)
    env["PYTHONPATH"]=str(source/"tests")
    record=command([sys.executable,"-m","unittest","-v","test_tickets."+suite],log,env)
    record.update(code_sha256=digest(code),tests_sha256=digest(source/"tests/test_tickets.py"))
    write(log,record)
    return record

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=["reference","live","replay"],required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--record",type=Path,help="Saved real MiniMax generation.json for replay")
    args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(ROOT) or out.exists():
        raise ValueError("Choose a new output directory within minimax; existing evidence is never overwritten.")
    out.mkdir(parents=True)
    source=out/"input"
    shutil.copytree(ROOT/"sample",source)
    # The model context contains only manifest sources, never the reference solution.
    runtime=Path(os.environ.get("SDD_RUNTIME_ROOT", str(Path.home()/".cache/minimax-sdd")))/out.name
    if runtime.exists():
        raise ValueError("Runtime already exists; use a unique output name.")
    write(out/"environment.json",{"python":sys.version,"mode":args.mode,
          "packages":{p:importlib.metadata.version(p) for p in
                      ["powercontext","pyseekdb","pylibseekdb","SQLAlchemy","httpx"]},
          "powercontext_commit":"cc752d8accb0bc4ffade2d4b84ef6e48206e122d"})
    module("ingest",source,runtime,out/"01-ingest.json")
    ctx=module("context",source,runtime,out/"02-context.json")
    assert ctx["previous"]["state"] is None
    write(out/"context.json",ctx)
    target_before=tests(source,source/"before/tickets.py","TargetTests",out/"03-before-target.json")
    regression_before=tests(source,source/"before/tickets.py","RegressionTests",out/"04-before-regression.json")
    assert target_before["exit_code"]==1 and "FAILED (failures=" in target_before["stderr"]
    assert "ERROR:" not in target_before["stderr"] and regression_before["exit_code"]==0
    model_used=False
    if args.mode=="live":
        from sdd.minimax_agent import generate
        code,record=generate(ctx)
        record.update(time_utc=datetime.now(timezone.utc).isoformat(),
                      before_sha256=digest(source/"before/tickets.py"))
        write(out/"generation.json",record)
        model_used=True
    elif args.mode=="replay":
        if not args.record:
            raise ValueError("--record is required")
        record=json.loads(args.record.read_text())
        assert record["provider"]=="MiniMax" and record["before_sha256"]==digest(source/"before/tickets.py")
        code=json.loads(record["final_content"])["code"]
        write(out/"generation.json",record)
        model_used=True
    else:
        code=(source/"reference/tickets.py").read_text()
        write(out/"NOT_MINIMAX.json",{"status":"reference-only",
              "reason":"Human-authored reference validates infrastructure, not MiniMax participation."})
    after=out/"after/tickets.py"
    after.parent.mkdir()
    after.write_text(code,encoding="utf-8")
    before_text=(source/"before/tickets.py").read_text().splitlines(keepends=True)
    (out/"change.diff").write_text("".join(difflib.unified_diff(
        before_text,code.splitlines(keepends=True),fromfile="before/tickets.py",
        tofile="after/tickets.py")),encoding="utf-8")
    target_after=tests(source,after,"TargetTests",out/"05-after-target.json")
    regression_after=tests(source,after,"RegressionTests",out/"06-after-regression.json")
    assert target_after["exit_code"]==0 and regression_after["exit_code"]==0
    assert target_before["tests_sha256"]==target_after["tests_sha256"]==regression_after["tests_sha256"]
    progress={"completed":["ingest","context","code_change","target_tests","regression_tests"],
              "todo":["review spec v2"],"code_sha256":digest(after),
              "validation":{"target_exit":0,"regression_exit":0},
              "minimax_used":model_used}
    write(out/"progress.json",progress)
    saved=module("save",source,runtime,out/"07-save.json",
                 ["--state-file",str(out/"progress.json")])
    # A new OS process reopens both databases: no in-memory state is carried over.
    resumed=module("context",source,runtime,out/"08-resumed.json")
    assert resumed["previous"]["state"]==progress and resumed["next_action"]=="review_previous_results"
    assert resumed["previous"]["ref"]==saved["ref"]
    # Real specification update/reimport, with the exact same document identity.
    source_v2=out/"input-v2"
    shutil.copytree(source,source_v2)
    shutil.copyfile(source_v2/"specs/tickets-v2.md",source_v2/"specs/tickets.md")
    module("ingest",source_v2,runtime,out/"09-reimport.json")
    updated=module("context",source_v2,runtime,out/"10-updated-context.json")
    old_spec=next(r for r in ctx["sources"] if r["kind"]=="spec")
    new_spec=next(r for r in updated["sources"] if r["kind"]=="spec")
    assert old_spec["sha256"]!=new_spec["sha256"] and 'MUST be exactly' in new_spec["content"]
    assert updated["previous"]["state"]==progress
    write(out/"summary.json",{"mode":args.mode,"engineering_checks":"passed",
          "minimax_actual_participation":"recorded" if model_used else "BLOCKED_NO_API_KEY",
          "submission_ready":model_used,"after_sha256":digest(after),
          "fixed_tests_sha256":digest(source/"tests/test_tickets.py"),
          "note":"Reference mode is not a complete competition submission." if not model_used else
                 "Real API evidence/replay; judges independently verify provider record and code."})
    print(json.dumps({"output":str(out),"submission_ready":model_used},ensure_ascii=False))

if __name__=="__main__":
    main()
