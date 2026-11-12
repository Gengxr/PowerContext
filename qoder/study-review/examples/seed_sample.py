"""交付样例：学习者A（线性代数：矩阵乘法、特征值）与学习者B（数据库：索引）。

用法（先启动 PowerContext Server）：
    uv run python examples/seed_sample.py            # 相对当前时间生成（推荐演示）
    uv run python examples/seed_sample.py --fixed    # 绝对固定时间（可复现验收）
    uv run python examples/seed_sample.py --pc-url http://127.0.0.1:18080

时间线（--fixed）：
    T0 = 2026-11-08T09:00:00Z  创建学习者与知识点（全部立即到期）
    T1 = 2026-11-08T10:00:00Z  A 复习：特征值=需要加强(间隔1天)，矩阵乘法=已掌握(间隔4天)
    T2 = 2026-11-11T09:00:00Z  观察时刻：特征值逾期1天在待复习首位；矩阵乘法未到期

默认模式把 T0/T1 平移到 now-3天 / now-2天，任何日期运行行为一致。
脚本幂等：已存在的知识点/复习不会重复创建。重置见 examples/reset.py。
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import rules
from app.models import AppState, Preference
from app.powercontext_client import PowerContextClient
from app.store import StudyStore

T0_FIXED = rules.parse_dt("2026-11-08T09:00:00Z")
T1_FIXED = rules.parse_dt("2026-11-08T10:00:00Z")
T2_FIXED = rules.parse_dt("2026-11-11T09:00:00Z")


def run_seed(pc_url: str, fixed: bool, audit_path: Path) -> dict:
    now = rules.utcnow()
    t0 = T0_FIXED if fixed else now - timedelta(days=3)
    t1 = T1_FIXED if fixed else now - timedelta(days=2)
    observe_at = T2_FIXED if fixed else now

    holder = {"t": t0}
    client = PowerContextClient(pc_url, audit_path=audit_path)
    store = StudyStore(client, clock=lambda: holder["t"])

    app_scope = store.ensure_app_scope()
    learner_a = store.create_learner("学习者A")
    learner_b = store.create_learner("学习者B")

    def ensure_kp(scope_id: str, course: str, title: str, notes: str):
        for kp in store.list_kps(scope_id):
            if kp.title == title:
                return kp
        return store.add_kp(scope_id, course, title, notes, mastery=0)

    kp_matrix = ensure_kp(learner_a.scope_id, "线性代数", "矩阵乘法", "注意维度匹配与乘法规则。")
    kp_eigen = ensure_kp(learner_a.scope_id, "线性代数", "特征值", "特征方程 det(A-λI)=0 的求解。")
    kp_index = ensure_kp(learner_b.scope_id, "数据库", "索引", "B+ 树结构与最左前缀原则。")

    holder["t"] = t1
    records_a = store.list_records(learner_a.scope_id)
    if not any(r.kp_id == kp_eigen.kp_id for r in records_a):
        store.complete_review(learner_a.scope_id, kp_eigen.kp_id, "needs_work", "计算不熟练，需要加强")
    if not any(r.kp_id == kp_matrix.kp_id for r in records_a):
        store.complete_review(learner_a.scope_id, kp_matrix.kp_id, "mastered", "已能熟练计算")

    prefs = store.get_prefs(learner_a.scope_id) or Preference()
    prefs.daily_goal = 5
    store.set_prefs(learner_a.scope_id, prefs)
    store.set_app_state(app_scope, AppState(selected_learner_scope_id=learner_a.scope_id))

    overview_a = store.overview(learner_a.scope_id, now=observe_at)
    overview_b = store.overview(learner_b.scope_id, now=observe_at)
    return {
        "mode": "fixed" if fixed else "relative",
        "t0": rules.format_dt(t0), "t1": rules.format_dt(t1),
        "observe_at": rules.format_dt(observe_at),
        "learner_a": {"scope_id": learner_a.scope_id, "name": learner_a.name},
        "learner_b": {"scope_id": learner_b.scope_id, "name": learner_b.name},
        "a_due_titles": [d["kp"]["title"] for d in overview_a["due"]],
        "a_upcoming_titles": [u["kp"]["title"] for u in overview_a["upcoming"]],
        "a_prefs": overview_a["prefs"],
        "b_due_titles": [d["kp"]["title"] for d in overview_b["due"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pc-url", default="http://127.0.0.1:18080")
    parser.add_argument("--fixed", action="store_true")
    parser.add_argument("--audit", default=str(Path(__file__).resolve().parent.parent / "runtime" / "audit.jsonl"))
    args = parser.parse_args()
    result = run_seed(args.pc_url, args.fixed, Path(args.audit))
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())