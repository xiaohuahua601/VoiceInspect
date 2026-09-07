import json
import mimetypes
import secrets
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, require_roles, user_can_access_device
from backend.api.schemas import KnowledgeTextRequest, LoginRequest, MessageCreateRequest, SessionCreateRequest
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.security import create_access_token, hash_password, verify_password
from backend.domain.enums import MessageRole, UserRole
from backend.providers.ollama import OllamaProvider
from backend.rag.service import KnowledgeService
from backend.repositories.db import get_db
from backend.repositories.models import AuditEvent, Device, DiagnosisSession, KnowledgeDoc, Message, User


router = APIRouter(prefix="/api/v1")
settings = get_settings()
provider = OllamaProvider(settings)
knowledge = KnowledgeService(provider)


def serialize_message(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "text": message.text,
        "status": message.status,
        "citations": message.citations or [],
        "stage_states": message.stage_states or {},
        "created_at": message.created_at,
    }


def serialize_session(session: DiagnosisSession) -> dict:
    return {"id": session.id, "title": session.title, "status": session.status, "device_id": session.device_id, "created_at": session.created_at}


@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        raise AppError("AUTH_INVALID", "用户名或密码不正确", 401, False, "auth")
    token = create_access_token(user.id, user.username, user.role, settings.access_token_secret, settings.access_token_minutes)
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "username": user.username, "role": user.role, "status": user.status, "organization_id": user.organization_id}}


@router.get("/health")
async def health(db: Session = Depends(get_db)) -> dict:
    model_health = await provider.health()
    db_ok = True
    try:
        db.execute(select(1))
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok and model_health["available"] else "degraded", "database": db_ok, "ollama": model_health, "models": {"llm": settings.ollama_llm_model, "embedding": settings.ollama_embed_model, "vision": settings.ollama_vision_model}}


@router.get("/devices")
def list_devices(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": item.id, "code": item.code, "model": item.model, "name": item.name} for item in db.scalars(select(Device).order_by(Device.code)).all()]


@router.post("/sessions")
def create_session(payload: SessionCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if payload.device_id and not db.get(Device, payload.device_id):
        raise AppError("DEVICE_NOT_FOUND", "设备不存在", 404, False, "session")
    session = DiagnosisSession(user_id=user.id, device_id=payload.device_id, title=payload.title.strip())
    db.add(session)
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="session.created", target=session.id, details={"device_id": payload.device_id}))
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
    return {**serialize_session(session), "messages": [serialize_message(item) for item in sorted(session.messages, key=lambda x: x.created_at)]}


@router.post("/messages")
async def create_message(payload: MessageCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    session = db.get(DiagnosisSession, payload.session_id)
    if not session or session.user_id != user.id:
        raise AppError("SESSION_NOT_FOUND", "会话不存在或无权访问", 404, False, "message")
    text = payload.text.strip()
    if not text:
        raise AppError("MESSAGE_EMPTY", "请输入需要诊断的问题", 422, False, "message")
    user_message = Message(session_id=session.id, role=MessageRole.USER.value, text=text, status="completed", stage_states={"input": "succeeded"})
    db.add(user_message)
    db.flush()
    stages = {"stt": "skipped", "vision": "skipped", "rag": "running", "llm": "pending", "tts": "skipped"}
    started = time.perf_counter()
    citations = await knowledge.search(db, text, top_k=5)
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
    return {"message": serialize_message(assistant), "metadata": metadata}


@router.post("/knowledge/text")
async def create_knowledge_text(payload: KnowledgeTextRequest, user: User = Depends(require_roles(UserRole.KNOWLEDGE_ADMIN, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    document = await knowledge.ingest_text(db, payload.name, payload.content, payload.version, payload.device_model, user.organization_id)
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="knowledge.indexed", target=document.id, details={"name": document.name, "chunks": len(document.chunks)}))
    db.commit()
    return {"id": document.id, "name": document.name, "version": document.version, "status": document.status, "chunks": len(document.chunks)}


@router.post("/knowledge/documents")
async def upload_knowledge_document(file: UploadFile = File(...), version: str = Form("1"), device_model: str | None = Form(None), user: User = Depends(require_roles(UserRole.KNOWLEDGE_ADMIN, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
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
        document = await knowledge.ingest_text(db, file.filename or safe_name, extracted, version, device_model, user.organization_id)
        db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="knowledge.uploaded", target=document.id, details={"original_name": file.filename, "size": len(content)}))
        db.commit()
        return {"id": document.id, "name": document.name, "version": document.version, "status": document.status, "chunks": len(document.chunks)}
    finally:
        path.unlink(missing_ok=True)


@router.get("/citations/{chunk_id}")
def get_citation(chunk_id: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    from backend.repositories.models import KnowledgeChunk

    row = db.get(KnowledgeChunk, chunk_id)
    if not row:
        raise AppError("CITATION_NOT_FOUND", "引用不存在", 404, False, "rag")
    document = db.get(KnowledgeDoc, row.doc_id)
    return {"citation_id": row.id, "document": document.name if document else "未知文档", "version": document.version if document else None, "page": row.page, "section": row.section, "quote_text": row.text}
