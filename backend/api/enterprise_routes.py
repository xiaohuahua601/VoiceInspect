from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, require_roles, user_can_access_device, visible_devices
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.security import hash_password, verify_password
from backend.domain.enums import FaultStatus, KnowledgeStatus, UserRole
from backend.repositories.db import get_db
from backend.providers.ollama import OllamaProvider
from backend.providers.stt import FasterWhisperSTT
from backend.providers.vision import OllamaVision
from backend.providers.tts import WindowsSapiTTS
from backend.providers.piper import PiperTTS
from backend.repositories.models import (
    AuditEvent, Device, DiagnosisSession, FaultEvent, FaultRecord, KnowledgeDoc,
    Organization, ProductionLine, ProviderConfig, ReportExport, Site, User, UserScope,
    new_id, utc_now,
)

router = APIRouter(prefix="/api/v1")
settings = get_settings()


class NamedPayload(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str = Field(min_length=1, max_length=80)


class SitePayload(NamedPayload):
    organization_id: str


class LinePayload(NamedPayload):
    site_id: str
    organization_id: str


class DevicePayload(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    model: str = Field(min_length=1, max_length=120)
    organization_id: str | None = None
    site_id: str | None = None
    line_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserPayload(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=200)
    role: str
    organization_id: str | None = None


class UserPatch(BaseModel):
    role: str | None = None
    status: str | None = None
    organization_id: str | None = None


class ScopePayload(BaseModel):
    scopes: list[dict[str, str | None]] = Field(default_factory=list)


class FaultAction(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    assigned_to: str | None = None
    resolution: str | None = Field(default=None, max_length=4000)


class ReportPayload(BaseModel):
    format: str = "csv"


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class ProviderPatch(BaseModel):
    model: str | None = Field(default=None, max_length=255)
    enabled: bool = True


def _forbidden(user: User, *roles: UserRole) -> None:
    if user.role not in {x.value for x in roles}:
        raise AppError("AUTH_FORBIDDEN", "当前账号没有执行此操作的权限", 403, False, "auth")


def _audit(db: Session, user: User, action: str, target: str, details: dict | None = None) -> None:
    db.add(AuditEvent(trace_id=new_id(), actor_id=user.id, action=action, target=target, details=details or {}))


def _device(db: Session, device_id: str, user: User) -> Device:
    item = db.get(Device, device_id)
    if not item or not user_can_access_device(user, item, db):
        raise AppError("DEVICE_NOT_FOUND", "设备不存在或无权访问", 404, False, "device")
    return item


def _device_view(x: Device) -> dict:
    return {"id": x.id, "code": x.code, "name": x.name, "model": x.model, "organization_id": x.organization_id,
            "site_id": x.site_id, "line_id": x.line_id, "metadata": x.metadata_json or {}, "created_at": x.created_at}


def _fault_view(x: FaultRecord) -> dict:
    return {"id": x.id, "device_id": x.device_id, "session_id": x.session_id, "symptom": x.symptom,
            "severity": x.severity, "status": x.status, "creator_id": x.creator_id, "assigned_to": x.assigned_to,
            "resolution": x.resolution, "created_at": x.created_at, "updated_at": x.updated_at}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    scopes = db.scalars(select(UserScope).where(UserScope.user_id == user.id)).all()
    return {"id": user.id, "username": user.username, "role": user.role, "status": user.status,
            "organization_id": user.organization_id,
            "scopes": [{"organization_id": x.organization_id, "site_id": x.site_id, "line_id": x.line_id} for x in scopes]}


@router.post("/auth/change-password")
def change_password(payload: PasswordChange, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if not verify_password(payload.current_password, user.password_hash):
        raise AppError("PASSWORD_INVALID", "当前密码不正确", 400, False, "auth")
    user.password_hash = hash_password(payload.new_password)
    _audit(db, user, "user.password_changed", user.id)
    db.commit()
    return {"status": "changed"}

@router.get("/roles")
def roles(user: User = Depends(get_current_user)) -> list[dict]:
    labels = {"operator": "操作员", "maintenance_supervisor": "维修主管", "knowledge_admin": "知识管理员", "system_admin": "系统管理员"}
    keys = labels if user.role == UserRole.SYSTEM_ADMIN.value else {user.role: labels.get(user.role, user.role)}
    return [{"id": k, "label": v} for k, v in keys.items()]


@router.get("/organizations")
def organization_list(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    q = select(Organization).order_by(Organization.code)
    if user.role != UserRole.SYSTEM_ADMIN.value:
        q = q.where(Organization.id == user.organization_id)
    return [{"id": x.id, "name": x.name, "code": x.code, "status": x.status} for x in db.scalars(q).all()]


@router.post("/organizations")
def organization_create(payload: NamedPayload, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    item = Organization(name=payload.name.strip(), code=payload.code.strip())
    db.add(item); db.flush(); _audit(db, user, "organization.created", item.id); db.commit()
    return {"id": item.id, "name": item.name, "code": item.code, "status": item.status}


@router.get("/sites")
def site_list(organization_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    q = select(Site).order_by(Site.code)
    if user.role != UserRole.SYSTEM_ADMIN.value:
        q = q.where(Site.organization_id == user.organization_id)
    elif organization_id:
        q = q.where(Site.organization_id == organization_id)
    return [{"id": x.id, "organization_id": x.organization_id, "name": x.name, "code": x.code, "status": x.status} for x in db.scalars(q).all()]


@router.post("/sites")
def site_create(payload: SitePayload, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    if not db.get(Organization, payload.organization_id):
        raise AppError("ORGANIZATION_NOT_FOUND", "组织不存在", 404, False, "organization")
    item = Site(organization_id=payload.organization_id, name=payload.name.strip(), code=payload.code.strip())
    db.add(item); db.flush(); _audit(db, user, "site.created", item.id); db.commit()
    return {"id": item.id, "organization_id": item.organization_id, "name": item.name, "code": item.code, "status": item.status}


@router.get("/production-lines")
def line_list(site_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    q = select(ProductionLine).order_by(ProductionLine.code)
    if user.role != UserRole.SYSTEM_ADMIN.value:
        q = q.where(ProductionLine.organization_id == user.organization_id)
    if site_id:
        q = q.where(ProductionLine.site_id == site_id)
    return [{"id": x.id, "site_id": x.site_id, "organization_id": x.organization_id, "name": x.name, "code": x.code, "status": x.status} for x in db.scalars(q).all()]


@router.post("/production-lines")
def line_create(payload: LinePayload, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    if not db.get(Site, payload.site_id) or not db.get(Organization, payload.organization_id):
        raise AppError("ORGANIZATION_NOT_FOUND", "组织或站点不存在", 404, False, "organization")
    item = ProductionLine(site_id=payload.site_id, organization_id=payload.organization_id, name=payload.name.strip(), code=payload.code.strip())
    db.add(item); db.flush(); _audit(db, user, "production_line.created", item.id); db.commit()
    return {"id": item.id, "site_id": item.site_id, "organization_id": item.organization_id, "name": item.name, "code": item.code, "status": item.status}


@router.get("/devices")
def device_list(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [_device_view(x) for x in visible_devices(user, db)]


@router.post("/devices")
def device_create(payload: DevicePayload, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    item = Device(code=payload.code.strip(), name=payload.name.strip(), model=payload.model.strip(), organization_id=payload.organization_id,
                  site_id=payload.site_id, line_id=payload.line_id, metadata_json=payload.metadata)
    db.add(item); db.flush(); _audit(db, user, "device.created", item.id); db.commit()
    return _device_view(item)


@router.get("/devices/{device_id}")
def device_detail(device_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return _device_view(_device(db, device_id, user))


@router.patch("/devices/{device_id}")
def device_patch(device_id: str, payload: DevicePayload, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    item = db.get(Device, device_id)
    if not item:
        raise AppError("DEVICE_NOT_FOUND", "设备不存在", 404, False, "device")
    item.code, item.name, item.model = payload.code.strip(), payload.name.strip(), payload.model.strip()
    item.organization_id, item.site_id, item.line_id, item.metadata_json = payload.organization_id, payload.site_id, payload.line_id, payload.metadata
    _audit(db, user, "device.updated", item.id); db.commit()
    return _device_view(item)


@router.get("/users")
def user_list(user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": x.id, "username": x.username, "role": x.role, "status": x.status, "organization_id": x.organization_id, "created_at": x.created_at}
            for x in db.scalars(select(User).order_by(User.username)).all()]


@router.post("/users")
def user_create(payload: UserPayload, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    valid = {x.value for x in UserRole if x.value != "guest"}
    if payload.role not in valid:
        raise AppError("ROLE_INVALID", "角色不存在", 422, False, "user")
    if db.scalar(select(User).where(User.username == payload.username.strip())):
        raise AppError("USER_EXISTS", "用户名已存在", 409, False, "user")
    item = User(username=payload.username.strip(), password_hash=hash_password(payload.password), role=payload.role, organization_id=payload.organization_id)
    db.add(item); db.flush(); _audit(db, user, "user.created", item.id); db.commit()
    return {"id": item.id, "username": item.username, "role": item.role, "status": item.status, "organization_id": item.organization_id}


@router.patch("/users/{user_id}")
def user_patch(user_id: str, payload: UserPatch, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    item = db.get(User, user_id)
    if not item:
        raise AppError("USER_NOT_FOUND", "用户不存在", 404, False, "user")
    if payload.role: item.role = payload.role
    if payload.status: item.status = payload.status
    if payload.organization_id is not None: item.organization_id = payload.organization_id
    _audit(db, user, "user.updated", item.id); db.commit()
    return {"id": item.id, "username": item.username, "role": item.role, "status": item.status, "organization_id": item.organization_id}


@router.patch("/users/{user_id}/scopes")
def user_scopes(user_id: str, payload: ScopePayload, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    target = db.get(User, user_id)
    if not target: raise AppError("USER_NOT_FOUND", "用户不存在", 404, False, "user")
    for row in db.scalars(select(UserScope).where(UserScope.user_id == target.id)).all(): db.delete(row)
    for value in payload.scopes:
        if not value.get("organization_id"): raise AppError("SCOPE_INVALID", "数据范围缺少组织", 422, False, "user")
        db.add(UserScope(user_id=target.id, organization_id=str(value["organization_id"]), site_id=value.get("site_id"), line_id=value.get("line_id")))
    _audit(db, user, "user.scopes_updated", target.id); db.commit()
    return me(target, db)


@router.get("/fault-records")
def fault_list(status: str | None = None, severity: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    ids = {x.id for x in visible_devices(user, db)}
    q = select(FaultRecord).where(FaultRecord.device_id.in_(ids)).order_by(desc(FaultRecord.updated_at))
    if status: q = q.where(FaultRecord.status == status)
    if severity: q = q.where(FaultRecord.severity == severity)
    return [_fault_view(x) for x in db.scalars(q).all()]


def _fault(db: Session, fault_id: str, user: User) -> FaultRecord:
    item = db.get(FaultRecord, fault_id)
    if not item: raise AppError("FAULT_NOT_FOUND", "故障记录不存在", 404, False, "fault")
    _device(db, item.device_id, user)
    return item


def _transition(db: Session, item: FaultRecord, user: User, target: FaultStatus, action: str, payload: FaultAction) -> dict:
    allowed = {FaultStatus.NEW: {FaultStatus.CONFIRMED}, FaultStatus.CONFIRMED: {FaultStatus.IN_PROGRESS},
               FaultStatus.IN_PROGRESS: {FaultStatus.PENDING_VERIFICATION}, FaultStatus.PENDING_VERIFICATION: {FaultStatus.CLOSED}}
    if target not in allowed.get(FaultStatus(item.status), set()):
        raise AppError("FAULT_STATUS_TRANSITION_INVALID", "当前故障状态不允许此操作", 409, False, "fault")
    before = item.status; item.status = target.value
    if target == FaultStatus.CONFIRMED: item.confirmed_by = user.id
    if target == FaultStatus.PENDING_VERIFICATION: item.verified_by = user.id
    if target == FaultStatus.CLOSED: item.closed_by, item.resolution = user.id, payload.resolution or payload.note
    if payload.assigned_to: item.assigned_to = payload.assigned_to
    db.add(FaultEvent(fault_id=item.id, actor_id=user.id, from_status=before, to_status=item.status, note=payload.note or payload.resolution))
    _audit(db, user, action, item.id, {"from": before, "to": item.status}); db.commit(); db.refresh(item)
    return _fault_view(item)


@router.get("/fault-records/{fault_id}")
def fault_detail(fault_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = _fault(db, fault_id, user)
    events = db.scalars(select(FaultEvent).where(FaultEvent.fault_id == item.id).order_by(FaultEvent.created_at)).all()
    return {**_fault_view(item), "events": [{"id": x.id, "from_status": x.from_status, "to_status": x.to_status, "note": x.note, "actor_id": x.actor_id, "created_at": x.created_at} for x in events]}


def _fault_action(fault_id: str, payload: FaultAction | None, target: FaultStatus, action: str, user: User, db: Session) -> dict:
    return _transition(db, _fault(db, fault_id, user), user, target, action, payload or FaultAction())


@router.post("/fault-records/{fault_id}/confirm")
def fault_confirm(fault_id: str, payload: FaultAction | None = None, user: User = Depends(require_roles(UserRole.MAINTENANCE_SUPERVISOR, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _fault_action(fault_id, payload, FaultStatus.CONFIRMED, "fault.confirmed", user, db)


@router.post("/fault-records/{fault_id}/assign")
def fault_assign(fault_id: str, payload: FaultAction, user: User = Depends(require_roles(UserRole.MAINTENANCE_SUPERVISOR, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    payload.assigned_to = payload.assigned_to or user.id
    return _fault_action(fault_id, payload, FaultStatus.IN_PROGRESS, "fault.assigned", user, db)


@router.post("/fault-records/{fault_id}/start")
def fault_start(fault_id: str, payload: FaultAction | None = None, user: User = Depends(require_roles(UserRole.MAINTENANCE_SUPERVISOR, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _fault_action(fault_id, payload, FaultStatus.IN_PROGRESS, "fault.started", user, db)


@router.post("/fault-records/{fault_id}/verify")
def fault_verify(fault_id: str, payload: FaultAction | None = None, user: User = Depends(require_roles(UserRole.MAINTENANCE_SUPERVISOR, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _fault_action(fault_id, payload, FaultStatus.PENDING_VERIFICATION, "fault.pending_verification", user, db)


@router.post("/fault-records/{fault_id}/close")
def fault_close(fault_id: str, payload: FaultAction, user: User = Depends(require_roles(UserRole.MAINTENANCE_SUPERVISOR, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _fault_action(fault_id, payload, FaultStatus.CLOSED, "fault.closed", user, db)


@router.get("/knowledge/documents")
def knowledge_list(status: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    q = select(KnowledgeDoc).order_by(desc(KnowledgeDoc.created_at))
    if user.role != UserRole.SYSTEM_ADMIN.value: q = q.where(KnowledgeDoc.organization_id == user.organization_id)
    if status: q = q.where(KnowledgeDoc.status == status)
    return [{"id": x.id, "name": x.name, "version": x.version, "status": x.status, "organization_id": x.organization_id, "failure_reason": x.failure_reason, "chunks": len(x.chunks), "created_at": x.created_at} for x in db.scalars(q).all()]


@router.get("/knowledge/documents/{document_id}")
def knowledge_detail(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(KnowledgeDoc, document_id)
    if not item or (user.role != UserRole.SYSTEM_ADMIN.value and item.organization_id != user.organization_id):
        raise AppError("KNOWLEDGE_NOT_FOUND", "知识文档不存在或��权访问", 404, False, "rag")
    return {"id": item.id, "name": item.name, "version": item.version, "status": item.status, "failure_reason": item.failure_reason,
            "chunks": [{"id": x.id, "page": x.page, "section": x.section, "text": x.text[:500], "device_model": x.device_model} for x in item.chunks]}


def _knowledge_action(document_id: str, target: KnowledgeStatus, action: str, user: User, db: Session) -> dict:
    item = db.get(KnowledgeDoc, document_id)
    if not item or (user.role != UserRole.SYSTEM_ADMIN.value and item.organization_id != user.organization_id):
        raise AppError("KNOWLEDGE_NOT_FOUND", "知识文档不存在或无权访问", 404, False, "rag")
    if target == KnowledgeStatus.PUBLISHED:
        db.query(KnowledgeDoc).filter(KnowledgeDoc.name == item.name, KnowledgeDoc.status == KnowledgeStatus.PUBLISHED.value).update({"status": KnowledgeStatus.RETIRED.value})
    item.status = target.value; _audit(db, user, action, item.id, {"status": item.status}); db.commit()
    return {"id": item.id, "status": item.status}


@router.post("/knowledge/documents/{document_id}/index")
def knowledge_index(document_id: str, user: User = Depends(require_roles(UserRole.KNOWLEDGE_ADMIN, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _knowledge_action(document_id, KnowledgeStatus.INDEXED, "knowledge.indexed", user, db)


@router.post("/knowledge/documents/{document_id}/publish")
def knowledge_publish(document_id: str, user: User = Depends(require_roles(UserRole.KNOWLEDGE_ADMIN, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _knowledge_action(document_id, KnowledgeStatus.PUBLISHED, "knowledge.published", user, db)


@router.post("/knowledge/documents/{document_id}/retire")
def knowledge_retire(document_id: str, user: User = Depends(require_roles(UserRole.KNOWLEDGE_ADMIN, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _knowledge_action(document_id, KnowledgeStatus.RETIRED, "knowledge.retired", user, db)


@router.post("/knowledge/documents/{document_id}/retry")
def knowledge_retry(document_id: str, user: User = Depends(require_roles(UserRole.KNOWLEDGE_ADMIN, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _knowledge_action(document_id, KnowledgeStatus.INDEXED, "knowledge.retried", user, db)


@router.post("/reports/faults")
def report_faults(payload: ReportPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if payload.format not in {"csv", "pdf"}: raise AppError("REPORT_FORMAT_INVALID", "仅支持 PDF 或 CSV", 422, False, "report")
    ids = {x.id for x in visible_devices(user, db)}
    rows = [_fault_view(x) for x in db.scalars(select(FaultRecord).where(FaultRecord.device_id.in_(ids)).order_by(desc(FaultRecord.created_at)).limit(500)).all()]
    out = io.StringIO()
    if rows:
        writer = csv.DictWriter(out, fieldnames=list(rows[0].keys())); writer.writeheader(); writer.writerows(rows)
    data, filename, content_type = out.getvalue().encode("utf-8-sig"), f"faults-{new_id()}.csv", "text/csv; charset=utf-8"
    if payload.format == "pdf":
        data, filename, content_type = _pdf_bytes(rows), f"faults-{new_id()}.pdf", "application/pdf"
    folder = Path("./data/exports"); folder.mkdir(parents=True, exist_ok=True); path = folder / filename; path.write_bytes(data)
    item = ReportExport(owner_id=user.id, report_type="faults", format=payload.format, file_name=filename, file_path=str(path))
    db.add(item); _audit(db, user, "report.created", item.id, {"format": payload.format}); db.commit()
    return {"id": item.id, "file_name": filename, "format": payload.format, "status": item.status}


@router.get("/reports/{report_id}")
def report_detail(report_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(ReportExport, report_id)
    if not item or (item.owner_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value):
        raise AppError("REPORT_NOT_FOUND", "报告不存在或无权访问", 404, False, "report")
    return {"id": item.id, "file_name": item.file_name, "format": item.format, "status": item.status, "created_at": item.created_at}


@router.get("/reports/{report_id}/download")
def report_download(report_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    item = db.get(ReportExport, report_id)
    if not item or (item.owner_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value):
        raise AppError("REPORT_NOT_FOUND", "报告不存在或无权访问", 404, False, "report")
    return FileResponse(item.file_path, filename=item.file_name)


@router.get("/settings/providers")
def provider_list(user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> list[dict]:
    defaults = {"llm": settings.ollama_llm_model, "embedding": settings.ollama_embed_model, "vision": settings.ollama_vision_model, "stt": settings.stt_model_size, "tts": settings.piper_voice}
    rows = {x.name: x for x in db.scalars(select(ProviderConfig)).all()}
    return [{"name": n, "model": rows[n].model if n in rows else m, "enabled": rows[n].enabled if n in rows else bool(m)} for n, m in defaults.items()]


@router.patch("/settings/providers/{name}")
async def provider_patch(name: str, payload: ProviderPatch, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    if name not in {"llm", "embedding", "vision", "stt", "tts"}:
        raise AppError("PROVIDER_NOT_FOUND", "Provider 不存在", 404, False, "settings")
    item = db.scalar(select(ProviderConfig).where(ProviderConfig.name == name)) or ProviderConfig(name=name)
    health = await _provider_health(name, payload.model)
    if payload.enabled and not health["available"]:
        raise AppError("PROVIDER_UNAVAILABLE", "Provider 健康检查未通过，不能启用", 503, True, "settings", health)
    item.model, item.enabled, item.updated_by, item.updated_at = payload.model, payload.enabled, user.id, utc_now()
    db.add(item)
    _audit(db, user, "provider.updated", item.id, {"name": name, "health": health})
    db.commit()
    return {"name": item.name, "model": item.model, "enabled": item.enabled, "health": health}

@router.get("/settings/health")
async def settings_health(user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    db.execute(select(1))
    checks = {name: await _provider_health(name) for name in ("llm", "embedding", "vision", "stt", "tts")}
    return {"status": "ok" if all(value.get("available") for value in checks.values()) else "degraded", "database": {"available": True}, **checks}

@router.get("/sessions")
def enterprise_session_list(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(DiagnosisSession).order_by(desc(DiagnosisSession.updated_at))).all()
    visible = []
    for item in rows:
        if item.user_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value:
            if not item.device_id:
                continue
            device = db.get(Device, item.device_id)
            if not device or not user_can_access_device(user, device, db):
                continue
        visible.append({
            "id": item.id,
            "title": item.title,
            "status": item.status,
            "device_id": item.device_id,
            "organization_id": item.organization_id,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        })
    return visible


@router.get("/sessions/{session_id}")
def enterprise_session_detail(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(DiagnosisSession, session_id)
    if not item:
        raise AppError("SESSION_NOT_FOUND", "会话不存在或无权访问", 404, False, "session")
    if item.user_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value:
        if not item.device_id or not user_can_access_device(user, db.get(Device, item.device_id), db):
            raise AppError("SESSION_NOT_FOUND", "会话不存在或无权访问", 404, False, "session")
    return {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "device_id": item.device_id,
        "organization_id": item.organization_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "text": message.text,
                "status": message.status,
                "citations": message.citations or [],
                "stage_states": message.stage_states or {},
                "created_at": message.created_at,
            }
            for message in sorted(item.messages, key=lambda value: value.created_at)
        ],
    }


async def _provider_health(name: str, model: str | None = None) -> dict:
    if name in {"llm", "embedding", "vision"}:
        health = await OllamaProvider(settings).health()
        wanted = model or {
            "llm": settings.ollama_llm_model,
            "embedding": settings.ollama_embed_model,
            "vision": settings.ollama_vision_model,
        }[name]
        available = bool(health.get("available")) and (not wanted or wanted in health.get("models", []))
        return {
            "available": available,
            "model": wanted,
            "models": health.get("models", []),
            "reason": None if available else "模型未安装或 Ollama 不可用",
        }
    provider = FasterWhisperSTT() if name == "stt" else (
        WindowsSapiTTS() if __import__("os").name == "nt" else PiperTTS()
    )
    result = await provider.health()
    return result.__dict__


@router.post("/settings/providers/{name}/health-check")
async def provider_health_check(name: str, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN))) -> dict:
    if name not in {"llm", "embedding", "vision", "stt", "tts"}:
        raise AppError("PROVIDER_NOT_FOUND", "Provider 不存在", 404, False, "settings")
    return {"name": name, **await _provider_health(name)}


def _pdf_bytes(rows: list[dict]) -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((48, 52), "VoiceInspect Fault Report", fontsize=18, color=(0.08, 0.13, 0.17))
    page.insert_text((48, 76), f"Generated records: {len(rows)}", fontsize=10, color=(0.35, 0.40, 0.43))
    y = 106
    for row in rows[:45]:
        text = f"{row['id'][:8]} | device={row['device_id'][:8]} | severity={row['severity']} | status={row['status']}"
        page.insert_text((48, y), text, fontsize=8, color=(0.08, 0.13, 0.17))
        y += 16
        if y > 760:
            page = document.new_page()
            y = 52
    return document.tobytes()


class EntityPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: str | None = Field(default=None, max_length=20)


@router.patch("/organizations/{organization_id}")
def organization_patch(organization_id: str, payload: EntityPatch, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    item = db.get(Organization, organization_id)
    if not item:
        raise AppError("ORGANIZATION_NOT_FOUND", "组织不存在", 404, False, "organization")
    if payload.name is not None:
        item.name = payload.name.strip()
    if payload.status is not None:
        item.status = payload.status
    _audit(db, user, "organization.updated", item.id)
    db.commit()
    return {"id": item.id, "name": item.name, "code": item.code, "status": item.status}


@router.patch("/sites/{site_id}")
def site_patch(site_id: str, payload: EntityPatch, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    item = db.get(Site, site_id)
    if not item:
        raise AppError("SITE_NOT_FOUND", "站点不存在", 404, False, "organization")
    if payload.name is not None:
        item.name = payload.name.strip()
    if payload.status is not None:
        item.status = payload.status
    _audit(db, user, "site.updated", item.id)
    db.commit()
    return {"id": item.id, "organization_id": item.organization_id, "name": item.name, "code": item.code, "status": item.status}


@router.patch("/production-lines/{line_id}")
def line_patch(line_id: str, payload: EntityPatch, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    item = db.get(ProductionLine, line_id)
    if not item:
        raise AppError("LINE_NOT_FOUND", "产线不存在", 404, False, "organization")
    if payload.name is not None:
        item.name = payload.name.strip()
    if payload.status is not None:
        item.status = payload.status
    _audit(db, user, "production_line.updated", item.id)
    db.commit()
    return {"id": item.id, "site_id": item.site_id, "organization_id": item.organization_id, "name": item.name, "code": item.code, "status": item.status}


@router.get("/audit-events")
def enterprise_audit_events(
    actor_id: str | None = None,
    action: str | None = None,
    target: str | None = None,
    trace_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(AuditEvent).order_by(desc(AuditEvent.created_at)).limit(500)
    if user.role != UserRole.SYSTEM_ADMIN.value:
        query = query.where(AuditEvent.actor_id == user.id)
    if actor_id:
        query = query.where(AuditEvent.actor_id == actor_id)
    if action:
        query = query.where(AuditEvent.action.contains(action))
    if target:
        query = query.where(AuditEvent.target.contains(target))
    if trace_id:
        query = query.where(AuditEvent.trace_id == trace_id)
    return [
        {
            "id": event.id,
            "trace_id": event.trace_id,
            "actor_id": event.actor_id,
            "action": event.action,
            "target": event.target,
            "result": event.result,
            "details": event.details,
            "created_at": event.created_at.isoformat(),
        }
        for event in db.scalars(query).all()
    ]


@router.post("/reports/session/{session_id}")
def report_session(session_id: str, payload: ReportPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    session = db.get(DiagnosisSession, session_id)
    if not session or (session.user_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value):
        raise AppError("SESSION_NOT_FOUND", "会话不存在或无权访问", 404, False, "report")
    if payload.format not in {"csv", "pdf"}:
        raise AppError("REPORT_FORMAT_INVALID", "仅支持 PDF 或 CSV", 422, False, "report")
    rows = [
        {
            "message_id": message.id,
            "role": message.role,
            "status": message.status,
            "text": message.text or "",
            "created_at": message.created_at.isoformat(),
            "citation_count": len(message.citations or []),
        }
        for message in session.messages
    ]
    if payload.format == "csv":
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=["message_id", "role", "status", "text", "created_at", "citation_count"])
        writer.writeheader()
        writer.writerows(rows)
        data, content_type = out.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8"
        filename = f"session-{session.id}.csv"
    else:
        summary_rows = [
            {"id": row["message_id"], "device_id": session.device_id or "none", "severity": row["role"], "status": row["status"]}
            for row in rows
        ]
        data, content_type = _pdf_bytes(summary_rows), "application/pdf"
        filename = f"session-{session.id}.pdf"
    folder = Path("./data/exports")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_bytes(data)
    item = ReportExport(owner_id=user.id, report_type="session", format=payload.format, file_name=filename, file_path=str(path), filters_json={"session_id": session.id})
    db.add(item)
    _audit(db, user, "report.session_created", item.id, {"session_id": session.id, "format": payload.format})
    db.commit()
    return {"id": item.id, "file_name": filename, "format": payload.format, "status": item.status}


class UserStatusPayload(BaseModel):
    status: str = Field(min_length=1, max_length=20)


@router.patch("/users/{user_id}/status")
def user_status(user_id: str, payload: UserStatusPayload, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    item = db.get(User, user_id)
    if not item:
        raise AppError("USER_NOT_FOUND", "用户不存在", 404, False, "user")
    if payload.status not in {"active", "disabled"}:
        raise AppError("USER_STATUS_INVALID", "账号状态无效", 422, False, "user")
    item.status = payload.status
    _audit(db, user, "user.status_updated", item.id, {"status": payload.status})
    db.commit()
    return {"id": item.id, "username": item.username, "role": item.role, "status": item.status, "organization_id": item.organization_id}
