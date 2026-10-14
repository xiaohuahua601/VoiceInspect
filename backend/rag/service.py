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


DIAGNOSTIC_DOCUMENT_TYPES = {
    "manufacturer_manual",
    "maintenance_guide",
    "safety_guidance",
    "fault_case",
    # Backward-compatible names used by the first public seed.
    "official_safety_guidance",
    "curated_maintenance_guide",
}


class KnowledgeService:
    def __init__(self, provider: OllamaProvider):
        self.provider = provider

    async def ingest_text(self, db: Session, name: str, content: str, version: str = "1", device_model: str | None = None, organization_id: str | None = None, source_metadata: dict | None = None) -> KnowledgeDoc:
        encoded = content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        existing = db.scalar(select(KnowledgeDoc).where(KnowledgeDoc.sha256 == digest, KnowledgeDoc.version == version))
        if existing:
            return existing
        pieces = chunk_text(content)
        metadata = {"device_model": device_model, **(source_metadata or {})}
        doc = KnowledgeDoc(name=name, version=version, status="indexing", organization_id=organization_id, content_text=content, metadata_json=metadata, sha256=digest)
        db.add(doc)
        db.flush()
        try:
            vectors = await self.provider.embed(pieces) if pieces else []
        except Exception as exc:
            doc.status = "failed"
            doc.failure_reason = "向量模型不可用或返回格式错误：" + str(exc)[:500]
            db.commit()
            raise AppError("RAG_EMBEDDING_FAILED", "知识文档向量生成失败，请检查 Embedding Provider 后重试", 503, True, "rag") from exc
        doc.status = "indexed"
        for index, (piece, vector) in enumerate(zip(pieces, vectors)):
            db.add(KnowledgeChunk(doc_id=doc.id, page=None, section=f"chunk-{index + 1}", text=piece, vector=vector, device_model=device_model))
        db.commit()
        db.refresh(doc)
        return doc

    async def search(
        self,
        db: Session,
        query: str,
        device_model: str | None = None,
        top_k: int = 5,
        include_document_types: set[str] | None = None,
        device_type: str | None = None,
    ) -> list[dict]:
        try:
            query_vector = (await self.provider.embed([query]))[0]
        except AppError:
            query_vector = None
        stmt = select(KnowledgeChunk, KnowledgeDoc).join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id).where(KnowledgeDoc.status == "published")
        if device_model:
            stmt = stmt.where((KnowledgeChunk.device_model == device_model) | (KnowledgeChunk.device_model.is_(None)))
        rows = db.execute(stmt).all()
        allowed_types = include_document_types or DIAGNOSTIC_DOCUMENT_TYPES
        rows = [
            (chunk, doc)
            for chunk, doc in rows
            if (doc.metadata_json or {}).get("document_type", "maintenance_guide") in allowed_types
            and (not device_type or not (doc.metadata_json or {}).get("device_type") or (doc.metadata_json or {}).get("device_type") == device_type)
        ]
        if query_vector is not None:
            scored = [(cosine(query_vector, chunk.vector or []), chunk, doc) for chunk, doc in rows]
        else:
            normalized_query = re.sub(r"\s+", "", query.lower())
            query_terms = {normalized_query[index:index + 2] for index in range(max(0, len(normalized_query) - 1))}
            scored = []
            for chunk, doc in rows:
                normalized_chunk = re.sub(r"\s+", "", chunk.text.lower())
                chunk_terms = {normalized_chunk[index:index + 2] for index in range(max(0, len(normalized_chunk) - 1))}
                overlap = len(query_terms & chunk_terms)
                if overlap:
                    scored.append((max(0.15, overlap / max(1, len(query_terms))), chunk, doc))
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
                "source_url": (doc.metadata_json or {}).get("source_url"),
                "publisher": (doc.metadata_json or {}).get("publisher"),
                "license": (doc.metadata_json or {}).get("license"),
                "document_type": (doc.metadata_json or {}).get("document_type"),
                "language": (doc.metadata_json or {}).get("language"),
                "applicability": (doc.metadata_json or {}).get("applicability"),
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

    async def reindex_document(self, db: Session, doc: KnowledgeDoc) -> KnowledgeDoc:
        if not doc.content_text:
            raise AppError("RAG_SOURCE_CONTENT_MISSING", "原始文本已不存在，无法重建向量", 409, False, "rag")
        pieces = chunk_text(doc.content_text)
        doc.status = "indexing"
        doc.failure_reason = None
        db.query(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc.id).delete(synchronize_session=False)
        db.flush()
        try:
            vectors = await self.provider.embed(pieces) if pieces else []
        except Exception as exc:
            doc.status = "failed"
            doc.failure_reason = "向量模型不可用或返回格式错误：" + str(exc)[:500]
            db.commit()
            raise AppError("RAG_EMBEDDING_FAILED", "知识文档向量生成失败，请检查 Embedding Provider 后重试", 503, True, "rag") from exc
        for index, (piece, vector) in enumerate(zip(pieces, vectors)):
            db.add(KnowledgeChunk(doc_id=doc.id, page=None, section=f"chunk-{index + 1}", text=piece, vector=vector, device_model=(doc.metadata_json or {}).get("device_model")))
        doc.status = "indexed"
        db.commit()
        db.refresh(doc)
        return doc
