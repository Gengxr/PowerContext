# Qoder 开发过程记录索引

本作品的主要需求拆解、编码、调试与验证均在 Qoder Desktop 中由主开发智能体实际完成。
本文件为过程索引；**原始逐轮对话与工具调用记录**保存在本地 Qoder 会话转录中（不随仓库提交）：

- 会话 ID：`7fd73b89-e990-4457-876d-b2be68721bbe`
- 转录路径（本地）：`C:\Users\35053\.qoder-cn\projects\C--Users-35053-Documents-Qoder-2026-11-11-7fd73b89\7fd73b89-e990-4457-876d-b2be68721bbe.jsonl`

## 真实开发里程碑（按发生顺序）

1. **仓库/基线/范围核对**：检查 `D:\seekdb` 工作区、分支与远端（origin 误绑 Gengxr/seekdb）；新增 `upstream`=oceanbase/powercontext、`powercontext`=Gengxr/PowerContext；基于 `2026-competition-ecosystem` @ `d647275c3` 创建独立 worktree `D:\seekdb-qoder-study` 与分支 `qoder-study-review`，保留队友未提交文件、不触碰其他赛题目录。
2. **环境与依赖固定**：安装 uv 0.13.7 + CPython 3.12.16；`pyproject.toml` 固定 `powercontext[cli,server]==1.5.1`、`pytest==8.4.2`；生成 `uv.lock`。
3. **核实官方接口（不猜测）**：启动真实 PowerContext Server，下载运行中 `/openapi.json`（存档 `live-openapi-1.5.1.json`），发现 1.5.1 实际为 Atomic Memory 契约（remember→records、list、ETag PUT 替换、lifecycle forgotten），与 main 分支文档不同；据此编写 `app/powercontext_client.py`。
4. **实现应用**：`app/rules.py`（确定性复习规则）、`app/models.py`、`app/store.py`（每学习者一个 Scope 隔离）、`app/server.py`（stdlib HTTP）、`app/static/`（原生 JS UI，textContent 渲染防 XSS）；应用进程不落盘业务状态。
5. **调试与修复**：修正 1.5.1 契约差异（entry/citation→AtomicMemory/ref/ETag）；修正排序 tie-break 为标题 Unicode 码点序；修正真实时钟下 API 全流程断言；Windows 控制台 GBK 乱码用 `PYTHONIOENCODING=utf-8`。
6. **自动化验证**：37 用例（规则/真实集成/存储/API/跨进程重启）全过；固定样例 8/8；详见 `TEST-REPORT.md`。
7. **浏览器实测与截图**：browser-use MCP 真实操作 UI（增删改、复习、偏好、切换学习者、重启恢复），截图存 `screenshots/`；期间记录到一次人工试用产生的真实写入（审计可查），随后软重置+重seed 恢复文档样例态。
8. **证据整理**：审计、OpenAPI、测试日志、样例验收、截图、索引（本目录）。
9. **发布与提交**：Qoder Sites 展示站发布与 GitHub 推送结果见 `submission.md`（含正式 URL、branch、commit、UID）。

## 使用的 Qoder 能力 / 工具

- Qoder 主智能体：需求拆解、编码、调试、验证、文档。
- Bash / uv / git（worktree 隔离、按命令代理访问 GitHub/PyPI）。
- browser-use MCP：真实浏览器 UI 验证与截图。
- Qoder Sites（sites-building / sites-hosting skill）：展示网站发布。

## 声明

- 未伪造 Qoder 截图、账号信息或使用历史；本索引与转录为真实过程。
- 未开展真实用户效果评估（无真实用户数据），不编造人数/节省时间/反馈/访问量。