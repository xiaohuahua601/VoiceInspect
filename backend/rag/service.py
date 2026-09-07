import hashlib
import math
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.errors import AppError
from backend.providers.ollama import OllamaProvider
from backend.repositories.models import KnowledgeChunk, KnowledgeDoc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def chunk_text(text: str, target: int = 600, overlap: int = 100) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + target)
        if end < len(clean):
            boundary = max(clean.rfind("。", start, end), clean.rfind("\n", start, end))
            if boundary > start + target // 2:
                end = boundary + 1
        chunks.append(clean[start:end].strip())
        if end >= len(clean):
            break
        start = max(end - overlap, start + 1)
    return chunks


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class KnowledgeService:
    def __init__(self, provider: OllamaProvider):
        self.provider = provider

    async def ingest_text(self, db: Session, name: str, content: str, version: str = "1", device_model: str | None = None, organization_id: str | None = None) -> KnowledgeDoc:
        encoded = content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        existing = db.scalar(select(KnowledgeDoc).where(KnowledgeDoc.sha256 == digest, KnowledgeDoc.version == version))
        if existing:
            return existing
        pieces = chunk_text(content)
        vectors = await self.provider.embed(pieces) if pieces else []
        doc = KnowledgeDoc(name=name, version=version, sha256=digest, status="indexed", organization_id=organization_id, metadata_json={"device_model": device_model})
        db.add(doc)
        db.flush()
        for index, (piece, vector) in enumerate(zip(pieces, vectors)):
            db.add(KnowledgeChunk(doc_id=doc.id, page=None, section=f"chunk-{index + 1}", text=piece, vector=vector, device_model=device_model))
        db.commit()
        db.refresh(doc)
        return doc

    async def search(self, db: Session, query: str, device_model: str | None = None, top_k: int = 5) -> list[dict]:
        query_vector = (await self.provider.embed([query]))[0]
        stmt = select(KnowledgeChunk, KnowledgeDoc).join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id).where(KnowledgeDoc.status == "published")
        if device_model:
            stmt = stmt.where((KnowledgeChunk.device_model == device_model) | (KnowledgeChunk.device_model.is_(None)))
        rows = db.execute(stmt).all()
        scored = [(cosine(query_vector, chunk.vector or []), chunk, doc) for chunk, doc in rows]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "citation_id": chunk.id,
                "doc_id": doc.id,
                "document": doc.name,
                "version": doc.version,
                "page": chunk.page,
                "section": chunk.section,
                "quote_text": chunk.text,
                "score": round(score, 4),
            }
            for score, chunk, doc in scored[: max(1, min(top_k, 12))]
            if score >= 0.15
        ]

    @staticmethod
    def extract_text(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".txt":
            return path.read_text(encoding="utf-8")
        if suffix == ".docx":
            from docx import Document

            document = Document(path)
            return "\n".join(paragraph.text for paragraph in document.paragraphs)
        if suffix == ".pdf":
            import fitz

            document = fitz.open(path)
            return "\n".join(page.get_text() for page in document)
        raise AppError("RAG_UNSUPPORTED_FILE", "仅支持 TXT、DOCX 和 PDF 文件", 415, False, "rag")
