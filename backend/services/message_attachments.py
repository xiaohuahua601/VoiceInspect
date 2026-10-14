"""Persistence and serialization helpers for message attachments."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.errors import AppError
from backend.repositories.advanced_models import Asset, BackgroundJob, MessageAsset
from backend.repositories.models import Message


def _attachment_payload(asset: Asset) -> dict[str, str | int]:
    return {
        "kind": asset.kind,
        "id": asset.id,
        "name": asset.original_name,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "preview_url": "/api/v1/assets/" + asset.id + "/content",
    }


def link_message_assets(
    db: Session,
    message: Message,
    owner_id: str,
    session_id: str,
    assets: Iterable[tuple[str, str | None]],
) -> None:
    """Validate and idempotently link uploaded assets to a persisted message."""

    for expected_kind, asset_id in assets:
        if not asset_id:
            continue
        asset = db.get(Asset, asset_id)
        if not asset or asset.owner_id != owner_id or asset.kind != expected_kind:
            raise AppError("ASSET_NOT_FOUND", "附件不存在或无权关联", 404, False, expected_kind)
        if asset.session_id and asset.session_id != session_id:
            raise AppError("ASSET_FORBIDDEN", "附件不属于当前会话", 403, False, expected_kind)
        if not asset.session_id:
            asset.session_id = session_id
        exists = db.scalar(
            select(MessageAsset).where(
                MessageAsset.message_id == message.id,
                MessageAsset.asset_id == asset.id,
            )
        )
        if not exists:
            db.add(MessageAsset(message_id=message.id, asset_id=asset.id))


def message_attachment_payloads(db: Session, message: Message) -> list[dict[str, str | int]]:
    """Return attachments in submission order, with a compatibility fallback."""

    rows = db.scalars(
        select(Asset)
        .join(MessageAsset, MessageAsset.asset_id == Asset.id)
        .where(MessageAsset.message_id == message.id)
        .order_by(MessageAsset.created_at, Asset.created_at)
    ).all()
    if not rows and message.role == "user" and message.job_id:
        job = db.get(BackgroundJob, message.job_id)
        payload = job.payload_json if job else {}
        fallback_ids = [payload.get("image_asset_id"), payload.get("audio_asset_id")]
        ids = [item for item in fallback_ids if item]
        if ids:
            assets = db.scalars(select(Asset).where(Asset.id.in_(ids))).all()
            by_id = {item.id: item for item in assets}
            rows = [by_id[item] for item in ids if item in by_id]
    return [_attachment_payload(asset) for asset in rows]
