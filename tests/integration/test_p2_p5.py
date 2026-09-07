from uuid import uuid4

from fastapi.testclient import TestClient

from backend.main import app


def auth_client():
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"username": "operator", "password": "change-me"})
    assert response.status_code == 200
    client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
    return client


def test_capability_health_and_asset_signature_validation():
    client = auth_client()
    capabilities = client.get("/api/v1/capabilities")
    assert capabilities.status_code == 200
    assert {"stt", "vision", "tts"} <= capabilities.json().keys()

    invalid = client.post(
        "/api/v1/assets",
        files={"file": ("fake.png", b"not-a-png", "image/png")},
        data={"kind": "image"},
    )
    assert invalid.status_code == 415
    assert invalid.json()["error"]["code"] == "IMAGE_SIGNATURE_INVALID"


def test_fault_confirmation_is_idempotent():
    client = auth_client()
    device = client.get("/api/v1/devices").json()[0]
    session = client.post("/api/v1/sessions", json={"title": "idempotency test", "device_id": device["id"]}).json()
    key = f"test-{uuid4()}"
    draft = client.post(
        "/api/v1/tool-drafts",
        json={
            "session_id": session["id"],
            "tool_name": "create_fault_record",
            "arguments": {"device_id": device["id"], "symptom": "test symptom", "severity": "low", "idempotency_key": key},
        },
    )
    assert draft.status_code == 200
    token = draft.json()["confirmation_token"]
    first = client.post(f"/api/v1/confirmations/{token}")
    second = client.post(f"/api/v1/confirmations/{token}")
    assert first.status_code == second.status_code == 200
    assert first.json()["fault_record_id"] == second.json()["fault_record_id"]
