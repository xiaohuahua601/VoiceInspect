# VoiceInspect

VoiceInspect 是一个本地优先的工业设备现场多模态诊断助手。当前仓库包含 P0/P1 的真实可运行基线：本地账号、SQLite 持久化、设备和会话管理、Ollama 文本回答、知识文档导入、向量检索、引用展示和审计记录。

## 当前能力状态

| 能力 | 状态 |
|---|---|
| 文本诊断 | 已实现，调用本地 Ollama |
| PDF/DOCX/TXT 知识导入 | 已实现 |
| Embedding 与本地检索 | 已实现，SQLite 持久化向量 |
| 引用展示与资料不足提示 | 已实现 |
| 语音 STT | 已接入 faster-whisper Provider；权重需本地下载 |
| 视觉 VLM | 已接入 Ollama JSON Provider；需配置已安装的视觉模型 |
| TTS | 已接入 Windows SAPI Provider；容器环境按能力状态降级 |
| 写工具与确认令牌 | 已实现草稿、确认、幂等故障记录和审计 |

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
## P2-P5 能力配置

语音依赖已经写入 pyproject.toml 的 audio extra。

安装命令：python -m pip install -e ".[test,audio]"

faster-whisper 首次使用需要下载 STT_MODEL_SIZE 对应权重。当前默认值是 small，下载失败时 API 会保留文字/图片能力并返回 STT_UNAVAILABLE 降级状态。

视觉能力通过 Ollama 配置。设置 OLLAMA_VISION_MODEL 为已安装的视觉模型标签，并使用 ollama list 检查。不要把文本模型当作视觉模型。GET /api/v1/capabilities 会检查模型标签是否存在；本轮环境中没有完成 6GB 视觉模型下载，因此视觉能力仍显示为不可用。

## 新增业务接口

- GET /api/v1/capabilities
- POST /api/v1/assets
- POST /api/v1/messages：支持 audio_asset_id 和 image_asset_id
- POST /api/v1/tasks/{task_id}/retry
- WS /api/v1/ws/sessions/{id}?access_token=<token>&last_event_seq=0
- POST /api/v1/tool-drafts
- POST /api/v1/confirmations/{token}
- GET /api/v1/audit-events
- POST /api/v1/tts

故障记录只能通过确认令牌创建，令牌绑定用户、草稿参数哈希和过期时间；重复确认返回原记录，不重复写入。

## 数据库迁移

首次创建或升级数据库：python -m pip install -e .，然后执行 alembic upgrade head。

应用启动仍会执行安全的 create_all 兼容初始化；生产部署应优先执行 Alembic 迁移并备份 data/db/voiceinspect.db。