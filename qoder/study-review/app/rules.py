"""学习回顾台 —— 纯函数复习调度规则。

所有规则都是确定性的、可解释的，不依赖任何模型或随机数。
时间一律使用带时区的 UTC datetime；`now` 由调用方注入，便于固定时间测试。

规则（与 DESIGN.md、前端 /api/rules 展示一致）：
1. 新知识点：interval_days = 1，next_review_at = created_at（创建即到期，等待首次复习）。
2. 复习结果决定下一次间隔与掌握程度：
   - needs_work（需要加强）: interval = 1 天, mastery = 0（薄弱）
   - ok（基本掌握）:       interval = min(30, max(2, 旧间隔 * 2)) 天, mastery = 1（一般）
   - mastered（已掌握）:   interval = min(30, max(4, 旧间隔 * 3)) 天, mastery = 2（已掌握）
   next_review_at = 复习时刻 + interval 天。
3. 到期判定：next_review_at <= now 即进入待复习列表。
4. 待复习排序（依次比较，全部升序/降序明确）：
   a. 逾期天数多的在前（overdue_days 降序）
   b. 掌握程度低的在前（mastery 升序）
   c. 到期时间早的在前（next_review_at 升序）
   d. 标题 Unicode 码点序在前（title 升序，保证完全确定）
5. 未到期知识点按 next_review_at 升序单独展示为“即将到期”。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MASTERY_WEAK = 0
MASTERY_MEDIUM = 1
MASTERY_MASTERED = 2
MASTERY_LABELS = {0: "薄弱", 1: "一般", 2: "已掌握"}

RESULT_NEEDS_WORK = "needs_work"
RESULT_OK = "ok"
RESULT_MASTERED = "mastered"
RESULT_LABELS = {
    RESULT_NEEDS_WORK: "需要加强",
    RESULT_OK: "基本掌握",
    RESULT_MASTERED: "已掌握",
}
VALID_RESULTS = (RESULT_NEEDS_WORK, RESULT_OK, RESULT_MASTERED)

INITIAL_INTERVAL_DAYS = 1
MAX_INTERVAL_DAYS = 30
DAY_SECONDS = 86400


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def initial_next_review(created_at: datetime) -> datetime:
    return created_at


def apply_review(prev_interval_days: int, result: str, reviewed_at: datetime) -> tuple[int, int, datetime]:
    """返回 (新间隔天数, 新掌握程度, 下次复习时间)。"""
    if result not in VALID_RESULTS:
        raise ValueError(f"未知复习结果: {result!r}，可选: {VALID_RESULTS}")
    if result == RESULT_NEEDS_WORK:
        interval, mastery = 1, MASTERY_WEAK
    elif result == RESULT_OK:
        interval, mastery = min(MAX_INTERVAL_DAYS, max(2, prev_interval_days * 2)), MASTERY_MEDIUM
    else:
        interval, mastery = min(MAX_INTERVAL_DAYS, max(4, prev_interval_days * 3)), MASTERY_MASTERED
    return interval, mastery, reviewed_at + timedelta(days=interval)


@dataclass(frozen=True)
class Schedulable:
    """排序所需的最小字段集合（KnowledgePoint 满足该协议）。"""

    title: str
    mastery: int
    next_review_at: datetime


def is_due(item: Schedulable, now: datetime) -> bool:
    return item.next_review_at <= now


def overdue_days(item: Schedulable, now: datetime) -> int:
    if not is_due(item, now):
        return 0
    return int((now - item.next_review_at).total_seconds() // DAY_SECONDS)


def due_sort_key(item: Schedulable, now: datetime) -> tuple:
    return (-overdue_days(item, now), item.mastery, item.next_review_at, item.title)


def sort_due(items: list, now: datetime) -> list:
    return sorted((i for i in items if is_due(i, now)), key=lambda i: due_sort_key(i, now))


def sort_upcoming(items: list, now: datetime, horizon_days: int) -> list:
    horizon = now + timedelta(days=horizon_days)
    return sorted(
        (i for i in items if not is_due(i, now) and i.next_review_at <= horizon),
        key=lambda i: (i.next_review_at, i.title),
    )


def explain(item: Schedulable, now: datetime) -> list[str]:
    """为单个知识点生成人类可读的排序/到期依据。"""
    reasons: list[str] = []
    if is_due(item, now):
        days = overdue_days(item, now)
        reasons.append("已逾期 %d 天，优先复习" % days if days > 0 else "今天到期，等待复习")
    else:
        reasons.append("尚未到期，%s 复习" % format_dt(item.next_review_at))
    reasons.append("掌握程度：%s（%d 级，越低越优先）" % (MASTERY_LABELS.get(item.mastery, "未知"), item.mastery))
    return reasons


def rules_document() -> dict:
    """供前端展示的完整规则说明（与代码实现一一对应）。"""
    return {
        "initial": "新知识点间隔 1 天，创建即到期，等待首次复习。",
        "results": {
            RESULT_NEEDS_WORK: {"label": RESULT_LABELS[RESULT_NEEDS_WORK], "interval": "1 天", "mastery": "0 薄弱"},
            RESULT_OK: {"label": RESULT_LABELS[RESULT_OK], "interval": "min(30, max(2, 旧间隔×2)) 天", "mastery": "1 一般"},
            RESULT_MASTERED: {"label": RESULT_LABELS[RESULT_MASTERED], "interval": "min(30, max(4, 旧间隔×3)) 天", "mastery": "2 已掌握"},
        },
        "due": "next_review_at <= 当前时间 即进入待复习列表。",
        "order": ["逾期天数降序", "掌握程度升序", "到期时间升序", "标题 Unicode 码点序升序"],
        "upcoming": "未到期知识点按到期时间升序展示在“即将到期”，展示窗口由偏好 upcoming_horizon_days 控制。",
        "note": "全部为确定性规则，不含模型推荐；时间由服务端时钟提供，测试注入固定时间。",
    }