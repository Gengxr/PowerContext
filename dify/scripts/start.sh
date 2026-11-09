#!/usr/bin/env bash
set -eu
task_app_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$task_app_dir"
if test -f private/backend.pid && kill -0 "$(cat private/backend.pid)" 2>/dev/null; then
  echo "Backend already running; inspect private/backend.pid"
  exit 1
fi
venv/bin/python scripts/init_runtime.py
task_cpu_set="$(venv/bin/python -c 'import os; print(",".join(map(str,sorted(os.sched_getaffinity(0))[:2])))')"
nohup taskset -c "$task_cpu_set" venv/bin/python scripts/serve.py > backend.log 2>&1 < /dev/null &
printf '%s\n' "$!" > private/backend.pid
echo "Started backend; inspect backend.log and /health"
