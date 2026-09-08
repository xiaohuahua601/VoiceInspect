from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import Depends, Header
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.security import decode_access_token
from backend.domain.enums import UserRole
from backend.repositories.db import get_db
from backend.repositories.models import Device, User, UserScope
from backend.repositories.advanced_models import AuthSession


def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError("AUTH_REQUIRED", "请先登录", 401, False, "auth")
    payload = decode_access_token(authorization[7:].strip(), get_settings().access_token_secret)
    if not payload:
        raise AppError("AUTH_INVALID", "登录状态已失效，请重新登录", 401, False, "auth")
    if payload.get("jti"):
        auth_session = db.scalar(select(AuthSession).where(AuthSession.jti == payload["jti"]))
        expires_at = auth_session.expires_at.replace(tzinfo=timezone.utc) if auth_session and auth_session.expires_at and auth_session.expires_at.tzinfo is None else (auth_session.expires_at if auth_session else None)
        if not auth_session or auth_session.revoked_at or not expires_at or expires_at <= datetime.now(timezone.utc):
            raise AppError("AUTH_INVALID", "登录状态已失效，请重新登录", 401, False, "auth")
        auth_session.last_seen_at = datetime.now(timezone.utc)
        db.commit()
    user = db.get(User, payload.get("sub"))
    if not user or user.status != "active":
        raise AppError("AUTH_INVALID", "登录状态已失效，请重新登录", 401, False, "auth")
    return user


def require_roles(*roles: UserRole) -> Callable:
    allowed = {role.value for role in roles}

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise AppError("AUTH_FORBIDDEN", "当前账号没有执行此操作的权限", 403, False, "auth")
        return user

    return dependency

def require_any_role(*roles: UserRole) -> Callable:
    return require_roles(*roles)


def user_can_access_device(user: User, device: Device, db: Session) -> bool:
    if user.role == UserRole.SYSTEM_ADMIN.value:
        return True
    if not device.organization_id or user.organization_id != device.organization_id:
        return False
    scopes = db.scalars(select(UserScope).where(UserScope.user_id == user.id)).all()
    if not scopes:
        return True
    return any(
        scope.organization_id == device.organization_id
        and (scope.site_id is None or scope.site_id == device.site_id)
        and (scope.line_id is None or scope.line_id == device.line_id)
        for scope in scopes
    )


def visible_devices(user: User, db: Session) -> list[Device]:
    devices = db.scalars(select(Device).order_by(Device.code)).all()
    return [device for device in devices if user_can_access_device(user, device, db)]