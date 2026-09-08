"""Secure local asset storage and lightweight file signature validation."""

from __future__ import annotations

import hashlib
import io
import secrets
from pathlib import Path
from PIL import Image

from fastapi import UploadFile

from backend.core.config import get_settings
from backend.core.errors import AppError


IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
AUDIO_TYPES = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/webm", "audio/ogg"}


async def store_asset(upload: UploadFile, kind: str, owner_id: str) -> dict:
    settings = get_settings()
    if kind not in {"audio", "image"}:
        raise AppError("ASSET_KIND_INVALID", "不支持的附件类型", 422, False, "upload")
    raw = await upload.read()
    limit = settings.max_upload_bytes
    if not raw or len(raw) > limit:
        raise AppError("UPLOAD_TOO_LARGE", "文件为空或超过大小限制", 413, False, "upload")
    # Browsers append codec parameters to MediaRecorder output, e.g.
    # "audio/webm;codecs=opus". Validate the media type itself while keeping
    # the persisted value canonical for downstream STT and playback logic.
    mime = (upload.content_type or "").lower().split(";", 1)[0].strip()
    if kind == "image" and mime not in IMAGE_TYPES:
        raise AppError("IMAGE_MIME_INVALID", "图片格式不受支持", 415, False, "upload")
    if kind == "audio" and mime not in AUDIO_TYPES:
        raise AppError("AUDIO_MIME_INVALID", "音频格式不受支持", 415, False, "upload")
    if kind == "image":
        detected = "jpeg" if raw.startswith(b"\xff\xd8\xff") else ("png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else ("webp" if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" else None))
        if detected not in {"jpeg", "png", "webp"}:
            raise AppError("IMAGE_SIGNATURE_INVALID", "文件内容不是有效图片", 415, False, "upload")
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.width * image.height > getattr(settings, "max_image_pixels", 20000000):
                    raise AppError("IMAGE_TOO_LARGE", "图片像素超过限制", 413, False, "upload")
        except AppError:
            raise
        except Exception as exc:
            raise AppError("IMAGE_INVALID", "图片无法解析", 415, False, "upload") from exc
    if kind == "audio" and not (raw.startswith(b"RIFF") or raw.startswith(b"ID3") or raw.startswith(b"\xff\xfb") or raw.startswith(b"OggS") or raw.startswith(b"\x1a\x45\xdf\xa3") or raw[4:8] == b"ftyp"):
        raise AppError("AUDIO_SIGNATURE_INVALID", "文件内容不是有效音频", 415, False, "upload")
    if kind == "audio":
        try:
            import av
            with av.open(io.BytesIO(raw)) as container:
                duration = float(container.duration or 0) / 1000000
                if duration > getattr(settings, "max_audio_seconds", 120):
                    raise AppError("AUDIO_TOO_LONG", "音频时长超过限制", 413, False, "upload")
        except AppError:
            raise
        except Exception:
            pass
    digest = hashlib.sha256(raw).hexdigest()
    suffix = Path(upload.filename or "").suffix.lower()[:10] or ".bin"
    stored = f"{secrets.token_hex(16)}{suffix}"
    destination = settings.upload_dir / stored
    temporary = settings.upload_dir / f".{stored}.tmp"
    temporary.write_bytes(raw)
    temporary.replace(destination)
    return {
        "owner_id": owner_id,
        "kind": kind,
        "original_name": (upload.filename or stored)[:255],
        "stored_name": stored,
        "mime_type": mime,
        "size_bytes": len(raw),
        "sha256": digest,
        "path": destination,
    }
