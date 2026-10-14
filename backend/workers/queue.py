"""SQLite-backed durable job queue shared by the API and worker process."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.repositories.advanced_models import BackgroundJob, JobEvent
from backend.repositories.models import utc_now


TERMINAL_JOB_STATES = {"succeeded", "partial", "failed", "cancelled"}
settings = get_settings()


def create_job(
    db: Session,
    *,
    kind: str,
    owner_id: str,
    payload: dict,
    session_id: str | None = None,
    request_id: str | None = None,
    max_attempts: int = 3,
) -> BackgroundJob:
    item = BackgroundJob(
        kind=kind,
        owner_id=owner_id,
        request_id=request_id,
        session_id=session_id,
        payload_json=payload,
        status="queued",
        max_attempts=max(1, max_attempts),
        available_at=utc_now(),
    )
    db.add(item)
    db.flush()
    append_event(db, item.id, "queued", {"job_id": item.id, "kind": kind})
    return item


def append_event(db: Session, job_id: str, event_type: str, payload: dict | None = None) -> JobEvent:
    last = db.scalar(select(JobEvent.sequence).where(JobEvent.job_id == job_id).order_by(desc(JobEvent.sequence)).limit(1)) or 0
    event = JobEvent(job_id=job_id, sequence=last + 1, event_type=event_type, payload=payload or {})
    db.add(event)
    return event


def recover_stale_jobs(db: Session, lease_seconds: int = 300) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=lease_seconds)
    rows = db.scalars(
        select(BackgroundJob).where(
            BackgroundJob.status == "running",
            BackgroundJob.locked_at.is_not(None),
            BackgroundJob.locked_at < cutoff,
        )
    ).all()
    for item in rows:
        item.status = "queued"
        item.locked_at = None
        item.locked_by = None
        item.available_at = utc_now()
        append_event(db, item.id, "requeued", {"reason": "worker_lease_expired"})
    if rows:
        db.commit()
    return len(rows)


def claim_next(db: Session, worker_id: str, lease_seconds: int = 300) -> BackgroundJob | None:
    recover_stale_jobs(db, lease_seconds)
    now = utc_now()
    candidates = db.scalars(
        select(BackgroundJob)
        .where(BackgroundJob.status == "queued", BackgroundJob.available_at <= now)
        .order_by(BackgroundJob.created_at)
        .limit(20)
    ).all()
    running_diagnosis = db.scalar(
        select(func.count()).select_from(BackgroundJob).where(
            BackgroundJob.status == "running",
            BackgroundJob.kind == "diagnosis.multimodal",
        )
    ) or 0
    item = next(
        (
            candidate
            for candidate in candidates
            if candidate.kind != "diagnosis.multimodal" or running_diagnosis < max(1, settings.worker_max_active_diagnosis)
        ),
        None,
    )
    if not item:
        return None
    item.status = "running"
    item.attempts += 1
    item.started_at = item.started_at or now
    item.locked_at = now
    item.locked_by = worker_id
    append_event(db, item.id, "running", {"attempt": item.attempts, "worker_id": worker_id})
    db.commit()
    db.refresh(item)
    return item


def request_cancel(db: Session, item: BackgroundJob) -> BackgroundJob:
    now = utc_now()
    item.cancel_requested_at = now
    if item.status == "queued":
        item.status = "cancelled"
        item.finished_at = now
        append_event(db, item.id, "cancelled", {"reason": "cancel_requested_before_start"})
    else:
        append_event(db, item.id, "cancel_requested", {})
    db.commit()
    db.refresh(item)
    return item


def is_cancel_requested(db: Session, job_id: str) -> bool:
    item = db.get(BackgroundJob, job_id)
    return bool(item and item.cancel_requested_at)


def finish_job(db: Session, item: BackgroundJob, status: str, result: dict | None = None, error_code: str | None = None) -> None:
    item.status = status
    item.result_json = result
    item.error_code = error_code
    item.finished_at = utc_now()
    item.locked_at = None
    item.locked_by = None
    append_event(db, item.id, status, result if result and status != "failed" else {"error_code": error_code} if error_code else {})
    db.commit()


def requeue_job(db: Session, item: BackgroundJob, error_code: str, delay_seconds: int = 0) -> None:
    item.status = "queued"
    item.error_code = error_code
    item.locked_at = None
    item.locked_by = None
    item.available_at = utc_now() + timedelta(seconds=max(0, delay_seconds))
    append_event(db, item.id, "requeued", {"error_code": error_code, "attempt": item.attempts, "next_attempt": item.attempts + 1})
    db.commit()


def retry_job(db: Session, item: BackgroundJob) -> BackgroundJob:
    if item.status not in TERMINAL_JOB_STATES or item.status == "succeeded":
        return item
    item.status = "queued"
    item.error_code = None
    item.result_json = None
    item.cancel_requested_at = None
    item.finished_at = None
    item.available_at = utc_now()
    append_event(db, item.id, "queued", {"reason": "manual_retry"})
    db.commit()
    db.refresh(item)
    return item


def job_view(item: BackgroundJob) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "owner_id": item.owner_id,
        "request_id": item.request_id,
        "session_id": item.session_id,
        "status": item.status,
        "result": item.result_json,
        "metrics": item.metrics_json or {},
        "error_code": item.error_code,
        "error_detail": item.error_detail,
        "attempts": item.attempts,
        "max_attempts": item.max_attempts,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
    }
