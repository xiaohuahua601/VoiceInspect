# VoiceInspect

VoiceInspect 是一个本地优先的工业设备现场多模态诊断助手，当前交付目标为 Windows Docker 环境的内部业务试点：账号、SQLite 持久化、文本/RAG、语音、视觉、TTS 适配器、受控工具、确认幂等、审计、持久化任务 Worker 和异步报告均已接入。

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

打开 http://127.0.0.1:5173，登录页支持四个本地演示账户一键填充。首次启动会创建 SQLite 数据库和四类演示设备：空压机 A-01、液压试验台 H-01、驱动电机 M-01、通用加工设备 P-01。

## 知识文档导入

知识库接口需要知识管理员或系统管理员令牌。当前默认系统管理员为 `admin / change-me-admin`，首次登录后应通过环境变量替换演示密码。文本导入接口：

```http
POST /api/v1/knowledge/text
Authorization: Bearer <token>
Content-Type: application/json

{"name":"空压机手册","content":"...","version":"1","device_model":"COMPRESSOR-A"}
```

## 开源数据集资产

项目提供 `data/datasets/catalog.json` 和 `scripts/import_open_datasets.py`。当前已登记 MetroPT-3 空压机、AI4I 2020 工业设备、液压系统、无位置传感器驱动和 IIT Kanpur 空压机声学数据集五个来源；前四个 UCI 数据集明确标注 CC BY 4.0，IIT Kanpur 数据集因下载页未声明标准开源许可证只登记来源，不自动复制。

导入数据集卡片并发布到 RAG：

```powershell
.\.venv\Scripts\python.exe scripts\import_open_datasets.py --publish
```

下载体量较小且许可明确的数据集到本地 `data/datasets/raw/`（原始文件被 Git 忽略）：

```powershell
.\.venv\Scripts\python.exe scripts\import_open_datasets.py --download --datasets ai4i-2020
```

数据集卡片参与问答检索，原始 CSV/信号/音频文件不会被当作维修手册。要把原始数据用于训练、异常检测或图表分析，需要后续的数据分析模块；知识卡片中的来源、许可证、适用边界和 SHA-256 用于审计和复现。
## 生产启动与管理员初始化

开发环境默认 SEED_DEMO_DATA=true，方便使用登录页的一键填充账户。正式部署应复制 .env.example 为 .env，替换密钥和密码，并设置 SEED_DEMO_DATA=false。迁移完成后可使用交互式脚本创建或轮换正式系统管理员，密码不会写入命令历史。

执行：
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts\provision_admin.py --username plant-admin

新建或重置账号的初始密码必须在首次登录后更新；密码至少 12 位并包含大写、小写和数字。/api/v1/health/live 是容器存活检查，/api/v1/health 还会反映 Ollama、Embedding、STT、VLM、TTS 等能力是否可用。

## Docker

Docker 方案包含 API、Web 和独立 Worker，SQLite、上传文件、知识库、向量索引、日志和报告均挂载到 `data/`。Ollama 默认运行在宿主机，容器内必须使用 `host.docker.internal`，不能使用容器内的 `localhost`。模型权重、密码和 `.env` 不会打包进镜像。详见 [docs/RUNBOOK.md](docs/RUNBOOK.md)。

## 生产模式、会话安全与备份

生产模式必须先执行 `alembic upgrade head`，并设置 `AUTO_CREATE_SCHEMA=false`；开发模式才允许兼容性 `create_all`。登录会话已持久化，支持退出、会话撤销、过期和登录失败限流。

备份数据（不包含 `.env`、模型权重和虚拟环境）：

```powershell
.\.venv\Scripts\python.exe scripts/backup_data.py
.\.venv\Scripts\python.exe scripts/restore_data.py data/backups/<备份目录> --confirm
```

恢复前应停止 API/Worker，恢复后执行 `alembic upgrade head`、健康检查和核心闭环验证。

## 测试

```powershell
python -m pytest
npm run build
npm run test:unit
npm run verify:premium
docker compose build api web worker
docker compose up -d
```

当前自动化回归覆盖后端 pytest、Alembic 漂移检查、前端构建、Vitest、UX 契约、Docker 健康、异步文本诊断、SSE `[DONE]` 结束标记和异步报告下载；具体通过数量以本次执行命令输出为准。AC-02/03/04/08 的正式数据集评测、性能基线和浏览器 E2E 仍需单独执行。任何未实际执行的项目都不会标记为通过。
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
| knowledge-admin | change-me-knowledge | 知识管理员 |
| admin | change-me-admin | 系统管理员 |

首次部署后请立即通过环境变量或后台账号管理替换演示密码。前端菜单隐藏不等于安全边界，所有受保护接口仍在服务端执行角色和组织范围校验。

## 企业后台迁移

    .\\.venv\\Scripts\\alembic.exe upgrade head
    .\\.venv\\Scripts\\alembic.exe check

企业迁移版本为 0002_enterprise、0003_enterprise_columns、0004_enterprise_indexes。已有单组织数据会在应用启动时归入 ORG-DEMO / SITE-DEMO / LINE-DEMO，A-01 迁移到默认产线。

## 质量门禁

已实际验证：

- 后端：32 项 pytest 通过
- Alembic：check 无待生成迁移
- 前端：TypeScript/Vite 构建通过
- 前端单元测试：8 项通过
- UI：UX 契约通过，严格项目审计 0 findings
- Docker：API、Web 镜像构建并启动，Worker 复用 API 镜像且健康检查通过
- API：四角色登录、令牌刷新、组织范围设备、故障确认幂等、非法状态转换、Provider 健康、异步诊断、SSE、CSV/PDF 异步生成和下载通过

尚未作为通过项声明：

- 真实浏览器截图、键盘和窄屏 E2E：当前浏览器自动化工具不可用
- 20 条普通话、10 张图片、Recall@5、Citation Precision 和性能目标：评测数据集尚未执行
- 真实 SSO、批量设备导入和 PostgreSQL/MySQL 部署：保留扩展边界，未纳入本地 MVP
