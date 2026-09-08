"""Single-process database-backed Worker for local Docker deployments."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from datetime import datetime, timezone

from backend.core.errors import AppError
from backend.core.config import get_settings
from backend.repositories.advanced_models import BackgroundJob
from backend.repositories.db import SessionLocal
from backend.repositories.models import ReportExport
from backend.services.diagnosis_jobs import run_multimodal_job
from backend.services.report_jobs import render_report
from backend.workers.queue import claim_next, finish_job, requeue_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("voiceinspect.worker")
settings = get_settings()


def write_heartbeat(worker_id: str) -> None:
    target = settings.log_dir / "worker-heartbeat.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"worker_id": worker_id, "updated_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def run_one() -> bool:
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    db = SessionLocal()
    try:
        job = claim_next(db, worker_id)
        if not job:
            return False
        logger.info("job started id=%s kind=%s attempt=%s", job.id, job.kind, job.attempts)
        try:
            if job.kind == "diagnosis.multimodal":
                result = asyncio.run(run_multimodal_job(db, job))
                status = "cancelled" if result.get("cancelled") else ("partial" if result.get("message", {}).get("status") == "partial" else "succeeded")
            elif job.kind == "report.render":
                report = db.get(ReportExport, job.payload_json["report_id"])
                if not report:
                    raise RuntimeError("report export not found")
                result = render_report(db, report)
                status = "succeeded"
            else:
                finish_job(db, job, "failed", error_code="JOB_KIND_UNSUPPORTED")
                return True
            finish_job(db, db.get(BackgroundJob, job.id), status, result)
        except AppError as exc:
            current = db.get(BackgroundJob, job.id)
            if current and current.attempts < current.max_attempts and exc.retryable:
                requeue_job(db, current, exc.code, delay_seconds=min(30, 2 ** current.attempts))
            else:
                finish_job(db, current or job, "failed", {"message": exc.message}, exc.code)
        except Exception:
            logger.exception("job failed id=%s kind=%s", job.id, job.kind)
            current = db.get(BackgroundJob, job.id)
            if current and current.attempts < current.max_attempts:
                requeue_job(db, current, "JOB_EXECUTION_FAILED", delay_seconds=min(30, 2 ** current.attempts))
            else:
                finish_job(db, current or job, "failed", error_code="JOB_EXECUTION_FAILED")
        return True
    finally:
        db.close()


def main() -> None:
    poll_seconds = float(os.getenv("WORKER_POLL_SECONDS", "1.0"))
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    logger.info("VoiceInspect worker started id=%s", worker_id)
    while True:
        write_heartbeat(worker_id)
        processed = run_one()
        if not processed:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
