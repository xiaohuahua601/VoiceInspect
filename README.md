# VoiceInspect

VoiceInspect 是一个本地优先的工业设备现场多模态诊断助手。当前仓库已实现 P0-P5 的本地能力骨架：账号、SQLite 持久化、文本/RAG、语音、视觉、TTS 适配器、受控工具、确认幂等和审计。

## 当前能力状态

| 能力 | 状态 |
|---|---|
| 文本诊断 | 已实现，调用本地 Ollama |
| PDF/DOCX/TXT 知识导入 | 已实现 |
| Embedding 与本地检索 | 已实现，SQLite 持久化向量 |
| 引用展示与资料不足提示 | 已实现 |
| 语音 STT | 已接入 faster-whisper Provider；本机 small 权重已完成真实转写验证，容器首次使用需准备权重 |
| 视觉 VLM | 已接入严格 JSON Ollama Provider；本机已验证 qwen2.5vl:3b |
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

当前自动化回归已覆盖 8 个 Python 测试、前端构建和 UX 契约；AC-02/03/04/08 的正式数据集评测、性能基线和浏览器 E2E 仍需单独执行。任何未实际执行的项目都不会标记为通过。
## P2-P5 能力配置

语音依赖已经写入 pyproject.toml 的 audio extra。

安装命令：python -m pip install -e ".[test,audio]"

faster-whisper 首次使用需要下载 STT_MODEL_SIZE 对应权重。当前默认值是 small，下载失败时 API 会保留文字/图片能力并返回 STT_UNAVAILABLE 降级状态。

视觉能力通过 Ollama 配置。本机当前使用并验证 OLLAMA_VISION_MODEL=qwen2.5vl:3b；使用 ollama list 检查模型标签，不要把文本模型当作视觉模型。GET /api/v1/capabilities 会检查模型标签是否存在。

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
## 企业后台页面

前端已升级为 Vue Router 企业后台，登录后可访问：

- 运营总览：设备、开放故障、已发布知识与能力健康
- 多模态诊断：保留文本、语音、图片、RAG、引用和受控建单
- 诊断会话：列表、搜索和会话详情
- 故障闭环：新建、确认、处理中、待验证、已关闭及事件时间线
- 设备资产：组织范围设备列表、资料和故障历史
- 知识库：上传、解析、索引、发布、停用和重试
- 报告中心：故障与会话 CSV/PDF 导出
- 审计追踪：动作、对象、trace_id 筛选
- 用户与权限：仅系统管理员可见
- 系统设置：Provider 健康、能力状态和配置校验，仅系统管理员可见

默认演示账号：

| 账号 | 密码 | 角色 |
|---|---|---|
| operator | change-me | 操作员 |
| supervisor | change-me-supervisor | 维修主管 |
| admin | change-me-admin | 系统管理员 |

首次部署后请立即通过环境变量或后台账号管理替换演示密码。前端菜单隐藏不等于安全边界，所有受保护接口仍在服务端执行角色和组织范围校验。

## 企业后台迁移

    .\\.venv\\Scripts\\alembic.exe upgrade head
    .\\.venv\\Scripts\\alembic.exe check

企业迁移版本为 0002_enterprise、0003_enterprise_columns、0004_enterprise_indexes。已有单组织数据会在应用启动时归入 ORG-DEMO / SITE-DEMO / LINE-DEMO，A-01 迁移到默认产线。

## 质量门禁

已实际验证：

- 后端：8 项 pytest 通过
- Alembic：check 无待生成迁移
- 前端：TypeScript/Vite 构建通过
- 前端单元测试：3 项通过
- Docker：API 与 Web 镜像构建、启动，API 健康检查通过
- API：四角色登录、组织范围设备、故障确认幂等、非法状态转换、Provider 健康、CSV/PDF 下载通过

尚未作为通过项声明：

- 真实浏览器截图、键盘和窄屏 E2E：当前浏览器自动化工具不可用
- 20 条普通话、10 张图片、Recall@5、Citation Precision 和性能目标：评测数据集尚未执行
- 真实 SSO、批量设备导入和 PostgreSQL/MySQL 部署：保留扩展边界，未纳入本地 MVP
