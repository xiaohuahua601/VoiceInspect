from fastapi.testclient import TestClient

from backend.main import app


def test_health_and_login():
    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "change-me"})
        assert login.status_code == 200
        assert login.json()["token_type"] == "bearer"


def test_protected_route_rejects_missing_token():
    with TestClient(app) as client:
        response = client.get("/api/v1/sessions")
        assert response.status_code == 401

def test_all_demo_accounts_can_login():
    accounts = [
        ("operator", "change-me", "operator"),
        ("supervisor", "change-me-supervisor", "maintenance_supervisor"),
        ("knowledge-admin", "change-me-knowledge", "knowledge_admin"),
        ("admin", "change-me-admin", "system_admin"),
    ]
    with TestClient(app) as client:
        for username, password, role in accounts:
            response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
            assert response.status_code == 200, response.text
            assert response.json()["user"]["role"] == role