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

        device = db.query(Device).filter(Device.code == "A-01").first()
        if not device:
            db.add(
                Device(
                    code="A-01",
                    model="COMPRESSOR-A",
                    name="空压机 A-01",
                    metadata_json={"location": "演示产线"},
                    organization_id=organization.id,
                    site_id=site.id,
                    line_id=line.id,
                )
            )
        else:
            device.organization_id, device.site_id, device.line_id = organization.id, site.id, line.id

        for account in (operator, supervisor):
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
