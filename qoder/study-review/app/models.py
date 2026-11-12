"""领域模型：知识点、复习记录、学习偏好、应用状态。

所有模型都以 JSON payload 形式存入 PowerContext Memory（text 字段），
ref（artifact 引用 + state_version）由 PowerContext 返回，用于后续更新/删除。
本应用不在本地保存任何业务数据文件。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from . import rules


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class KnowledgePoint:
    kp_id: str
    course: str
    title: str
    notes: str
    mastery: int
    created_at: datetime
    updated_at: datetime
    interval_days: int
    next_review_at: datetime
    review_count: int = 0
    last_result: str | None = None
    ref: dict | None = field(default=None, repr=False)

    def to_payload(self) -> dict:
        return {
            "type": "knowledge-point",
            "kp_id": self.kp_id,
            "course": self.course,
            "title": self.title,
            "notes": self.notes,
            "mastery": self.mastery,
            "created_at": rules.format_dt(self.created_at),
            "updated_at": rules.format_dt(self.updated_at),
            "interval_days": self.interval_days,
            "next_review_at": rules.format_dt(self.next_review_at),
            "review_count": self.review_count,
            "last_result": self.last_result,
        }

    @classmethod
    def from_payload(cls, payload: dict, ref: dict | None = None) -> "KnowledgePoint":
        return cls(
            kp_id=payload["kp_id"],
            course=payload["course"],
            title=payload["title"],
            notes=payload.get("notes", ""),
            mastery=int(payload["mastery"]),
            created_at=rules.parse_dt(payload["created_at"]),
            updated_at=rules.parse_dt(payload["updated_at"]),
            interval_days=int(payload["interval_days"]),
            next_review_at=rules.parse_dt(payload["next_review_at"]),
            review_count=int(payload.get("review_count", 0)),
            last_result=payload.get("last_result"),
            ref=ref,
        )

    @classmethod
    def create(cls, course: str, title: str, notes: str, mastery: int, now: datetime) -> "KnowledgePoint":
        if mastery not in rules.MASTERY_LABELS:
            raise ValueError("掌握程度必须是 0(薄弱)/1(一般)/2(已掌握)")
        return cls(
            kp_id=new_id("kp"),
            course=course.strip(),
            title=title.strip(),
            notes=notes,
            mastery=mastery,
            created_at=now,
            updated_at=now,
            interval_days=rules.INITIAL_INTERVAL_DAYS,
            next_review_at=rules.initial_next_review(now),
        )


@dataclass
class ReviewRecord:
    record_id: str
    kp_id: str
    kp_title: str
    result: str
    reviewed_at: datetime
    note: str
    prev_interval_days: int
    new_interval_days: int
    next_review_at: datetime
    source_id: str | None = None
    ref: dict | None = field(default=None, repr=False)

    def to_payload(self) -> dict:
        return {
            "type": "review-record",
            "record_id": self.record_id,
            "kp_id": self.kp_id,
            "kp_title": self.kp_title,
            "result": self.result,
            "reviewed_at": rules.format_dt(self.reviewed_at),
            "note": self.note,
            "prev_interval_days": self.prev_interval_days,
            "new_interval_days": self.new_interval_days,
            "next_review_at": rules.format_dt(self.next_review_at),
            "source_id": self.source_id,
        }

    @classmethod
    def from_payload(cls, payload: dict, ref: dict | None = None) -> "ReviewRecord":
        return cls(
            record_id=payload["record_id"],
            kp_id=payload["kp_id"],
            kp_title=payload["kp_title"],
            result=payload["result"],
            reviewed_at=rules.parse_dt(payload["reviewed_at"]),
            note=payload.get("note", ""),
            prev_interval_days=int(payload["prev_interval_days"]),
            new_interval_days=int(payload["new_interval_days"]),
            next_review_at=rules.parse_dt(payload["next_review_at"]),
            source_id=payload.get("source_id"),
            ref=ref,
        )


@dataclass
class Preference:
    daily_goal: int = 3
    show_upcoming: bool = True
    upcoming_horizon_days: int = 7
    ref: dict | None = field(default=None, repr=False)

    def to_payload(self) -> dict:
        return {
            "type": "learner-preference",
            "daily_goal": self.daily_goal,
            "show_upcoming": self.show_upcoming,
            "upcoming_horizon_days": self.upcoming_horizon_days,
        }

    @classmethod
    def from_payload(cls, payload: dict, ref: dict | None = None) -> "Preference":
        return cls(
            daily_goal=int(payload.get("daily_goal", 3)),
            show_upcoming=bool(payload.get("show_upcoming", True)),
            upcoming_horizon_days=int(payload.get("upcoming_horizon_days", 7)),
            ref=ref,
        )

    def validate(self) -> None:
        if not (1 <= self.daily_goal <= 50):
            raise ValueError("每日目标需在 1..50 之间")
        if not (1 <= self.upcoming_horizon_days <= 60):
            raise ValueError("即将到期展示窗口需在 1..60 天之间")


@dataclass
class AppState:
    selected_learner_scope_id: str | None = None
    updated_at: datetime | None = None
    ref: dict | None = field(default=None, repr=False)

    def to_payload(self) -> dict:
        return {
            "type": "app-state",
            "selected_learner_scope_id": self.selected_learner_scope_id,
            "updated_at": rules.format_dt(self.updated_at) if self.updated_at else None,
        }

    @classmethod
    def from_payload(cls, payload: dict, ref: dict | None = None) -> "AppState":
        updated = payload.get("updated_at")
        return cls(
            selected_learner_scope_id=payload.get("selected_learner_scope_id"),
            updated_at=rules.parse_dt(updated) if updated else None,
            ref=ref,
        )


@dataclass
class Learner:
    scope_id: str
    name: str
    title: str
    summary: str