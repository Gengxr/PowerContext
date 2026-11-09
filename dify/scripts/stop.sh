#!/usr/bin/env bash
set -eu
task_app_dir="$(cd "$(dirname "$0")/.." && pwd)"
task_pid="$(cat "$task_app_dir/private/backend.pid")"
if ! kill -0 "$task_pid" 2>/dev/null; then
  echo "Backend is not running"
  exit 0
fi
task_actual_dir="$(readlink -f "/proc/$task_pid/cwd")"
task_actual_cmd="$(tr '\0' ' ' < "/proc/$task_pid/cmdline")"
if test "$task_actual_dir" != "$task_app_dir" || [[ "$task_actual_cmd" != *"scripts/serve.py"* ]]; then
  echo "PID ownership mismatch; refusing to signal"
  exit 1
fi
kill -TERM "$task_pid"
echo "Requested graceful shutdown of this backend only"
