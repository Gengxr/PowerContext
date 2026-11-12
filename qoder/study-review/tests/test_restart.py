"""跨进程重启恢复测试：真实应用子进程被杀死后重启，状态从 PowerContext 恢复。

使用固定时钟（STUDY_REVIEW_FIXED_NOW=T2），断言与运行日期无关。
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path

import pytest

from app import rules
from app.models import AppState, Preference
from app.powercontext_client import PowerContextClient
from app.store import StudyStore

ROOT = Path(__file__).resolve().parent.parent
T0 = rules.parse_dt("2026-11-08T09:00:00Z")
T1 = rules.parse_dt("2026-11-08T10:00:00Z")
T2 = rules.parse_dt("2026-11-11T09:00:00Z")


def _get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _start_app(pc_url, port, tmp_path, fixed_now):
    env = dict(os.environ)
    env.update({
        "STUDY_REVIEW_PC_URL": pc_url,
        "STUDY_REVIEW_HOST": "127.0.0.1",
        "STUDY_REVIEW_PORT": str(port),
        "STUDY_REVIEW_AUDIT": str(tmp_path / "restart-audit.jsonl"),
        "STUDY_REVIEW_FIXED_NOW": fixed_now,
        "PYTHONIOENCODING": "utf-8",
    })
    log = (tmp_path / f"app-{port}.log").open("a", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "app"], stdout=log,
                            stderr=subprocess.STDOUT, env=env, cwd=str(ROOT))
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("应用进程提前退出: " + (tmp_path / f"app-{port}.log").read_text(encoding="utf-8", errors="replace")[-1500:])
        try:
            _get(url + "/api/health", timeout=3)
            return proc, url, log
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("应用未就绪")


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_cross_process_restart_recovery(pc_server, tmp_path, unique_name):
    # 1) 在测试进程内用固定时钟写入样例数据（真实 PowerContext）
    holder = {"t": T0}
    client = PowerContextClient(pc_server, audit_path=tmp_path / "seed-audit.jsonl")
    store = StudyStore(client, clock=lambda: holder["t"])
    app_scope = store.ensure_app_scope()
    a = store.create_learner("重启A" + unique_name)
    b = store.create_learner("重启B" + unique_name)
    m = store.add_kp(a.scope_id, "线性代数", "矩阵乘法", "", 0)
    e = store.add_kp(a.scope_id, "线性代数", "特征值", "", 0)
    store.add_kp(b.scope_id, "数据库", "索引", "", 0)
    holder["t"] = T1
    store.complete_review(a.scope_id, e.kp_id, "needs_work", "需要加强")
    store.complete_review(a.scope_id, m.kp_id, "mastered", "已掌握")
    store.set_prefs(a.scope_id, Preference(daily_goal=5))
    store.set_app_state(app_scope, AppState(selected_learner_scope_id=a.scope_id))

    fixed_now = rules.format_dt(T2)
    port = _free_port()

    # 2) 启动应用进程 #1（固定时钟 T2），验证恢复
    proc1, url1, log1 = _start_app(pc_server, port, tmp_path, fixed_now)
    try:
        state = _get(url1 + "/api/state")
        assert state["selected_learner_scope_id"] == a.scope_id
        ov = _get(url1 + "/api/overview?learner=" + a.scope_id)
        assert [d["kp"]["title"] for d in ov["due"]] == ["特征值"]
        assert ov["due"][0]["overdue_days"] == 1
        assert [u["kp"]["title"] for u in ov["upcoming"]] == ["矩阵乘法"]
        assert ov["prefs"]["daily_goal"] == 5
        pid1 = proc1.pid
    finally:
        proc1.terminate()
        proc1.wait(timeout=10)
        log1.close()

    # 3) 全新进程 #2（不同 PID，同一 PowerContext），验证状态仍在并参与列表
    proc2, url2, log2 = _start_app(pc_server, port, tmp_path, fixed_now)
    try:
        assert proc2.pid != pid1
        state = _get(url2 + "/api/state")
        assert state["selected_learner_scope_id"] == a.scope_id
        ov = _get(url2 + "/api/overview?learner=" + a.scope_id)
        assert [d["kp"]["title"] for d in ov["due"]] == ["特征值"]
        assert ov["prefs"]["daily_goal"] == 5
        assert ov["totals"]["review_records"] == 2

        # 4) 切换到 B：不得看到 A 的数据；选择状态写回 PowerContext
        req = urllib.request.Request(
            url2 + "/api/state", method="PUT",
            data=json.dumps({"selected_learner_scope_id": b.scope_id}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            assert resp.status == 200
        ov_b = _get(url2 + "/api/overview?learner=" + b.scope_id)
        assert [d["kp"]["title"] for d in ov_b["due"]] == ["索引"]
        assert ov_b["totals"]["review_records"] == 0
    finally:
        proc2.terminate()
        proc2.wait(timeout=10)
        log2.close()

    # 5) 进程 #3：验证“切换到 B”的选择也被持久化恢复
    proc3, url3, log3 = _start_app(pc_server, port, tmp_path, fixed_now)
    try:
        state = _get(url3 + "/api/state")
        assert state["selected_learner_scope_id"] == b.scope_id
    finally:
        proc3.terminate()
        proc3.wait(timeout=10)
        log3.close()