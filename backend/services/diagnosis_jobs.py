"""Durable multimodal diagnosis execution used by the background worker."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.api.dependencies import user_can_access_device
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.domain.device_profiles import equipment_type
from backend.domain.enums import UserRole
from backend.providers.ollama import OllamaProvider
from backend.providers.stt import FasterWhisperSTT
from backend.providers.vision import OllamaVision
from backend.rag.service import KnowledgeService
from backend.repositories.advanced_models import Asset, BackgroundJob, CapabilityTask, SessionEvent
from backend.repositories.models import AuditEvent, Device, DiagnosisSession, Message, ProviderConfig, User, utc_now
from backend.services.diagnosis_quality import build_diagnosis_result
from backend.services.vision_rules import apply_visual_rules, needs_visual_review
from backend.workers.queue import append_event, is_cancel_requested

settings = get_settings()

IMAGE_ONLY_PROMPT = "请根据图片观察结果，分析当前设备状态并给出安全检查建议。"
IMAGE_ONLY_MESSAGE = "已上传现场图片，请分析设备状态。"


def _device_context(device: Device | None) -> str:
    if not device:
        return "当前设备：未指定"
    return f"当前设备：{device.name}（编号 {device.code}，型号 {device.model}）"


def _vision_prompt(device: Device | None, text: str) -> str:
    query = text or IMAGE_ONLY_PROMPT
    return f"{_device_context(device)}\n现场问题：{query}\n请重点识别异常，不要只描述设备类型或外观。"


def _diagnosis_prompt(device: Device | None, text: str) -> str:
    return (
        f"{_device_context(device)}\n用户问题：{text}\n"
        "请严格按以下 Markdown 标题输出：## 结论、## 图片直接观察、## 知识库事实、## 可能原因、## 推荐检查、## 安全措施、## 不确定性。"
        "把图片现场证据视为现场一等证据；必须区分直接观察、知识库事实、可能原因和未确认内容。"
        "没有图像证据时不得给出确定性故障结论；所有故障判断使用‘疑似’语义。"
    )


def _visual_item_text(item: Any) -> str:
    if isinstance(item, dict):
        detail = str(item.get("description") or item.get("name") or item.get("code") or item)
        evidence = item.get("evidence")
        confidence = item.get("confidence")
        suffix = []
        if evidence:
            suffix.append("证据：" + ", ".join(str(value) for value in evidence) if isinstance(evidence, list) else "证据：" + str(evidence))
        if confidence is not None:
            suffix.append(f"置信度：{confidence}")
        return detail + ("；" + "；".join(suffix) if suffix else "")
    return str(item)


def _visual_evidence(observations: dict[str, Any]) -> str:
    lines = ["[图片现场证据]"]
    if observations.get("scene_summary"):
        lines.append(f"场景：{observations['scene_summary']}")
    for label, key in (
        ("客观观察", "observations"),
        ("仪表读数", "measurements"),
        ("候选异常", "candidate_anomalies"),
        ("疑似异常", "suspected_anomalies"),
        ("不确定性", "uncertainties"),
        ("安全提示", "safety_flags"),
    ):
        values = observations.get(key) or []
        if values:
            lines.append(f"{label}：")
            lines.extend(f"- {_visual_item_text(item)}" for item in values)
    return "\n".join(lines)


def _runtime_settings(db: Session):
    runtime = settings.model_copy(deep=True)
    rows = {row.name: row for row in db.scalars(select(ProviderConfig)).all()}
    if rows.get("llm") and rows["llm"].model:
        runtime.ollama_llm_model = rows["llm"].model
    if rows.get("embedding") and rows["embedding"].model:
        runtime.ollama_embed_model = rows["embedding"].model
    if rows.get("vision") and rows["vision"].model:
        runtime.ollama_vision_model = rows["vision"].model
    return runtime


def _session_event(db: Session, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
    last = db.scalar(select(SessionEvent.sequence).where(SessionEvent.session_id == session_id).order_by(desc(SessionEvent.sequence)).limit(1)) or 0
    db.add(SessionEvent(session_id=session_id, sequence=last + 1, event_type=event_type, payload=payload))


def _task(db: Session, session_id: str, capability: str, job_id: str, asset_id: str | None = None) -> CapabilityTask:
    item = CapabilityTask(
        session_id=session_id,
        capability=capability,
        input_asset_id=asset_id,
        job_id=job_id,
        status="running",
        started_at=utc_now(),
    )
    db.add(item)
    db.flush()
    return item


def _task_done(task: CapabilityTask, status: str, result: dict | None = None, error_code: str | None = None) -> None:
    task.status = status
    task.result_json = result
    task.error_code = error_code
    task.finished_at = utc_now()


def _emit(db: Session, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
    append_event(db, job_id, event_type, payload)
    db.commit()


def _message_payload(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "text": message.text,
        "status": message.status,
        "citations": message.citations or [],
        "stage_states": message.stage_states or {},
        "observations": message.observations or {},
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


async def run_multimodal_job(db: Session, job: BackgroundJob) -> dict[str, Any]:
    payload = job.payload_json
    user = db.get(User, payload.get("user_id"))
    session = db.get(DiagnosisSession, payload.get("session_id"))
    if not user or user.status != "active" or not session:
        raise AppError("SESSION_NOT_FOUND", "会话不存在或无权访问", 404, False, "session")
    device = db.get(Device, session.device_id) if session.device_id else None
    if user.role != UserRole.SYSTEM_ADMIN.value and session.user_id != user.id and not (device and user_can_access_device(user, device, db)):
        raise AppError("SESSION_NOT_FOUND", "会话不存在或无权访问", 404, False, "session")

    runtime = _runtime_settings(db)
    runtime_ollama = OllamaProvider(runtime)
    runtime_knowledge = KnowledgeService(runtime_ollama)
    runtime_vision = OllamaVision(runtime)
    stt = FasterWhisperSTT()
    text = str(payload.get("text") or "").strip()
    transcript: dict | None = None
    observations: dict | None = None
    stage_states: dict[str, Any] = {"stt": "skipped", "vision": "skipped", "rag": "pending", "llm": "pending", "tts": "skipped"}
    started = time.perf_counter()

    if is_cancel_requested(db, job.id):
        return {"cancelled": True}

    audio_asset_id = payload.get("audio_asset_id")
    if audio_asset_id:
        asset = db.get(Asset, audio_asset_id)
        if not asset or asset.owner_id != user.id or asset.kind != "audio":
            raise AppError("ASSET_NOT_FOUND", "音频附件不存在或无权访问", 404, False, "stt")
        task = _task(db, session.id, "stt", job.id, asset.id)
        db.commit()
        _emit(db, job.id, "stage", {"stage": "stt", "status": "running"})
        try:
            result = await stt.transcribe(settings.upload_dir / asset.stored_name)
            transcript = {"text": result.text, "language": result.language, "duration_ms": result.duration_ms, "segments": result.segments}
            text = (text + "\n" + result.text).strip()
            stage_states["stt"] = "succeeded"
            _task_done(task, "succeeded", transcript)
            db.commit()
            _emit(db, job.id, "stage", {"stage": "stt", "status": "succeeded", "result": transcript})
        except Exception as exc:
            stage_states["stt"] = "failed"
            _task_done(task, "failed", {"message": str(exc)}, "STT_UNAVAILABLE")
            db.commit()
            _emit(db, job.id, "stage", {"stage": "stt", "status": "failed", "error_code": "STT_UNAVAILABLE"})

    image_asset_id = payload.get("image_asset_id")
    if image_asset_id:
        asset = db.get(Asset, image_asset_id)
        if not asset or asset.owner_id != user.id or asset.kind != "image":
            raise AppError("ASSET_NOT_FOUND", "图片附件不存在或无权访问", 404, False, "vision")
        task = _task(db, session.id, "vision", job.id, asset.id)
        db.commit()
        _emit(db, job.id, "stage", {"stage": "vision", "status": "running"})
        try:
            result = await runtime_vision.analyze(settings.upload_dir / asset.stored_name, _vision_prompt(device, text))
            observations = apply_visual_rules(result.__dict__, device)
            stage_states["vision"] = "needs_review" if needs_visual_review(observations) else "succeeded"
            _task_done(task, stage_states["vision"], observations)
            db.commit()
            _emit(db, job.id, "stage", {"stage": "vision", "status": stage_states["vision"], "observations": observations})
        except Exception as exc:
            stage_states["vision"] = "failed"
            _task_done(task, "failed", {"message": str(exc)}, "VLM_UNAVAILABLE")
            db.commit()
            _emit(db, job.id, "stage", {"stage": "vision", "status": "failed", "error_code": "VLM_UNAVAILABLE"})

    message_text = text
    if not text:
        if image_asset_id:
            text = IMAGE_ONLY_PROMPT
            message_text = IMAGE_ONLY_MESSAGE
        else:
            raise AppError("MESSAGE_EMPTY", "请输入文字或提供可用的语音输入，或附加现场图片", 422, False, "message")

    user_message = Message(
        session_id=session.id,
        role="user",
        text=message_text,
        status="completed",
        transcript=transcript,
        observations=observations,
        stage_states=stage_states,
    )
    db.add(user_message)
    db.flush()
    _session_event(db, session.id, "message.input", {"message_id": user_message.id, "stages": stage_states})
    db.commit()
    _emit(db, job.id, "start", {"message_id": user_message.id, "stage_states": stage_states})

    try:
        citations = await runtime_knowledge.search(db, text, device_model=device.model if device else None, device_type=equipment_type(device), top_k=5)
    except Exception:
        citations = []
    stage_states["rag"] = "succeeded" if citations else "partial"
    evidence = [f"[{item['document']} / {item['section']}] {item['quote_text']}" for item in citations]
    if observations:
        evidence.insert(0, _visual_evidence(observations))
    _emit(db, job.id, "stage", {"stage": "rag", "status": stage_states["rag"], "citation_count": len(citations)})

    stage_states["llm"] = "running"
    _emit(db, job.id, "stage", {"stage": "llm", "status": "running"})
    answer_parts: list[str] = []
    metadata: dict[str, Any] = {}
    try:
        async for item in runtime_ollama.stream_generate(_diagnosis_prompt(device, text), evidence):
            if is_cancel_requested(db, job.id):
                return {"cancelled": True}
            if item.get("type") == "chunk":
                content = str(item.get("content", ""))
                answer_parts.append(content)
                _emit(db, job.id, "chunk", {"content": content})
            elif item.get("type") == "done":
                metadata = item.get("metadata", {})
    except Exception:
        stage_states["llm"] = "failed"
        _emit(db, job.id, "stage", {"stage": "llm", "status": "failed", "error_code": "MODEL_STREAM_FAILED"})

    answer = "".join(answer_parts).strip()
    if stage_states["llm"] != "failed":
        stage_states["llm"] = "succeeded" if answer else "failed"
    diagnosis = build_diagnosis_result(observations, citations, device)
    stage_states["completed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    result_status = "completed" if answer and not any(stage_states[x] in {"failed", "needs_review"} for x in ("stt", "vision", "llm")) else "partial"
    assistant = Message(
        session_id=session.id,
        role="assistant",
        text=answer or "诊断回答未能完成，请保留现有证据后重试。",
        status=result_status,
        citations=citations,
        stage_states=stage_states,
        observations={**(observations or {}), "diagnosis": diagnosis},
    )
    db.add(assistant)
    db.add(AuditEvent(trace_id=str(__import__("uuid").uuid4()), actor_id=user.id, action="diagnosis.multimodal_completed", target=assistant.id, details={"model": metadata, "citation_count": len(citations), "stages": stage_states, "job_id": job.id}))
    _session_event(db, session.id, "message.completed", {"message_id": assistant.id, "stages": stage_states})
    db.commit()
    db.refresh(assistant)
    result = {"message": _message_payload(assistant), "metadata": metadata}
    _emit(db, job.id, "complete", result)
    return result
