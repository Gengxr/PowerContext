"""固定时间端到端验收脚本（真实 PowerContext，独立学习者，可重复运行）。

在固定时间 T0/T1/T2 下验证：
1. 待复习列表符合公开排序与到期规则（A：特征值逾期在首位，矩阵乘法未到期）；
2. 学习者隔离（B 只见索引，看不到 A 的任何数据）；
3. 偏好持久化（A daily_goal=5）；
4. 新 StudyStore/客户端实例（模拟重启读取）恢复全部状态。

结果写入 evidence/sample-verification.json，并在 stdout 打印 PASS/FAIL。
跨进程重启验证由 tests/test_restart.py 覆盖（真实子进程）。
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import rules
from app.models import AppState, Preference
from app.powercontext_client import PowerContextClient
from app.store import StudyStore

T0 = rules.parse_dt("2026-11-08T09:00:00Z")
T1 = rules.parse_dt("2026-11-08T10:00:00Z")
T2 = rules.parse_dt("2026-11-11T09:00:00Z")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pc-url", default="http://127.0.0.1:18080")
    parser.add_argument("--out", default=str(ROOT / "evidence" / "sample-verification.json"))
    args = parser.parse_args()

    run_id = uuid.uuid4().hex[:8]
    audit_path = ROOT / "runtime" / f"verify-audit-{run_id}.jsonl"
    holder = {"t": T0}
    client = PowerContextClient(args.pc_url, audit_path=audit_path)
    store = StudyStore(client, clock=lambda: holder["t"])
    checks: list[dict] = []

    def check(name: str, ok: bool, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + " :: " + json.dumps(detail, ensure_ascii=False))

    app_scope = store.ensure_app_scope()
    a = store.create_learner(f"验证A-{run_id}")
    b = store.create_learner(f"验证B-{run_id}")
    kp_matrix = store.add_kp(a.scope_id, "线性代数", "矩阵乘法", "维度匹配。", 0)
    kp_eigen = store.add_kp(a.scope_id, "线性代数", "特征值", "det(A-λI)=0。", 0)
    kp_index = store.add_kp(b.scope_id, "数据库", "索引", "B+ 树。", 0)

    holder["t"] = T1
    store.complete_review(a.scope_id, kp_eigen.kp_id, "needs_work", "需要加强")
    store.complete_review(a.scope_id, kp_matrix.kp_id, "mastered", "已掌握")
    store.set_prefs(a.scope_id, Preference(daily_goal=5))
    store.set_app_state(app_scope, AppState(selected_learner_scope_id=a.scope_id))

    # 观察时刻 T2：全新客户端 + Store（等价于重启后重新读取）
    client2 = PowerContextClient(args.pc_url, audit_path=audit_path)
    store2 = StudyStore(client2, clock=lambda: T2)
    ov_a = store2.overview(a.scope_id, now=T2)
    ov_b = store2.overview(b.scope_id, now=T2)

    a_due = [d["kp"]["title"] for d in ov_a["due"]]
    a_up = [u["kp"]["title"] for u in ov_a["upcoming"]]
    b_due = [d["kp"]["title"] for d in ov_b["due"]]
    check("A 待复习 == [特征值]", a_due == ["特征值"], a_due)
    check("A 即将到期 == [矩阵乘法]", a_up == ["矩阵乘法"], a_up)
    eigen_due = next(d for d in ov_a["due"] if d["kp"]["title"] == "特征值")
    check("特征值逾期 1 天", eigen_due["overdue_days"] == 1, eigen_due["overdue_days"])
    check("B 待复习 == [索引]", b_due == ["索引"], b_due)
    b_titles = [k["kp"]["title"] for k in ov_b["due"]] + [k["kp"]["title"] for k in ov_b["upcoming"]]
    check("B 看不到 A 的数据", "特征值" not in b_titles and "矩阵乘法" not in b_titles, b_titles)
    check("A 偏好 daily_goal=5 恢复", ov_a["prefs"]["daily_goal"] == 5, ov_a["prefs"])
    state = store2.get_app_state(app_scope)
    check("应用状态恢复选中 A", state.selected_learner_scope_id == a.scope_id, state.selected_learner_scope_id)
    recs = store2.list_records(a.scope_id)
    check("A 复习记录 2 条且含 Source 证据", len(recs) == 2 and all(r.source_id for r in recs),
          [{"result": r.result, "source_id": r.source_id} for r in recs])

    passed = all(c["ok"] for c in checks)
    report = {
        "run_id": run_id,
        "pc_url": args.pc_url,
        "fixed_times": {"T0": rules.format_dt(T0), "T1": rules.format_dt(T1), "T2": rules.format_dt(T2)},
        "checks": checks,
        "passed": passed,
        "audit_log": str(audit_path),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(("ALL PASS" if passed else "SOME FAILED") + f" -> {out}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())