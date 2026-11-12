"""领域存储层测试：CRUD、复习规则落库、学习者隔离、偏好与状态持久化。

全部经真实 PowerContext Server；时钟固定，断言与运行日期无关。
"""

from datetime import timedelta

import pytest

from app import rules
from app.models import AppState, Preference
from app.store import NotFoundError, StudyStore

T0 = rules.parse_dt("2026-11-08T09:00:00Z")
T1 = rules.parse_dt("2026-11-08T10:00:00Z")
T2 = rules.parse_dt("2026-11-11T09:00:00Z")


@pytest.fixture()
def learner_a(store, unique_name):
    return store.create_learner("A" + unique_name)


@pytest.fixture()
def learner_b(store, unique_name):
    return store.create_learner("B" + unique_name)


def test_learner_create_and_list(store, unique_name):
    a = store.create_learner("甲" + unique_name)
    b = store.create_learner("乙" + unique_name)
    names = [l.name for l in store.list_learners()]
    assert "甲" + unique_name in names and "乙" + unique_name in names
    again = store.create_learner("甲" + unique_name)
    assert again.scope_id == a.scope_id
    assert store.get_prefs(a.scope_id) is not None


def test_kp_crud(store, learner_a, clock):
    kp = store.add_kp(learner_a.scope_id, "线性代数", "矩阵乘法", "笔记", 0)
    assert kp.interval_days == 1 and kp.next_review_at == T0
    fetched = store.get_kp(learner_a.scope_id, kp.kp_id)
    assert fetched.title == "矩阵乘法"

    clock.t = T1
    updated = store.update_kp(learner_a.scope_id, kp.kp_id, notes="新笔记", mastery=1)
    assert updated.notes == "新笔记" and updated.mastery == 1
    assert store.get_kp(learner_a.scope_id, kp.kp_id).updated_at == T1

    store.delete_kp(learner_a.scope_id, kp.kp_id)
    assert store.list_kps(learner_a.scope_id) == []
    with pytest.raises(NotFoundError):
        store.get_kp(learner_a.scope_id, kp.kp_id)


def test_review_updates_schedule_and_records(store, learner_a, clock):
    kp = store.add_kp(learner_a.scope_id, "线性代数", "特征值", "", 0)
    clock.t = T1
    updated, record = store.complete_review(learner_a.scope_id, kp.kp_id, "needs_work", "需要加强")
    assert updated.interval_days == 1
    assert updated.mastery == 0
    assert updated.next_review_at == T1 + timedelta(days=1)
    assert updated.review_count == 1 and updated.last_result == "needs_work"
    assert record.prev_interval_days == 1 and record.new_interval_days == 1
    assert record.source_id and record.source_id.startswith("review-")

    clock.t = T1 + timedelta(days=1)
    updated2, record2 = store.complete_review(learner_a.scope_id, kp.kp_id, "mastered", "")
    assert updated2.interval_days == 4 and updated2.mastery == 2
    assert updated2.review_count == 2
    records = store.list_records(learner_a.scope_id, kp_id=kp.kp_id)
    assert len(records) == 2
    assert records[0].record_id == record2.record_id


def test_delete_kp_archives_records(store, learner_a, clock):
    kp = store.add_kp(learner_a.scope_id, "数据库", "索引", "", 0)
    clock.t = T1
    store.complete_review(learner_a.scope_id, kp.kp_id, "ok", "")
    store.delete_kp(learner_a.scope_id, kp.kp_id)
    assert store.list_records(learner_a.scope_id) == []


def test_prefs_persist_and_revise(store, learner_a):
    prefs = store.set_prefs(learner_a.scope_id, Preference(daily_goal=5, show_upcoming=False, upcoming_horizon_days=3))
    assert prefs.daily_goal == 5
    loaded = store.get_prefs(learner_a.scope_id)
    assert loaded.daily_goal == 5 and loaded.show_upcoming is False and loaded.upcoming_horizon_days == 3
    store.set_prefs(learner_a.scope_id, Preference(daily_goal=2))
    assert store.get_prefs(learner_a.scope_id).daily_goal == 2
    with pytest.raises(ValueError):
        store.set_prefs(learner_a.scope_id, Preference(daily_goal=0))


def test_app_state_persist(store):
    app_scope = store.ensure_app_scope()
    store.set_app_state(app_scope, AppState(selected_learner_scope_id="scp_x"))
    assert store.get_app_state(app_scope).selected_learner_scope_id == "scp_x"
    store.set_app_state(app_scope, AppState(selected_learner_scope_id=None))
    assert store.get_app_state(app_scope).selected_learner_scope_id is None


def test_learner_isolation(store, learner_a, learner_b, clock):
    kp_a = store.add_kp(learner_a.scope_id, "线性代数", "特征值", "A 的笔记", 0)
    store.add_kp(learner_b.scope_id, "数据库", "索引", "B 的笔记", 0)
    clock.t = T1
    store.complete_review(learner_a.scope_id, kp_a.kp_id, "needs_work", "")

    b_kps = store.list_kps(learner_b.scope_id)
    assert [k.title for k in b_kps] == ["索引"]
    assert store.list_records(learner_b.scope_id) == []
    ov_b = store.overview(learner_b.scope_id, now=T2)
    assert [d["kp"]["title"] for d in ov_b["due"]] == ["索引"]
    ov_a = store.overview(learner_a.scope_id, now=T2)
    assert [d["kp"]["title"] for d in ov_a["due"]] == ["特征值"]


def test_overview_matches_fixed_time_scenario(store, learner_a, learner_b, clock):
    m = store.add_kp(learner_a.scope_id, "线性代数", "矩阵乘法", "", 0)
    e = store.add_kp(learner_a.scope_id, "线性代数", "特征值", "", 0)
    store.add_kp(learner_b.scope_id, "数据库", "索引", "", 0)
    clock.t = T1
    store.complete_review(learner_a.scope_id, e.kp_id, "needs_work", "需要加强")
    store.complete_review(learner_a.scope_id, m.kp_id, "mastered", "已掌握")
    store.set_prefs(learner_a.scope_id, Preference(daily_goal=5))

    ov = store.overview(learner_a.scope_id, now=T2)
    assert [d["kp"]["title"] for d in ov["due"]] == ["特征值"]
    assert ov["due"][0]["overdue_days"] == 1
    assert [u["kp"]["title"] for u in ov["upcoming"]] == ["矩阵乘法"]
    assert ov["prefs"]["daily_goal"] == 5
    assert ov["progress"]["reviewed_today"] == 0  # T2 当天没有复习
    assert ov["totals"] == {"knowledge_points": 2, "review_records": 2}


def test_restart_readback_new_client(pc_server, tmp_path, learner_a, store, clock):
    """新客户端 + 新 Store 实例（等价重启读取）能恢复全部状态。"""
    from app.powercontext_client import PowerContextClient

    kp = store.add_kp(learner_a.scope_id, "线性代数", "特征值", "", 0)
    clock.t = T1
    store.complete_review(learner_a.scope_id, kp.kp_id, "needs_work", "")
    store.set_prefs(learner_a.scope_id, Preference(daily_goal=5))

    client2 = PowerContextClient(pc_server, audit_path=tmp_path / "audit2.jsonl")
    store2 = StudyStore(client2, clock=lambda: T2)
    ov = store2.overview(learner_a.scope_id, now=T2)
    assert [d["kp"]["title"] for d in ov["due"]] == ["特征值"]
    assert ov["prefs"]["daily_goal"] == 5
    assert len(store2.list_records(learner_a.scope_id)) == 1