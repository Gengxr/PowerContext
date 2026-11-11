# 规有所依：可审计的 SDD 工程上下文
## 当前交付状态（请先读）
**本提交尚不具备题目六项全通过条件，不建议直接提测。**
参赛者尚无 MiniMax API Key，所以没有真实 MiniMax 开发记录。
`sample/reference/` 是人工编写的基础设施测试参考实现，不是模型生成结果。
`evidence/verified-reference/`（若验证完成）仅证明实际 seekdb / PowerContext 集成和测试流程；
不能替代 MiniMax 实际参与。禁止把 reference 日志改名当作模型记录。

本作品基于官方 powercontext 的 `2026-competition-ecosystem` 分支，
所有资产仅在 `minimax/`。本地目录仍是 D:\seekdb，但本题不使用上一题 seekdb C++ 基线。
推送至 Gengxr/seekdb 的独立 `minimax-sdd-submit` 分支。
平台需绑定该仓库并指定此分支/最新提交；是否允许该仓库名以赛事平台规则为准。

## 环境与安装
Linux x86_64 / Python 3.12；Windows 请在 Ubuntu WSL 中运行。
本地嵌入式 seekdb，无需 Docker、独立数据库服务或外部 embedding 服务。
建议至少 4 GB 可用内存、3 GB 磁盘。运行数据库放在 Linux 原生目录 `~/.cache/minimax-sdd/`（不提交），可通过 SDD_RUNTIME_ROOT 修改；WSL 不要把数据库放在 /mnt/d。
```bash
cd /mnt/d/seekdb/minimax
python3 -m venv ~/.venvs/minimax-sdd
source ~/.venvs/minimax-sdd/bin/activate
pip install -r requirements.txt
```
PowerContext 精确固定源码 commit；Python 其余依赖版本见 requirements.txt，
实际运行版本见 evidence 下 environment.json。首次安装需联网。
PowerContext 使用官方 SDK 的 SQLiteProfile + SourceRepository + ContentSourceAdapter，
SQLite 只存 PowerContext 状态；工程资料由真正 seekdb 存储和检索。

## 验证样例及必需来源
任务 ticket-status：为 list_tickets 增加 open/closed 精确筛选。
必须保持不传筛选时全量返回、按 id 升序、字段不丢失、输入不被修改及空输入行为。
规格 SDD-002 同时规定非法状态抛 ValueError；v2 增补错误消息约束。
必要来源列于 sample/manifest.json：
- sample/specs/tickets.md：SDD-001、SDD-002、SDD-003。
- sample/before/tickets.py：list_tickets。
- sample/tests/test_tickets.py：TargetTests 与 RegressionTests。
- sample/data.json：初始数据。
每条检索结果含真实文件位置、行号、内容 SHA256、数据库文档 ID。
规格文件修改后必须重新 ingest；内容与索引不一致时拒绝返回旧资料。

## CLI 输入输出
以下命令均从 minimax 目录执行。stdout 为结果 JSON，seekdb 某些版本另有启动提示。
```bash
python -m sdd ingest --source sample --runtime ~/.cache/minimax-sdd/manual
python -m sdd context --source sample --runtime ~/.cache/minimax-sdd/manual
python -m sdd save --source sample --runtime ~/.cache/minimax-sdd/manual --state-file progress.json
python -m sdd context --source sample --runtime ~/.cache/minimax-sdd/manual
```
progress.json 由调用者提供，例如：
```json
{"completed":["review_specs"],"todo":["implement"],"validation":{}}
```
ingest：输入 manifest 和真实文件，更新 seekdb 任务文档。
context：输入任务 manifest，输出数据库检索结果和 PowerContext 最新状态。
save：将任务进展作为 PowerContext Source 保存。
重启后 context 使用前次状态，将 next_action 从 implement_and_test 改为
review_previous_results，并把验证结果一起提供给开发助手。

## 无密钥基础设施验证（不能算 MiniMax 验收）
```bash
python verify.py --mode reference --output evidence/reference-new
```
顺序：导入 → DB 检索 → 初始空状态 → 原代码目标测试失败、回归通过 →
人工参考实现同组目标/回归测试通过 → 写 PowerContext →
新进程重启读状态 → 更新规格并重新导入 → 检索确认 v2。
日志逐项记录命令、退出码、源文件和测试 SHA256。
输出目录及同名 runtime 必须不存在；重置最安全方式是选用新的输出名称。
已有历史证据永不覆盖。

## 补齐真实 MiniMax 开发记录（必须）
1. 在 MiniMax 开放平台获取可调用文本模型的 API Key。
2. 复制 .env.example 为 .env，在本机填入密钥；.env 已忽略，勿提交。
   国内站 https://api.minimaxi.com/v1；国际站 https://api.minimax.io/v1。
   模型默认 MiniMax-M2.5，需确认账号实际权限；Token Plan 接入限制以账号为准。
3. 执行：
```bash
python verify.py --mode live --output evidence/submission
```
此命令会向 MiniMax 发送从 DB 检索所得的上下文及恢复状态，只允许模型修改
tickets.py，保存请求/最终代码/响应标识/用量（不保存密钥或私有思维链）。
实际模型代码必须通过与 before 完全相同的测试；失败会停止，不伪造通过结果。
成功后 evidence/submission 包含 after 快照、change.diff、开发记录、测试结果、
数据库检索日志和 PowerContext 写入/复用日志。
4. 检查所有材料，提交 evidence/submission，推送新的 commit 后再提测。
   当前未配置密钥，不能承诺模型调用必定成功或生成必定通过。
5. 裁判可不重复消耗模型额度，复用已提交的真实记录：
```bash
python verify.py --mode replay --record evidence/submission/generation.json --output evidence/judge-replay
```
replay 从模型记录的 final_content 重建修改后代码并重新执行 DB、状态和测试流程；
它不是新的 MiniMax 调用，记录真实性仍由评审核对。

## 已知限制
- 任务范围由显式 manifest 声明；使用 seekdb metadata 查询，不宣称语义向量召回。
  显式 2 维占位向量仅满足 collection schema，不参与排序/选择。
- 不支持多进程同时打开同一 embedded seekdb 路径；CLI 调用应串行执行。
- 单次模型生成、不自动修复失败补丁。所有失败保留日志。
- 模型候选代码有基础 AST 检查及超时，但不构成安全沙箱；应仅对可信任务运行。
- 缺少 MiniMax 真实记录意味着依题意整题不能获得 20 分。

详见 DESIGN.md、ACCEPTANCE.md 和 SOURCES.md。
