# VoiceInspect 开源数据资产

`catalog.json` 保存经过来源和许可核验的数据集目录。原始压缩包和解压文件只保存在本地 `data/datasets/raw/`，该目录被 `.gitignore` 忽略，不会提交到 Git。

数据资产分两类：

- `dataset_card`：许可明确、允许下载的数据集。可用脚本下载并记录 SHA-256。
- `dataset_catalog_only`：来源可追溯，但许可或下载权限未充分明确，只登记元数据，不自动复制文件。

原始传感器/音频数据不是问答手册，当前不会直接写入 RAG。脚本会把数据集字段、设备类型、故障标签、来源和适用边界作为知识卡片导入，供诊断回答引用；后续数据分析模块再读取 `raw/` 训练或评估模型。

运行：

```powershell
.\.venv\Scripts\python.exe scripts\import_open_datasets.py --download --publish
```

使用这些数据集时必须保留来源、许可证和对应论文引用。通用数据集不能替代现场设备型号手册，也不能单独作为维修结论依据。
