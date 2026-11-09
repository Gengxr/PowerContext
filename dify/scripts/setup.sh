#!/usr/bin/env bash
set -eu
task_app_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$task_app_dir"
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python >=3.11 required"'
if ! test -x venv/bin/python; then
  python3 -m venv venv || test -x venv/bin/python
fi
if ! venv/bin/python -m pip --version >/dev/null 2>&1; then
  mkdir -p private
  python3 -c 'import urllib.request; urllib.request.urlretrieve("https://bootstrap.pypa.io/pip/pip.pyz", "private/pip.pyz")'
  venv/bin/python private/pip.pyz install pip==25.1.1
fi
venv/bin/python -m pip install -r requirements.lock.txt
venv/bin/python scripts/init_runtime.py
venv/bin/python -m pytest -q
echo "Setup complete. Start with: bash scripts/start.sh"
