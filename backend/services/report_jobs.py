"""Background report rendering for readable, auditable CSV and PDF exports."""

from __future__ import annotations

import csv
import io
import textwrap
from collections import Counter
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.repositories.models import (
    Device,
    DiagnosisSession,
    FaultEvent,
    FaultRecord,
    Message,
    ReportExport,
    User,
    utc_now,
)


def _clean(value: object | None, fallback: str = "-") -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    return text or fallback


def _date(value: object | None) -> str:
    if value is None:
        return "-"
    return str(value).replace("+00:00", " UTC")[:19]


STATUS_LABELS = {
    "new": "新建",
    "confirmed": "已确认",
    "in_progress": "处理中",
    "pending_verification": "待验证",
    "closed": "已关闭",
    "open": "新建",
}
SEVERITY_LABELS = {"low": "低", "medium": "中", "high": "高", "critical": "紧急"}


def _status_label(value: object | None) -> str:
    return STATUS_LABELS.get(_clean(value, ""), _clean(value))


def _severity_label(value: object | None) -> str:
    return SEVERITY_LABELS.get(_clean(value, ""), _clean(value))


def _fault_view(item: FaultRecord, db: Session) -> dict:
    device = db.get(Device, item.device_id)
    assignee = db.get(User, item.assigned_to) if item.assigned_to else None
    creator = db.get(User, item.creator_id)
    events = db.scalars(
        select(FaultEvent).where(FaultEvent.fault_id == item.id).order_by(FaultEvent.created_at)
    ).all()
    session = db.get(DiagnosisSession, item.session_id) if item.session_id else None
    messages = []
    if session:
        messages = db.scalars(
            select(Message).where(Message.session_id == session.id).order_by(Message.created_at)
        ).all()
    return {
        "id": item.id,
        "device_id": item.device_id,
        "device_code": device.code if device else item.device_id,
        "device_name": device.name if device else "未登记设备",
        "device_model": device.model if device else "-",
        "session_id": item.session_id or "",
        "symptom": item.symptom,
        "fault_location": item.fault_location or "",
        "observed_evidence": item.observed_evidence or "",
        "severity": item.severity,
        "severity_label": _severity_label(item.severity),
        "status": item.status,
        "status_label": _status_label(item.status),
        "creator_id": item.creator_id,
        "creator_name": creator.username if creator else item.creator_id,
        "assigned_to": item.assigned_to or "",
        "assignee_name": assignee.username if assignee else "未分派",
        "resolution": item.resolution or "",
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "due_at": item.due_at,
        "events": [
            {
                "from_status": event.from_status or "开始",
                "to_status": event.to_status,
                "note": event.note or "",
                "created_at": event.created_at,
                "actor_id": event.actor_id,
            }
            for event in events
        ],
        "messages": [
            {
                "role": message.role,
                "text": message.text or "",
                "citations": message.citations or [],
                "created_at": message.created_at,
            }
            for message in messages
            if message.text
        ],
    }


def _fault_rows(db: Session, device_ids: set[str]) -> list[dict]:
    if not device_ids:
        return []
    faults = db.scalars(
        select(FaultRecord)
        .where(FaultRecord.device_id.in_(device_ids))
        .order_by(desc(FaultRecord.created_at))
        .limit(500)
    ).all()
    return [_fault_view(fault, db) for fault in faults]


CSV_FIELDS = [
    ("故障编号", "id"),
    ("故障现象", "symptom"),
    ("故障部位/位置", "fault_location"),
    ("现场证据/排查依据", "observed_evidence"),
    ("设备编号", "device_code"),
    ("设备名称", "device_name"),
    ("设备型号", "device_model"),
    ("严重级别", "severity"),
    ("处理状态", "status"),
    ("负责人", "assignee_name"),
    ("创建时间", "created_at"),
    ("更新时间", "updated_at"),
    ("处理期限", "due_at"),
    ("处理结果", "resolution"),
    ("创建人", "creator_name"),
    ("关联会话", "session_id"),
]


