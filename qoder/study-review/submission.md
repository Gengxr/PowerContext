# 提交说明 · 学习回顾台（OceanBase 2026 生态赛 · Qoder 赛题）

本文件为参赛提交说明。所有「已完成」项均有真实运行证据支撑，证据位于 `qoder/study-review/evidence/`。
未实际完成的事项在「未完成项 / 已知限制」中如实列出，不夸大、不虚构。

## 1. 作品概述

「学习回顾台」是面向学生的薄弱知识点管理、复习调度与学习记录工具。核心能力：

- 多学习者（≥2）数据隔离：每个学习者对应一个独立的 PowerContext Scope。
- 知识点管理：课程、标题、笔记、掌握程度；增 / 删 / 改 / 查（删除同时归档其复习记录）。
- 待复习列表：按公开、可解释的确定性规则排序与判定到期（不含模型智能推荐，亦不宣称）。
- 复习记录与调度：记录「需要加强 / 基本掌握 / 已掌握」，按规则更新间隔与下次复习时间，并留存 Source 证据。
- 偏好与进度保存：每日目标、即将到期窗口、当前选中学习者均持久化。
- 重启即恢复：应用进程不落盘任何业务状态，重启后从 PowerContext 读回并实际用于列表与界面。

技术栈：Python 标准库后端（`ThreadingHTTPServer` + `urllib`）+ 原生 JavaScript 前端（`textContent` 渲染防 XSS）+ **真实 PowerContext 1.5.1**（官方 HTTP API，SQLite 持久化，基本记忆模式，无需付费模型）。PowerContext 是唯一业务存储，不用普通 JSON 文件或自建数据库冒充。

## 2. 在线展示网站（Qoder Sites）

| 项 | 值 |
| --- | --- |
| 官方公开 URL | https://study-review-desk-owkhdvldatp.qoder.zone |
| 可见范围 | public（任何人都可访问，已按用户授权设置） |
| 公网验证 | 已用未登录客户端（curl，无 Cookie）验证：首页 HTTP 200；两张真实截图与样式表均 HTTP 200 且内容类型正确 |
| Sites projectId | `01a1ceab-94b2-7c6e-993d-9b27c97e084f` |
| Sites siteId | `01a1ceab-94b3-7b7a-8324-fcd8684736b0` |
| 发布状态 | 已发布并核对 `published: true`（publish Operation succeeded 且 committed） |
| 展示站源码 | 本仓库 `qoder/study-review/site/`（即所发布的静态产物） |

**重要声明：该网站是静态作品展示入口，不是在线运行的应用。** 核心应用需按 README 在本地运行；网站不冒充在线应用。网站内含简介、真实痛点与目标用户、核心功能、两张真实运行截图、可解释规则、技术结构与 PowerContext 的实际作用、正确的 GitHub 分支链接、本地安装与体验说明、已验证能力与已知限制。

## 3. 仓库与版本

| 项 | 值 |
| --- | --- |
| 提交仓库 | https://github.com/Gengxr/PowerContext |
| 提交分支 | `qoder-study-review`（新建分支，未覆盖 / 未强制推送任何已有分支） |
| 基线 | oceanbase/powercontext `2026-competition-ecosystem` @ `d647275c308e09b7b623f322a26f5c4e85734fb0` |
| 代码与证据提交（commit 1） | `30b87aba26bdbb97b82de8676e7756a317a1c20c` |
| 交付目录 | 仓库根 `qoder/study-review/`（全部交付物均在 `qoder/` 下） |
| 应用源码哈希 | `b955bb49cc2a312debfabf5bba6449af512eda5999118f886e482d28edc34a70`（app/ tests/ examples/ scripts/ + pyproject.toml + uv.lock，共 23 文件，SHA-256；详见 `evidence/TEST-REPORT.md`） |

说明：commit 1 包含全部应用代码、测试、样例、证据、README/DESIGN 与展示站源码；本 `submission.md` 作为同一分支上的后续提交加入。分支 HEAD 的完整提交 ID 见 `git log` 与最终交付回复。未改动 minimax、stepfun、dify、gaode 等其他赛题目录；未提交真实凭据、运行数据库（`runtime/`）、依赖目录（`.venv/`）或无关大文件（见 `.gitignore`）。

## 4. Qoder 账号 UID

| 项 | 值 |
| --- | --- |
| Qoder 账号 UID | `01a1ca54-58b1-7e14-bd24-32076a2cdd17` |

来源：Qoder Sites 插件为本发布动作保存的发布记录中的 `ownerUid` 字段（即当前登录、拥有该站点的账号），非虚构。该记录的 `sourceSession` 与本次开发会话一致（`7fd73b89-e990-4457-876d-b2be68721bbe`）。

## 5. 验收项 → 证据位置

所有路径相对 `qoder/study-review/`。完整映射另见 `evidence/INDEX.md`。

