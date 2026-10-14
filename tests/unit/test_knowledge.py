import pytest
import asyncio

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.rag.service import KnowledgeService
from backend.repositories.db import Base
from backend.repositories.advanced_models import BackgroundJob  # Register background_jobs for Base metadata.
from backend.repositories.models import KnowledgeChunk, KnowledgeDoc


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def test_search_only_published_and_keeps_source_metadata():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    service = KnowledgeService(FakeEmbedder())
    with Session(engine) as db:
        published = KnowledgeDoc(name="官方安全摘要", version="2026.09", sha256="a" * 64, status="published", metadata_json={
            "source_url": "https://www.osha.gov/compressed-gas-equipment/standards",
            "publisher": "U.S. OSHA", "document_type": "safety_guidance", "applicability": "通用空压机安全",
        })
        dataset = KnowledgeDoc(name="数据集卡片", version="1", sha256="c" * 64, status="published", metadata_json={"document_type": "dataset_card"})
        retired = KnowledgeDoc(name="旧版本", version="1", sha256="b" * 64, status="retired", metadata_json={"source_url": "https://invalid.example"})
        db.add_all([published, dataset, retired]); db.flush()
        db.add_all([
            KnowledgeChunk(doc_id=published.id, section="pressure", text="安全阀不得被隔离。", vector=[1.0, 0.0]),
            KnowledgeChunk(doc_id=dataset.id, section="card", text="不应作为维修依据。", vector=[1.0, 0.0]),
            KnowledgeChunk(doc_id=retired.id, section="old", text="不应被检索。", vector=[1.0, 0.0]),
        ]); db.commit()
        citations = asyncio.run(service.search(db, "安全阀", top_k=5))
        assert [item["document"] for item in citations] == ["官方安全摘要"]
        assert citations[0]["source_url"].startswith("https://www.osha.gov")


def test_search_can_explicitly_include_dataset_cards():
    engine = create_engine("sqlite:///:memory:"); Base.metadata.create_all(engine)
    service = KnowledgeService(FakeEmbedder())
    with Session(engine) as db:
        doc = KnowledgeDoc(name="数据集卡片", version="1", sha256="d" * 64, status="published", metadata_json={"document_type": "dataset_card"})
        db.add(doc); db.flush(); db.add(KnowledgeChunk(doc_id=doc.id, section="card", text="字段说明", vector=[1.0, 0.0])); db.commit()
        result = asyncio.run(service.search(db, "字段", include_document_types={"dataset_card"}))
        assert result[0]["document_type"] == "dataset_card"

@pytest.mark.asyncio
async def test_embedding_failure_is_persisted_for_retry():
    class BrokenProvider:
        async def embed(self, texts):
            raise RuntimeError("embedding offline")

    from backend.core.errors import AppError
    from backend.rag.service import KnowledgeService
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        with pytest.raises(AppError) as error:
            await KnowledgeService(BrokenProvider()).ingest_text(db, "失败资料", "需要建立向量", organization_id="org")
        assert error.value.code == "RAG_EMBEDDING_FAILED"
        doc = db.scalar(select(KnowledgeDoc).where(KnowledgeDoc.name == "失败资料"))
        assert doc and doc.status == "failed" and "embedding offline" in (doc.failure_reason or "")
def test_search_filters_out_other_device_types():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    service = KnowledgeService(FakeEmbedder())
    with Session(engine) as db:
        compressor = KnowledgeDoc(name="空压机资料", version="1", sha256="e" * 64, status="published", metadata_json={"document_type": "maintenance_guide", "device_type": "compressor"})
        hydraulic = KnowledgeDoc(name="液压资料", version="1", sha256="f" * 64, status="published", metadata_json={"document_type": "maintenance_guide", "device_type": "hydraulic_system"})
        db.add_all([compressor, hydraulic]); db.flush()
        db.add_all([
            KnowledgeChunk(doc_id=compressor.id, section="compressor", text="压力波动", vector=[1.0, 0.0]),
            KnowledgeChunk(doc_id=hydraulic.id, section="hydraulic", text="压力波动", vector=[1.0, 0.0]),
        ]); db.commit()
        citations = asyncio.run(service.search(db, "压力波动", device_type="hydraulic_system"))
        assert [item["document"] for item in citations] == ["液压资料"]


def test_search_falls_back_when_embedding_is_unavailable():
    class BrokenSearchEmbedder:
        async def embed(self, texts):
            from backend.core.errors import AppError
            raise AppError("RAG_EMBED_FAILED", "offline", 503, True, "rag")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    service = KnowledgeService(BrokenSearchEmbedder())
    with Session(engine) as db:
        compressor = KnowledgeDoc(name="空压机手册", version="1", sha256="1" * 64, status="published", metadata_json={"document_type": "maintenance_guide", "device_type": "compressor"})
        hydraulic = KnowledgeDoc(name="液压手册", version="1", sha256="2" * 64, status="published", metadata_json={"document_type": "maintenance_guide", "device_type": "hydraulic_system"})
        dataset = KnowledgeDoc(name="空压机数据集", version="1", sha256="3" * 64, status="published", metadata_json={"document_type": "dataset_card", "device_type": "compressor"})
        db.add_all([compressor, hydraulic, dataset]); db.flush()
        db.add_all([
            KnowledgeChunk(doc_id=compressor.id, section="temperature", text="排气温度异常时检查冷却器和润滑油。", vector=[1.0, 0.0]),
            KnowledgeChunk(doc_id=hydraulic.id, section="temperature", text="温度异常时检查液压冷却器。", vector=[1.0, 0.0]),
            KnowledgeChunk(doc_id=dataset.id, section="card", text="空压机温度异常数据字段。", vector=[1.0, 0.0]),
        ]); db.commit()
        citations = asyncio.run(service.search(db, "空压机温度异常如何检查冷却和润滑", device_type="compressor"))
        assert [item["document"] for item in citations] == ["空压机手册"]