from uuid import uuid4

from fastapi.testclient import TestClient

from backend.main import app
from backend.repositories.advanced_models import Asset, BackgroundJob, CapabilityTask, JobEvent, MessageAsset, SessionEvent
from backend.repositories.db import SessionLocal
from backend.repositories.models import AuditEvent, Device, FaultRecord, Message, ReportExport, User


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

def test_active_session_detail_restores_user_attachment_metadata():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        session = client.post("/api/v1/sessions", headers=headers, json={"title": "附件恢复测试"}).json()
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.username == "operator").one()
            message = Message(session_id=session["id"], role="user", text="请检查现场图片", status="completed", stage_states={"input": "succeeded"})
            db.add(message)
            db.flush()
            asset = Asset(owner_id=owner.id, session_id=session["id"], kind="image", original_name="现场图片.png", stored_name=f"attachment-{message.id}.png", mime_type="image/png", size_bytes=12, sha256="0" * 64)
            db.add(asset)
            db.flush()
            db.add(MessageAsset(message_id=message.id, asset_id=asset.id))
            db.commit()
            message_id, asset_id = message.id, asset.id
        finally:
            db.close()
        detail = client.get(f"/api/v1/sessions/{session['id']}", headers=headers)
        assert detail.status_code == 200
        restored = next(item for item in detail.json()["messages"] if item["id"] == message_id)
        assert restored["attachments"] == [{"kind": "image", "id": asset_id, "name": "现场图片.png", "mime_type": "image/png", "size_bytes": 12, "preview_url": f"/api/v1/assets/{asset_id}/content"}]


def test_session_delete_removes_session_artifacts_and_preserves_fault_record():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        created = client.post("/api/v1/sessions", headers=headers, json={"title": "会话删除回归测试"})
        assert created.status_code == 200
        session_id = created.json()["id"]
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.username == "operator").one()
            device = db.query(Device).filter(Device.code == "A-01").one()
            message = Message(session_id=session_id, role="user", text="请保留故障但删除会话", status="completed")
            db.add(message)
            db.flush()
            asset = Asset(owner_id=owner.id, session_id=session_id, kind="image", original_name="delete-test.png", stored_name=f"delete-{message.id}.png", mime_type="image/png", size_bytes=12, sha256="a" * 64)
            job = BackgroundJob(kind="diagnosis.multimodal", owner_id=owner.id, session_id=session_id, status="succeeded", payload_json={})
            db.add_all([asset, job])
            db.flush()
            db.add_all([
                MessageAsset(message_id=message.id, asset_id=asset.id),
                CapabilityTask(session_id=session_id, message_id=message.id, capability="vision", status="succeeded", input_asset_id=asset.id, job_id=job.id),
                JobEvent(job_id=job.id, sequence=1, event_type="completed", payload={}),
                SessionEvent(session_id=session_id, sequence=1, event_type="completed", payload={}),
                ReportExport(owner_id=owner.id, report_type="session", format="pdf", status="ready", file_name="delete-test.pdf", file_path="", job_id=job.id),
            ])
            fault = FaultRecord(device_id=device.id, session_id=session_id, symptom="保留的故障", severity="low", status="new", creator_id=owner.id, idempotency_key=f"delete-test-{uuid4()}")
            db.add(fault)
            db.commit()
            message_id, asset_id, job_id, fault_id = message.id, asset.id, job.id, fault.id
        finally:
            db.close()

        removed = client.delete(f"/api/v1/sessions/{session_id}", headers=headers)
        assert removed.status_code == 200, removed.text
        assert removed.json()["deleted"] is True
        assert client.get(f"/api/v1/sessions/{session_id}", headers=headers).status_code == 404

        db = SessionLocal()
        try:
            assert db.get(Message, message_id) is None
            assert db.get(Asset, asset_id) is None
            assert db.get(BackgroundJob, job_id) is None
            assert db.query(MessageAsset).filter(MessageAsset.message_id == message_id).count() == 0
            assert db.query(CapabilityTask).filter(CapabilityTask.session_id == session_id).count() == 0
            assert db.query(JobEvent).filter(JobEvent.job_id == job_id).count() == 0
            assert db.query(SessionEvent).filter(SessionEvent.session_id == session_id).count() == 0
            retained_fault = db.get(FaultRecord, fault_id)
            assert retained_fault is not None
            assert retained_fault.session_id is None
            assert db.query(AuditEvent).filter(AuditEvent.action == "session.deleted", AuditEvent.target == session_id).count() == 1
        finally:
            db.close()


def test_session_delete_rejects_active_job_until_cancelled():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        session = client.post("/api/v1/sessions", headers=headers, json={"title": "活动任务删除保护"}).json()
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.username == "operator").one()
            job = BackgroundJob(kind="diagnosis.multimodal", owner_id=owner.id, session_id=session["id"], status="running", payload_json={})
            db.add(job)
            db.commit()
            job_id = job.id
        finally:
            db.close()

        denied = client.delete(f"/api/v1/sessions/{session['id']}", headers=headers)
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "SESSION_DELETE_JOB_ACTIVE"

        db = SessionLocal()
        try:
            db.get(BackgroundJob, job_id).status = "cancelled"
            db.commit()
        finally:
            db.close()
        assert client.delete(f"/api/v1/sessions/{session['id']}", headers=headers).status_code == 200


def test_batch_session_delete_deduplicates_and_reports_partial_results():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        deletable = client.post("/api/v1/sessions", headers=headers, json={"title": "批量删除可删除"}).json()
        active = client.post("/api/v1/sessions", headers=headers, json={"title": "批量删除活动任务"}).json()
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.username == "operator").one()
            job = BackgroundJob(kind="diagnosis.text", owner_id=owner.id, session_id=active["id"], status="running", payload_json={})
            db.add(job)
            db.commit()
            job_id = job.id
        finally:
            db.close()

        response = client.post(
            "/api/v1/sessions/batch-delete",
            headers=headers,
            json={"session_ids": [deletable["id"], active["id"], "missing-session", deletable["id"]]},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["requested"] == 3
        assert [item["id"] for item in result["deleted"]] == [deletable["id"]]
        assert [item["id"] for item in result["skipped"]] == [active["id"]]
        assert [item["id"] for item in result["failed"]] == ["missing-session"]
        assert client.get(f"/api/v1/sessions/{deletable['id']}", headers=headers).status_code == 404
        assert client.get(f"/api/v1/sessions/{active['id']}", headers=headers).status_code == 200

        db = SessionLocal()
        try:
            db.get(BackgroundJob, job_id).status = "cancelled"
            db.commit()
        finally:
            db.close()
        assert client.delete(f"/api/v1/sessions/{active['id']}", headers=headers).status_code == 200