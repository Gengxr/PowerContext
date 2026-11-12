"""领域存储层：学习者 / 知识点 / 复习记录 / 偏好 / 应用状态。

分工说明：本层不持有任何本地业务数据库或 JSON 状态文件。
- 每个学习者 = 一个 PowerContext Scope（数据隔离边界）。
- 知识点 / 复习记录 / 偏好 / 应用状态 = 该 Scope 内的 PowerContext Memory 条目，
  text 为结构化 JSON payload，更新用 revise，删除用 retire。
- 每次完成复习额外通过 /v1/sources/content 捕获一条 Source 证据。
- 应用进程重启后重新从 PowerContext 读取全部状态（无本地缓存）。
"""

from __future__ import annotations

import json
from datetime import datetime

from . import rules
from .models import AppState, KnowledgePoint, Learner, Preference, ReviewRecord, new_id
from .powercontext_client import PowerContextClient, PowerContextError

APP_SCOPE_TITLE = "study-review-app"
APP_SCOPE_KEY = "study-review-app-v1"
LEARNER_TITLE_PREFIX = "study-review-learner:"

KIND_KP = "knowledge-point"
KIND_RECORD = "review-record"
KIND_PREF = "learner-preference"
KIND_APP_STATE = "app-state"


class NotFoundError(KeyError):
    pass


