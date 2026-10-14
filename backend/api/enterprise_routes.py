from __future__ import annotations

import csv
import io
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, require_roles, user_can_access_device, visible_devices
from backend.api.pagination import normalize_page, page_result
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.security import hash_password, password_policy_error, verify_password
from backend.domain.enums import FaultStatus, KnowledgeStatus, UserRole
from backend.repositories.db import get_db
from backend.rag.service import KnowledgeService
from backend.providers.factory import create_embedding_provider, create_llm_provider, use_qwen
from backend.providers.stt import FasterWhisperSTT
from backend.providers.vision import OllamaVision
from backend.providers.tts import WindowsSapiTTS
from backend.providers.piper import PiperTTS
from backend.repositories.models import (
    AuditEvent, Citation, Device, DiagnosisSession, FaultEvent, FaultRecord, KnowledgeDoc, Message,
    Notification, Organization, ProductionLine, ProviderConfig, ReportExport, Site, User, UserScope,
    new_id, utc_now,
)
from backend.workers.queue import create_job, job_view
from backend.services.message_attachments import message_attachment_payloads
from backend.repositories.advanced_models import (
    Asset, BackgroundJob, CapabilityTask, Confirmation, JobEvent, MessageAsset,
    SessionEvent, ToolCall, ToolDraft,
)

