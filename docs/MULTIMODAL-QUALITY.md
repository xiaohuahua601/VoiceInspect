# 多模态诊断质量基线

## 当前链路

1. 用户选择设备并提交文字、语音或图片。
2. 图片保留原始资产，送入 EXIF 方向校正和 1600px 内的 VLM 预处理副本。
3. 本地 VLM 执行两轮 JSON 推理：第一轮提取客观观察/读数，第二轮复核候选异常。
4. Pydantic 校验字段、置信度和数组形状；设备类型别名、温度边界、泄漏/开盖/裸露/烧蚀/报警等强信号由确定性规则复核。
5. 没有观察、设备不匹配或没有带证据候选异常时，视觉阶段为 `needs_review`，不能当作成功诊断。
6. RAG 只检索已发布的维护、安全、故障案例和型号资料；`dataset_card` 不作为维修依据。
7. 助手 Markdown 之外保存结构化证据包，前端展示观察、读数、疑似异常、检查建议、安全提示和不确定性。

## 本地知识包

运行 `\.venv\Scripts\python.exe scripts\seed_device_knowledge.py --publish` 可索引四类通用知识包。通用资料不等同于厂商手册，具体阈值和维护周期必须以设备制造商资料复核。

## 数据集 ETL

运行 `\.venv\Scripts\python.exe scripts\build_dataset_summaries.py`，只为本地已下载 CSV 生成字段/标签/范围摘要。原始数据不进入诊断 RAG。公开数据集下载失败或未完成时，不得将空文件标记为已下载。

## 视觉评测门禁

`data/vision/manifest.jsonl` 是清单源。`\.venv\Scripts\python.exe evals\vision_manifest_check.py` 检查本地覆盖率。当前仅有一个合成空压机异常图，四类设备每类至少 12 张本地标注图片的发布门禁尚未满足；公开参考链接标为 pending，不计入 Recall 或误报率。