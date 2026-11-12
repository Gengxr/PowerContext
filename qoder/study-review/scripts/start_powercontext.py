"""启动真实 PowerContext Server（SQLite 持久化，基本记忆模式，无需模型 API）。

用法：
    uv run python scripts/start_powercontext.py [--port 18080] [--runtime-dir runtime]

脚本会在 runtime/ 下生成 pc.env（绝对路径 SQLite URL），然后调用官方
`powercontext server run --env-file runtime/pc.env`。数据只写入本项目
runtime/ 目录，不影响用户默认的 PowerContext 安装。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_env(runtime_dir: Path, port: int) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    db_path = (runtime_dir / "powercontext.db").resolve()
    sqlite_url = "sqlite+aiosqlite:///" + str(db_path).replace("\\", "/")
    env_file = runtime_dir / "pc.env"
    env_file.write_text(
        "\n".join([
            "# 由 scripts/start_powercontext.py 生成（学习回顾台专用，勿提交）",
            "POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1",
            f"POWERCONTEXT_SERVER_HTTP_PORT={port}",
            "POWERCONTEXT_SERVER_DATABASE_KIND=sqlite",
            f"POWERCONTEXT_SERVER_DATABASE_URL={sqlite_url}",
            "POWERCONTEXT_SERVER_ACCESS_MODE=disabled",
            "POWERCONTEXT_SERVER_DASHBOARD_ENABLED=false",
            "POWERCONTEXT_SERVER_LOGGING_LEVEL=INFO",
            "",
        ]),
        encoding="utf-8",
    )
    return env_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("STUDY_REVIEW_PC_PORT", "18080")))
    parser.add_argument("--runtime-dir", default=str(PROJECT_ROOT / "runtime"))
    args = parser.parse_args()

    runtime_dir = Path(args.runtime_dir).resolve()
    env_file = build_env(runtime_dir, args.port)
    scripts_dir = Path(sys.executable).parent
    exe = scripts_dir / ("powercontext.exe" if os.name == "nt" else "powercontext")
    if not exe.exists():
        print("未找到 powercontext CLI，请先 uv sync（依赖 powercontext[cli,server]==1.5.1）", file=sys.stderr)
        return 2
    print(f"[study-review] PowerContext Server: http://127.0.0.1:{args.port}  数据: {runtime_dir}", flush=True)
    proc = subprocess.run([str(exe), "server", "run", "--env-file", str(env_file)])
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())