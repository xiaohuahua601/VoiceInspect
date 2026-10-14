from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.api.pagination import normalize_page, page_result
from backend.repositories.advanced_models import BackgroundJob, JobEvent
from backend.repositories.db import Base
from backend.services.diagnosis_jobs import _ChunkBuffer
from backend.workers.queue import claim_next, create_job, finish_job, request_cancel, retry_job


def make_db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[BackgroundJob.__table__, JobEvent.__table__])
    return Session(engine)


def test_job_lifecycle_persists_events_and_retry():
    db = make_db()
    try:
        item = create_job(db, kind="test", owner_id="user-1", payload={"value": 1})
        db.commit()
        claimed = claim_next(db, "worker-1")
        assert claimed and claimed.status == "running" and claimed.attempts == 1
        finish_job(db, claimed, "failed", error_code="TEST_FAILED")
        assert db.get(BackgroundJob, item.id).status == "failed"
        retried = retry_job(db, db.get(BackgroundJob, item.id))
        assert retried.status == "queued" and retried.error_code is None
        events = db.query(JobEvent).filter(JobEvent.job_id == item.id).order_by(JobEvent.sequence).all()
        assert [event.event_type for event in events] == ["queued", "running", "failed", "queued"]
    finally:
        db.close()


def test_queued_job_can_be_cancelled_before_claim():
    db = make_db()
    try:
        item = create_job(db, kind="test", owner_id="user-1", payload={})
        db.commit()
        cancelled = request_cancel(db, item)
        assert cancelled.status == "cancelled"
        assert claim_next(db, "worker-1") is None
    finally:
        db.close()


def test_stream_chunk_buffer_batches_events():
    db = make_db()
    try:
        item = create_job(db, kind="diagnosis.multimodal", owner_id="user-1", request_id="req-1", payload={})
        db.commit()
        buffer = _ChunkBuffer(db, item.id)
        buffer.add("一")
        buffer.add("二")
        buffer.flush()
        events = db.query(JobEvent).filter(JobEvent.job_id == item.id, JobEvent.event_type == "chunk").all()
        assert len(events) == 1
        assert events[0].payload["content"] == "一二"
        assert events[0].payload["chunk_index"] == 1
        assert buffer.persisted_events == 1
    finally:
        db.close()


def test_pagination_contract_validates_and_returns_metadata():
    assert normalize_page(2, 10) == (2, 10)
    assert page_result([11, 12], 25, 2, 10)["meta"] == {"page": 2, "page_size": 10, "total": 25, "pages": 3}
