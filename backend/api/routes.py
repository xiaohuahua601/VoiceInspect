import json
import mimetypes
import secrets
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, require_roles, user_can_access_device
from backend.api.schemas import KnowledgeTextRequest, LoginRequest, MessageCreateRequest, SessionCreateRequest, SessionUpdateRequest
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.security import create_access_token, decode_access_token, hash_password, verify_password
from backend.domain.enums import MessageRole, UserRole
from backend.providers.factory import create_embedding_provider, create_llm_provider, use_qwen
from backend.rag.service import KnowledgeService
from backend.repositories.db import get_db
from backend.repositories.models import AuditEvent, Device, DiagnosisSession, KnowledgeDoc, Message, User
from backend.repositories.advanced_models import AuthSession, LoginAttempt
from backend.services.message_attachments import message_attachment_payloads
from backend.domain.device_profiles import equipment_type


router = APIRouter(prefix="/api/v1")
settings = get_settings()
provider = create_llm_provider(settings)
knowledge = KnowledgeService(create_embedding_provider(settings))
def serialize_message(db: Session, message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "text": message.text,
        "status": message.status,
        "citations": message.citations or [],
        "stage_states": message.stage_states or {},
        "observations": message.observations or {},
        "attachments": message_attachment_payloads(db, message),
        "created_at": message.created_at,
    }


def serialize_session(session: DiagnosisSession) -> dict:
    return {"id": session.id, "title": session.title, "status": session.status, "device_id": session.device_id, "created_at": session.created_at}


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    username_key = payload.username.strip().lower()
    ip_address = request.client.host if request.client else "unknown"
    attempt = db.scalar(select(LoginAttempt).where(LoginAttempt.username_key == username_key, LoginAttempt.ip_address == ip_address))
    if attempt and attempt.locked_until:
        locked_until = attempt.locked_until.replace(tzinfo=timezone.utc) if attempt.locked_until.tzinfo is None else attempt.locked_until
    else:
        locked_until = None
    if locked_until and locked_until > now:
        raise AppError("AUTH_RATE_LIMITED", "登录失败次数过多，请稍后重试", 429, True, "auth")
    if attempt and locked_until and locked_until <= now:
        attempt.failed_count = 0
        attempt.locked_until = None
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or user.status != "active" or not verify_password(payload.password, user.password_hash):
        if not attempt:
            attempt = LoginAttempt(username_key=username_key, ip_address=ip_address)
            db.add(attempt)
        attempt.failed_count = (attempt.failed_count or 0) + 1
        attempt.last_attempt_at = now
        if attempt.failed_count >= settings.login_max_attempts:
            attempt.locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
        db.commit()
        raise AppError("AUTH_INVALID", "用户名或密码不正确", 401, False, "auth")
    if attempt:
        attempt.failed_count = 0
        attempt.locked_until = None
        attempt.last_attempt_at = now
    active = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > datetime.now(timezone.utc))).all()
    if len(active) >= settings.max_active_sessions_per_user:
        oldest = sorted(active, key=lambda item: item.last_seen_at)[0]
        oldest.revoked_at = datetime.now(timezone.utc)
    jti = secrets.token_urlsafe(24)
    expires_at = now + timedelta(minutes=settings.access_token_minutes)
    token = create_access_token(user.id, user.username, user.role, settings.access_token_secret, settings.access_token_minutes, jti=jti)
    db.add(AuthSession(user_id=user.id, jti=jti, expires_at=expires_at, user_agent=request.headers.get("user-agent"), ip_address=request.client.host if request.client else None))
    db.commit()
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "username": user.username, "role": user.role, "status": user.status, "organization_id": user.organization_id, "must_change_password": user.must_change_password}}


def _token_payload(authorization: str | None) -> dict | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return decode_access_token(authorization[7:].strip(), settings.access_token_secret)


@router.post("/auth/refresh")
def refresh_token(authorization: str | None = Header(default=None), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    payload = _token_payload(authorization)
    if not payload or not payload.get("jti"):
        raise AppError("AUTH_INVALID", "登录状态已失效，请重新登录", 401, False, "auth")
    current = db.scalar(select(AuthSession).where(AuthSession.jti == payload["jti"], AuthSession.user_id == user.id))
    if not current or current.revoked_at:
        raise AppError("AUTH_INVALID", "登录状态已失效，请重新登录", 401, False, "auth")
    now = datetime.now(timezone.utc)
    current.revoked_at = now
    jti = secrets.token_urlsafe(24)
    expires_at = now + timedelta(minutes=settings.access_token_minutes)
    token = create_access_token(user.id, user.username, user.role, settings.access_token_secret, settings.access_token_minutes, jti=jti)
    db.add(AuthSession(user_id=user.id, jti=jti, expires_at=expires_at, user_agent=current.user_agent, ip_address=current.ip_address))
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="auth.refreshed", target=current.id))
    db.commit()
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "username": user.username, "role": user.role, "status": user.status, "organization_id": user.organization_id, "must_change_password": user.must_change_password}}


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    payload = _token_payload(authorization)
    if payload and payload.get("jti"):
        session = db.scalar(select(AuthSession).where(AuthSession.jti == payload["jti"], AuthSession.user_id == user.id))
        if session:
            session.revoked_at = datetime.now(timezone.utc)
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="auth.logout", target=user.id))
    db.commit()
    return {"status": "logged_out"}


