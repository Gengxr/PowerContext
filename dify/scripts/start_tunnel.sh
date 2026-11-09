#!/usr/bin/env bash
set -eu
task_app_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$task_app_dir"
if test -f private/tunnel.pid && kill -0 "$(cat private/tunnel.pid)" 2>/dev/null; then
  echo "Tunnel already running; inspect private/tunnel.pid"
  exit 1
fi
venv/bin/python scripts/install_tunnel.py
nohup private/bin/cloudflared tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8038 >private/tunnel.log 2>&1 </dev/null &
printf '%s\n' "$!" >private/tunnel.pid
echo "Started temporary HTTPS tunnel; URL appears in private/tunnel.log"
