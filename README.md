# VoiceInspect

VoiceInspect 是一个本地优先的工业设备现场多模态诊断助手。当前仓库包含 P0/P1 的真实可运行基线：本地账号、SQLite 持久化、设备和会话管理、Ollama 文本回答、知识文档导入、向量检索、引用展示和审计记录。

## 当前能力状态

| 能力 | 状态 |
|---|---|
| 文本诊断 | 已实现，调用本地 Ollama |
| PDF/DOCX/TXT 知识导入 | 已实现 |
| Embedding 与本地检索 | 已实现，SQLite 持久化向量 |
| 引用展示与资料不足提示 | 已实现 |
| 语音 STT | Provider 预留，需安装 faster-whisper 与模型 |
| 视觉 VLM | Provider 预留，需配置 Ollama 视觉模型 |
| TTS | 后续阶段 |
| 写工具与确认令牌 | 后续阶段 |

## 本地启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
Copy-Item .env.example .env
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

另一个 PowerShell 窗口启动前端：

```powershell
npm install
npm run dev
```

打开 http://127.0.0.1:5173，使用演示账号 `operator / change-me`。首次启动会创建 SQLite 数据库和 `A-01` 演示设备。

## 知识文档导入

知识库接口需要知识管理员或系统管理员令牌。当前默认系统管理员为 `admin / change-me-admin`，首次登录后应通过环境变量替换演示密码。文本导入接口：

```http
POST /api/v1/knowledge/text
Authorization: Bearer <token>
Content-Type: application/json

{"name":"空压机手册","content":"...","version":"1","device_model":"COMPRESSOR-A"}
```

## Docker

Docker 方案会将 SQLite 和本地数据挂载到 `data/`。Ollama 默认运行在宿主机，容器内必须使用 `host.docker.internal`，不能使用容器内的 `localhost`。模型权重、密码和 `.env` 不会打包进镜像。

## 测试

```powershell
python -m pytest
npm run build
npm run verify:premium
```

完整 MVP 还需要补齐本地 STT、VLM、TTS 并执行需求文档中的 AC-01 至 AC-08。任何未实际执行的模型评测或浏览器 E2E 都不会标记为通过。
