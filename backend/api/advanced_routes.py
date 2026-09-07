"""P2-P5 capability routes layered ahead of the original text baseline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.security import decode_access_token
from backend.domain.enums import UserRole
from backend.providers.ollama import OllamaProvider
from backend.providers.stt import FasterWhisperSTT
from backend.providers.tts import WindowsSapiTTS
from backend.providers.piper import PiperTTS
from backend.providers.vision import OllamaVision
from backend.rag.service import KnowledgeService
from backend.repositories.advanced_models import Asset, CapabilityTask, Confirmation, SessionEvent, ToolCall, ToolDraft
from backend.repositories.db import get_db
from backend.repositories.models import AuditEvent, Device, DiagnosisSession, FaultRecord, Message, User
from backend.services.asset_security import store_asset


router = APIRouter(prefix="/api/v1")
settings = get_settings()
ollama = OllamaProvider(settings)
knowledge = KnowledgeService(ollama)
stt = FasterWhisperSTT()
vision = OllamaVision()
tts = WindowsSapiTTS() if __import__("os").name == "nt" else PiperTTS()


class MultimodalMessage(BaseModel):
    session_id: str
    text: str = ""
    audio_asset_id: str | None = None
    image_asset_id: str | None = None


class ToolDraftRequest(BaseModel):
    session_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _session_for(db: Session, session_id: str, user: User) -> DiagnosisSession:
    session = db.get(DiagnosisSession, session_id)
    if not session or (session.user_id != user.id and user.role != UserRole.SYSTEM_ADMIN.value):
        raise AppError("SESSION_NOT_FOUND", "会话不存在或无权访问", 404, False, "session")
    return session


def _event(db: Session, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
    last = db.scalar(select(SessionEvent.sequence).where(SessionEvent.session_id == session_id).order_by(desc(SessionEvent.sequence)).limit(1)) or 0
    db.add(SessionEvent(session_id=session_id, sequence=last + 1, event_type=event_type, payload=payload))


def _task(db: Session, session_id: str, capability: str, asset_id: str | None = None) -> CapabilityTask:
    item = CapabilityTask(session_id=session_id, capability=capability, input_asset_id=asset_id, status="running", started_at=datetime.now(timezone.utc))
    db.add(item)
    db.flush()
    return item


def _task_done(task: CapabilityTask, status: str, result: dict | None = None, error_code: str | None = None) -> None:
    task.status = status
    task.result_json = result
    task.error_code = error_code
    task.finished_at = datetime.now(timezone.utc)


@router.get("/capabilities")
async def capabilities(_: User = Depends(get_current_user)) -> dict:
    llm = await ollama.health()
    return {
        "database": {"available": True},
        "llm": llm,
        "embedding": {"available": bool(llm.get("available")), "model": settings.ollama_embed_model},
        "stt": (await stt.health()).__dict__,
        "vision": (await vision.health()).__dict__,
        "tts": (await tts.health()).__dict__,
    }


@router.post("/assets")
async def upload_asset(file: UploadFile = File(...), kind: str = Form(...), session_id: str | None = Form(None), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if session_id:
        _session_for(db, session_id, user)
    data = await store_asset(file, kind, user.id)
    item = Asset(**{key: value for key, value in data.items() if key != "path"}, session_id=session_id)
    db.add(item)
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="asset.uploaded", target=item.id, details={"kind": kind, "size": item.size_bytes}))
    db.commit()
    return {"id": item.id, "kind": item.kind, "name": item.original_name, "mime_type": item.mime_type, "size_bytes": item.size_bytes, "status": item.status}


@router.post("/messages")
async def create_multimodal_message(payload: MultimodalMessage, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    session = _session_for(db, payload.session_id, user)
    text = payload.text.strip()
    transcript: dict | None = None
    observations: dict | None = None
    stage_states: dict[str, Any] = {"stt": "skipped", "vision": "skipped", "rag": "pending", "llm": "pending", "tts": "skipped"}
    started = time.perf_counter()
    if payload.audio_asset_id:
        asset = db.get(Asset, payload.audio_asset_id)
        if not asset or asset.owner_id != user.id or asset.kind != "audio":
            raise AppError("ASSET_NOT_FOUND", "音频附件不存在或无权访问", 404, False, "stt")
        task = _task(db, session.id, "stt", asset.id)
        db.commit()
        try:
            result = await stt.transcribe(settings.upload_dir / asset.stored_name)
            transcript = {"text": result.text, "language": result.language, "duration_ms": result.duration_ms, "segments": result.segments}
            text = (text + "\n" + result.text).strip()
            stage_states["stt"] = "succeeded"
            _task_done(task, "succeeded", transcript)
        except Exception as exc:
            stage_states["stt"] = "failed"
            _task_done(task, "failed", {"message": str(exc)}, "STT_UNAVAILABLE")
    if payload.image_asset_id:
        asset = db.get(Asset, payload.image_asset_id)
        if not asset or asset.owner_id != user.id or asset.kind != "image":
            raise AppError("ASSET_NOT_FOUND", "图片附件不存在或无权访问", 404, False, "vision")
        task = _task(db, session.id, "vision", asset.id)
        db.commit()
        try:
            result = await vision.analyze(settings.upload_dir / asset.stored_name, text or "观察设备状态")
            observations = result.__dict__
            stage_states["vision"] = "succeeded"
            _task_done(task, "succeeded", observations)
        except Exception as exc:
            stage_states["vision"] = "failed"
            _task_done(task, "failed", {"message": str(exc)}, "VLM_UNAVAILABLE")
    if not text:
        raise AppError("MESSAGE_EMPTY", "请输入文字或提供可用的语音输入", 422, False, "message")
    user_message = Message(session_id=session.id, role="user", text=text, status="completed", transcript=transcript, observations=observations, stage_states=stage_states)
    db.add(user_message)
    db.flush()
    _event(db, session.id, "message.input", {"message_id": user_message.id, "stages": stage_states})
    citations = await knowledge.search(db, text, top_k=5)
    stage_states["rag"] = "succeeded" if citations else "partial"
    evidence = [f"[{item['document']} / {item['section']}] {item['quote_text']}" for item in citations]
    if observations:
        evidence.insert(0, "图片观察：" + json.dumps(observations, ensure_ascii=False))
    stage_states["llm"] = "running"
    db.commit()
    answer, metadata = await ollama.generate(text, evidence)
    stage_states["llm"] = "succeeded" if answer else "failed"
    stage_states["completed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    result_status = "completed" if answer and not any(stage_states[x] == "failed" for x in ("stt", "vision")) else "partial"
    assistant = Message(session_id=session.id, role="assistant", text=answer, status=result_status, citations=citations, stage_states=stage_states, observations=observations)
    db.add(assistant)
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="diagnosis.multimodal_completed", target=assistant.id, details={"model": metadata, "stages": stage_states}))
    _event(db, session.id, "message.completed", {"message_id": assistant.id, "stages": stage_states})
    db.commit()
    db.refresh(assistant)
    return {"message": {"id": assistant.id, "role": assistant.role, "text": assistant.text, "status": assistant.status, "citations": assistant.citations or [], "stage_states": assistant.stage_states or {}, "observations": assistant.observations or {}, "created_at": assistant.created_at}, "metadata": metadata}


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(CapabilityTask, task_id)
    if not task:
        raise AppError("TASK_NOT_FOUND", "能力任务不存在", 404, False, "task")
    _session_for(db, task.session_id, user)
    if task.status not in {"failed", "partial"}:
        raise AppError("TASK_NOT_RETRYABLE", "当前任务状态不可重试", 409, False, "task")
    asset = db.get(Asset, task.input_asset_id) if task.input_asset_id else None
    if not asset:
        raise AppError("ASSET_NOT_FOUND", "任务输入附件不存在", 404, False, "task")
    task.status = "running"
    db.commit()
    try:
        result = await (stt.transcribe(settings.upload_dir / asset.stored_name) if task.capability == "stt" else vision.analyze(settings.upload_dir / asset.stored_name, "重新观察设备"))
        data = result.__dict__ if hasattr(result, "__dict__") else result
        _task_done(task, "succeeded", data)
        db.commit()
        return {"id": task.id, "status": task.status, "result": data}
    except Exception as exc:
        _task_done(task, "failed", {"message": str(exc)}, f"{task.capability.upper()}_UNAVAILABLE")
        db.commit()
        raise AppError(task.error_code or "TASK_FAILED", "能力重试失败", 503, True, task.capability)


async def _user_from_token(token: str | None, db: Session) -> User | None:
    if not token:
        return None
    payload = decode_access_token(token, settings.access_token_secret)
    return db.get(User, payload.get("sub")) if payload else None


@router.websocket("/ws/sessions/{session_id}")
async def session_events(websocket: WebSocket, session_id: str, db: Session = Depends(get_db)) -> None:
    await websocket.accept()
    user = await _user_from_token(websocket.query_params.get("access_token"), db)
    if not user:
        await websocket.close(code=1008)
        return
    try:
        _session_for(db, session_id, user)
        last = int(websocket.query_params.get("last_event_seq", "0"))
        while True:
            rows = db.scalars(select(SessionEvent).where(SessionEvent.session_id == session_id, SessionEvent.sequence > last).order_by(SessionEvent.sequence)).all()
            for item in rows:
                await websocket.send_json({"sequence": item.sequence, "event_type": item.event_type, "payload": item.payload, "created_at": item.created_at.isoformat()})
                last = item.sequence
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, asyncio.CancelledError):
        return


READ_ONLY_TOOLS = {"search_manual", "get_device_history", "get_device_profile", "export_session_report"}
ALL_TOOLS = READ_ONLY_TOOLS | {"create_fault_record"}


@router.post("/tool-drafts")
def create_tool_draft(payload: ToolDraftRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    session = _session_for(db, payload.session_id, user)
    if payload.tool_name not in ALL_TOOLS:
        raise AppError("TOOL_NOT_ALLOWED", "工具不在允许列表中", 403, False, "tool")
    draft = ToolDraft(session_id=session.id, owner_id=user.id, tool_name=payload.tool_name, arguments=payload.arguments)
    db.add(draft)
    db.flush()
    raw = json.dumps(payload.arguments, sort_keys=True, ensure_ascii=False).encode()
    args_hash = hashlib.sha256(raw).hexdigest()
    token = secrets.token_urlsafe(32)
    confirmation = Confirmation(token=token, draft_id=draft.id, owner_id=user.id, args_hash=args_hash, expires_at=datetime.now(timezone.utc) + timedelta(seconds=getattr(settings, "confirmation_ttl_seconds", 600)))
    db.add(confirmation)
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="tool.draft_created", target=draft.id, details={"tool": payload.tool_name, "args_hash": args_hash}))
    db.commit()
    return {"draft_id": draft.id, "tool_name": draft.tool_name, "arguments": draft.arguments, "confirmation_token": token, "expires_at": confirmation.expires_at}


@router.post("/confirmations/{token}")
def confirm_tool(token: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    confirmation = db.get(Confirmation, token)
    if not confirmation or confirmation.owner_id != user.id:
        raise AppError("CONFIRMATION_NOT_FOUND", "确认令牌不存在或无权使用", 404, False, "tool")
    if confirmation.used:
        return confirmation.result_json or {"status": "already_processed"}
    expires_at = confirmation.expires_at.replace(tzinfo=timezone.utc) if confirmation.expires_at.tzinfo is None else confirmation.expires_at
    if expires_at < datetime.now(timezone.utc):
        raise AppError("CONFIRMATION_EXPIRED", "确认令牌已过期", 409, False, "tool")
    draft = db.get(ToolDraft, confirmation.draft_id)
    if not draft:
        raise AppError("TOOL_DRAFT_NOT_FOUND", "工具草稿不存在", 404, False, "tool")
    args = draft.arguments
    result: dict[str, Any]
    if draft.tool_name == "create_fault_record":
        device_id = args.get("device_id")
        symptom = str(args.get("symptom", "")).strip()
        idem = str(args.get("idempotency_key", "")).strip()
        if not device_id or not symptom or not idem or not db.get(Device, device_id):
            raise AppError("FAULT_ARGUMENTS_INVALID", "故障记录参数不完整或设备不存在", 422, False, "tool")
        existing = db.scalar(select(FaultRecord).where(FaultRecord.idempotency_key == idem))
        if existing:
            result = {"status": "already_exists", "fault_record_id": existing.id}
        else:
            record = FaultRecord(device_id=device_id, symptom=symptom, severity=args.get("severity", "medium"), creator_id=user.id, idempotency_key=idem)
            db.add(record)
            db.flush()
            result = {"status": "created", "fault_record_id": record.id}
    elif draft.tool_name == "get_device_profile":
        device = db.get(Device, args.get("device_id"))
        if not device:
            raise AppError("DEVICE_NOT_FOUND", "设备不存在", 404, False, "tool")
        result = {"id": device.id, "code": device.code, "model": device.model, "name": device.name, "metadata": device.metadata_json}
    elif draft.tool_name == "get_device_history":
        result = {"records": [{"id": x.id, "symptom": x.symptom, "severity": x.severity, "status": x.status, "created_at": x.created_at.isoformat()} for x in db.scalars(select(FaultRecord).where(FaultRecord.device_id == args.get("device_id")).order_by(desc(FaultRecord.created_at)).limit(50)).all()]}
    elif draft.tool_name == "search_manual":
        result = {"citations": asyncio.run(knowledge.search(db, str(args.get("query", "")), top_k=5))}
    else:
        session = _session_for(db, draft.session_id, user)
        result = {"session_id": session.id, "status": session.status, "message_count": len(session.messages)}
    confirmation.used = True
    confirmation.result_json = result
    draft.status = "executed"
    db.add(ToolCall(draft_id=draft.id, owner_id=user.id, tool_name=draft.tool_name, args_hash=confirmation.args_hash, result_json=result))
    db.add(AuditEvent(trace_id=str(uuid4()), actor_id=user.id, action="tool.executed", target=draft.id, details={"tool": draft.tool_name, "result": result}))
    db.commit()
    return result


@router.get("/devices/{device_id}/history")
def device_history(device_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    device = db.get(Device, device_id)
    if not device:
        raise AppError("DEVICE_NOT_FOUND", "设备不存在", 404, False, "history")
    rows = db.scalars(select(FaultRecord).where(FaultRecord.device_id == device_id).order_by(desc(FaultRecord.created_at)).limit(100)).all()
    return {
        "device": {"id": device.id, "code": device.code, "model": device.model, "name": device.name},
        "records": [{"id": row.id, "symptom": row.symptom, "severity": row.severity, "status": row.status, "creator_id": row.creator_id, "created_at": row.created_at.isoformat()} for row in rows],
    }

@router.get("/audit-events")
def list_audit_events(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    query = select(AuditEvent).order_by(desc(AuditEvent.created_at)).limit(200)
    if user.role != UserRole.SYSTEM_ADMIN.value:
        query = query.where(AuditEvent.actor_id == user.id)
    return [{"id": x.id, "trace_id": x.trace_id, "action": x.action, "target": x.target, "result": x.result, "details": x.details, "created_at": x.created_at.isoformat()} for x in db.scalars(query).all()]


@router.post("/tts")
async def synthesize(payload: SynthesizeRequest, user: User = Depends(get_current_user)) -> FileResponse:
    output = settings.upload_dir / f"tts-{user.id}-{secrets.token_hex(8)}.wav"
    try:
        await tts.synthesize(payload.text, output)
    except Exception as exc:
        raise AppError("TTS_UNAVAILABLE", str(exc), 503, True, "tts") from exc
    return FileResponse(output, media_type="audio/wav", filename="voiceinspect-answer.wav")
