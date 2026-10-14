"""Durable multimodal diagnosis execution used by the background worker."""

from __future__ import annotations

import time
from datetime import datetime, timezone
import logging
from typing import Any, Callable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.api.dependencies import user_can_access_device
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.domain.device_profiles import equipment_type
from backend.domain.enums import UserRole
from backend.providers.factory import create_embedding_provider, create_llm_provider, create_vision_provider
from backend.providers.stt import FasterWhisperSTT
from backend.rag.service import KnowledgeService
from backend.repositories.advanced_models import Asset, BackgroundJob, CapabilityTask, SessionEvent
from backend.services.message_attachments import link_message_assets, message_attachment_payloads
from backend.repositories.models import AuditEvent, Device, DiagnosisSession, Message, ProviderConfig, User, utc_now
from backend.services.diagnosis_quality import build_diagnosis_result
from backend.services.vision_rules import apply_visual_rules, needs_visual_review
from backend.workers.queue import append_event, is_cancel_requested

settings = get_settings()
logger = logging.getLogger("voiceinspect.diagnosis")

IMAGE_ONLY_PROMPT = "请根据图片观察结果，分析当前设备状态并给出安全检查建议。"
IMAGE_ONLY_MESSAGE = "已上传现场图片，请分析设备状态。"


def _device_context(device: Device | None) -> str:
    if not device:
        return "当前设备：未指定"
    return f"当前设备：{device.name}（编号 {device.code}，型号 {device.model}）"


def _vision_prompt(device: Device | None, text: str) -> str:
    query = text or IMAGE_ONLY_PROMPT
    return f"{_device_context(device)}\n现场问题：{query}\n请重点识别异常，不要只描述设备类型或外观。"