| 验收项 | 证据位置 |
| --- | --- |
| 主要增删改查（知识点 / 复习 / 偏好 / 状态） | `evidence/pytest-full.log`（test_store.py 9、test_api.py 5）；`evidence/powercontext-audit.jsonl`；浏览器实测见 `evidence/TEST-REPORT.md` §4 |
| 复习规则（可解释、确定性、固定时间） | `app/rules.py`；`evidence/pytest-full.log`（test_rules.py 14）；`evidence/sample-verification.json`；截图 01/02 的「排序与到期规则」框 |
| 学习者隔离（≥2 人，B 不见 A） | `evidence/pytest-full.log`（store/api/integration 隔离用例）；`evidence/sample-verification.json`（「B 看不到 A 的数据」）；`evidence/screenshots/02-overview-learnerB-isolation.png` |
| PowerContext 真实写入 / 读取（非 JSON / 自建库冒充） | `app/powercontext_client.py`（1.5.1 真实 HTTP 契约）；`evidence/pytest-full.log`（test_powercontext_integration.py 8）；`evidence/powercontext-audit.jsonl`；`evidence/live-openapi-1.5.1.json` |
| 新进程启动后状态恢复 | `evidence/pytest-full.log`（test_restart.py 1，真实子进程 kill→重启）；`evidence/restart-recovery-app.log`；截图 01/02（重启后列表 / 偏好一致） |
| 固定可重复样例（初始数据 / 步骤 / 预期 / 重置） | `examples/seed_sample.py`、`examples/verify_sample.py`、`examples/reset.py`；`evidence/seed-run.log`、`evidence/verify-run.log`、`evidence/sample-verification.json`、`evidence/sample-verification-audit.jsonl`；README「验证样例」 |
| 实际界面截图 | `evidence/screenshots/01-overview-learnerA.png`、`02-overview-learnerB-isolation.png` |
| 测试结果（命令 / 退出码 / 依赖版本 / 代码哈希） | `evidence/TEST-REPORT.md`、`evidence/pytest-full.log`、`evidence/pytest-collected.txt`、`uv.lock`、`pyproject.toml` |
| 组件读写及复用记录 | `evidence/powercontext-audit.jsonl`、`evidence/sample-verification-audit.jsonl`、`evidence/live-openapi-1.5.1.json` |
| Qoder 开发过程记录索引 | `evidence/DEV-PROCESS.md` |

## 6. 已验证能力（真实运行）

- **自动化测试 37 个全部通过，退出码 0**：规则 14 + 真实 PowerContext 集成 8 + 存储 9 + API 5 + 跨进程重启 1。集成测试由 `tests/conftest.py` 启动**真实** `powercontext server run` 子进程（独立 SQLite / 端口 / `POWERCONTEXT_HOME`），非模拟接口。原始输出见 `evidence/pytest-full.log`，用例清单见 `evidence/pytest-collected.txt`。
- **固定样例端到端 8/8 断言通过**（`VERIFY_EXIT=0`）：A 待复习==[特征值]、A 即将到期==[矩阵乘法]、特征值逾期 1 天、B 待复习==[索引]、B 看不到 A 数据、A 偏好 daily_goal=5 恢复、app-state 恢复选中、A 复习记录 2 条且含 Source 证据。见 `evidence/sample-verification.json`。
- **真实 PowerContext 读写**：remember / list / ETag(If-Match) 替换 / lifecycle forgotten / Source，逐请求审计留痕（`evidence/powercontext-audit.jsonl`）。
- **跨进程重启恢复**：真实子进程 kill 后新进程读回列表 / 偏好 / 选中态（`evidence/restart-recovery-app.log`、test_restart.py）。
- **浏览器实测**：增 / 删 / 改、记录复习（间隔按规则更新）、保存偏好、切换学习者；真实截图见 `evidence/screenshots/`。
- **公网展示站**：未登录客户端验证首页与静态资源 HTTP 200（见 §2）。

固定观察时刻：`T0=2026-11-08T09:00:00Z`、`T1=2026-11-08T10:00:00Z`、`T2=2026-11-11T09:00:00Z`，经可注入时钟（`ManualClock` / `STUDY_REVIEW_FIXED_NOW`）注入，不依赖运行日期。

## 7. 安装与体验

完整环境、精确依赖、干净环境安装 / 初始化 / 启动命令、PowerContext 接入方式、验证样例与测试命令、重启恢复、已知限制见 `README.md`；架构与规则设计见 `DESIGN.md`。速览：

```bash
cd qoder/study-review
uv sync                                       # 固定 powercontext[cli,server]==1.5.1
uv run python scripts/start_powercontext.py   # 终端 A：真实 PowerContext Server
uv run python examples/seed_sample.py --fixed # 终端 B：固定样例（幂等）
uv run python -m app                          # http://127.0.0.1:18081
uv run python examples/verify_sample.py       # 8 项断言
uv run python -m pytest                       # 37 用例
uv run python examples/reset.py --yes         # 安全软重置
```

## 8. 复用与许可

- 复用 **PowerContext**（oceanbase/powercontext，**Apache-2.0**），经其**官方 HTTP API** 调用，**未修改其源码**；依赖固定为 PyPI `powercontext[cli,server]==1.5.1`，`uv.lock` 锁定。
- 基线为官方竞赛分支 `2026-competition-ecosystem`；本作品全部新增代码原创，位于 `qoder/study-review/`。
- 展示站为原创静态 HTML/CSS，截图为真实运行画面（非设计稿、非伪造）。

## 9. 未完成项 / 已知限制

- **尚未开展真实用户效果评估**（无真实用户数据；不编造人数、节省时间、反馈或访问量）。
- 单机单实例本地演示；PowerContext 以 loopback 免认证运行，仅适合本地体验，不面向公网多租户。
- 复习调度为确定性规则，间隔上限 30 天；**无模型智能推荐**（亦不宣称）。
- 在线展示网站为**静态作品入口**，核心应用需本地运行（网站不冒充在线应用）。
- 展示站公网可达性已验证；核心应用的在线多租户部署不在本次交付范围内。

## 10. 开发过程记录

真实 Qoder 开发过程索引见 `evidence/DEV-PROCESS.md`（会话 `7fd73b89-e990-4457-876d-b2be68721bbe`）。该索引基于真实会话与工具调用整理，未伪造 Qoder 截图、账号信息或使用历史。