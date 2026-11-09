"""单worker运行，保持嵌入seekdb实例的唯一生命周期。"""
from pathlib import Path
import os
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
for line in (root/"private/runtime.env").read_text(encoding="utf-8").splitlines():
    key, value = line.split("=", 1)
    os.environ.setdefault(key, value)
import uvicorn

if __name__ == "__main__":
    uvicorn.run("lost_found.app:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8038")),
                workers=1, log_level="info")