def _diagnosis_prompt(device: Device | None, text: str, visual_status: str = "absent") -> str:
    if visual_status == "available":
        visual_guard = (
            "本次请求已附带图片且视觉分析已完成。只要资料区存在[图片现场证据]，严禁写‘未提供实际图片证据’、‘本次输入未附带设备图片’或‘无法查看图片’。"
            "必须在‘## 图片直接观察’复述实际观察；没有充分异常证据时，应写‘已识别图片，但未发现具有充分证据的明确异常’。"
        )
    elif visual_status == "failed":
        visual_guard = (
            "本次请求已附带图片，但视觉分析阶段失败。必须明确写‘已收到图片，但图片分析失败，请重试或补充清晰图片’，严禁写‘未提供图片’或虚构图片观察。"
        )
    else:
        visual_guard = "本次请求没有图片现场证据；不要虚构图片观察。"
    return (
        f"{_device_context(device)}\n用户问题：{text}\n"
        "请严格按以下 Markdown 标题输出：## 结论、## 图片直接观察、## 知识库事实、## 可能原因、## 推荐检查、## 安全措施、## 不确定性。"
        "把图片现场证据视为现场一等证据；必须区分直接观察、知识库事实、可能原因和未确认内容。"
        + visual_guard
        + "没有图像证据时不得给出确定性故障结论；所有故障判断使用‘疑似’语义。"
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
    if runtime.model_provider.strip().lower() in {"qwen", "dashscope"}:
        if rows.get("llm") and rows["llm"].model:
            runtime.qwen_model = rows["llm"].model
        if rows.get("vision") and rows["vision"].model:
            runtime.qwen_model = rows["vision"].model
    else:
        if rows.get("llm") and rows["llm"].model:
            runtime.ollama_llm_model = rows["llm"].model
        if rows.get("vision") and rows["vision"].model:
            runtime.ollama_vision_model = rows["vision"].model
    if rows.get("embedding") and rows["embedding"].model:
        runtime.ollama_embed_model = rows["embedding"].model
    return runtime


def _session_event(db: Session, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
    last = db.scalar(select(SessionEvent.sequence).where(SessionEvent.session_id == session_id).order_by(desc(SessionEvent.sequence)).limit(1)) or 0
    db.add(SessionEvent(session_id=session_id, sequence=last + 1, event_type=event_type, payload=payload))


def _task(db: Session, session_id: str, capability: str, job_id: str, asset_id: str | None = None) -> CapabilityTask:
    existing = db.scalar(select(CapabilityTask).where(CapabilityTask.job_id == job_id, CapabilityTask.capability == capability))
    if existing:
        return existing
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


class _ChunkBuffer:
    def __init__(self, db: Session, job_id: str) -> None:
        self.db = db
        self.job_id = job_id
        self.parts: list[str] = []
        self.first_at: datetime | None = None
        self.last_at: datetime | None = None
        self.chunk_index = 0
        self.persisted_events = 0

    def add(self, content: str) -> None:
        now = datetime.now(timezone.utc)
        self.parts.append(content)
        self.first_at = self.first_at or now
        self.last_at = now
        if len(self.parts) >= max(1, settings.diagnosis_stream_flush_chunks) or (
            self.first_at and (now - self.first_at).total_seconds() * 1000 >= max(1, settings.diagnosis_stream_flush_ms)
        ):
            self.flush()

    def flush(self) -> None:
        if not self.parts:
            return
        self.chunk_index += 1
        append_event(
            self.db,
            self.job_id,
            "chunk",
            {
                "content": "".join(self.parts),
                "chunk_index": self.chunk_index,
                "first_token_at": self.first_at.isoformat() if self.first_at else None,
                "last_token_at": self.last_at.isoformat() if self.last_at else None,
            },
        )
        self.db.commit()
        self.persisted_events += 1
        self.parts.clear()
        self.first_at = None
        self.last_at = None


def _task_done(task: CapabilityTask, status: str, result: dict | None = None, error_code: str | None = None) -> None:
    task.status = status
    task.result_json = result
    task.error_code = error_code
    task.finished_at = utc_now()


def _emit(db: Session, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
    append_event(db, job_id, event_type, payload)
    db.commit()


def _message_payload(db: Session, message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "text": message.text,
        "status": message.status,
        "citations": message.citations or [],
        "stage_states": message.stage_states or {},
        "observations": message.observations or {},
        "attachments": message_attachment_payloads(db, message),
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

    text = str(payload.get("text") or "").strip()
    audio_asset_id = payload.get("audio_asset_id")
    image_asset_id = payload.get("image_asset_id")
    transcript: dict | None = None
    observations: dict | None = None
    stage_states: dict[str, Any] = {"stt": "skipped", "vision": "skipped", "rag": "pending", "llm": "pending", "tts": "skipped"}
    if audio_asset_id:
        stage_states["stt"] = "pending"
    if image_asset_id:
        stage_states["vision"] = "pending"
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    created_at = job.created_at or started_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    timings: dict[str, Any] = {
        "attempt": job.attempts,
        "worker_started_at": started_at.isoformat(),
        "queue_wait_ms": round(max(0.0, (started_at - created_at).total_seconds() * 1000), 1),
    }
    existing_user_message = db.scalar(select(Message).where(Message.job_id == job.id, Message.role == "user"))
    if existing_user_message:
        transcript = existing_user_message.transcript
        observations = existing_user_message.observations
        previous_stages = existing_user_message.stage_states or {}
        stage_states.update({key: previous_stages.get(key, value) for key, value in stage_states.items()})
        if transcript and transcript.get("text"):
            text = (text + "\n" + str(transcript["text"])).strip()

    if not text and not audio_asset_id and not image_asset_id:
        raise AppError("MESSAGE_EMPTY", "请输入文字或提供可用的语音输入，或附加现场图片", 422, False, "message")

    # Persist evidence before any provider runs. Provider failures must not make
    # an uploaded image or audio recording disappear after a browser refresh.
    user_message = existing_user_message
    if not user_message:
        initial_text = text or (IMAGE_ONLY_MESSAGE if image_asset_id else "已上传现场语音，正在转写并分析设备状态。")
        user_message = Message(
            session_id=session.id,
            job_id=job.id,
            role="user",
            text=initial_text,
            status="completed",
            transcript=None,
            observations=None,
            stage_states=stage_states,
        )
        db.add(user_message)
        db.flush()
        link_message_assets(db, user_message, user.id, session.id, (("image", image_asset_id), ("audio", audio_asset_id)))
        session.updated_at = utc_now()
        _session_event(db, session.id, "message.input", {"message_id": user_message.id, "stages": stage_states})
        db.commit()
    else:
        link_message_assets(db, user_message, user.id, session.id, (("image", image_asset_id), ("audio", audio_asset_id)))
        session.updated_at = utc_now()
        db.commit()

    _emit(db, job.id, "start", {"message_id": user_message.id, "stage_states": stage_states})
    if is_cancel_requested(db, job.id):
        return {"cancelled": True}

    runtime = _runtime_settings(db)
    runtime_llm = create_llm_provider(runtime)
    runtime_knowledge = KnowledgeService(create_embedding_provider(runtime))
    runtime_vision = create_vision_provider(runtime)
    stt = FasterWhisperSTT()

    if audio_asset_id and not (existing_user_message and stage_states.get("stt") == "succeeded"):
        stage_started = time.perf_counter()
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
            timings["stt_ms"] = round((time.perf_counter() - stage_started) * 1000, 1)
        except Exception as exc:
            stage_states["stt"] = "failed"
            _task_done(task, "failed", {"message": str(exc)}, "STT_UNAVAILABLE")
            db.commit()
            _emit(db, job.id, "stage", {"stage": "stt", "status": "failed", "error_code": "STT_UNAVAILABLE"})
            timings["stt_ms"] = round((time.perf_counter() - stage_started) * 1000, 1)

    if image_asset_id and not (existing_user_message and stage_states.get("vision") in {"succeeded", "needs_review"}):
        stage_started = time.perf_counter()
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
            timings["vision_ms"] = round((time.perf_counter() - stage_started) * 1000, 1)
        except Exception as exc:
            stage_states["vision"] = "failed"
            _task_done(task, "failed", {"message": str(exc)}, "VLM_UNAVAILABLE")
            db.commit()
            _emit(db, job.id, "stage", {"stage": "vision", "status": "failed", "error_code": "VLM_UNAVAILABLE"})
            timings["vision_ms"] = round((time.perf_counter() - stage_started) * 1000, 1)

    message_text = text
    if not text:
        if image_asset_id:
            text = IMAGE_ONLY_PROMPT
            message_text = IMAGE_ONLY_MESSAGE
        else:
            raise AppError("MESSAGE_EMPTY", "请输入文字或提供可用的语音输入，或附加现场图片", 422, False, "message")

    user_message.text = message_text
    user_message.transcript = transcript
    user_message.observations = observations
    user_message.stage_states = stage_states
    session.updated_at = utc_now()
    db.commit()
    rag_started = time.perf_counter()
    rag_error: str | None = None
    try:
        citations = await runtime_knowledge.search(db, text, device_model=device.model if device else None, device_type=equipment_type(device), top_k=5)
    except Exception as exc:
        citations = []
        rag_error = type(exc).__name__
        stage_states["rag"] = "failed"
    else:
        stage_states["rag"] = "succeeded" if citations else "partial"
    timings["rag_ms"] = round((time.perf_counter() - rag_started) * 1000, 1)
    evidence = [f"[{item['document']} / {item['section']}] {item['quote_text']}" for item in citations]
    if observations:
        evidence.insert(0, _visual_evidence(observations))
    elif image_asset_id and stage_states.get("vision") == "failed":
        evidence.insert(0, "[图片处理状态]\n已收到图片附件，但视觉分析阶段失败；不得将其描述为未提供图片。请提示用户重试或补充清晰图片，不要虚构图片观察。")
    _emit(db, job.id, "stage", {"stage": "rag", "status": stage_states["rag"], "citation_count": len(citations)})

    stage_states["llm"] = "running"
    _emit(db, job.id, "stage", {"stage": "llm", "status": "running"})
    answer_parts: list[str] = []
    metadata: dict[str, Any] = {}
    chunk_buffer = _ChunkBuffer(db, job.id)
    llm_started = time.perf_counter()
    try:
        visual_status = "absent"
        if image_asset_id:
            visual_status = "available" if observations else "failed"
        async for item in runtime_llm.stream_generate(_diagnosis_prompt(device, text, visual_status), evidence):
            if is_cancel_requested(db, job.id):
                chunk_buffer.flush()
                return {"cancelled": True}
            if item.get("type") == "chunk":
                content = str(item.get("content", ""))
                answer_parts.append(content)
                chunk_buffer.add(content)
            elif item.get("type") == "done":
                metadata = item.get("metadata", {})
    except AppError as exc:
        chunk_buffer.flush()
        stage_states["llm"] = "failed"
        timings["llm_ms"] = round((time.perf_counter() - llm_started) * 1000, 1)
        job.metrics_json = {**timings, "chunk_events": chunk_buffer.persisted_events, "rag_error": rag_error}
        job.error_detail = str(exc.details.get("reason") if exc.details else "")[:500] or type(exc).__name__
        user_message.stage_states = stage_states
        user_message.transcript = transcript
        user_message.observations = observations
        db.commit()
        _emit(db, job.id, "stage", {"stage": "llm", "status": "failed", "error_code": exc.code, "retryable": exc.retryable})
        # A model error must reach the durable job state.  Do not fall
        # through to the normal assistant-message path with a placeholder
        # answer that looks like a low-confidence diagnosis.
        raise
    except Exception as exc:
        chunk_buffer.flush()
        stage_states["llm"] = "failed"
        timings["llm_ms"] = round((time.perf_counter() - llm_started) * 1000, 1)
        job.metrics_json = {**timings, "chunk_events": chunk_buffer.persisted_events, "rag_error": rag_error}
        job.error_detail = type(exc).__name__
        user_message.stage_states = stage_states
        user_message.transcript = transcript
        user_message.observations = observations
        db.commit()
        logger.exception("diagnosis stream failed job_id=%s attempt=%s", job.id, job.attempts)
        _emit(db, job.id, "stage", {"stage": "llm", "status": "failed", "error_code": "MODEL_STREAM_FAILED", "retryable": True})
        raise AppError("MODEL_STREAM_FAILED", "模型回答生成失败，请重试", 503, True, "llm") from exc

    chunk_buffer.flush()
    timings["llm_ms"] = round((time.perf_counter() - llm_started) * 1000, 1)
    answer = "".join(answer_parts).strip()
    if not answer:
        stage_states["llm"] = "failed"
        job.error_detail = "empty_model_response"
        job.metrics_json = {**timings, "chunk_events": chunk_buffer.persisted_events, "rag_error": rag_error}
        user_message.stage_states = stage_states
        user_message.transcript = transcript
        user_message.observations = observations
        db.commit()
        _emit(db, job.id, "stage", {"stage": "llm", "status": "failed", "error_code": "MODEL_EMPTY_RESPONSE", "retryable": True})
        raise AppError("MODEL_EMPTY_RESPONSE", "模型未返回有效回答，请重试", 503, True, "llm")
    if stage_states["llm"] != "failed":
        stage_states["llm"] = "succeeded"
    diagnosis = build_diagnosis_result(observations, citations, device)
    stage_states["completed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    timings["total_ms"] = stage_states["completed_ms"]
    timings["chunk_events"] = chunk_buffer.persisted_events
    timings["rag_error"] = rag_error
    timings["llm"] = metadata
    job.metrics_json = timings
    user_message.stage_states = stage_states
    user_message.transcript = transcript
    user_message.observations = observations
    result_status = "completed" if answer and not any(stage_states[x] in {"failed", "cancelled"} for x in ("stt", "vision", "rag", "llm")) else "partial"
    assistant = Message(
        session_id=session.id,
        job_id=job.id,
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
    result = {"message": _message_payload(db, assistant), "metadata": metadata, "metrics": timings}
    _emit(db, job.id, "complete", result)
    return result



