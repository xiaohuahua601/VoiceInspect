"""Background report rendering for CSV and PDF exports."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.repositories.models import DiagnosisSession, FaultRecord, ReportExport, utc_now


def _fault_view(item: FaultRecord, db: Session) -> dict:
    return {
        "id": item.id,
        "device_id": item.device_id,
        "session_id": item.session_id or "",
        "symptom": item.symptom,
        "severity": item.severity,
        "status": item.status,
        "creator_id": item.creator_id,
        "assigned_to": item.assigned_to or "",
        "resolution": item.resolution or "",
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat() if item.updated_at else "",
    }


def _pdf_bytes(rows: list[dict]) -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((48, 52), "VoiceInspect Report", fontsize=18, color=(0.08, 0.13, 0.17))
    page.insert_text((48, 76), f"Generated records: {len(rows)}", fontsize=10, color=(0.35, 0.40, 0.43))
    y = 106
    for row in rows[:45]:
        text = f"{str(row.get('id', ''))[:8]} | device={str(row.get('device_id', ''))[:8]} | severity={row.get('severity', '')} | status={row.get('status', '')}"
        page.insert_text((48, y), text, fontsize=8, color=(0.08, 0.13, 0.17))
        y += 16
        if y > 760:
            page = document.new_page()
            y = 52
    return document.tobytes()


def render_report(db: Session, item: ReportExport) -> dict:
    filters = item.filters_json or {}
    rows: list[dict]
    if item.report_type == "session":
        session = db.get(DiagnosisSession, filters.get("session_id"))
        rows = [
            {
                "message_id": message.id,
                "role": message.role,
                "status": message.status,
                "text": message.text or "",
                "created_at": message.created_at.isoformat(),
                "citation_count": len(message.citations or []),
            }
            for message in (session.messages if session else [])
        ]
    else:
        device_ids = set(filters.get("device_ids") or [])
        rows = [
            _fault_view(fault, db)
            for fault in db.scalars(
                select(FaultRecord).where(FaultRecord.device_id.in_(device_ids)).order_by(desc(FaultRecord.created_at)).limit(500)
            ).all()
        ] if device_ids else []

    folder = Path("./data/exports")
    folder.mkdir(parents=True, exist_ok=True)
    if item.report_type == "session":
        if item.format == "csv":
            output = io.StringIO()
            fields = ["message_id", "role", "status", "text", "created_at", "citation_count"]
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            data = output.getvalue().encode("utf-8-sig")
            content_name = f"session-{item.id}.csv"
        else:
            summary = [{"id": row["message_id"], "device_id": filters.get("device_id", "none"), "severity": row["role"], "status": row["status"]} for row in rows]
            data = _pdf_bytes(summary)
            content_name = f"session-{item.id}.pdf"
    elif item.format == "csv":
        output = io.StringIO()
        fields = list(rows[0].keys()) if rows else ["id", "device_id", "symptom", "severity", "status", "created_at"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        data = output.getvalue().encode("utf-8-sig")
        content_name = f"faults-{item.id}.csv"
    else:
        data = _pdf_bytes(rows)
        content_name = f"faults-{item.id}.pdf"

    path = folder / content_name
    path.write_bytes(data)
    item.file_name = content_name
    item.file_path = str(path)
    item.status = "ready"
    item.completed_at = utc_now()
    item.error_code = None
    db.commit()
    return {"id": item.id, "file_name": item.file_name, "format": item.format, "status": item.status}
