"""Index the curated, source-linked public knowledge pack.

Default behavior leaves documents indexed but unpublished. Use --publish only after a
knowledge administrator has reviewed the source metadata and applicability.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from backend.main import seed_demo_data
from backend.providers.factory import create_embedding_provider
from backend.rag.service import KnowledgeService
from backend.repositories.db import SessionLocal, init_db
from backend.repositories.models import AuditEvent, KnowledgeDoc, User, new_id
from backend.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true", help="publish indexed documents after import")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "data/knowledge/public/manifest.json").read_text(encoding="utf-8"))
    init_db()
    seed_demo_data()
    settings = get_settings()
    service = KnowledgeService(create_embedding_provider(settings))
    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.username == settings.demo_admin_username))
        if not admin:
            raise RuntimeError("demo system administrator is not available")
        for item in manifest:
            content_path = root / "data/knowledge/public" / item["path"]
            content = content_path.read_text(encoding="utf-8")
            metadata = {key: item.get(key) for key in ("source_url", "publisher", "license", "document_type", "language", "applicability")}
            metadata["device_type"] = item.get("device_type")
            metadata["sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
            document = asyncio.run(service.ingest_text(db, item["name"], content, item["version"], None, admin.organization_id, metadata))
            if args.publish:
                db.query(KnowledgeDoc).filter(KnowledgeDoc.name == document.name, KnowledgeDoc.id != document.id, KnowledgeDoc.status == "published").update({"status": "retired"})
                document.status = "published"
            db.add(AuditEvent(trace_id=new_id(), actor_id=admin.id, action="knowledge.public_seeded", target=document.id, details={"published": args.publish, "source_url": metadata["source_url"], "sha256": metadata["sha256"]}))
            db.commit()
            print(f"{document.name}: {document.status} ({len(document.chunks)} chunks)")
    finally:
        db.close()


if __name__ == "__main__":
    main()