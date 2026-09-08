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

    recorded = client.post(
        "/api/v1/assets",
        files={"file": ("现场录音.webm", b"\x1a\x45\xdf\xa3\x93\x42\x82\x88", "audio/webm;codecs=opus")},
        data={"kind": "audio"},
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["mime_type"] == "audio/webm"


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


def test_task_detail_and_session_event_replay_are_scoped():
    client = auth_client()
    device = client.get("/api/v1/devices").json()[0]
    session = client.post("/api/v1/sessions", json={"title": "事件回放测试", "device_id": device["id"]}).json()
    events = client.get(f"/api/v1/sessions/{session['id']}/events")
    assert events.status_code == 200
    assert isinstance(events.json(), list)
    missing = client.get("/api/v1/tasks/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "TASK_NOT_FOUND"