@router.get("/auth/sessions")
def auth_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at > now).order_by(AuthSession.created_at.desc())).all()
    return [{"id": row.id, "created_at": row.created_at, "last_seen_at": row.last_seen_at, "expires_at": row.expires_at, "revoked": bool(row.revoked_at)} for row in rows]


@router.delete("/auth/sessions/{session_id}")
def revoke_auth_session(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    row = db.get(AuthSession, session_id)
    if not row or row.user_id != user.id:
        raise AppError("AUTH_SESSION_NOT_FOUND", "登录会话不存在", 404, False, "auth")
    row.revoked_at = datetime.now(timezone.utc)
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="auth.session_revoked", target=row.id))
    db.commit()
    return {"status": "revoked"}


@router.get("/health/live")
def health_live(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(select(1))
    except Exception:
        raise AppError("DATABASE_UNAVAILABLE", "数据库暂时不可用", 503, True, "health")
    return {"status": "ok"}


@router.get("/health")
async def health(db: Session = Depends(get_db)) -> dict:
    model_health = await provider.health()
    db_ok = True
    try:
        db.execute(select(1))
    except Exception:
        db_ok = False
    heartbeat = settings.log_dir / "worker-heartbeat.json"
    worker_ok = False
    worker_detail: dict = {"available": False, "reason": "worker heartbeat not found"}
    if heartbeat.exists():
        try:
            age = max(0.0, datetime.now(timezone.utc).timestamp() - heartbeat.stat().st_mtime)
            worker_ok = age <= 30
            worker_detail = {"available": worker_ok, "age_seconds": round(age, 1), "heartbeat": json.loads(heartbeat.read_text(encoding="utf-8"))}
        except (OSError, ValueError, json.JSONDecodeError):
            worker_detail = {"available": False, "reason": "worker heartbeat unreadable"}
    return {"status": "ok" if db_ok and model_health["available"] and worker_ok else "degraded", "database": db_ok, "worker": worker_detail, "provider": settings.model_provider, "model": model_health, "ollama": model_health, "models": {"llm": settings.qwen_model if use_qwen(settings) else settings.ollama_llm_model, "embedding": settings.ollama_embed_model, "vision": settings.qwen_model if use_qwen(settings) else settings.ollama_vision_model}}


@router.get("/devices")
def list_devices(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": item.id, "code": item.code, "model": item.model, "name": item.name} for item in db.scalars(select(Device).order_by(Device.code)).all() if user_can_access_device(user, item, db)]


@router.post("/sessions")
def create_session(payload: SessionCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if payload.device_id:
        device = db.get(Device, payload.device_id)
        if not device:
            raise AppError("DEVICE_NOT_FOUND", "设备不存在", 404, False, "session")
        if not user_can_access_device(user, device, db):
            raise AppError("DEVICE_FORBIDDEN", "当前账号无权使用该设备", 403, False, "session")
    session = DiagnosisSession(user_id=user.id, device_id=payload.device_id, title=payload.title.strip())
    db.add(session)
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="session.created", target=session.id, details={"device_id": payload.device_id}))
    db.commit()
    db.refresh(session)
    return serialize_session(session)


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, payload: SessionUpdateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    session = db.get(DiagnosisSession, session_id)
    if not session or (session.user_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value):
        raise AppError("SESSION_NOT_FOUND", "会话不存在或无权访问", 404, False, "session")
    device = db.get(Device, payload.device_id) if payload.device_id else None
    if payload.device_id and (not device or not user_can_access_device(user, device, db)):
        raise AppError("DEVICE_FORBIDDEN", "当前账号无权使用该设备", 403, False, "session")
    session.device_id = payload.device_id
    session.updated_at = session.updated_at
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="session.device_changed", target=session.id, details={"device_id": payload.device_id}))
    db.commit()
    db.refresh(session)
    return serialize_session(session)


@router.get("/sessions")
def list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(DiagnosisSession).where(DiagnosisSession.user_id == user.id).order_by(DiagnosisSession.updated_at.desc())).all()
    return [serialize_session(item) for item in rows]


