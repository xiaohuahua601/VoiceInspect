import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes import router
from backend.api.advanced_routes import router as advanced_router
from backend.api.enterprise_routes import router as enterprise_router
from backend.core.config import get_settings
from backend.core.errors import AppError, app_error_handler
from backend.core.security import hash_password
from backend.repositories.db import SessionLocal, init_db
from backend.repositories.models import Device, Organization, ProductionLine, Site, User, UserScope
from backend.repositories import advanced_models  # noqa: F401


settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(message)s")


def seed_demo_data() -> None:
    db = SessionLocal()
    try:
        organization = db.query(Organization).filter(Organization.code == "ORG-DEMO").first()
        if not organization:
            organization = Organization(name="演示制造集团", code="ORG-DEMO")
            db.add(organization)
            db.flush()

        site = db.query(Site).filter(Site.organization_id == organization.id, Site.code == "SITE-DEMO").first()
        if not site:
            site = Site(organization_id=organization.id, name="演示工厂", code="SITE-DEMO")
            db.add(site)
            db.flush()

        line = db.query(ProductionLine).filter(ProductionLine.site_id == site.id, ProductionLine.code == "LINE-DEMO").first()
        if not line:
            line = ProductionLine(site_id=site.id, organization_id=organization.id, name="一号装配线", code="LINE-DEMO")
            db.add(line)
            db.flush()

        operator = db.query(User).filter(User.username == settings.demo_operator_username).first()
        if not operator:
            operator = User(
                username=settings.demo_operator_username,
                password_hash=hash_password(settings.demo_operator_password),
                role="operator",
                organization_id=organization.id,
            )
            db.add(operator)
            db.flush()
        elif not operator.organization_id:
            operator.organization_id = organization.id

        admin = db.query(User).filter(User.username == settings.demo_admin_username).first()
        if not admin:
            admin = User(
                username=settings.demo_admin_username,
                password_hash=hash_password(settings.demo_admin_password),
                role="system_admin",
                organization_id=organization.id,
            )
            db.add(admin)
        elif not admin.organization_id:
            admin.organization_id = organization.id

        supervisor = db.query(User).filter(User.username == settings.demo_supervisor_username).first()
        if not supervisor:
            supervisor = User(
                username=settings.demo_supervisor_username,
                password_hash=hash_password(settings.demo_supervisor_password),
                role="maintenance_supervisor",
                organization_id=organization.id,
            )
            db.add(supervisor)
            db.flush()
        elif not supervisor.organization_id:
            supervisor.organization_id = organization.id

        knowledge_admin = db.query(User).filter(User.username == settings.demo_knowledge_admin_username).first()
        if not knowledge_admin:
            knowledge_admin = User(
                username=settings.demo_knowledge_admin_username,
                password_hash=hash_password(settings.demo_knowledge_admin_password),
                role="knowledge_admin",
                organization_id=organization.id,
            )
            db.add(knowledge_admin)
            db.flush()
        elif not knowledge_admin.organization_id:
            knowledge_admin.organization_id = organization.id
        demo_devices = [
            {
                "code": "A-01",
                "model": "COMPRESSOR-A",
                "name": "空压机 A-01",
                "metadata": {"location": "演示产线", "equipment_type": "compressor", "dataset_slugs": ["metropt-3", "iitk-air-compressor-acoustic"], "quick_prompts": ["空压机 A-01 出现压力波动，应该按什么顺序检查？", "如何判断空压机 A-01 温度异常是冷却还是润滑问题？", "空压机 A-01 的安全阀和储气罐有哪些检查注意事项？"]},
            },
            {
                "code": "H-01",
                "model": "HYDRAULIC-SYSTEM-A",
                "name": "液压试验台 H-01",
                "metadata": {"location": "演示产线", "equipment_type": "hydraulic_system", "dataset_slugs": ["hydraulic-systems-447"], "quick_prompts": ["液压试验台 H-01 压力下降时，如何区分泄漏、阀滞后和蓄能器压力不足？", "液压试验台 H-01 液压泵温度升高应先检查哪些传感器和部件？", "如何根据液压试验台 H-01 的传感器数据判断冷却器效率异常？"]},
            },
            {
                "code": "M-01",
                "model": "MOTOR-DRIVE-A",
                "name": "驱动电机 M-01",
                "metadata": {"location": "演示产线", "equipment_type": "motor", "dataset_slugs": ["sensorless-drive-325"], "quick_prompts": ["驱动电机 M-01 电流波动时，应如何排查负载、轴承和驱动器？", "如何用驱动电机 M-01 的转速、扭矩和振动信号判断驱动异常？", "驱动电机 M-01 启动失败前需要检查哪些安全项？"]},
            },
            {
                "code": "P-01",
                "model": "INDUSTRIAL-MACHINE-A",
                "name": "通用加工设备 P-01",
                "metadata": {"location": "演示产线", "equipment_type": "industrial_machine", "dataset_slugs": ["ai4i-2020"], "quick_prompts": ["通用加工设备 P-01 出现工具磨损报警时，如何确认是否需要更换？", "通用加工设备 P-01 温度与转速同时异常时，优先检查哪些因素？", "如何区分通用加工设备 P-01 的功率故障、过载和散热异常？"]},
            },
        ]
        for item in demo_devices:
            device = db.query(Device).filter(Device.code == item["code"]).first()
            if not device:
                db.add(
                    Device(
                        code=item["code"],
                        model=item["model"],
                        name=item["name"],
                        metadata_json=item["metadata"],
                        organization_id=organization.id,
                        site_id=site.id,
                        line_id=line.id,
                    )
                )
            else:
                device.model = item["model"]
                device.name = item["name"]
                device.metadata_json = item["metadata"]
                device.organization_id, device.site_id, device.line_id = organization.id, site.id, line.id

        for account in (operator, supervisor, knowledge_admin):
            if not db.query(UserScope).filter(UserScope.user_id == account.id).first():
                db.add(UserScope(user_id=account.id, organization_id=organization.id, site_id=site.id, line_id=line.id))

        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_demo_data()
    yield


app = FastAPI(title="VoiceInspect API", version="0.1.0", lifespan=lifespan)
app.add_exception_handler(AppError, app_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    request.state.trace_id = request.headers.get("X-Trace-Id", str(uuid4()))
    response = await call_next(request)
    response.headers["X-Trace-Id"] = request.state.trace_id
    return response


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception):
    logging.exception("unhandled VoiceInspect error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务暂时不可用，请稍后重试",
                "retryable": True,
                "stage": "api",
            }
        },
    )


app.include_router(enterprise_router)
app.include_router(advanced_router)
app.include_router(router)