def _entry_payload(entry: dict) -> dict | None:
    try:
        payload = json.loads(entry["text"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


class StudyStore:
    def __init__(self, client: PowerContextClient, clock=rules.utcnow):
        self.client = client
        self.clock = clock

    # ---- Scope / 学习者 ----
    def ensure_app_scope(self) -> str:
        try:
            desc = self.client.create_scope(
                title=APP_SCOPE_TITLE,
                summary="学习回顾台应用级状态（当前选择的学习者等）",
                idempotency_key=APP_SCOPE_KEY,
            )
            return desc["scope_id"]
        except PowerContextError as e:
            if e.status not in (409,):
                raise
        for scope in self._all_scopes():
            if scope["title"] == APP_SCOPE_TITLE:
                return scope["scope_id"]
        raise PowerContextError("应用 Scope 创建冲突且无法找到既有 Scope")

    def _all_scopes(self) -> list[dict]:
        items: list[dict] = []
        cursor = None
        while True:
            page = self.client.list_scopes(limit=100, cursor=cursor)
            items.extend(page.get("items", []))
            cursor = page.get("next_cursor")
            if not cursor:
                return items

    def create_learner(self, name: str) -> Learner:
        name = name.strip()
        if not name:
            raise ValueError("学习者名称不能为空")
        if len(name) > 64:
            raise ValueError("学习者名称过长（<=64 字符）")
        title = LEARNER_TITLE_PREFIX + name
        try:
            desc = self.client.create_scope(
                title=title,
                summary=f"学习回顾台学习者数据边界：{name}",
                idempotency_key="study-review-learner:" + name,
            )
        except PowerContextError as e:
            if e.status != 409:
                raise
            desc = next((s for s in self._all_scopes() if s["title"] == title), None)
            if desc is None:
                raise
        learner = Learner(scope_id=desc["scope_id"], name=name, title=desc["title"],
                          summary=desc["summary"])
        if self.get_prefs(learner.scope_id) is None:
            self.set_prefs(learner.scope_id, Preference())
        return learner

    def list_learners(self) -> list[Learner]:
        learners = []
        for scope in self._all_scopes():
            title = scope.get("title", "")
            if title.startswith(LEARNER_TITLE_PREFIX):
                learners.append(Learner(
                    scope_id=scope["scope_id"],
                    name=title[len(LEARNER_TITLE_PREFIX):],
                    title=title,
                    summary=scope.get("summary", ""),
                ))
        return sorted(learners, key=lambda l: l.name)

    def get_learner(self, scope_id: str) -> Learner:
        for learner in self.list_learners():
            if learner.scope_id == scope_id:
                return learner
        raise NotFoundError(f"学习者不存在: {scope_id}")

    # ---- Memory 条目通用 ----
    def _entries(self, scope_id: str, kind: str) -> list[tuple[dict, dict]]:
        result = []
        for record in self.client.list_all_atomic_memories(scope_id, kind=kind, states=["active"]):
            payload = _entry_payload(record)
            if payload is not None:
                result.append((payload, self._ref_of(record)))
        return result

    @staticmethod
    def _ref_of(record: dict) -> dict:
        return {"artifact": record["artifact"], "state_version": record["state_version"]}

    def _remember(self, scope_id: str, kind: str, payload: dict, reason: str) -> dict:
        record = self.client.remember(scope_id, kind, json.dumps(payload, ensure_ascii=False), reason=reason)
        return self._ref_of(record)

    def _revise(self, scope_id: str, ref: dict, kind: str, payload: dict) -> dict:
        artifact_id = ref["artifact"]["artifact_id"]
        _, etag = self.client.get_artifact(scope_id, artifact_id)
        self.client.replace_atomic_memory(
            scope_id, artifact_id, kind, json.dumps(payload, ensure_ascii=False), if_match=etag)
        state = self.client.get_atomic_state(scope_id, artifact_id)
        return {"artifact": state["artifact"], "state_version": state["state_version"]}

    def _forget(self, scope_id: str, ref: dict, reason: str) -> None:
        self.client.forget_atomic_memory(scope_id, ref["artifact"], ref["state_version"])

    # ---- 知识点 ----
    def add_kp(self, scope_id: str, course: str, title: str, notes: str, mastery: int) -> KnowledgePoint:
        if not course.strip() or not title.strip():
            raise ValueError("课程与标题不能为空")
        kp = KnowledgePoint.create(course, title, notes, mastery, self.clock())
        kp.ref = self._remember(scope_id, KIND_KP, kp.to_payload(), "添加知识点")
        return kp

    def list_kps(self, scope_id: str) -> list[KnowledgePoint]:
        return [KnowledgePoint.from_payload(p, c) for p, c in self._entries(scope_id, KIND_KP)]

    def get_kp(self, scope_id: str, kp_id: str) -> KnowledgePoint:
        for kp in self.list_kps(scope_id):
            if kp.kp_id == kp_id:
                return kp
        raise NotFoundError(f"知识点不存在: {kp_id}")

    def update_kp(self, scope_id: str, kp_id: str, *, course: str | None = None,
                  title: str | None = None, notes: str | None = None,
                  mastery: int | None = None) -> KnowledgePoint:
        kp = self.get_kp(scope_id, kp_id)
        if course is not None:
            kp.course = course.strip()
        if title is not None:
            kp.title = title.strip()
        if notes is not None:
            kp.notes = notes
        if mastery is not None:
            if mastery not in rules.MASTERY_LABELS:
                raise ValueError("掌握程度必须是 0/1/2")
            kp.mastery = mastery
        if not kp.course or not kp.title:
            raise ValueError("课程与标题不能为空")
        kp.updated_at = self.clock()
        kp.ref = self._revise(scope_id, kp.ref, KIND_KP, kp.to_payload())
        return kp

    def delete_kp(self, scope_id: str, kp_id: str) -> None:
        kp = self.get_kp(scope_id, kp_id)
        for record in self.list_records(scope_id, kp_id=kp_id):
            self._forget(scope_id, record.ref, "删除知识点时归档其复习记录")
        self._forget(scope_id, kp.ref, "删除知识点")

    # ---- 复习 ----
    def complete_review(self, scope_id: str, kp_id: str, result: str, note: str = "") -> tuple[KnowledgePoint, ReviewRecord]:
        kp = self.get_kp(scope_id, kp_id)
        now = self.clock()
        prev_interval = kp.interval_days
        interval, mastery, next_review = rules.apply_review(prev_interval, result, now)
        record = ReviewRecord(
            record_id=new_id("rev"),
            kp_id=kp.kp_id,
            kp_title=kp.title,
            result=result,
            reviewed_at=now,
            note=note,
            prev_interval_days=prev_interval,
            new_interval_days=interval,
            next_review_at=next_review,
        )
        source_id = "review-" + record.record_id
        content = (
            f"学习回顾：{kp.course} / {kp.title}\n"
            f"结果：{rules.RESULT_LABELS[result]}\n"
            f"时间：{rules.format_dt(now)}\n"
            f"间隔：{prev_interval} 天 -> {interval} 天，下次复习 {rules.format_dt(next_review)}\n"
            f"备注：{note or '无'}"
        )
        try:
            self.client.capture_content_source(
                scope_id, source_id, content,
                metadata={"origin": "study-review", "kp_id": kp.kp_id, "result": result},
            )
            record.source_id = source_id
        except PowerContextError:
            record.source_id = None
        record.ref = self._remember(scope_id, KIND_RECORD, record.to_payload(), "完成一次复习")
        kp.interval_days = interval
        kp.mastery = mastery
        kp.next_review_at = next_review
        kp.review_count += 1
        kp.last_result = result
        kp.updated_at = now
        kp.ref = self._revise(scope_id, kp.ref, KIND_KP, kp.to_payload())
        return kp, record

    def list_records(self, scope_id: str, kp_id: str | None = None) -> list[ReviewRecord]:
        records = [ReviewRecord.from_payload(p, c) for p, c in self._entries(scope_id, KIND_RECORD)]
        if kp_id is not None:
            records = [r for r in records if r.kp_id == kp_id]
        return sorted(records, key=lambda r: r.reviewed_at, reverse=True)

    # ---- 偏好 ----
    def get_prefs(self, scope_id: str) -> Preference | None:
        entries = self._entries(scope_id, KIND_PREF)
        if not entries:
            return None
        payload, ref = entries[0]
        return Preference.from_payload(payload, ref)

    def set_prefs(self, scope_id: str, prefs: Preference) -> Preference:
        prefs.validate()
        existing = self.get_prefs(scope_id)
        if existing is None:
            prefs.ref = self._remember(scope_id, KIND_PREF, prefs.to_payload(), "保存学习偏好")
        else:
            prefs.ref = self._revise(scope_id, existing.ref, KIND_PREF, prefs.to_payload())
        return prefs

    # ---- 应用状态（当前选择的学习者） ----
    def get_app_state(self, app_scope_id: str) -> AppState:
        entries = self._entries(app_scope_id, KIND_APP_STATE)
        if not entries:
            return AppState()
        payload, ref = entries[0]
        return AppState.from_payload(payload, ref)

    def set_app_state(self, app_scope_id: str, state: AppState) -> AppState:
        state.updated_at = self.clock()
        existing = self.get_app_state(app_scope_id)
        if existing is None or existing.ref is None:
            state.ref = self._remember(app_scope_id, KIND_APP_STATE, state.to_payload(), "保存当前进度")
        else:
            state.ref = self._revise(app_scope_id, existing.ref, KIND_APP_STATE, state.to_payload())
        return state

    # ---- 概览（待复习 / 即将到期 / 今日进度） ----
    def overview(self, scope_id: str, now: datetime | None = None) -> dict:
        now = now or self.clock()
        kps = self.list_kps(scope_id)
        prefs = self.get_prefs(scope_id) or Preference()
        due = rules.sort_due(kps, now)
        upcoming = rules.sort_upcoming(kps, now, prefs.upcoming_horizon_days) if prefs.show_upcoming else []
        records = self.list_records(scope_id)
        today = now.date()
        reviewed_today = sum(1 for r in records if r.reviewed_at.astimezone(rules.timezone.utc).date() == today)
        return {
            "now": rules.format_dt(now),
            "prefs": prefs.to_payload(),
            "due": [
                {
                    "kp": kp.to_payload(),
                    "overdue_days": rules.overdue_days(kp, now),
                    "reasons": rules.explain(kp, now),
                }
                for kp in due
            ],
            "upcoming": [{"kp": kp.to_payload(), "reasons": rules.explain(kp, now)} for kp in upcoming],
            "progress": {"reviewed_today": reviewed_today, "daily_goal": prefs.daily_goal},
            "totals": {"knowledge_points": len(kps), "review_records": len(records)},
        }