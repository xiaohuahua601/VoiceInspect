from uuid import uuid4

from fastapi.testclient import TestClient

from backend.main import app


def test_logout_revokes_persisted_bearer_session():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "change-me"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        sessions = client.get("/api/v1/auth/sessions", headers=headers)
        assert sessions.status_code == 200
        assert sessions.json()
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
        expired = client.get("/api/v1/auth/me", headers=headers)
        assert expired.status_code == 401
        assert expired.json()["error"]["code"] == "AUTH_INVALID"


def test_refresh_rotates_bearer_session():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "change-me"})
        old_token = login.json()["access_token"]
        refreshed = client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {old_token}"})
        assert refreshed.status_code == 200
        new_token = refreshed.json()["access_token"]
        assert new_token != old_token
        assert client.get("/api/v1/sessions", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
        assert client.get("/api/v1/sessions", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200


def test_failed_login_is_rate_limited_after_threshold():
    with TestClient(app) as client:
        username = f"rate-limit-check-{uuid4().hex}"
        for _ in range(5):
            response = client.post("/api/v1/auth/login", json={"username": username, "password": "wrong"})
            assert response.status_code == 401
        locked = client.post("/api/v1/auth/login", json={"username": username, "password": "wrong"})
        assert locked.status_code == 429
        assert locked.json()["error"]["code"] == "AUTH_RATE_LIMITED"

def test_liveness_probe_is_independent_from_model_health():
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_refresh_rotates_bearer_session():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "change-me"})
        old_token = login.json()["access_token"]
        refreshed = client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {old_token}"})
        assert refreshed.status_code == 200
        new_token = refreshed.json()["access_token"]
        assert new_token != old_token
        assert client.get("/api/v1/sessions", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
        assert client.get("/api/v1/sessions", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200


def test_new_user_password_requires_strong_policy_and_first_login_change():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "change-me-admin"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        weak = client.post("/api/v1/users", headers=headers, json={"username": "weak-password-user", "password": "shortpass", "role": "operator"})
        assert weak.status_code == 422
        assert weak.json()["error"]["code"] == "PASSWORD_POLICY_INVALID"
        username = f"first-login-{uuid4().hex[:8]}"
        strong = client.post("/api/v1/users", headers=headers, json={"username": username, "password": "StrongPassword9", "role": "operator"})
        assert strong.status_code == 200
        assert strong.json()["must_change_password"] is True
