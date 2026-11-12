"""应用 HTTP API 端到端测试（真实应用子进程 + 真实 PowerContext）。"""

import json
import urllib.error
import urllib.request

import pytest


def call(base, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


@pytest.fixture()
def base(app_server):
    return app_server["url"]


def test_health(base):
    status, body = call(base, "GET", "/api/health")
    assert status == 200 and body["app"] == "ok" and body["powercontext"] is True


def test_full_api_flow(base):
    status, learner = call(base, "POST", "/api/learners", {"name": "API学习者"})
    assert status == 201
    sid = learner["scope_id"]
    q = "?learner=" + sid

    status, kp = call(base, "POST", "/api/kps" + q,
                      {"course": "线性代数", "title": "特征值", "notes": "n", "mastery": 0})
    assert status == 201
    kp_id = kp["kp_id"]

    status, kps = call(base, "GET", "/api/kps" + q)
    assert status == 200 and len(kps["kps"]) == 1

    status, updated = call(base, "PUT", "/api/kp" + q + "&kp_id=" + kp_id, {"notes": "改"})
    assert status == 200 and updated["notes"] == "改"

    status, reviewed = call(base, "POST", "/api/review" + q,
                            {"kp_id": kp_id, "result": "needs_work", "note": "加强"})
    assert status == 200
    assert reviewed["kp"]["interval_days"] == 1
    assert reviewed["record"]["source_id"]

    status, records = call(base, "GET", "/api/records" + q)
    assert status == 200 and len(records["records"]) == 1

    status, prefs = call(base, "PUT", "/api/prefs" + q, {"daily_goal": 5})
    assert status == 200 and prefs["daily_goal"] == 5

    status, ov = call(base, "GET", "/api/overview" + q)
    assert status == 200 and ov["prefs"]["daily_goal"] == 5
    # 真实时钟：needs_work 后下次复习在明天，故当前无到期、进入即将到期
    assert ov["due"] == []
    assert [u["kp"]["title"] for u in ov["upcoming"]] == ["特征值"]
    assert ov["progress"]["reviewed_today"] == 1

    status, state = call(base, "PUT", "/api/state", {"selected_learner_scope_id": sid})
    assert status == 200 and state["selected_learner_scope_id"] == sid
    status, state = call(base, "GET", "/api/state")
    assert state["selected_learner_scope_id"] == sid

    status, deleted = call(base, "DELETE", "/api/kp" + q + "&kp_id=" + kp_id)
    assert status == 200
    status, kps = call(base, "GET", "/api/kps" + q)
    assert kps["kps"] == []


def test_api_isolation(base):
    _, a = call(base, "POST", "/api/learners", {"name": "隔离甲"})
    _, b = call(base, "POST", "/api/learners", {"name": "隔离乙"})
    call(base, "POST", "/api/kps?learner=" + a["scope_id"],
         {"course": "线性代数", "title": "特征值", "mastery": 0})
    call(base, "POST", "/api/kps?learner=" + b["scope_id"],
         {"course": "数据库", "title": "索引", "mastery": 0})
    _, kps_b = call(base, "GET", "/api/kps?learner=" + b["scope_id"])
    assert [k["title"] for k in kps_b["kps"]] == ["索引"]
    _, ov_b = call(base, "GET", "/api/overview?learner=" + b["scope_id"])
    assert [d["kp"]["title"] for d in ov_b["due"]] == ["索引"]


def test_api_errors(base):
    status, _ = call(base, "GET", "/api/overview")
    assert status == 400
    status, _ = call(base, "GET", "/api/overview?learner=scp_nonexistent")
    assert status == 404
    _, learner = call(base, "POST", "/api/learners", {"name": "错误用例"})
    q = "?learner=" + learner["scope_id"]
    status, _ = call(base, "POST", "/api/kps" + q, {"course": "", "title": "", "mastery": 0})
    assert status == 400
    _, kp = call(base, "POST", "/api/kps" + q, {"course": "C", "title": "T", "mastery": 0})
    status, _ = call(base, "POST", "/api/review" + q, {"kp_id": kp["kp_id"], "result": "bad"})
    assert status == 400
    status, _ = call(base, "PUT", "/api/kp" + q + "&kp_id=kp-none", {"title": "x"})
    assert status == 404


def test_static_frontend(base):
    with urllib.request.urlopen(base + "/", timeout=10) as resp:
        html = resp.read().decode("utf-8")
    assert resp.status == 200 and "学习回顾台" in html
    with urllib.request.urlopen(base + "/app.js", timeout=10) as resp:
        assert resp.status == 200