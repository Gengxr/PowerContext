"""下载官方 cloudflared Linux amd64，并核验 GitHub release 提供的 SHA256。"""
import hashlib
from pathlib import Path
import platform
import urllib.request

VERSION = "2026.10.7"
SHA256 = "1f99fb518b83dec2ba8d870a7cc991d82a77e6196295a3d2754ba17ab9f91872"
URL = f"https://github.com/cloudflare/cloudflared/releases/download/{VERSION}/cloudflared-linux-amd64"
if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
    raise SystemExit("此脚本只支持 Linux x86_64；其他平台请按 Cloudflare 官方下载页安装。")
target = Path(__file__).resolve().parents[1]/"private/bin/cloudflared"
target.parent.mkdir(parents=True, exist_ok=True)
if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == SHA256:
    print("Verified existing official cloudflared "+VERSION)
else:
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit("SHA256不匹配，拒绝保存或运行。")
    target.write_bytes(data)
target.chmod(0o700)
print("cloudflared SHA256 verified")
