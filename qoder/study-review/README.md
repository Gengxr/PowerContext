# 学习回顾台（Study Review Desk）

OceanBase 2026 生态赛 · Qoder 赛题作品。面向学生的**薄弱知识点管理 + 复习调度 + 学习记录**工具：
把「哪些知识点该复习、复习得怎样、下次什么时候复习」交给确定性规则与真实 PowerContext 持久化，
减少每次重新整理学习状态的时间。

- 代码仓库：https://github.com/Gengxr/PowerContext
- 分支：`qoder-study-review`（基于官方 `oceanbase/powercontext` 的 `2026-competition-ecosystem`）
- 交付目录：`qoder/study-review/`（本目录）
- 展示网站：见 `submission.md`（Qoder Sites 发布；核心应用按本文本地运行）

## 功能

- 创建 / 选择学习者（≥2 名），**每人一个 PowerContext Scope，数据完全隔离**。
- 添加知识点：课程、标题、笔记、掌握程度；支持编辑、删除（删除同时归档其复习记录）。
- 待复习列表：按**公开、可解释的确定性规则**排序（逾期天数降序 → 掌握程度升序 → 到期时间升序 → 标题 Unicode 码点序）。
- 记录复习结果（需要加强 / 基本掌握 / 已掌握），按规则更新间隔、掌握度与下一次复习时间，并留存 Source 证据。
- 保存学习偏好（每日目标、即将到期展示窗口）与当前进度 / 选中学习者。
- **重启恢复**：应用进程不落盘业务状态，重启后从 PowerContext 读回并实际用于待复习列表、偏好与界面。
- 不含模型智能推荐（亦不宣称）；全部为可测试的确定性规则。

## 环境与精确依赖

| 组件 | 版本 |
| --- | --- |
| Python | >=3.11,<3.13（验证用 3.12.16） |
| uv | 0.13.7（包管理 / 虚拟环境） |
| powercontext[cli,server] | **1.5.1**（PyPI 固定，见 `pyproject.toml` / `uv.lock`） |
| pytest（dev） | 8.4.2 |

持久化使用 PowerContext **官方 SQLite 后端**（`sqlite+aiosqlite:///`），基本记忆模式，**无需任何付费模型 API**。
除 PowerContext 外**不引入业务数据库**：PowerContext 是唯一业务存储（分工见 DESIGN.md）。

## 从干净环境安装 / 初始化 / 启动

```bash
# 0) 前置：安装 uv（https://docs.astral.sh/uv/），Python 由 uv 自动管理
cd qoder/study-review

# 1) 安装固定依赖（含 powercontext[cli,server]==1.5.1 与 dev 组 pytest）
uv sync

# 2) 终端 A：启动真实 PowerContext Server（数据只写本项目 runtime/，不影响默认安装）
uv run python scripts/start_powercontext.py          # 默认 http://127.0.0.1:18080

# 3) 终端 B：生成固定样例初始数据（幂等），再启动应用
uv run python examples/seed_sample.py --fixed
uv run python -m app                                  # 默认 http://127.0.0.1:18081

# 4) 浏览器打开 http://127.0.0.1:18081
```

可复现演示（固定观察时刻 T2，与文档样例完全一致）：

```bash
STUDY_REVIEW_FIXED_NOW=2026-11-11T09:00:00Z uv run python -m app
```

### 环境变量（见 `.env.example`）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| STUDY_REVIEW_PC_URL | http://127.0.0.1:18080 | PowerContext Server 地址 |
| STUDY_REVIEW_PC_TOKEN | 空 | 可选 Bearer Token（loopback 免认证） |
| STUDY_REVIEW_HOST / PORT | 127.0.0.1 / 18081 | 应用监听 |
| STUDY_REVIEW_AUDIT | runtime/audit.jsonl | 逐请求审计日志 |
| STUDY_REVIEW_FIXED_NOW | 空 | 可选固定时钟（ISO8601，仅演示/测试） |

## PowerContext 实际接入方法

