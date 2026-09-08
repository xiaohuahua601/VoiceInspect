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

def test_session_device_context_can_switch_with_access_check():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "change-me"})
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        devices = client.get("/api/v1/devices", headers=headers).json()
        compressor = next(item for item in devices if item["code"] == "A-01")
        hydraulic = next(item for item in devices if item["code"] == "H-01")
        session = client.post("/api/v1/sessions", headers=headers, json={"title": "设备上下文测试", "device_id": compressor["id"]}).json()
        updated = client.patch(f"/api/v1/sessions/{session['id']}", headers=headers, json={"device_id": hydraulic["id"]})
        assert updated.status_code == 200
        assert updated.json()["device_id"] == hydraulic["id"]
        forbidden = client.patch(f"/api/v1/sessions/{session['id']}", headers=headers, json={"device_id": "missing-device"})
        assert forbidden.status_code == 403