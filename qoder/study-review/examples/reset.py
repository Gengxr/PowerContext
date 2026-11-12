"""安全重置学习回顾台数据。

软重置（默认）：通过真实 PowerContext API 将应用 Scope 与所有学习者 Scope
内的活跃 Memory 条目置为 forgotten。Scope 本身保留（空壳），不影响其他应用
的数据，也不触碰用户默认 PowerContext 安装。

硬重置（--hard）：删除本项目 runtime/ 目录（PowerContext SQLite 数据库、
pc.env、日志、审计）。要求 PowerContext Server 已停止；脚本会先探测健康端点，
若仍在运行则拒绝执行。只删除本项目 runtime/，不删除其他任何目录。

用法：
    uv run python examples/reset.py --yes          # 软重置
    uv run python examples/reset.py --hard --yes   # 硬重置（先停服务器）
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.powercontext_client import PowerContextClient, PowerContextError
from app.store import APP_SCOPE_TITLE, LEARNER_TITLE_PREFIX, StudyStore


def soft_reset(pc_url: str) -> int:
    client = PowerContextClient(pc_url)
    store = StudyStore(client)
    scopes = [s for s in store._all_scopes()
              if s["title"] == APP_SCOPE_TITLE or s["title"].startswith(LEARNER_TITLE_PREFIX)]
    total = 0
    for scope in scopes:
        records = client.list_all_atomic_memories(scope["scope_id"], states=["active"])
        for rec in records:
            client.forget_atomic_memory(scope["scope_id"], rec["artifact"], rec["state_version"])
            total += 1
        print(f"已清空 Scope {scope['title']}（{len(records)} 条）")
    print(f"软重置完成：共 forgotten {total} 条 Memory。")
    return 0


def hard_reset(pc_url: str) -> int:
    client = PowerContextClient(pc_url)
    try:
        client.health_live()
    except PowerContextError:
        pass
    else:
        print("PowerContext Server 仍在运行，硬重置已拒绝。请先停止服务器再执行。", file=sys.stderr)
        return 2
    runtime = ROOT / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
        print(f"已删除 {runtime}")
    else:
        print("runtime/ 不存在，无需删除。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pc-url", default="http://127.0.0.1:18080")
    parser.add_argument("--hard", action="store_true")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认")
    args = parser.parse_args()
    if not args.yes:
        answer = input("确认" + ("硬重置（删除 runtime/）" if args.hard else "软重置（清空应用数据）") + "？[y/N] ")
        if answer.strip().lower() != "y":
            print("已取消。")
            return 1
    return hard_reset(args.pc_url) if args.hard else soft_reset(args.pc_url)


if __name__ == "__main__":
    raise SystemExit(main())