router = APIRouter(prefix="/api/v1")
settings = get_settings()
knowledge_service = KnowledgeService(create_embedding_provider(settings))


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
    fault_location: str | None = Field(default=None, max_length=255)
    observed_evidence: str | None = Field(default=None, max_length=4000)
    resolution: str | None = Field(default=None, max_length=4000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class ReportPayload(BaseModel):
    format: str = "csv"


class SessionBatchDeletePayload(BaseModel):
    session_ids: list[str] = Field(min_length=1, max_length=100)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class PasswordReset(BaseModel):
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


def _fault_view(x: FaultRecord, db: Session | None = None) -> dict:
    assignee = db.get(User, x.assigned_to) if db and x.assigned_to else None
    return {"id": x.id, "device_id": x.device_id, "session_id": x.session_id, "symptom": x.symptom,
            "fault_location": x.fault_location, "observed_evidence": x.observed_evidence,
            "severity": x.severity, "status": x.status, "creator_id": x.creator_id, "assigned_to": x.assigned_to,
            "assigned_to_name": assignee.username if assignee else None,
            "resolution": x.resolution, "due_at": x.due_at, "created_at": x.created_at, "updated_at": x.updated_at}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    scopes = db.scalars(select(UserScope).where(UserScope.user_id == user.id)).all()
    return {"id": user.id, "username": user.username, "role": user.role, "status": user.status,
            "must_change_password": user.must_change_password, "organization_id": user.organization_id,
            "scopes": [{"organization_id": x.organization_id, "site_id": x.site_id, "line_id": x.line_id} for x in scopes]}


@router.post("/auth/change-password")
def change_password(payload: PasswordChange, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if not verify_password(payload.current_password, user.password_hash):
        raise AppError("PASSWORD_INVALID", "当前密码不正确", 400, False, "auth")
    if policy_error := password_policy_error(payload.new_password):
        raise AppError("PASSWORD_POLICY_INVALID", policy_error, 422, False, "auth")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
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
def device_list(page: int | None = None, page_size: int = 20, search: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict] | dict:
    normalized = normalize_page(page, page_size)
    items = [_device_view(x) for x in visible_devices(user, db)]
    if search:
        keyword = search.strip().lower()
        items = [item for item in items if keyword in (item["code"] + item["name"] + item["model"]).lower()]
    if normalized:
        current_page, current_size = normalized
        start = (current_page - 1) * current_size
        return page_result(items[start:start + current_size], len(items), current_page, current_size)
    return items


@router.post("/devices")
def device_create(payload: DevicePayload, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    _validate_device_hierarchy(db, payload.organization_id, payload.site_id, payload.line_id)
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
    _validate_device_hierarchy(db, payload.organization_id, payload.site_id, payload.line_id)
    item.code, item.name, item.model = payload.code.strip(), payload.name.strip(), payload.model.strip()
    item.organization_id, item.site_id, item.line_id, item.metadata_json = payload.organization_id, payload.site_id, payload.line_id, payload.metadata
    _audit(db, user, "device.updated", item.id); db.commit()
    return _device_view(item)


@router.get("/users")
def user_list(page: int | None = None, page_size: int = 20, search: str | None = None, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> list[dict] | dict:
    normalized = normalize_page(page, page_size)
    q = select(User).order_by(User.username)
    if search:
        keyword = f"%{search.strip()}%"
        q = q.where(User.username.ilike(keyword) | User.role.ilike(keyword) | User.organization_id.ilike(keyword))
    rows = db.scalars(q).all()
    items = [{"id": x.id, "username": x.username, "role": x.role, "status": x.status, "organization_id": x.organization_id, "must_change_password": x.must_change_password, "created_at": x.created_at} for x in rows]
    if normalized:
        current_page, current_size = normalized
        start = (current_page - 1) * current_size
        return page_result(items[start:start + current_size], len(items), current_page, current_size)
    return items


@router.post("/users")
def user_create(payload: UserPayload, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    valid = {x.value for x in UserRole if x.value != "guest"}
    if payload.role not in valid:
        raise AppError("ROLE_INVALID", "角色不存在", 422, False, "user")
    if payload.organization_id and not db.get(Organization, payload.organization_id):
        raise AppError("ORGANIZATION_NOT_FOUND", "组织不存在", 404, False, "organization")
    if db.scalar(select(User).where(User.username == payload.username.strip())):
        raise AppError("USER_EXISTS", "用户名已存在", 409, False, "user")
    if policy_error := password_policy_error(payload.password):
        raise AppError("PASSWORD_POLICY_INVALID", policy_error, 422, False, "user")
    item = User(username=payload.username.strip(), password_hash=hash_password(payload.password), role=payload.role, organization_id=payload.organization_id, must_change_password=True)
    db.add(item); db.flush(); _audit(db, user, "user.created", item.id); db.commit()
    return {"id": item.id, "username": item.username, "role": item.role, "status": item.status, "organization_id": item.organization_id, "must_change_password": item.must_change_password}


@router.patch("/users/{user_id}")
def user_patch(user_id: str, payload: UserPatch, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    item = db.get(User, user_id)
    if not item:
        raise AppError("USER_NOT_FOUND", "用户不存在", 404, False, "user")
    if payload.role:
        valid = {x.value for x in UserRole if x.value != "guest"}
        if payload.role not in valid:
            raise AppError("ROLE_INVALID", "角色不存在", 422, False, "user")
        item.role = payload.role
    if payload.status:
        if payload.status not in {"active", "disabled"}:
            raise AppError("USER_STATUS_INVALID", "账号状态无效", 422, False, "user")
        item.status = payload.status
        if payload.status == "disabled":
            from backend.repositories.advanced_models import AuthSession
            now = datetime.now(timezone.utc)
            for session in db.scalars(select(AuthSession).where(AuthSession.user_id == item.id, AuthSession.revoked_at.is_(None))).all():
                session.revoked_at = now
    if payload.organization_id is not None:
        if not db.get(Organization, payload.organization_id):
            raise AppError("ORGANIZATION_NOT_FOUND", "组织不存在", 404, False, "organization")
        item.organization_id = payload.organization_id
    _audit(db, user, "user.updated", item.id); db.commit()
    return {"id": item.id, "username": item.username, "role": item.role, "status": item.status, "organization_id": item.organization_id, "must_change_password": item.must_change_password}


@router.post("/users/{user_id}/reset-password")
def user_reset_password(user_id: str, payload: PasswordReset, user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    target = db.get(User, user_id)
    if not target:
        raise AppError("USER_NOT_FOUND", "用户不存在", 404, False, "user")
    if policy_error := password_policy_error(payload.new_password):
        raise AppError("PASSWORD_POLICY_INVALID", policy_error, 422, False, "user")
    target.password_hash = hash_password(payload.new_password)
    target.must_change_password = True
    from backend.repositories.advanced_models import AuthSession
    now = datetime.now(timezone.utc)
    for session in db.scalars(select(AuthSession).where(AuthSession.user_id == target.id, AuthSession.revoked_at.is_(None))).all():
        session.revoked_at = now
    _audit(db, user, "user.password_reset", target.id)
    db.commit()
    return {"id": target.id, "username": target.username, "must_change_password": True}


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
def fault_list(status: str | None = None, severity: str | None = None, search: str | None = None, page: int | None = None, page_size: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict] | dict:
    normalized = normalize_page(page, page_size)
    ids = {x.id for x in visible_devices(user, db)}
    q = select(FaultRecord).where(FaultRecord.device_id.in_(ids)).order_by(desc(FaultRecord.updated_at))
    if status: q = q.where(FaultRecord.status == status)
    if severity: q = q.where(FaultRecord.severity == severity)
    items = [_fault_view(x, db) for x in db.scalars(q).all()]
    if search:
        keyword = search.strip().lower()
        items = [item for item in items if keyword in (item["symptom"] + item["device_id"] + (item["assigned_to_name"] or "")).lower()]
    if normalized:
        current_page, current_size = normalized
        start = (current_page - 1) * current_size
        return page_result(items[start:start + current_size], len(items), current_page, current_size)
    return items


def _fault(db: Session, fault_id: str, user: User) -> FaultRecord:
    item = db.get(FaultRecord, fault_id)
    if not item: raise AppError("FAULT_NOT_FOUND", "故障记录不存在", 404, False, "fault")
    _device(db, item.device_id, user)
    return item


def _validate_assignee(db: Session, item: FaultRecord, assigned_to: str | None) -> User | None:
    if not assigned_to:
        return None
    device = db.get(Device, item.device_id)
    assignee = db.get(User, assigned_to)
    if not assignee or assignee.status != "active" or assignee.role not in {UserRole.OPERATOR.value, UserRole.MAINTENANCE_SUPERVISOR.value} or not device or assignee.organization_id != device.organization_id:
        raise AppError("FAULT_ASSIGNEE_INVALID", "负责人必须是同组织的在岗操作员或维修主管", 422, False, "fault")
    return assignee

def _transition(db: Session, item: FaultRecord, user: User, target: FaultStatus, action: str, payload: FaultAction) -> dict:
    allowed = {FaultStatus.NEW: {FaultStatus.CONFIRMED}, FaultStatus.CONFIRMED: {FaultStatus.IN_PROGRESS},
               FaultStatus.IN_PROGRESS: {FaultStatus.PENDING_VERIFICATION}, FaultStatus.PENDING_VERIFICATION: {FaultStatus.CLOSED}}
    if target not in allowed.get(FaultStatus(item.status), set()):
        raise AppError("FAULT_STATUS_TRANSITION_INVALID", "当前故障状态不允许此操作", 409, False, "fault")
    before = item.status; item.status = target.value
    if payload.fault_location is not None: item.fault_location = payload.fault_location.strip() or None
    if payload.observed_evidence is not None: item.observed_evidence = payload.observed_evidence.strip() or None
    if target == FaultStatus.CONFIRMED: item.confirmed_by = user.id
    if target == FaultStatus.PENDING_VERIFICATION: item.verified_by = user.id
    if target == FaultStatus.CLOSED:
        location = item.fault_location
        evidence = item.observed_evidence
        resolution = (payload.resolution or payload.note or "").strip()
        if not location or not evidence or not resolution:
            raise AppError("FAULT_CLOSURE_CONTEXT_REQUIRED", "关闭故障前必须填写故障部位、现场证据和处理结果", 422, False, "fault")
        item.closed_by, item.resolution = user.id, resolution
    if payload.assigned_to: item.assigned_to = _validate_assignee(db, item, payload.assigned_to).id
    db.add(FaultEvent(fault_id=item.id, actor_id=user.id, from_status=before, to_status=item.status, note=payload.note or payload.resolution))
    _audit(db, user, action, item.id, {"from": before, "to": item.status}); db.commit(); db.refresh(item)
    return _fault_view(item, db)


@router.get("/fault-records/assignees")
def fault_assignees(fault_id: str, user: User = Depends(require_roles(UserRole.MAINTENANCE_SUPERVISOR, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> list[dict]:
    item = _fault(db, fault_id, user)
    device = db.get(Device, item.device_id)
    if not device:
        raise AppError("FAULT_NOT_FOUND", "故障设备不存在", 404, False, "fault")
    q = select(User).where(
        User.organization_id == device.organization_id,
        User.status == "active",
        User.role.in_([UserRole.OPERATOR.value, UserRole.MAINTENANCE_SUPERVISOR.value]),
    ).order_by(User.username)
    return [{"id": x.id, "username": x.username, "role": x.role, "status": x.status, "organization_id": x.organization_id} for x in db.scalars(q).all()]


@router.get("/fault-records/overdue")
def overdue_faults(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    now = datetime.now(timezone.utc)
    ids = {x.id for x in visible_devices(user, db)}
    rows = db.scalars(select(FaultRecord).where(FaultRecord.device_id.in_(ids), FaultRecord.due_at.is_not(None), FaultRecord.due_at < now, FaultRecord.status != FaultStatus.CLOSED.value).order_by(FaultRecord.due_at)).all()
    return [_fault_view(x, db) for x in rows]


@router.get("/fault-records/{fault_id}")
def fault_detail(fault_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = _fault(db, fault_id, user)
    events = db.scalars(select(FaultEvent).where(FaultEvent.fault_id == item.id).order_by(FaultEvent.created_at)).all()
    processing_event = next(
        (event for event in reversed(events) if event.to_status == FaultStatus.PENDING_VERIFICATION.value and event.note),
        None,
    )
    processing_actor = db.get(User, processing_event.actor_id) if processing_event else None
    return {
        **_fault_view(item, db),
        "processing_result": processing_event.note if processing_event else None,
        "processing_by_name": processing_actor.username if processing_actor else None,
        "processing_by_role": processing_actor.role if processing_actor else None,
        "processing_at": processing_event.created_at if processing_event else None,
        "events": [
            {
                "id": x.id,
                "from_status": x.from_status,
                "to_status": x.to_status,
                "note": x.note,
                "actor_id": x.actor_id,
                "actor_name": (db.get(User, x.actor_id).username if db.get(User, x.actor_id) else x.actor_id),
                "actor_role": (db.get(User, x.actor_id).role if db.get(User, x.actor_id) else None),
                "created_at": x.created_at,
            }
            for x in events
        ],
    }


def _fault_action(fault_id: str, payload: FaultAction | None, target: FaultStatus, action: str, user: User, db: Session) -> dict:
    return _transition(db, _fault(db, fault_id, user), user, target, action, payload or FaultAction())


@router.post("/fault-records/{fault_id}/confirm")
def fault_confirm(fault_id: str, payload: FaultAction | None = None, user: User = Depends(require_roles(UserRole.MAINTENANCE_SUPERVISOR, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _fault_action(fault_id, payload, FaultStatus.CONFIRMED, "fault.confirmed", user, db)


@router.post("/fault-records/{fault_id}/assign")
def fault_assign(fault_id: str, payload: FaultAction, user: User = Depends(require_roles(UserRole.MAINTENANCE_SUPERVISOR, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    item = _fault(db, fault_id, user)
    if not payload.assigned_to:
        raise AppError("FAULT_ASSIGNEE_REQUIRED", "请选择负责人", 422, False, "fault")
    assignee = _validate_assignee(db, item, payload.assigned_to)
    if item.status in {FaultStatus.CLOSED.value, FaultStatus.PENDING_VERIFICATION.value}:
        raise AppError("FAULT_STATUS_TRANSITION_INVALID", "当前故障状态不允许分派或改派", 409, False, "fault")
    if item.status not in {FaultStatus.CONFIRMED.value, FaultStatus.IN_PROGRESS.value}:
        raise AppError("FAULT_STATUS_TRANSITION_INVALID", "请先确认故障后再分派", 409, False, "fault")
    if item.status == FaultStatus.IN_PROGRESS.value and item.assigned_to == assignee.id:
        return _fault_view(item, db)
    before = item.status
    item.assigned_to = assignee.id
    if not item.due_at:
        item.due_at = datetime.now(timezone.utc) + timedelta(hours=24)
    if before == FaultStatus.CONFIRMED.value:
        item.status = FaultStatus.IN_PROGRESS.value
    note = payload.note or ("重新分派给 " + assignee.username if before == FaultStatus.IN_PROGRESS.value else "分派给 " + assignee.username)
    db.add(FaultEvent(fault_id=item.id, actor_id=user.id, from_status=before, to_status=item.status, note=note))
    db.add(Notification(recipient_id=assignee.id, kind="fault_assignment", title="新的故障处理任务", body=f"故障 {item.id[:8]} 已分派给你：{item.symptom[:120]}", target_type="fault", target_id=item.id))
    _audit(db, user, "fault.reassigned" if before == FaultStatus.IN_PROGRESS.value else "fault.assigned", item.id, {"from": before, "to": item.status, "assigned_to": assignee.id, "assigned_to_name": assignee.username, "idempotency_key": payload.idempotency_key})
    db.commit(); db.refresh(item)
    return _fault_view(item, db)

@router.post("/fault-records/{fault_id}/start")
def fault_start(fault_id: str, payload: FaultAction | None = None, user: User = Depends(require_roles(UserRole.MAINTENANCE_SUPERVISOR, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _fault_action(fault_id, payload, FaultStatus.IN_PROGRESS, "fault.started", user, db)


@router.post("/fault-records/{fault_id}/submit-verification")
def fault_submit_verification(fault_id: str, payload: FaultAction, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = _fault(db, fault_id, user)
    if user.role != UserRole.OPERATOR.value or item.assigned_to != user.id:
        raise AppError("AUTH_FORBIDDEN", "只有当前负责人操作员可以提交处理结果", 403, False, "auth")
    if item.status != FaultStatus.IN_PROGRESS.value:
        raise AppError("FAULT_STATUS_TRANSITION_INVALID", "只有处理中故障可以提交处理结果", 409, False, "fault")
    if not (payload.note or payload.resolution):
        raise AppError("FAULT_PROCESSING_NOTE_REQUIRED", "请填写处理结果或复测说明", 422, False, "fault")
    location = (payload.fault_location or item.fault_location or "").strip()
    evidence = (payload.observed_evidence or item.observed_evidence or "").strip()
    if not location or not evidence:
        raise AppError("FAULT_CLOSURE_CONTEXT_REQUIRED", "请先填写故障部位和现场证据", 422, False, "fault")

    before = item.status
    item.fault_location = location
    item.observed_evidence = evidence
    item.status = FaultStatus.PENDING_VERIFICATION.value
    db.add(FaultEvent(
        fault_id=item.id,
        actor_id=user.id,
        from_status=before,
        to_status=item.status,
        note=payload.note or payload.resolution,
    ))
    _audit(db, user, "fault.submitted_for_verification", item.id, {
        "from": before,
        "to": item.status,
        "assigned_to": item.assigned_to,
    })
    db.commit()
    db.refresh(item)
    return _fault_view(item, db)


@router.post("/fault-records/{fault_id}/verify")
def fault_verify(fault_id: str, payload: FaultAction | None = None, user: User = Depends(require_roles(UserRole.MAINTENANCE_SUPERVISOR, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _fault_action(fault_id, payload, FaultStatus.PENDING_VERIFICATION, "fault.pending_verification", user, db)


@router.post("/fault-records/{fault_id}/close")
def fault_close(fault_id: str, payload: FaultAction, user: User = Depends(require_roles(UserRole.MAINTENANCE_SUPERVISOR, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    return _fault_action(fault_id, payload, FaultStatus.CLOSED, "fault.closed", user, db)


@router.get("/notifications")
def notification_list(page: int | None = None, page_size: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict] | dict:
    normalized = normalize_page(page, page_size)
    rows = db.scalars(select(Notification).where(Notification.recipient_id == user.id).order_by(desc(Notification.created_at)).limit(500)).all()
    items = [{"id": x.id, "kind": x.kind, "title": x.title, "body": x.body, "target_type": x.target_type, "target_id": x.target_id, "read": bool(x.read_at), "created_at": x.created_at} for x in rows]
    if normalized:
        current_page, current_size = normalized
        start = (current_page - 1) * current_size
        return page_result(items[start:start + current_size], len(items), current_page, current_size)
    return items


@router.post("/notifications/read-all")
def notification_read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Mark only the current user's notifications as read."""
    now = utc_now()
    updated = db.query(Notification).filter(
        Notification.recipient_id == user.id,
        Notification.read_at.is_(None),
    ).update({"read_at": now}, synchronize_session=False)
    db.commit()
    return {"updated": int(updated), "read": True}


@router.post("/notifications/{notification_id}/read")
def notification_read(notification_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(Notification, notification_id)
    if not item or item.recipient_id != user.id:
        raise AppError("NOTIFICATION_NOT_FOUND", "通知不存在", 404, False, "notification")
    item.read_at = utc_now(); db.commit()
    return {"id": item.id, "read": True}


@router.get("/knowledge/documents")
def knowledge_list(status: str | None = None, search: str | None = None, page: int | None = None, page_size: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict] | dict:
    normalized = normalize_page(page, page_size)
    q = select(KnowledgeDoc).order_by(desc(KnowledgeDoc.created_at))
    if user.role != UserRole.SYSTEM_ADMIN.value: q = q.where(KnowledgeDoc.organization_id == user.organization_id)
    if status: q = q.where(KnowledgeDoc.status == status)
    items = [{"id": x.id, "name": x.name, "version": x.version, "status": x.status, "organization_id": x.organization_id, "failure_reason": x.failure_reason, "metadata": x.metadata_json or {}, "chunks": len(x.chunks), "created_at": x.created_at} for x in db.scalars(q).all()]
    if search:
        keyword = search.strip().lower()
        items = [item for item in items if keyword in (item["name"] + str(item["metadata"])).lower()]
    if normalized:
        current_page, current_size = normalized
        start = (current_page - 1) * current_size
        return page_result(items[start:start + current_size], len(items), current_page, current_size)
    return items


@router.get("/knowledge/documents/{document_id}")
def knowledge_detail(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(KnowledgeDoc, document_id)
    if not item or (user.role != UserRole.SYSTEM_ADMIN.value and item.organization_id != user.organization_id):
        raise AppError("KNOWLEDGE_NOT_FOUND", "知识文档不存在或��权访问", 404, False, "rag")
    return {"id": item.id, "name": item.name, "version": item.version, "status": item.status, "failure_reason": item.failure_reason, "metadata": item.metadata_json or {},
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
async def knowledge_retry(document_id: str, user: User = Depends(require_roles(UserRole.KNOWLEDGE_ADMIN, UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> dict:
    item = db.get(KnowledgeDoc, document_id)
    if not item or (user.role != UserRole.SYSTEM_ADMIN.value and item.organization_id != user.organization_id):
        raise AppError("KNOWLEDGE_NOT_FOUND", "知识文档不存在或无权访问", 404, False, "rag")
    item = await knowledge_service.reindex_document(db, item)
    _audit(db, user, "knowledge.retried", item.id, {"chunks": len(item.chunks)})
    db.commit()
    return {"id": item.id, "status": item.status, "chunks": len(item.chunks), "failure_reason": item.failure_reason}



@router.post("/reports/faults", status_code=202)
def report_faults(payload: ReportPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if payload.format not in {"csv", "pdf"}: raise AppError("REPORT_FORMAT_INVALID", "仅支持 PDF 或 CSV", 422, False, "report")
    ids = {x.id for x in visible_devices(user, db)}
    item = ReportExport(owner_id=user.id, report_type="faults", format=payload.format, file_name="", file_path="", status="queued", filters_json={"device_ids": list(ids)})
    db.add(item)
    db.flush()
    job = create_job(db, kind="report.render", owner_id=user.id, payload={"report_id": item.id}, max_attempts=2)
    item.job_id = job.id
    _audit(db, user, "report.created", item.id, {"format": payload.format, "job_id": job.id})
    db.commit()
    return {"id": item.id, "job_id": job.id, "file_name": None, "format": payload.format, "status": item.status}


@router.get("/reports")
def report_list(page: int | None = None, page_size: int = 20, status: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict] | dict:
    normalized = normalize_page(page, page_size)
    query = select(ReportExport).order_by(desc(ReportExport.created_at))
    if user.role != UserRole.SYSTEM_ADMIN.value:
        query = query.where(ReportExport.owner_id == user.id)
    if status:
        query = query.where(ReportExport.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query).all() if not normalized else db.scalars(query.offset((normalized[0] - 1) * normalized[1]).limit(normalized[1])).all()
    items = [{"id": item.id, "job_id": item.job_id, "report_type": item.report_type, "file_name": item.file_name or None, "format": item.format, "status": item.status, "error_code": item.error_code, "created_at": item.created_at, "completed_at": item.completed_at} for item in rows]
    if normalized:
        return page_result(items, total, normalized[0], normalized[1])
    return items


@router.get("/reports/{report_id}")
def report_detail(report_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(ReportExport, report_id)
    if not item or (item.owner_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value):
        raise AppError("REPORT_NOT_FOUND", "报告不存在或无权访问", 404, False, "report")
    return {"id": item.id, "job_id": item.job_id, "file_name": item.file_name or None, "format": item.format, "status": item.status, "error_code": item.error_code, "created_at": item.created_at, "completed_at": item.completed_at}


@router.get("/reports/{report_id}/download")
def report_download(report_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    item = db.get(ReportExport, report_id)
    if not item or (item.owner_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value):
        raise AppError("REPORT_NOT_FOUND", "报告不存在或无权访问", 404, False, "report")
    if item.status != "ready" or not item.file_path:
        raise AppError("REPORT_NOT_READY", "报告仍在生成，请稍后重试", 409, True, "report")
    if not Path(item.file_path).is_file():
        raise AppError("REPORT_FILE_MISSING", "报告文件不存在，请重新生成", 500, True, "report")
    return FileResponse(item.file_path, filename=item.file_name)


@router.get("/settings/providers")
def provider_list(user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)), db: Session = Depends(get_db)) -> list[dict]:
    defaults = {"llm": settings.qwen_model if use_qwen(settings) else settings.ollama_llm_model, "embedding": settings.ollama_embed_model, "vision": settings.qwen_model if use_qwen(settings) else settings.ollama_vision_model, "stt": settings.stt_model_size, "tts": settings.piper_voice}
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
    configured = {row.name: row.model for row in db.scalars(select(ProviderConfig)).all()}
    checks = {name: await _provider_health(name, configured.get(name)) for name in ("llm", "embedding", "vision", "stt", "tts")}
    return {"status": "ok" if all(value.get("available") for value in checks.values()) else "degraded", "database": {"available": True}, **checks}

@router.get("/sessions")
def enterprise_session_list(page: int | None = None, page_size: int = 20, search: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict] | dict:
    normalized = normalize_page(page, page_size)
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
            "user_id": item.user_id,
            "status": item.status,
            "device_id": item.device_id,
            "organization_id": item.organization_id,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        })
    if search:
        keyword = search.strip().lower()
        visible = [item for item in visible if keyword in (item["title"] + (item["device_id"] or "")).lower()]
    if normalized:
        current_page, current_size = normalized
        start = (current_page - 1) * current_size
        return page_result(visible[start:start + current_size], len(visible), current_page, current_size)
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
        "user_id": item.user_id,
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
                "observations": message.observations or {},
                "transcript": message.transcript or {},
                "attachments": message_attachment_payloads(db, message),
                "created_at": message.created_at,
            }
            for message in sorted(item.messages, key=lambda value: value.created_at)
        ],
    }

def _delete_session_data(db: Session, item: DiagnosisSession, user: User) -> tuple[dict, list[Path]]:
    """Remove conversation-owned data without committing the surrounding transaction."""
    message_ids = list(db.scalars(select(Message.id).where(Message.session_id == item.id)))
    job_ids = list(db.scalars(select(BackgroundJob.id).where(BackgroundJob.session_id == item.id)))
    draft_ids = list(db.scalars(select(ToolDraft.id).where(ToolDraft.session_id == item.id)))
    assets = list(db.scalars(select(Asset).where(Asset.session_id == item.id)))
    report_rows = list(db.scalars(select(ReportExport).where(ReportExport.job_id.in_(job_ids)))) if job_ids else []
    file_paths = [settings.upload_dir / asset.stored_name for asset in assets]
    file_paths.extend(Path(report.file_path) for report in report_rows if report.file_path)

    # Fault records have an independent operational and audit lifecycle. Retain
    # them but break the optional conversation link before deleting the session.
    db.query(FaultRecord).filter(FaultRecord.session_id == item.id).update({"session_id": None}, synchronize_session=False)
    if draft_ids:
        db.execute(delete(Confirmation).where(Confirmation.draft_id.in_(draft_ids)))
        db.execute(delete(ToolCall).where(ToolCall.draft_id.in_(draft_ids)))
        db.execute(delete(ToolDraft).where(ToolDraft.id.in_(draft_ids)))
    if job_ids:
        db.execute(delete(JobEvent).where(JobEvent.job_id.in_(job_ids)))
        if report_rows:
            db.execute(delete(ReportExport).where(ReportExport.id.in_([report.id for report in report_rows])))
    db.execute(delete(CapabilityTask).where(CapabilityTask.session_id == item.id))
    if message_ids:
        db.execute(delete(MessageAsset).where(MessageAsset.message_id.in_(message_ids)))
        db.execute(delete(Citation).where(Citation.message_id.in_(message_ids)))
        db.execute(delete(Message).where(Message.id.in_(message_ids)))
    db.execute(delete(SessionEvent).where(SessionEvent.session_id == item.id))
    if job_ids:
        db.execute(delete(BackgroundJob).where(BackgroundJob.id.in_(job_ids)))
    if assets:
        db.execute(delete(Asset).where(Asset.id.in_([asset.id for asset in assets])))

    title = item.title
    db.delete(item)
    summary = {
        "id": item.id,
        "title": title,
        "deleted": True,
        "message_count": len(message_ids),
        "attachment_count": len(assets),
        "report_count": len(report_rows),
        "job_count": len(job_ids),
    }
    _audit(db, user, "session.deleted", item.id, {
        "title": title,
        "message_count": len(message_ids),
        "attachment_count": len(assets),
        "report_count": len(report_rows),
        "job_count": len(job_ids),
        "fault_links_retained": True,
    })
    return summary, file_paths


def _remove_session_files(file_paths: list[Path]) -> int:
    removed_files = 0
    roots = (settings.upload_dir.resolve(), settings.export_dir.resolve())
    for path in file_paths:
        resolved = path.resolve()
        if any(root == resolved or root in resolved.parents for root in roots):
            try:
                resolved.unlink(missing_ok=True)
                removed_files += 1
            except OSError:
                # The database operation is authoritative. A missing or locked
                # local file must not make a deleted session appear restored.
                pass
    return removed_files


def _session_delete_job(db: Session, session_id: str) -> str | None:
    return db.scalar(
        select(BackgroundJob.id).where(
            BackgroundJob.session_id == session_id,
            BackgroundJob.status.in_({"queued", "running", "retrying"}),
        ).limit(1)
    )


@router.post("/sessions/batch-delete")
def batch_delete_sessions(payload: SessionBatchDeletePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Delete selected sessions in one transaction and report non-deletable rows."""
    session_ids = list(dict.fromkeys(payload.session_ids))
    deleted: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    file_paths: list[Path] = []
    try:
        for session_id in session_ids:
            item = db.get(DiagnosisSession, session_id)
            if not item or (item.user_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value):
                failed.append({"id": session_id, "reason": "会话不存在或无权删除"})
                continue
            active_job = _session_delete_job(db, item.id)
            if active_job:
                skipped.append({
                    "id": item.id,
                    "title": item.title,
                    "reason": "会话仍有正在处理的任务，请先等待完成或取消任务",
                    "job_id": active_job,
                })
                continue
            summary, paths = _delete_session_data(db, item, user)
            deleted.append(summary)
            file_paths.extend(paths)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "requested": len(session_ids),
        "deleted": deleted,
        "skipped": skipped,
        "failed": failed,
        "files_removed": _remove_session_files(file_paths),
    }


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Permanently remove an owned session after all active work has stopped."""
    item = db.get(DiagnosisSession, session_id)
    if not item or (item.user_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value):
        raise AppError("SESSION_NOT_FOUND", "会话不存在或无权删除", 404, False, "session")
    active_job = _session_delete_job(db, item.id)
    if active_job:
        raise AppError(
            "SESSION_DELETE_JOB_ACTIVE",
            "会话仍有正在处理的任务，请先等待完成或取消任务后再删除",
            409,
            True,
            "session",
            {"job_id": active_job},
        )
    try:
        summary, file_paths = _delete_session_data(db, item, user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"id": summary["id"], "deleted": True, "files_removed": _remove_session_files(file_paths)}

async def _provider_health(name: str, model: str | None = None) -> dict:
    if name in {"llm", "embedding", "vision"}:
        if name == "embedding":
            health = await create_embedding_provider(settings).health()
            wanted = model or settings.ollama_embed_model
            reason = "Embedding 模型未安装或 Ollama 不可用"
        else:
            health = await create_llm_provider(settings).health()
            wanted = model or (settings.qwen_model if use_qwen(settings) else (settings.ollama_llm_model if name == "llm" else settings.ollama_vision_model))
            reason = "模型未配置或服务不可用"
        available = bool(health.get("available"))
        models = health.get("models", [])
        if available and models and wanted:
            available = wanted in models
        return {"available": available, "model": wanted, "models": models, "reason": None if available else reason}
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
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int | None = None,
    page_size: int = 20,
    search: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict] | dict:
    normalized = normalize_page(page, page_size)
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
    if created_from:
        query = query.where(AuditEvent.created_at >= created_from)
    if created_to:
        query = query.where(AuditEvent.created_at <= created_to)
    if search:
        query = query.where(AuditEvent.action.contains(search) | AuditEvent.target.contains(search) | AuditEvent.trace_id.contains(search))
    items = [
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
    if normalized:
        current_page, current_size = normalized
        start = (current_page - 1) * current_size
        return page_result(items[start:start + current_size], len(items), current_page, current_size)
    return items


@router.post("/reports/session/{session_id}", status_code=202)
def report_session(session_id: str, payload: ReportPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    session = db.get(DiagnosisSession, session_id)
    if not session or (session.user_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value):
        raise AppError("SESSION_NOT_FOUND", "会话不存在或无权访问", 404, False, "report")
    if payload.format not in {"csv", "pdf"}:
        raise AppError("REPORT_FORMAT_INVALID", "仅支持 PDF 或 CSV", 422, False, "report")
    item = ReportExport(owner_id=user.id, report_type="session", format=payload.format, file_name="", file_path="", status="queued", filters_json={"session_id": session.id, "device_id": session.device_id})
    db.add(item)
    db.flush()
    job = create_job(db, kind="report.render", owner_id=user.id, payload={"report_id": item.id}, max_attempts=2)
    item.job_id = job.id
    _audit(db, user, "report.session_created", item.id, {"session_id": session.id, "format": payload.format, "job_id": job.id})
    db.commit()
    return {"id": item.id, "job_id": job.id, "file_name": None, "format": payload.format, "status": item.status}


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
    if payload.status == "disabled":
        from backend.repositories.advanced_models import AuthSession
        now = datetime.now(timezone.utc)
        for session in db.scalars(select(AuthSession).where(AuthSession.user_id == item.id, AuthSession.revoked_at.is_(None))).all():
            session.revoked_at = now
    _audit(db, user, "user.status_updated", item.id, {"status": payload.status})
    db.commit()
    return {"id": item.id, "username": item.username, "role": item.role, "status": item.status, "organization_id": item.organization_id, "must_change_password": item.must_change_password}