def _csv_bytes(rows: list[dict]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[label for label, _ in CSV_FIELDS])
    writer.writeheader()
    for row in rows:
        writer.writerow({
            label: _date(row[key]) if key.endswith("_at")
            else _severity_label(row.get(key)) if key == "severity"
            else _status_label(row.get(key)) if key == "status"
            else _clean(row.get(key))
            for label, key in CSV_FIELDS
        })
    return output.getvalue().encode("utf-8-sig")


class _PdfReport:
    """Small layout helper with an embedded CJK font and bounded cells."""

    width = 595
    height = 842
    left = 44
    right = 551
    body = (0.12, 0.17, 0.21)
    muted = (0.36, 0.42, 0.46)
    teal = (0.02, 0.43, 0.43)
    navy = (0.06, 0.12, 0.17)
    line_color = (0.84, 0.86, 0.85)
    pale = (0.96, 0.97, 0.95)
    orange = (0.74, 0.34, 0.05)

    def __init__(self) -> None:
        import fitz

        self.fitz = fitz
        self.document = fitz.open()
        candidates = (
            Path("assets/fonts/NotoSansSC-Regular.otf"),
            Path("/app/assets/fonts/NotoSansSC-Regular.otf"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf"),
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/msyh.ttf"),
        )
        self.font_file = next((path for path in candidates if path.is_file()), None)
        self.font_name = "voiceinspect-cjk" if self.font_file else "china-s"
        self.page = self.document.new_page(width=self.width, height=self.height)
        self._register_font()
        self.y = 42

    def _register_font(self) -> None:
        if not self.font_file:
            self.measure_font = self.fitz.Font("china-s")
            return
        try:
            self.page.insert_font(fontname=self.font_name, fontfile=str(self.font_file))
            self.measure_font = self.fitz.Font(fontfile=str(self.font_file))
        except Exception:
            # Keep local development usable when the optional system font is
            # not available; Docker installs the embedded Noto CJK font.
            self.font_file = None
            self.font_name = "china-s"
            self.measure_font = self.fitz.Font("china-s")

    def new_page(self) -> None:
        self.page = self.document.new_page(width=self.width, height=self.height)
        self._register_font()
        self.y = 42

    def ensure(self, height: float) -> None:
        # Keep a real safety margin for the footer.  The previous 48pt
        # threshold still allowed a detail card's second row to reach the
        # footer text and produce overlapping glyphs in the exported PDF.
        if self.y + height > self.height - 72:
            self.new_page()

    def text(self, value: object, size: float = 9, color=None, x: float | None = None, y: float | None = None) -> None:
        self.page.insert_text(
            (x if x is not None else self.left, y if y is not None else self.y),
            _clean(value, ""),
            fontsize=size,
            fontname=self.font_name,
            color=color or self.body,
        )

    def fit_text(self, value: object, width: float, size: float = 7.5) -> str:
        """Return a single-line value that cannot run into the next cell."""
        content = _clean(value, "")
        if not content:
            return ""
        if self.measure_font.text_length(content, fontsize=size) <= width:
            return content
        suffix = "…"
        while content and self.measure_font.text_length(content + suffix, fontsize=size) > width:
            content = content[:-1]
        return (content + suffix) if content else suffix

    def paragraph(self, value: object, size: float = 9, color=None, width: int = 48, gap: float = 4) -> None:
        content = _clean(value, "")
        if not content:
            self.y += gap
            return
        lines = textwrap.wrap(content, width=width, break_long_words=True, break_on_hyphens=False) or [""]
        line_height = size * 1.55
        for line in lines:
            self.ensure(line_height + gap)
            self.text(line, size=size, color=color)
            self.y += line_height
        self.y += gap

    def heading(self, value: str, level: int = 2) -> None:
        size = 15 if level == 1 else 11
        self.ensure(size + 22)
        self.page.draw_rect(self.fitz.Rect(self.left, self.y - 12, self.left + 4, self.y + size + 2), color=self.teal, fill=self.teal)
        self.text(value, size=size, color=self.navy, x=self.left + 12)
        self.y += size + 15

    def line(self) -> None:
        self.page.draw_line((self.left, self.y), (self.right, self.y), color=self.line_color, width=0.6)
        self.y += 8

    def label_value(self, label: str, value: object, x: float, y: float, width: float = 150) -> None:
        self.text(label, size=7.5, color=self.muted, x=x, y=y)
        self.page.insert_textbox(
            self.fitz.Rect(x, y + 5, x + width, y + 23),
            self.fit_text(value, width, size=9),
            fontsize=9,
            fontname=self.font_name,
            color=self.body,
        )

    def footer(self) -> None:
        for index, page in enumerate(self.document, 1):
            page.insert_text((self.left, self.height - 24), "VoiceInspect · 故障处理报告", fontsize=7, fontname=self.font_name, color=self.muted)
            page.insert_text((self.right - 50, self.height - 24), f"第 {index} 页", fontsize=7, fontname=self.font_name, color=self.muted)

    def bytes(self) -> bytes:
        self.footer()
        return self.document.tobytes()


def _pdf_bytes(rows: list[dict], report_id: str) -> bytes:
    report = _PdfReport()
    now = utc_now()

    report.page.draw_rect(report.fitz.Rect(0, 0, report.width, 105), color=report.navy, fill=report.navy)
    report.text("VOICEINSPECT", size=9, color=(0.35, 0.91, 0.84), x=44, y=34)
    report.text("故障处理报告", size=23, color=(1, 1, 1), x=44, y=67)
    report.text(f"报告编号  {_clean(report_id)[:18]}...", size=8, color=(0.79, 0.85, 0.86), x=44, y=86)
    report.text(f"生成时间  {_date(now)}", size=8, color=(0.79, 0.85, 0.86), x=400, y=86)
    report.y = 133

    status_counts = Counter(_clean(row.get("status")) for row in rows)
    severity_counts = Counter(_clean(row.get("severity")) for row in rows)
    report.heading("一、报告摘要", 1)
    report.paragraph(
        f"本报告汇总当前授权范围内的故障记录，共 {len(rows)} 条。报告用于现场维修协同、处理过程追踪和事后审计，不替代设备制造商手册或现场安全规程。",
        size=9.5,
        width=52,
    )
    cards = [
        ("故障总数", str(len(rows)), report.teal),
        ("待处理", str(sum(status_counts.get(value, 0) for value in ("new", "confirmed", "in_progress"))), report.orange),
        ("高严重级别", str(severity_counts.get("high", 0)), (0.65, 0.12, 0.08)),
        ("已关闭", str(status_counts.get("closed", 0)), (0.22, 0.43, 0.29)),
    ]
    card_width = 116
    for index, (label, value, color) in enumerate(cards):
        x = report.left + index * (card_width + 10)
        report.page.draw_rect(report.fitz.Rect(x, report.y, x + card_width, report.y + 49), color=report.line_color, fill=report.pale, width=0.6)
        report.text(label, size=7.5, color=report.muted, x=x + 10, y=report.y + 17)
        report.text(value, size=17, color=color, x=x + 10, y=report.y + 39)
    report.y += 70

    report.heading("二、故障清单", 1)
    columns = [(44, 76, "编号"), (125, 112, "设备"), (241, 103, "故障现象"), (349, 43, "级别"), (402, 63, "状态"), (477, 74, "负责人")]
    report.page.draw_rect(report.fitz.Rect(report.left, report.y - 12, report.right, report.y + 14), color=report.navy, fill=report.navy)
    for x, _, label in columns:
        report.text(label, size=7.5, color=(1, 1, 1), x=x, y=report.y + 4)
    report.y += 28
    for index, row in enumerate(rows, 1):
        report.ensure(29)
        if index % 2 == 0:
            report.page.draw_rect(report.fitz.Rect(report.left, report.y - 13, report.right, report.y + 14), color=report.pale, fill=report.pale)
        values = [
            (44, report.fit_text(f"{index:02d} {_clean(row['id'])[:8]}", 76)),
            (125, report.fit_text(f"{_clean(row['device_name'])} / {_clean(row['device_code'])}", 112)),
            (241, report.fit_text(row["symptom"], 103)),
            (349, report.fit_text(row["severity_label"], 43)),
            (402, report.fit_text(row["status_label"], 63)),
            (477, report.fit_text(row["assignee_name"], 74)),
        ]
        for x, value in values:
            report.text(value, size=7.5, color=report.body, x=x, y=report.y + 4)
        report.page.draw_line((report.left, report.y + 15), (report.right, report.y + 15), color=report.line_color, width=0.4)
        report.y += 29

    for index, row in enumerate(rows, 1):
        report.heading(f"三、故障详情 {index:02d}", 1)
        report.paragraph(f"{_clean(row['symptom'])}", size=11, color=report.navy, width=52, gap=2)
        # The metadata card is atomic: start it on a fresh page when the
        # complete two-row card would approach the footer.  Without this
        # guard, the second row can be painted over the footer on long lists.
        report.ensure(94)
        report.page.draw_rect(report.fitz.Rect(report.left, report.y, report.right, report.y + 66), color=report.line_color, fill=(0.98, 0.98, 0.97), width=0.6)
        label_y = report.y + 17
        report.label_value("设备", f"{_clean(row['device_name'])}（{_clean(row['device_code'])}）", 54, label_y, 205)
        report.label_value("型号", row["device_model"], 278, label_y, 115)
        report.label_value("严重级别", row["severity_label"], 416, label_y, 95)
        report.label_value("处理状态", row["status_label"], 54, label_y + 31, 205)
        report.label_value("负责人", row["assignee_name"], 278, label_y + 31, 115)
        report.label_value("处理期限", _date(row["due_at"]), 416, label_y + 31, 95)
        report.y += 82

        report.heading("处理时间线", 2)
        if row["events"]:
            for event in row["events"]:
                report.ensure(27)
                report.text(f"{_date(event['created_at'])}  {_status_label(event['from_status'])} → {_status_label(event['to_status'])}", size=8.5, color=report.teal)
                report.y += 13
                if event["note"]:
                    report.paragraph(f"处理备注：{event['note']}", size=8, color=report.muted, width=57, gap=1)
        else:
            report.paragraph("暂无状态流转记录。", size=8.5, color=report.muted)

        report.heading("处理结果", 2)
        report.paragraph(row["resolution"] or "尚未填写处理结果，故障仍需现场人员继续跟进。", size=9, width=57)
        if row["messages"]:
            report.heading("关联诊断证据", 2)
            assistant_messages = [message for message in row["messages"] if message["role"] == "assistant"]
            if assistant_messages:
                latest = assistant_messages[-1]
                report.paragraph(f"诊断建议：{latest['text'][:650]}", size=8.5, width=57)
                citations = latest["citations"] or []
                if citations:
                    report.paragraph("引用依据：" + "；".join(f"{_clean(item.get('document'))} / {_clean(item.get('section'))}" for item in citations[:5]), size=8, color=report.muted, width=57)
            else:
                report.paragraph("关联会话暂无助手诊断建议。", size=8.5, color=report.muted)
        report.line()

    report.heading("四、报告说明", 1)
    report.paragraph("状态和处理记录来自 VoiceInspect 系统内的故障闭环。负责人、处理期限和解决方案由维修主管或授权人员维护。涉及人身、压力容器、带电部件或高温部件时，必须先执行现场隔离、泄压、断电和个人防护要求。", size=8.5, color=report.muted, width=57)
    return report.bytes()


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
        rows = _fault_rows(db, set(filters.get("device_ids") or []))

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
            data = _pdf_bytes([], item.id)
            content_name = f"session-{item.id}.pdf"
    elif item.format == "csv":
        data = _csv_bytes(rows)
        content_name = f"faults-{item.id}.csv"
    else:
        data = _pdf_bytes(rows, item.id)
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
