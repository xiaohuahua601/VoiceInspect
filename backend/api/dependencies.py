from collections.abc import Callable

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.security import decode_access_token
from backend.domain.enums import UserRole
from backend.repositories.db import get_db
from backend.repositories.models import User


def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError("AUTH_REQUIRED", "请先登录", 401, False, "auth")
    payload = decode_access_token(authorization[7:].strip(), get_settings().access_token_secret)
    if not payload:
        raise AppError("AUTH_INVALID", "登录状态已失效，请重新登录", 401, False, "auth")
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
