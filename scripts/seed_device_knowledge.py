"""Index the four generic device knowledge packs into the local database.

Packs are intentionally generic and remain indexed until a knowledge admin publishes them.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from backend.core.config import get_settings
from backend.main import seed_demo_data
from backend.providers.factory import create_embedding_provider
from backend.rag.service import KnowledgeService
from backend.repositories.db import SessionLocal, init_db
from backend.repositories.models import AuditEvent, KnowledgeDoc, User, new_id

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/knowledge/packs/manifest.json"


async def run(publish: bool) -> None:
    init_db()
    seed_demo_data()
    settings = get_settings()
    service = KnowledgeService(create_embedding_provider(settings))
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.username == settings.demo_knowledge_admin_username))
        if not admin:
            raise RuntimeError("knowledge admin demo account is not available")
        for entry in entries:
            path = ROOT / "data/knowledge/packs" / entry["path"]
            text = path.read_text(encoding="utf-8")
            metadata = {key: entry.get(key) for key in ("source_url", "publisher", "license", "document_type", "applicability")}
            metadata.update({"language": "zh-CN", "device_type": entry.get("device_type"), "source_kind": "curated_pack"})
            previous = db.scalars(
                select(KnowledgeDoc).where(
                    KnowledgeDoc.name == entry["name"],
                    KnowledgeDoc.status == "published",
                    KnowledgeDoc.version != entry["version"],
                )
            ).all()
            for old_doc in previous:
                old_doc.status = "retired"
            doc = await service.ingest_text(db, entry["name"], text, entry["version"], None, admin.organization_id, metadata)
            if publish and doc.status != "published":
                doc.status = "published"
            db.add(AuditEvent(trace_id=new_id(), actor_id=admin.id, action="knowledge.device_pack_indexed", target=doc.id, details={"device_type": entry.get("device_type"), "published": publish, "chunks": len(doc.chunks)}))
            db.commit()
            print(f"{entry.get('device_type') or 'general'}: {doc.status}; chunks={len(doc.chunks)}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true", help="publish packs after indexing")
    args = parser.parse_args()
    asyncio.run(run(args.publish))


if __name__ == "__main__":
    main()
