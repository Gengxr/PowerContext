# 阶跃星辰 · 浏览器本地知识库
资产全部在 stepfun，基于 powercontext/2026-competition-ecosystem。
## 启动
Node.js 20.19+，Chrome / Edge 最新版。无模型 API Key，无云端推理。
```sh
cd stepfun
npm ci
npm run build
npm start
```
打开 http://localhost:3070 。首次运行 seekdb-js 自动下载当前系统原生组件。
默认嵌入式数据库为用户主目录 .stepfun-seekdb，支持 Windows x64、Linux x64/arm64、
macOS arm64。不要把 WSL 数据库存到 /mnt/d，可用 SEEKDB_PATH 指定 Linux 路径。
数据库不需要预置内容，前端点击“导入样例”即可从空库初始化。
npm 的 legacy-peer-deps 仅避免 seekdb 默认 embedding peer 的 workspace 发布问题；
本项目显式 embeddingFunction:null，不安装或调用任何服务端 embedding 模型。
如原生组件下载受网络影响，使用可访问网络，或配置 SDK 官方
SEEKDB_BINDINGS_BASE_URL/SEEKDB_BINDINGS_CACHE_DIR。
也可通过 SEEKDB_HOST、SEEKDB_PORT、SEEKDB_USER、SEEKDB_PASSWORD 连接现有 seekdb
server（test 数据库）；不要把密码提交到仓库。

## 操作与验证
1. 名称填 notes，选择 FP16，点击“导入样例”，等进度及索引刷新完成。
2. 查询 How can I reset my password?，应显示 password 原文。
3. 导入新 .txt/.md 后查询其中内容。800 字符分块，文件名+偏移为稳定 ID，
   相同 ID upsert 更新；重复导入不产生重复 ID。不提供文件删除功能。
4. 切换知识库名称导入另一份文档；列表选择已有知识库，结果应隔离。
5. 勾选强制 WASM，重复导入和查询，界面显示实际后端。
   不支持 WebGPU / shader-f16 时自动选择 WASM；WebGPU 加载异常也自动重试 WASM。
6. “运行实验”执行固定语料、8 个查询、每配置 3 轮，并导出 stepfun-results.json。
   基线 FP32/WASM/batch1；INT8/WASM/batch1 与 batch8（隔离批处理优化）；
   FP16/优先WebGPU/batch8。记录实际后端，降级结果不能冒充 WebGPU。
7. 把实际导出的日志放到 stepfun/results/，更新 TECHNICAL.md 实测表并提交后提测。

## 计时和模型
模型：Xenova/all-MiniLM-L6-v2，revision
751bff37182d3f1213fa05d7196b954e230abad9，Apache-2.0。
Transformers.js 3.8.1；上游预导出 ONNX FP32、FP16、INT8 动态量化版本。
明确 dtype=fp16/q8/fp32，不在下载时假装进行量化。
只在浏览器 Worker 内 feature-extraction、mean pooling、L2 normalize，384 维。
模型下载源 https://huggingface.co/Xenova/all-MiniLM-L6-v2 。
运行时文档 https://huggingface.co/docs/transformers.js/guides/dtypes 。
SDK https://github.com/oceanbase/seekdb-js 。

实验从实际下载的 ONNX ArrayBuffer.byteLength 测量体积，统计同类模型权重文件，
不含各精度共用 tokenizer、配置、WASM；此模型每精度一个 ONNX 文件。
报告 compression=fp32_bytes/quantized_bytes。检索质量 Recall@5：
8 个查询各有一个相关文档 ID，命中数/8。样例是小型英文集，不代表中文/通用基准。
原始每轮数据保留；第一轮与后两轮分开，中位数仅用后两轮 warm 数据。
模型缓存由浏览器管理。真正冷下载请清理站点缓存并重启页面；
基准体积测量本身可能预热 HTTP 缓存，不将 loadMs 称为纯冷下载时间。
阶段包括 loadMs（下载+初始化）、embedMs、writeMs、refreshMs、
queryEmbedMs、searchMs、endToEndMs。完整冷下载分离计时尚待补充。

## 当前验证边界
构建/服务启动与数据库验证见 results/validation.json（若已生成）。
**浏览器完整模型推理、WebGPU/WASM 双路径、量化质量与性能表必须以实际运行日志为准。**
本次本地浏览器预览超时，不能宣称这些验收项已通过；不填造性能数字。
长文本有 tokenizer 长度上限，适合小型英文文本库；请避免敏感资料。
服务仅监听本机，无认证，不适合直接公开部署。
