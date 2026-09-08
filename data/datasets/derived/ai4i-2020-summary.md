# ETL 数据摘要：AI4I 2020 工业预测性维护数据集

## 处理边界
这是由本地原始数据生成的字段与统计摘要，用于算法验证和数据字段问答，不是现场维修证据，也不替代制造商手册。

## 数据概况
设备类型：industrial_machine、rotating_equipment
行数：10000；字段数：14。
字段：UDI、Product ID、Type、Air temperature [K]、Process temperature [K]、Rotational speed [rpm]、Torque [Nm]、Tool wear [min]、Machine failure、TWF、HDF、PWF、OSF、RNF

## 数值范围摘要
{"UDI": {"min": 1.0, "max": 10000.0}, "Air temperature [K]": {"min": 295.3, "max": 304.5}, "Process temperature [K]": {"min": 305.7, "max": 313.8}, "Rotational speed [rpm]": {"min": 1168.0, "max": 2886.0}, "Torque [Nm]": {"min": 3.8, "max": 76.6}, "Tool wear [min]": {"min": 0.0, "max": 253.0}, "Machine failure": {"min": 0.0, "max": 1.0}, "TWF": {"min": 0.0, "max": 1.0}, "HDF": {"min": 0.0, "max": 1.0}, "PWF": {"min": 0.0, "max": 1.0}, "OSF": {"min": 0.0, "max": 1.0}, "RNF": {"min": 0.0, "max": 1.0}}

## 故障标签摘要
{"Machine failure": {"0": 9661, "1": 339}}

## 来源
来源页面：https://archive.ics.uci.edu/dataset/601/ai4i%2B2020%2Bpredictive%2Bmaintenance%2Bdataset
许可证：CC BY 4.0