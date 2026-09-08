from __future__ import annotations

import argparse
import getpass
import os

from sqlalchemy import select

from backend.core.security import hash_password, password_policy_error
from backend.repositories.db import SessionLocal
from backend.repositories.models import Organization, User


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or rotate a VoiceInspect system administrator.")
    parser.add_argument("--username", required=True, help="Administrator username")
    parser.add_argument("--password", help="Password; omit to use VOICEINSPECT_ADMIN_PASSWORD or an interactive prompt")
    parser.add_argument("--organization-id", default=None)
    args = parser.parse_args()

    password = args.password or os.getenv("VOICEINSPECT_ADMIN_PASSWORD") or getpass.getpass("New administrator password: ")
    policy_error = password_policy_error(password)
    if policy_error:
        raise SystemExit(policy_error)

    db = SessionLocal()
    try:
        if args.organization_id and not db.get(Organization, args.organization_id):
            raise SystemExit("organization not found")
        user = db.scalar(select(User).where(User.username == args.username.strip()))
        if user is None:
            user = User(
                username=args.username.strip(),
                password_hash=hash_password(password),
                role="system_admin",
                organization_id=args.organization_id,
                status="active",
            )
            db.add(user)
            action = "created"
        else:
            user.password_hash = hash_password(password)
            user.role = "system_admin"
            user.status = "active"
            if args.organization_id:
                if not db.get(Organization, args.organization_id):
                    raise SystemExit("organization not found")
                user.organization_id = args.organization_id
            action = "rotated"
        db.commit()
        print(f"system administrator {action}: {user.username}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
