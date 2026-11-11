# 一页技术说明
## 模块结构
CLI / verify.py → manifest 文档导入 → seekdb engineering collection
→ 按 task 查询规格、代码、测试、数据 → 校验来源路径/哈希
→ 合并 PowerContext 任务状态 → MiniMax HTTP 代码修改
→ 同一组功能与回归测试 → PowerContext 保存 → 新进程恢复。

## 三项技术分工
**MiniMax**：OpenAI-compatible HTTPS chat/completions，真实 live 模式中根据工程
上下文生成完整 tickets.py。记录请求上下文、公开最终代码、响应标识与 usage。
reference 模式由人工参考实现替代，仅开发测试用；不声称满足 MiniMax 必做项。
**seekdb**：pyseekdb Embedded Client，工程文档和 metadata 持久存储在本地 seekdb
原生数据库。context 输出直接来自 collection.get(where={task:...})，不是从文件
拼凑固定答案。文件读仅用于导入和检索后来源一致性校验。
**PowerContext**：固定源码版本 SDK，官方 SourceRepository 持久保存任务记录，
按 scope/task 读取最新 journal 项；SQLiteProfile 是 PowerContext 的存储后端。
重启后读取 completed/todo/validation 并改变 next_action，恢复信息进入模型上下文。

## 规格变更
同一文档 ID 重新导入替换内容；清除该任务的旧文档以避免已删除资料残留。
spec v1/v2 留有独立证据快照。查询验证内容哈希，未重新导入就拒绝过时索引。

## 证据与边界
固定测试集：before 应有真正断言失败，不能有导入或启动 ERROR；
after 要求目标和回归全部通过。每条日志绑定代码/测试哈希。
所有样例、模块和证据均放 minimax。模型不能修改测试或其他赛题。
不复原完整 Agent 会话；保存并实际复用任务状态已覆盖题目基础要求。
