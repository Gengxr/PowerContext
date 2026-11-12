"""复习规则单元测试：全部使用固定时间，不依赖运行日期。"""

from datetime import timedelta

import pytest

from app import rules
from app.models import KnowledgePoint

T = rules.parse_dt("2026-11-11T09:00:00Z")


def kp(title, mastery=0, next_review=T, created=T - timedelta(days=5)):
    return KnowledgePoint(
        kp_id="kp-" + title, course="课程", title=title, notes="",
        mastery=mastery, created_at=created, updated_at=created,
        interval_days=1, next_review_at=next_review,
    )


def test_initial_schedule_due_immediately():
    created = T
    assert rules.initial_next_review(created) == created
    item = kp("新知识点", next_review=created)
    assert rules.is_due(item, created)


def test_needs_work_resets_to_one_day():
    interval, mastery, nxt = rules.apply_review(7, "needs_work", T)
    assert (interval, mastery) == (1, 0)
    assert nxt == T + timedelta(days=1)


def test_ok_doubles_with_floor_two():
    assert rules.apply_review(1, "ok", T)[:2] == (2, 1)
    assert rules.apply_review(2, "ok", T)[:2] == (4, 1)
    assert rules.apply_review(10, "ok", T)[:2] == (20, 1)


def test_mastered_triples_with_floor_four():
    assert rules.apply_review(1, "mastered", T)[:2] == (4, 2)
    assert rules.apply_review(4, "mastered", T)[:2] == (12, 2)
    assert rules.apply_review(12, "mastered", T)[:2] == (30, 2)


def test_interval_cap_30():
    assert rules.apply_review(20, "ok", T)[0] == 30
    assert rules.apply_review(20, "mastered", T)[0] == 30


def test_invalid_result_rejected():
    with pytest.raises(ValueError):
        rules.apply_review(1, "excellent", T)


def test_due_boundary_inclusive():
    item = kp("边界", next_review=T)
    assert rules.is_due(item, T)
    assert not rules.is_due(item, T - timedelta(seconds=1))


def test_overdue_days_floor():
    item = kp("逾期", next_review=T - timedelta(days=2, hours=23))
    assert rules.overdue_days(item, T) == 2
    assert rules.overdue_days(kp("未到期", next_review=T + timedelta(days=1)), T) == 0


def test_due_order_overdue_then_mastery_then_time_then_title():
    items = [
        kp("D-逾期1天-薄弱", mastery=0, next_review=T - timedelta(days=1)),
        kp("A-逾期3天-已掌握", mastery=2, next_review=T - timedelta(days=3)),
        kp("B-逾期3天-薄弱", mastery=0, next_review=T - timedelta(days=3)),
        kp("C-逾期3天-薄弱-更早", mastery=0, next_review=T - timedelta(days=3, hours=2)),
        kp("E-今天到期", mastery=1, next_review=T),
        kp("F-未到期", mastery=0, next_review=T + timedelta(days=1)),
    ]
    ordered = rules.sort_due(items, T)
    assert [i.title for i in ordered] == [
        "C-逾期3天-薄弱-更早",   # 逾期3天+2小时，逾期天数同为3但到期更早
        "B-逾期3天-薄弱",
        "A-逾期3天-已掌握",
        "D-逾期1天-薄弱",
        "E-今天到期",
    ]


def test_due_order_title_tiebreak():
    # 标题按 Unicode 码点序：乙(U+4E59) < 甲(U+7532)
    items = [kp("甲", next_review=T), kp("乙", next_review=T)]
    assert [i.title for i in rules.sort_due(items, T)] == ["乙", "甲"]


def test_upcoming_horizon_and_order():
    items = [
        kp("远处", next_review=T + timedelta(days=10)),
        kp("近处", next_review=T + timedelta(days=2)),
        kp("已到期", next_review=T - timedelta(days=1)),
    ]
    up = rules.sort_upcoming(items, T, horizon_days=7)
    assert [i.title for i in up] == ["近处"]


def test_explain_mentions_overdue_and_mastery():
    reasons = rules.explain(kp("特征值", mastery=0, next_review=T - timedelta(days=1)), T)
    assert any("逾期 1 天" in r for r in reasons)
    assert any("薄弱" in r for r in reasons)


def test_datetime_roundtrip():
    assert rules.parse_dt(rules.format_dt(T)) == T
    assert rules.parse_dt("2026-11-11T09:00:00+00:00") == T


def test_rules_document_complete():
    doc = rules.rules_document()
    assert set(doc["results"]) == {"needs_work", "ok", "mastered"}
    assert len(doc["order"]) == 4