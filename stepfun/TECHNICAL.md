# 一页技术说明
**结构**：浏览器 Web Worker（Transformers.js）→ 本机 Express →
seekdb-js 1.4.0 → embedded seekdb / server。只有 Worker 计算文档与查询向量。
后端拒绝缺失或非 384 维向量，没有文本转向量替代路径。

**量化**：公开 MiniLM，固定 revision 751bff37182d3f1213fa05d7196b954e230abad9。
使用同一仓库 ONNX FP32 / FP16 / INT8（q8）产物，来源与许可见 README。
模型文件体积由实验按钮实际读取字节数；压缩比和质量变化由相同语料测量。
不能把模型仓库标称大小当成本机性能实测。

**后端**：显式 device:webgpu，检查 GPU adapter 和 FP16 shader-f16；
不可用或 WebGPU 加载失败时自动 WASM。界面显示实际后端，不隐藏降级。
允许强制 WASM 复现无 GPU 场景。

**数据库**：collection 内保存 id、document、metadata.source、384维 cosine 向量，
SDK 自动建全文与向量索引。hybridSearch 同时传全文 query 和 knn.queryEmbeddings，
rank.rrf 由数据库 DBMS_HYBRID_SEARCH 执行，前端只展示结果。
upsert 后 await refresh_index，完成后才允许查询。

**状态与优化**：批量8编码对比单条编码；Worker 常驻并复用 pipeline，
同一精度不重复加载；每次导入批量写入后仅刷新一次。稳定文档 ID 支持增量 upsert，
库名含模型精度，防止精度切换造成未声明的混用。UI 忙时禁用切换，
服务端串行操作避免写入/刷新/查询竞态。

**实验状态**：浏览器预览环境超时，尚无模型推理实测结果，以下均待真实导出日志。
|配置|模型字节|吞吐|检索延迟|端到端|Recall@5|
|---|---|---|---|---|---|
|FP32/WASM/batch1|待测|待测|待测|待测|待测|
|INT8/WASM/batch1|待测|待测|待测|待测|待测|
|INT8/WASM/batch8|待测|待测|待测|待测|待测|
|FP16/WebGPU/batch8|待测|待测|待测|待测|待测|
固定语料与相关性标注在 web/data.js。实验记录浏览器、CPU线程数、模型 revision、
实际后端和批大小；另需人工记录设备型号、内存、GPU与驱动。
本表尚未完成，不能声称作品已满足全部性能与质量验收。
