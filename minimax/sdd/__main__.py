import argparse
import json
from pathlib import Path
from .context import ingest, context
from .state import state

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["ingest","context","save"])
    parser.add_argument("--source", type=Path, default=Path("sample"))
    parser.add_argument("--runtime", type=Path, default=Path.home()/".cache/minimax-sdd/manual")
    parser.add_argument("--state-file", type=Path)
    args = parser.parse_args()
    args.runtime.mkdir(parents=True, exist_ok=True)
    if args.command == "ingest":
        result = ingest(args.source, args.runtime)
    elif args.command == "context":
        result = context(args.source, args.runtime)
    else:
        if not args.state_file:
            parser.error("save requires --state-file")
        task = json.loads((args.source / "manifest.json").read_text())["task"]
        result = state(args.runtime / "powercontext.sqlite",task,json.loads(args.state_file.read_text()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
if __name__ == "__main__":
    main()
