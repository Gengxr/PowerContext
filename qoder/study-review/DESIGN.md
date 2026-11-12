# 设计说明（学习回顾台）

## 目标与取舍

面向学生管理薄弱知识点与复习任务。取舍：**轻量、可复现、无付费模型**——
Python stdlib 后端 + 原生 JS 前端 + 真实 PowerContext（官方 SQLite 后端）承担全部持久化。
复习优先级用**公开确定性规则**而非模型推荐，保证可解释、可测试、可复现。

## 架构

```
浏览器(原生 JS, textContent 渲染)
   │  HTTP JSON
app/server.py (stdlib ThreadingHTTPServer)
   │  调用
app/store.py (业务编排: 规则 + 隔离 + 恢复)
   │  真实 HTTP
app/powercontext_client.py (1.5.1 Atomic Memory 契约, 逐请求审计)
   │  HTTP
PowerContext Server (官方, SQLite 持久化, 基本记忆模式)
```

- **应用进程无本地业务状态**：不写业务 JSON/自建库；一切读写经 PowerContext。重启即恢复（恢复不是额外功能，而是架构必然）。
- **唯一业务存储 = PowerContext（SQLite）**。不另设业务数据库，故无「业务库 vs PowerContext」分工问题；
  runtime/ 下的 SQLite 文件即 PowerContext 官方后端数据目录（不提交）。

## PowerContext 数据模型

- **Scope = 隔离边界**：每学习者一个 Scope（title `study-review-learner:<name>`，幂等创建）；
  应用级 Scope（`study-review-app`）存 app-state。跨学习者查询只在自己的 Scope 内进行 → 天然隔离。
- **Atomic Memory = 业务对象**，kind 区分四类，text 为 JSON payload：
  - `knowledge-point`：kp_id/course/title/notes/mastery/interval_days/next_review_at/review_count/last_result/created_at/updated_at
  - `review-record`：record_id/kp_id/result/note/prev_interval/new_interval/reviewed_at/next_review_at/source_id
  - `learner-preference`：daily_goal(1..50)/show_upcoming/upcoming_horizon_days(1..60)
  - `app-state`：selected_learner_scope_id/updated_at
- **引用 ref** = `{artifact, state_version}`（1.5.1 契约），用于更新/删除定位。
- **Source 证据**：每次复习 `POST /v1/sources/content` 存一条 `review-<record_id>`，record.source_id 指向它。

## 契约要点（1.5.1，实测核实，存档 evidence/live-openapi-1.5.1.json）

- remember → `{changed, records:[AtomicMemoryRecord]}`（非 main 文档的 entry/citation）。
- list → `POST /v1/atomic-memory/list {scope_id, kind, states, limit<=100, cursor}` → `{items, next_cursor}`。
- 更新 → GET artifact 取 ETag（`"revision:N"`）→ PUT 带 `If-Match` + `{content:{schema, kind, text}}`；过期 ETag 被拒（乐观并发）。
- 删除 → `POST /v1/atomic-memory/lifecycle {scope_id, target:{artifact,state_version}, state:"forgotten"}`。
- 读取状态 → GET `.../artifacts/atomic-memory/{id}/state`。

## 复习规则（app/rules.py，纯函数、固定时间可测）

- 新知识点：interval=1 天，next_review=created_at（创建即到期）。
- 复习结果 → (新间隔, 掌握度)：
  - needs_work → (1, 0)
  - ok → (min(30, max(2, 旧间隔×2)), 1)
  - mastered → (min(30, max(4, 旧间隔×3)), 2)
  - next_review = reviewed_at + 新间隔。
- 到期判定：next_review_at <= now。
- 逾期天数：floor((now - next_review_at)/86400)。
- 待复习排序：(-逾期天数, 掌握度, next_review_at, 标题 Unicode 码点序)。
- 即将到期：未到期且落在偏好窗口内，按 (next_review_at, 标题) 升序。
- 今日进度：reviewed_at 落在 now 当日（UTC）的记录数 / daily_goal。

## 隔离 / 恢复 / 并发 / 安全

- 隔离：Scope 边界 + API 层 learner 参数校验；B 的请求只读 B 的 Scope。
- 恢复：启动读 app-state 得选中学习者；overview 实时由 PowerContext 列表计算 → 重启后列表/偏好/选中态一致。
- 并发：更新走 ETag/If-Match，冲突拒绝而非覆盖。
- 安全：前端仅 textContent 渲染（防 XSS）；静态服务带路径穿越防护；loopback 监听；不提交凭据/运行库。

## 测试策略

- 纯规则：固定时间单测（14）。
- 真实集成：conftest 启动真实 powercontext server 子进程（临时 SQLite/端口/隔离 HOME），8 用例覆盖契约与隔离；**不用 mock 替代**。
- 存储/API：9+5 用例覆盖 CRUD、调度、隔离、错误、静态。
- 跨进程重启：1 用例编排 3 个真实 app 子进程，kill 后断言恢复与选择持久化。
- 固定样例：examples/verify_sample.py 8 断言（独立学习者，可重复）。
- 时间全部可注入（ManualClock / STUDY_REVIEW_FIXED_NOW），不依赖运行日期。

## 已知限制

单机单实例、loopback 免认证；间隔上限 30 天；无模型推荐；展示站不冒充在线应用；未做真实用户效果评估。