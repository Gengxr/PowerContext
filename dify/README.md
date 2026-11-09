# 明日失物招领处

你接手一间只接收明日失物的柜台。你可以查验证据，也可以改写一次未来。改写会改变真正的失主：昨天查到的证据仍保留在档案中，但不能再当作当前时间线的依据。把东西交还、误交或封存，都会留下无法被模型随意改写的结局。

这是 OceanBase 生态赛 Dify 赛题的参赛实现，使用 Dify Chatflow 编排和真实 seekdb 持久化。三件原创虚构失物为末班车票、雨的借条、空白留声片。没有使用真实个人信息。

公开试玩：[明日失物招领处](https://udify.app/chat/6X83sMj42azMRYaC)。填写自己保存的随机档案号，选择失物，发送“开门”。请勿用验证样例中的档案号开启新游戏，那些档案已经结案。

## 当前验证边界

2026-11-09 已完成 Dify Cloud 实际导入、五步剧情全流程、模型真实叙述、新对话恢复、公开版恢复与发布。当前公开发布版本为 #2。结案追踪中的8个业务节点全部成功，模型节点实测耗时28.558秒、约3.095K tokens；公开版状态查询耗时25.45秒、3,041 tokens。所有模型输出和回执均来自实际运行，见 `evidence/验证报告.md`、对话文本及截图。

真实 seekdb 后端另通过7项规则/DSL边界测试、并发重复请求、事务回执、错误认证、进程重启和服务器重启后恢复测试。正式比赛评分另以平台提测结果为准。当前试玩后端使用临时 Cloudflare Quick Tunnel；服务器或隧道重启后需按下文更新地址，复现不依赖这条临时地址。

## 目录

- `workflow/app.yaml`：基于实际运行的 Cloud 导出，将开场白按已核验的公开版本 #2 补齐；11个业务节点及连线与实测导出一致。服务密钥为空，复现时替换后端地址并配置密钥。
- `workflow/明日失物招领处.ifpkg`：同一完整 DSL 的 Dify 1.18+ 应用包，包含开场白，已核验排除真实密钥；来源和摘要见导出校验记录。
- `lost_found/`：API、剧情状态机、真实 seekdb 事务存储及全部初始化剧情。
- `scripts/`：安装、启动、停止、生成 DSL、后端验收和重启验收。
- `requirements.lock.txt`：实际运行环境的完整依赖版本。
- `evidence/`：实际后端运行证据。
- `验收样例.md`：Dify 内完整试玩、反例与复核方法。

## 从空环境运行后端

已验证环境为 Linux x86_64、Python 3.12；最低 Python 3.11。使用可写的 SSD 目录，预留至少 2GB 磁盘和 1GB 内存。无需 Docker、sudo、GPU 或已有 OceanBase 服务。

```bash
cd dify
bash scripts/setup.sh
bash scripts/start.sh
curl http://127.0.0.1:8038/health
venv/bin/python scripts/verify_backend.py
```

首次初始化会创建 `private/runtime.env`，生成至少 24 字符的随机 `LF_API_TOKEN`；不会输出口令。默认数据库目录为当前账号家目录的 `.local/share/tomorrow-lost-found/seekdb`，可以在启动前修改 `LF_DATA_DIR` 指向新的独立目录。脚本仅启动本项目单进程服务，监听 `127.0.0.1:8038`，默认绑定两个可用 CPU。数据库通过 pylibseekdb 启动，Linux 默认仅用本地 Unix socket，不开放数据库 TCP 端口。

首次启动自动建表、导入 `cases.json`。已有档案不会被清空；若剧情种子版本冲突则明确拒绝启动，需换新数据目录或自行迁移。不要直接用新的剧情覆盖旧档案。

```bash
# 验证完整业务，再重启，仅终止核对 PID、工作目录及命令行均匹配的本项目服务。
venv/bin/python scripts/verify_backend.py
bash scripts/stop.sh
# 等待 backend.log 显示 Application shutdown complete 后启动。
bash scripts/start.sh
# 等待 /health 可达，再运行：
venv/bin/python scripts/verify_persistence.py
```

## 接入 Dify Cloud

Dify Cloud 的 HTTP 节点无法访问部署者的 `127.0.0.1`。请通过自己配置的 HTTPS 域名反向代理到 8038 端口，并保留 `Authorization` 请求头；不要暴露数据库端口。服务会校验 Bearer 密钥。

也可为复现测试使用 Cloudflare 官方 Quick Tunnel：

```bash
bash scripts/start_tunnel.sh
# 从 private/tunnel.log 取得 https://...trycloudflare.com 根地址。
```

脚本只转发本项目 HTTP 端口，下载官方 cloudflared 2026.10.7 并核验官方发布摘要 SHA256。Quick Tunnel 是临时测试服务：没有可用性保证，停止进程后地址失效，重启时地址变化。长期试玩请配置稳定域名。每次地址变化后，必须同步更新 Dify 的 `BACKEND_URL` 并重新发布。

1. 已实测 Dify Cloud，DSL版本0.7.0。在现有 Chatflow 左上角菜单选择“导入应用”，选 `workflow/明日失物招领处.ifpkg`。应用包格式需要Dify 1.18+；自部署还必须确认所用版本支持DSL 0.7.0。本项目未在旧版自部署Dify上验收，不保证早期版本兼容。
2. 安装应用列出的 `langgenius/openai:1.1.0` 依赖。在模型供应商中配置可用的 GPT-5；也可在“值夜人叙述”节点选择自己可用的聊天模型。模型服务账号、额度和凭证需由复现者自行提供，不包含在包中。
   本作品使用结构化剧情和事务存储，不需要Embedding、Rerank或额外知识库服务。后端配置占位示例见 `config/runtime.env.example`，实际首次配置由初始化脚本生成。
3. 在“环境变量”中将 `BACKEND_URL` 改为 HTTPS 后端根地址（不要尾斜杠），将 Secret 类型的 `LF_API_TOKEN` 填为 `private/runtime.env` 中对应值。公开包有意不包含实际密钥，不能空着运行。
4. 打开预览，按 `验收样例.md` 跑完整对话，检查节点运行记录中 HTTP 确实返回真实回执，模型节点确实完成叙述。
   如果覆盖导入到已有应用后开场白没有显示，在“功能→对话开场白”启用并填写 `app.yaml` 中的开场白，再发布；本次实测也按此方式核对了公开页。
5. 点击发布，通过访问入口取得公开试玩地址；新开对话使用同一档案号发送“状态”，确认跨会话恢复。
6. 对最终已运行版本再次导出，关闭“导出密钥值”。将其作为最终 DSL/应用包交付，附实际运行截图、节点日志及公开试玩链接。

若需要生成仅用于本人导入的已配置包，可以运行：

```bash
venv/bin/python scripts/build_dsl.py --backend-url https://你的域名 --live-secrets
```

产物为 `private/configured.ifpkg`，包含服务密钥，仅供导入自己的 Dify 应用，不可公开提交。直接运行 `scripts/build_dsl.py` 会重新生成不含密钥的开发流程，并覆盖 `workflow/` 的归档文件；正式提交应使用实际运行后从 Dify 再次导出的文件，不要把开发生成文件替代已验收的导出。

## 工作流和真实数据库使用

Dify 负责用户输入、JSON 编码、输入分支、HTTP 读取与结算、回执校验、错误分支、模型叙述和最终输出。代码节点只做字符串与 JSON 处理，外部访问通过 HTTP 节点完成。HTTP 超时会提示先查询状态，避免把可能已完成的动作误报成未执行。

seekdb 是游戏档案的真实存储：`lf_cases` 存储剧情种子，`lf_sessions` 存储当前状态，`lf_requests` 存储去重回执，`lf_events` 存储每次有效变化。同一档案行锁定后，在一个事务中更新状态并登记事件和请求回执；相同请求 ID 的重试返回原回执，不重复扣币。相同 ID 配不同指令返回 409。进程重启后从数据库读回同一结局。

档案由“档案号＋失物编号”确定，不依赖 Dify 的内存或聊天历史。档案号区分大小写，应自选随机串并妥善保存，不要填真实身份标识。剧情规则及归属由状态机判定；模型只接收公开证据，已查验的旧线索标记为历史。模型失败时仍可展示原始回执，但验收时必须单独确认至少一次模型真实运行成功，不能把兜底叙述当作模型运行证据。

## 提交范围

按照题面，最终文件进入报名团队 `Gengxr/PowerContext`、从官方 `2026-competition-ecosystem` 分支建立的独立 Dify 提交分支根目录 `dify/`。只提交源码、全部 DSL、数据种子、安装依赖、说明、验收样例与脱敏的实际证据；不要提交 `private/`、运行数据库、真实密钥、日志、虚拟环境或下载的二进制文件。不要误用高德的分支及 Commit id。

官方依据：[Dify 赛题](https://open.oceanbase.com/train/detail/21?questionId=600076)、[题面详解](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/lhfslihtnnb8yqh6)、[Dify 导入与导出](https://docs.dify.ai/en/cloud/use-dify/workspace/export-import-apps)、[HTTP 节点](https://docs.dify.ai/en/cloud/use-dify/nodes/http-request)、[Code 节点](https://docs.dify.ai/en/cloud/use-dify/nodes/code)、[seekdb Python bindings](https://github.com/oceanbase/seekdb-bindings/tree/main/python)、[Quick Tunnel 限制](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。
