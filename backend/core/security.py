import base64
import hashlib
import hmac
import json
import secrets
import time


def password_policy_error(password: str) -> str | None:
    if len(password) < 12:
        return "密码至少需要 12 个字符"
    if not any(char.isupper() for char in password):
        return "密码必须包含至少一个大写字母"
    if not any(char.islower() for char in password):
        return "密码必须包含至少一个小写字母"
    if not any(char.isdigit() for char in password):
        return "密码必须包含至少一个数字"
    return None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt_text, digest_text = encoded.split("$", 2)
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str, username: str, role: str, secret: str, minutes: int, jti: str | None = None) -> str:
    payload = {"sub": user_id, "username": username, "role": role, "exp": int(time.time()) + minutes * 60}
    if jti:
        payload["jti"] = jti
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest()
    return raw + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def decode_access_token(token: str, secret: str) -> dict | None:
    try:
        raw, signature_text = token.split(".", 1)
        expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        if not hmac.compare_digest(actual, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
