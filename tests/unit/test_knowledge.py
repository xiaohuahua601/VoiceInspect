import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.rag.service import KnowledgeService
from backend.repositories.db import Base
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
            "publisher": "U.S. OSHA",
            "applicability": "通用空压机安全",
        })
        retired = KnowledgeDoc(name="旧版本", version="1", sha256="b" * 64, status="retired", metadata_json={"source_url": "https://invalid.example"})
        db.add_all([published, retired])
        db.flush()
        db.add_all([
            KnowledgeChunk(doc_id=published.id, section="pressure", text="安全阀不得被隔离。", vector=[1.0, 0.0]),
            KnowledgeChunk(doc_id=retired.id, section="old", text="不应被检索。", vector=[1.0, 0.0]),
        ])
        db.commit()
        citations = asyncio.run(service.search(db, "安全阀", top_k=5))
        assert len(citations) == 1
        assert citations[0]["document"] == "官方安全摘要"
        assert citations[0]["source_url"].startswith("https://www.osha.gov")
        assert citations[0]["publisher"] == "U.S. OSHA"
        assert citations[0]["applicability"] == "通用空压机安全"


def test_ingest_persists_generic_scope_metadata():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    service = KnowledgeService(FakeEmbedder())
    with Session(engine) as db:
        doc = asyncio.run(service.ingest_text(db, "通用维护", "压力异常时先隔离能源。", "1", None, "org-1", {
            "source_url": "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.169",
            "publisher": "U.S. OSHA",
            "document_type": "official_safety_guidance",
            "applicability": "通用空压机；非特定型号",
        }))
        assert doc.status == "indexed"
        assert doc.metadata_json["device_model"] is None
        assert doc.metadata_json["applicability"] == "通用空压机；非特定型号"