# 证据索引（验收项 → 证据位置）

所有路径相对 `qoder/study-review/`。

| 验收项 | 证据 |
| --- | --- |
| 主要增删改查（知识点/复习/偏好/状态） | `evidence/pytest-full.log`（test_store.py 9、test_api.py 5）；`evidence/powercontext-audit.jsonl`；浏览器实测（见 TEST-REPORT §4） |
| 复习规则（可解释、确定性、固定时间） | `app/rules.py`；`evidence/pytest-full.log`（test_rules.py 14）；UI「排序与到期规则」框（截图 01/02）；`evidence/sample-verification.json` |
| 学习者隔离（≥2 人，B 不见 A） | `evidence/pytest-full.log`（test_store/test_api/test_powercontext_integration 隔离用例）；`evidence/sample-verification.json` check「B 看不到 A 的数据」；`evidence/screenshots/02-overview-learnerB-isolation.png` |
| PowerContext 真实写入/读取（非 JSON/自建库冒充） | `app/powercontext_client.py`（真实 HTTP 契约）；`evidence/pytest-full.log`（test_powercontext_integration.py 8）；`evidence/powercontext-audit.jsonl`；`evidence/live-openapi-1.5.1.json` |
| 新进程启动后状态恢复 | `evidence/pytest-full.log`（test_restart.py 1，真实子进程）；`evidence/restart-recovery-app.log`；截图 01/02（重启后列表/偏好一致） |
| 固定可重复样例（初始数据/步骤/预期/重置） | `examples/seed_sample.py`、`examples/verify_sample.py`、`examples/reset.py`；`evidence/seed-run.log`、`evidence/verify-run.log`、`evidence/sample-verification.json`、`evidence/sample-verification-audit.jsonl`；README「验证样例」 |
| 实际界面截图 | `evidence/screenshots/01-overview-learnerA.png`、`02-overview-learnerB-isolation.png` |
| 测试结果（命令/退出码/依赖版本/代码哈希） | `evidence/TEST-REPORT.md`、`evidence/pytest-full.log`、`evidence/pytest-collected.txt`、`uv.lock`、`pyproject.toml` |
| Qoder 开发过程记录索引 | `evidence/DEV-PROCESS.md` |
| 组件读写及复用记录 | `evidence/powercontext-audit.jsonl`、`evidence/sample-verification-audit.jsonl`、`evidence/live-openapi-1.5.1.json` |

## 文件清单

- `TEST-REPORT.md` — 测试与验证总报告（环境/版本/哈希/命令/退出码/限制）
- `INDEX.md` — 本索引
- `DEV-PROCESS.md` — Qoder 开发过程索引
- `pytest-full.log` — 全量测试原始输出（37 passed，PYTEST_EXIT=0）
- `pytest-collected.txt` — 用例清单（--collect-only）
- `sample-verification.json` / `sample-verification-audit.jsonl` / `verify-run.log` — 固定样例 8/8 验收及其审计
- `seed-run.log` — 初始数据生成输出
- `powercontext-audit.jsonl` — 演示期 PowerContext 逐请求读写审计
- `restart-recovery-app.log` — 新进程恢复启动日志
- `live-openapi-1.5.1.json` — 运行中服务器 OpenAPI 契约存档（1.5.1）
- `screenshots/` — 真实界面截图