@router.get("/sessions/{session_id}")
def get_session(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    session = db.get(DiagnosisSession, session_id)
    if not session or (session.user_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value):
        raise AppError("SESSION_NOT_FOUND", "会话不存在或无权访问", 404, False, "session")
    return {**serialize_session(session), "messages": [serialize_message(db, item) for item in sorted(session.messages, key=lambda x: x.created_at)]}


@router.post("/messages")
async def create_message(payload: MessageCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    session = db.get(DiagnosisSession, payload.session_id)
    if not session or session.user_id != user.id:
        raise AppError("SESSION_NOT_FOUND", "会话不存在或无权访问", 404, False, "message")
    text = payload.text.strip()
    if not text:
        raise AppError("MESSAGE_EMPTY", "请输入需要诊断的问题", 422, False, "message")
    device_id = payload.device_id or session.device_id
    device = db.get(Device, device_id) if device_id else None
    if device_id and (not device or not user_can_access_device(user, device, db)):
        raise AppError("DEVICE_FORBIDDEN", "当前账号无权使用该设备", 403, False, "message")
    if device_id != session.device_id:
        session.device_id = device_id
    user_message = Message(session_id=session.id, role=MessageRole.USER.value, text=text, status="completed", stage_states={"input": "succeeded"})
    db.add(user_message)
    db.flush()
    stages = {"stt": "skipped", "vision": "skipped", "rag": "running", "llm": "pending", "tts": "skipped"}
    started = time.perf_counter()
    citations = await knowledge.search(db, text, device_model=device.model if device else None, device_type=equipment_type(device), top_k=5)
    stages["rag"] = "succeeded" if citations else "partial"
    stages["llm"] = "running"
    db.commit()
    evidence = [f"[{item['document']} / {item['section']}] {item['quote_text']}" for item in citations]
    answer, metadata = await provider.generate(text, evidence)
    stages["llm"] = "succeeded"
    stages["completed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    assistant = Message(session_id=session.id, role=MessageRole.ASSISTANT.value, text=answer, status="completed" if answer else "partial", citations=citations, stage_states=stages)
    db.add(assistant)
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="diagnosis.completed", target=assistant.id, details={"model": metadata, "citation_count": len(citations), "stages": stages}))
    session.updated_at = session.updated_at
    db.commit()
    db.refresh(assistant)
    return {"message": serialize_message(db, assistant), "metadata": metadata}


@router.post("/knowledge/text")
async def create_knowledge_text(payload: KnowledgeTextRequest, user: User = Depends(require_roles(UserRole.KNOWLEDGE_ADMIN, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    document = await knowledge.ingest_text(db, payload.name, payload.content, payload.version, payload.device_model, user.organization_id, {"source_url": payload.source_url, "publisher": payload.publisher, "license": payload.license, "document_type": payload.document_type, "language": payload.language, "applicability": payload.applicability})
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="knowledge.indexed", target=document.id, details={"name": document.name, "chunks": len(document.chunks)}))
    db.commit()
    return {"id": document.id, "name": document.name, "version": document.version, "status": document.status, "chunks": len(document.chunks), "metadata": document.metadata_json or {}}


@router.post("/knowledge/documents")
async def upload_knowledge_document(file: UploadFile = File(...), version: str = Form("1"), device_model: str | None = Form(None), source_url: str | None = Form(None), publisher: str | None = Form(None), license: str | None = Form(None), document_type: str | None = Form(None), language: str = Form("zh-CN"), applicability: str | None = Form(None), user: User = Depends(require_roles(UserRole.KNOWLEDGE_ADMIN, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    allowed = {".txt", ".docx", ".pdf"}
    if suffix not in allowed:
        raise AppError("RAG_UNSUPPORTED_FILE", "仅支持 TXT、DOCX 和 PDF 文件", 415, False, "rag")
    content = await file.read()
    if not content or len(content) > settings.max_upload_bytes:
        raise AppError("UPLOAD_TOO_LARGE", "文件为空或超过 10MB 限制", 413, False, "upload")
    safe_name = f"{secrets.token_hex(12)}{suffix}"
    path = settings.knowledge_dir / safe_name
    path.write_bytes(content)
    try:
        extracted = knowledge.extract_text(path)
        document = await knowledge.ingest_text(db, file.filename or safe_name, extracted, version, device_model, user.organization_id, {"source_url": source_url, "publisher": publisher, "license": license, "document_type": document_type, "language": language, "applicability": applicability})
        db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="knowledge.uploaded", target=document.id, details={"original_name": file.filename, "size": len(content)}))
        db.commit()
        return {"id": document.id, "name": document.name, "version": document.version, "status": document.status, "chunks": len(document.chunks), "metadata": document.metadata_json or {}}
    finally:
        path.unlink(missing_ok=True)


@router.get("/citations/{chunk_id}")
def get_citation(chunk_id: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    from backend.repositories.models import KnowledgeChunk

    row = db.get(KnowledgeChunk, chunk_id)
    if not row:
        raise AppError("CITATION_NOT_FOUND", "引用不存在", 404, False, "rag")
    document = db.get(KnowledgeDoc, row.doc_id)
    return {"citation_id": row.id, "document": document.name if document else "未知文档", "version": document.version if document else None, "page": row.page, "section": row.section, "quote_text": row.text, "metadata": document.metadata_json if document else {}}