通过**真实官方 HTTP API**（`app/powercontext_client.py`，契约存档 `evidence/live-openapi-1.5.1.json`，1.5.1）：

- 每个学习者 = 一个 Scope（`POST /v1/scopes`，幂等）；应用级 Scope 存 app-state。隔离边界即 Scope。
- 业务对象以 Atomic Memory 承载（`POST /v1/memory/remember`），kind 区分
  `knowledge-point` / `review-record` / `learner-preference` / `app-state`，text 为 JSON payload。
- 读取：`POST /v1/atomic-memory/list`（按 kind + states=active，cursor 分页）。
- 更新：`GET .../artifacts/atomic-memory/{id}` 取 ETag → `PUT` 带 `If-Match` 替换（乐观并发）。
- 删除：`POST /v1/atomic-memory/lifecycle` 置 `forgotten`（软删除/归档）。
- 每次复习另存一条 Source（`POST /v1/sources/content`）作为证据；并可用 `POST /v1/memory/search`、`/v1/context/prepare`。
- **应用进程不写任何本地业务文件**；重启后上述读取即恢复列表/偏好/选中态。

## 验证样例与测试

固定时间：`T0=2026-11-08T09:00:00Z`（创建）、`T1=2026-11-08T10:00:00Z`（A 复习）、`T2=2026-11-11T09:00:00Z`（观察）。

样例：A「线性代数」= 矩阵乘法 + 特征值；B「数据库」= 索引。A 对特征值记「需要加强」、矩阵乘法记「已掌握」。
T2 预期：A 待复习=[特征值]（逾期 1 天）、即将到期=[矩阵乘法]；B 待复习=[索引]；B 不见 A 数据；A 偏好 daily_goal=5。

```bash
uv run python examples/seed_sample.py --fixed   # 初始数据（幂等）
uv run python examples/verify_sample.py         # 8 项断言，全过退出码 0
uv run python -m pytest                         # 37 用例（规则/真实集成/存储/API/跨进程重启）
```

安全重置：

```bash
uv run python examples/reset.py --yes           # 软重置：经真实 API 将本应用条目置 forgotten
uv run python examples/reset.py --hard --yes    # 硬重置：仅删本项目 runtime/（需先停 Server）
```

证据与退出码/版本/源码哈希见 `evidence/TEST-REPORT.md`、`evidence/INDEX.md`。

## 重启恢复方法

1. 正常使用时所有状态已在 PowerContext（SQLite）。
2. 停止应用（Ctrl-C），重新 `uv run python -m app`。
3. 启动日志打印「恢复的当前学习者: …」；界面待复习列表、偏好、选中学习者与重启前一致。
   跨进程恢复由 `tests/test_restart.py`（真实子进程）与 `evidence/restart-recovery-app.log` 佐证。

## 目录结构

```
qoder/study-review/
  app/            后端（rules/models/store/powercontext_client/server）+ static/ 前端
  tests/          37 用例（含真实 PowerContext 集成与跨进程重启）
  examples/       seed_sample / verify_sample / reset
  scripts/        start_powercontext.py
  evidence/       测试报告/索引/开发过程/审计/契约/截图
  pyproject.toml  uv.lock  .env.example  .gitignore
  README.md  DESIGN.md  submission.md
```

## 已知限制

- 单机单实例本地演示；PowerContext loopback 免认证，不面向公网多租户。
- 复习调度为确定性规则，无模型推荐；间隔上限 30 天。
- 展示网站为作品展示入口，**核心应用需按本文本地运行**（网站不冒充在线应用）。
- 尚未开展真实用户效果评估（无真实用户数据）。

## 复用与许可

- 复用 **PowerContext**（https://github.com/oceanbase/powercontext ，**Apache-2.0**；PyPI `powercontext==1.5.1`）
  作为唯一存储/记忆组件，仅经官方 HTTP API 调用，**未复制/修改其源码**。
- 本作品新增代码为原创，全部位于 `qoder/study-review/`，未改动 minimax/stepfun/dify/gaode 等其他赛题目录；
  随上游 Apache-2.0 仓库提交。