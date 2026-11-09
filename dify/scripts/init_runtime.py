"""创建本机专用配置；真实凭据不进入Git、DSL导出或提交包。"""
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
private = root / "private"
private.mkdir(exist_ok=True)
env = private / "runtime.env"
if env.exists():
    print("Existing private/runtime.env retained")
else:
    token = secrets.token_urlsafe(32)
    data = Path.home()/".local/share/tomorrow-lost-found/seekdb"
    env.write_text(f"LF_API_TOKEN={token}\nLF_DATA_DIR={data}\n", encoding="utf-8")
    if os.name != "nt":
        env.chmod(0o600)
    print("Created private/runtime.env; token not displayed")
