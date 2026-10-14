from uuid import uuid4

from fastapi.testclient import TestClient

from backend.main import app


def login(username: str, password: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
    return client


def create_fault(operator: TestClient) -> str:
    device = operator.get("/api/v1/devices").json()[0]
    session = operator.post("/api/v1/sessions", json={"title": "负责人闭环测试", "device_id": device["id"]}).json()
    draft = operator.post("/api/v1/tool-drafts", json={
        "session_id": session["id"],
        "tool_name": "create_fault_record",
        "arguments": {
            "device_id": device["id"],
            "symptom": "assignment test",
            "fault_location": "冷却器出口管路",
            "observed_evidence": "压力表读数波动，现场记录已留存",
            "severity": "medium",
            "idempotency_key": str(uuid4()),
        },
    })
    assert draft.status_code == 200, draft.text
    confirmation = operator.post(f"/api/v1/confirmations/{draft.json()['confirmation_token']}")
    assert confirmation.status_code == 200, confirmation.text
    return confirmation.json()["fault_record_id"]


def test_operator_is_read_only_and_supervisor_can_assign_and_reassign():
    operator = login("operator", "change-me")
    supervisor = login("supervisor", "change-me-supervisor")
    fault_id = create_fault(operator)

    forbidden = operator.post(f"/api/v1/fault-records/{fault_id}/confirm", json={"note": "operator must not confirm"})
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "AUTH_FORBIDDEN"

    candidates = supervisor.get(f"/api/v1/fault-records/assignees?fault_id={fault_id}")
    assert candidates.status_code == 200
    candidate_ids = {row["id"] for row in candidates.json()}
    assert candidate_ids

    confirmed = supervisor.post(f"/api/v1/fault-records/{fault_id}/confirm", json={"note": "主管确认"})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"

    assigned = supervisor.post(f"/api/v1/fault-records/{fault_id}/assign", json={"assigned_to": operator.get("/api/v1/auth/me").json()["id"], "idempotency_key": "assignment-once"})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "in_progress"
    assert assigned.json()["assigned_to_name"] == "operator"
    notifications = operator.get("/api/v1/notifications")
    assert notifications.status_code == 200
    assert any(item["kind"] == "fault_assignment" and item["target_id"] == fault_id for item in notifications.json())
    assert supervisor.get("/api/v1/fault-records/overdue").status_code == 200

    detail_before = supervisor.get(f"/api/v1/fault-records/{fault_id}").json()
    repeated = supervisor.post(f"/api/v1/fault-records/{fault_id}/assign", json={"assigned_to": assigned.json()["assigned_to"], "idempotency_key": "assignment-once"})
    assert repeated.status_code == 200
    detail_after = supervisor.get(f"/api/v1/fault-records/{fault_id}").json()
    assert len(detail_after["events"]) == len(detail_before["events"])

    invalid = supervisor.post(f"/api/v1/fault-records/{fault_id}/assign", json={"assigned_to": "does-not-exist"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "FAULT_ASSIGNEE_INVALID"

    reassigned = supervisor.post(f"/api/v1/fault-records/{fault_id}/assign", json={"assigned_to": supervisor.get("/api/v1/auth/me").json()["id"], "note": "主管接手"})
    assert reassigned.status_code == 200
    assert reassigned.json()["assigned_to_name"] == "supervisor"

    verified = supervisor.post(f"/api/v1/fault-records/{fault_id}/verify", json={"note": "验证通过"})
    assert verified.status_code == 200
    assert verified.json()["status"] == "pending_verification"

    closed = supervisor.post(f"/api/v1/fault-records/{fault_id}/close", json={"resolution": "已完成处理"})
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"

    blocked = supervisor.post(f"/api/v1/fault-records/{fault_id}/assign", json={"assigned_to": operator.get("/api/v1/auth/me").json()["id"]})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "FAULT_STATUS_TRANSITION_INVALID"


def test_assigned_operator_can_submit_processing_result_for_supervisor_verification():
    operator = login("operator", "change-me")
    supervisor = login("supervisor", "change-me-supervisor")
    fault_id = create_fault(operator)
    assert supervisor.post(f"/api/v1/fault-records/{fault_id}/confirm", json={"note": "主管确认"}).status_code == 200
    operator_id = operator.get("/api/v1/auth/me").json()["id"]
    assigned = supervisor.post(
        f"/api/v1/fault-records/{fault_id}/assign",
        json={"assigned_to": operator_id, "idempotency_key": str(uuid4())},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "in_progress"

    submitted = operator.post(
        f"/api/v1/fault-records/{fault_id}/submit-verification",
        json={"note": "已调整冷却风道并完成复测，压力恢复正常"},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "pending_verification"
    detail = supervisor.get(f"/api/v1/fault-records/{fault_id}")
    assert detail.status_code == 200
    assert detail.json()["processing_result"] == "已调整冷却风道并完成复测，压力恢复正常"
    assert detail.json()["processing_by_name"] == "operator"

    operator_forbidden = operator.post(f"/api/v1/fault-records/{fault_id}/close", json={"resolution": "operator must not close"})
    assert operator_forbidden.status_code == 403
    closed = supervisor.post(f"/api/v1/fault-records/{fault_id}/close", json={"resolution": "主管验证通过并关闭"})
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"


def test_operator_can_mark_only_own_notifications_as_read():
    operator = login("operator", "change-me")
    supervisor = login("supervisor", "change-me-supervisor")
    fault_id = create_fault(operator)
    assert supervisor.post(f"/api/v1/fault-records/{fault_id}/confirm", json={"note": "通知测试"}).status_code == 200
    operator_id = operator.get("/api/v1/auth/me").json()["id"]
    assigned = supervisor.post(
        f"/api/v1/fault-records/{fault_id}/assign",
        json={"assigned_to": operator_id, "idempotency_key": str(uuid4())},
    )
    assert assigned.status_code == 200, assigned.text

    unread_before = [item for item in operator.get("/api/v1/notifications").json() if not item["read"]]
    assert any(item["target_id"] == fault_id for item in unread_before)
    marked = operator.post("/api/v1/notifications/read-all")
    assert marked.status_code == 200, marked.text
    assert marked.json()["updated"] >= 1
    assert all(item["read"] for item in operator.get("/api/v1/notifications").json())

    repeated = operator.post("/api/v1/notifications/read-all")
    assert repeated.status_code == 200
    assert repeated.json()["updated"] == 0
