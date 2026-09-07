import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes import router
from backend.core.config import get_settings
from backend.core.errors import AppError, app_error_handler
from backend.core.security import hash_password
from backend.repositories.db import SessionLocal, init_db
from backend.repositories.models import Device, User


settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(message)s")


def seed_demo_data() -> None:
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == settings.demo_operator_username).first():
            db.add(User(username=settings.demo_operator_username, password_hash=hash_password(settings.demo_operator_password), role="operator"))
        if not db.query(User).filter(User.username == settings.demo_admin_username).first():
            db.add(User(username=settings.demo_admin_username, password_hash=hash_password(settings.demo_admin_password), role="system_admin"))
        if not db.query(Device).filter(Device.code == "A-01").first():
            db.add(Device(code="A-01", model="COMPRESSOR-A", name="空压机 A-01", metadata_json={"location": "演示产线"}))
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
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    request.state.trace_id = request.headers.get("X-Trace-Id", str(uuid4()))
    response = await call_next(request)
    response.headers["X-Trace-Id"] = request.state.trace_id
    return response


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception):
    logging.exception("unhandled VoiceInspect error", exc_info=exc)
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR", "message": "服务暂时不可用，请稍后重试", "retryable": True, "stage": "api"}})


app.include_router(router)
