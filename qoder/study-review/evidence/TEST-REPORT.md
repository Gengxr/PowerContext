# 测试与验证报告（学习回顾台）

- 报告日期：2026-11-12
- 代码基线：oceanbase/powercontext `2026-competition-ecosystem` @ `d647275c3`，独立分支 `qoder-study-review`
- 交付目录：`qoder/study-review/`
- 源码哈希（app/ tests/ examples/ scripts/ 全部文件 + pyproject.toml + uv.lock，共 23 个文件，SHA-256）：
  `b955bb49cc2a312debfabf5bba6449af512eda5999118f886e482d28edc34a70`

## 环境 / 依赖版本

| 组件 | 版本 |
| --- | --- |
| CPython | 3.12.16（uv 管理） |
| uv | 0.13.7 |
| powercontext[cli,server] | 1.5.1（PyPI 固定） |
| pytest | 8.4.2 |
| PowerContext 持久化 | SQLite（`sqlite+aiosqlite:///`，官方后端） |
| PowerContext 模式 | 基本记忆模式（basic memory），无需模型 API；loopback 免认证 |

依赖锁定见 `uv.lock`；精确声明见 `pyproject.toml`。

## 1. 自动化测试（真实 PowerContext 集成，非模拟接口）

命令（在 `qoder/study-review/` 下）：

```
uv sync
uv run python -m pytest
```

本次证据运行命令与退出码：

```
./.venv/Scripts/python.exe -m pytest -q   # 原始输出见 pytest-full.log
PYTEST_EXIT=0
```

结果：**37 passed，退出码 0**（`pytest-full.log` 中 37 个 `.`；`-q` 与 addopts 叠加为 `-qq` 故无汇总行，用例清单见 `pytest-collected.txt`）。

| 测试文件 | 用例数 | 覆盖 |
| --- | --- | --- |
| tests/test_rules.py | 14 | 复习间隔/掌握度/到期/排序/逾期天数等纯规则（固定时间） |
| tests/test_powercontext_integration.py | 8 | 真实 HTTP 契约：health、scope 幂等、remember/list/replace(ETag)/forget、过期 ETag 拒绝、Source+search、context/prepare、分页、scope 隔离 |
| tests/test_store.py | 9 | 业务 CRUD、复习调度、删除归档记录、偏好、app-state、学习者隔离、固定时间 overview、新客户端读回 |
| tests/test_api.py | 5 | 应用 HTTP API：health、全流程、隔离、错误处理、静态资源 |
| tests/test_restart.py | 1 | 跨进程恢复：真实子进程 seed→app1 断言→kill→app2 断言+切 B→kill→app3 断言 B 选择持久化 |
| 合计 | 37 | |

集成测试由 `tests/conftest.py` 在临时目录启动**真实** `powercontext server run` 子进程（独立 SQLite、独立端口、隔离 `POWERCONTEXT_HOME`），测试结束自动终止；不使用 mock 接口替代真实集成。

固定时间：`T0=2026-11-08T09:00:00Z`、`T1=2026-11-08T10:00:00Z`、`T2=2026-11-11T09:00:00Z`，通过可注入时钟（`ManualClock` / `STUDY_REVIEW_FIXED_NOW`）注入，不依赖运行日期。

## 2. 固定样例端到端验收（真实 PowerContext）

命令：

```
uv run python examples/seed_sample.py --fixed     # 初始数据（幂等）
uv run python examples/verify_sample.py           # 8 项断言
```

本次运行：`VERIFY_EXIT=0`，**8/8 PASS**（`verify-run.log`、`sample-verification.json`、`sample-verification-audit.jsonl`）。

断言：A 待复习==[特征值]；A 即将到期==[矩阵乘法]；特征值逾期 1 天；B 待复习==[索引]；B 看不到 A 数据；A 偏好 daily_goal=5 恢复；app-state 恢复选中；A 复习记录 2 条且含 Source 证据。

## 3. 跨进程 / 重启恢复

- 自动化：`tests/test_restart.py`（真实子进程，见上）。
- 演示实证：`restart-recovery-app.log` 为新进程启动日志，打印 `恢复的当前学习者: scp_1wxj...`（从 PowerContext app-state 读回），随后 UI 待复习列表与偏好与重启前一致（截图 01/02）。
- 应用进程不落盘任何业务状态，全部经 PowerContext HTTP API 读写，故重启即恢复。

## 4. 界面实测（浏览器）

真实浏览器操作并截图（`screenshots/`）：
- 01-overview-learnerA.png：A 概览，特征值逾期 1 天在待复习首位、矩阵乘法在即将到期、偏好 5、复习历史 2 条。
- 02-overview-learnerB-isolation.png：切换 B 后仅见索引（逾期 3 天）、偏好 3、无 A 任何数据。
- 另实测：添加/编辑/删除知识点、记录复习（间隔按规则更新）、保存偏好、切换学习者；全部经真实 API 落库（见 `powercontext-audit.jsonl`）。

## 5. 组件读写 / 复用记录

- `powercontext-audit.jsonl`：演示期应用对 PowerContext 的逐请求审计（method/path/status/耗时/scope/kind），含 remember/list/PUT(If-Match)/lifecycle forget/sources 等真实读写。
- `sample-verification-audit.jsonl`：样例验收独立审计。
- `live-openapi-1.5.1.json`：运行中服务器 `/openapi.json` 存档（version 1.5.1，142 paths），为客户端契约依据。
- `seed-run.log`：初始数据生成输出。

## 已知限制

- 单机单实例演示；PowerContext 以 loopback 免认证运行，仅适合本地体验，不面向公网多租户。
- 复习调度为确定性规则，不含模型智能推荐（亦不宣称）。
- 展示网站为作品展示入口，核心应用按 README 本地运行（网站不冒充在线应用）。