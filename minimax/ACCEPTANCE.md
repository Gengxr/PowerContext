# 验收映射
| 必做项 | 入口/证据 | 当前状态 |
|---|---|---|
| 能运行 | requirements.txt、verify.py | 以实际 reference 日志为准 |
| MiniMax 实际参与 | live 模式生成 generation.json 与 change.diff | **未完成：缺 API Key** |
| 上下文正确 | 02-context、09-reimport、10-updated-context | 由真实运行校验 |
| 数据库参与 | 01-ingest、context.database_query、sources.database_id | seekdb 实际读写 |
| 状态复用 | 07-save、08-resumed，独立 Python 进程 | PowerContext 实际读写 |
| 修改有效 | 03/04/05/06 日志，同一 tests_sha256 | reference 仅证明测试链路；正式需 live/replay |

## 固定行为
TargetTests：open / closed 精确筛选；非法状态及空输入非法状态抛 ValueError。
RegressionTests：默认排序及完整字段、不修改输入、有效状态空输入、筛选后字段与副本。
before 缺少筛选功能，预期 4 个目标测试失败；回归 4 个通过。
参考实现目标 4 个、回归 4 个通过。不能把参考实现称为 MiniMax 生成。
规格 v2 用于演示重导入更新；同一次 before/after 测试始终使用相同文件。
