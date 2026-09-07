"""Download approved public datasets and import traceable dataset cards into RAG."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

from sqlalchemy import select

from backend.core.config import get_settings
from backend.main import seed_demo_data
from backend.providers.ollama import OllamaProvider
from backend.rag.service import KnowledgeService
from backend.repositories.db import SessionLocal, init_db
from backend.repositories.models import AuditEvent, KnowledgeDoc, User, new_id


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data/datasets/catalog.json"
RAW_ROOT = ROOT / "data/datasets/raw"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as handle:
        for member in handle.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"拒绝路径穿越压缩包成员: {member.filename}")
        handle.extractall(destination)


def existing_asset(item: dict) -> dict:
    archive = RAW_ROOT / item["slug"] / "source.zip"
    if archive.exists() and archive.stat().st_size > 0:
        return {"status": "downloaded", "archive": str(archive.relative_to(ROOT)), "sha256": sha256_file(archive)}
    return {"status": "not_requested"}


def download(item: dict) -> dict:
    if not item.get("download"):
        return {"status": "catalog_only"}
    folder = RAW_ROOT / item["slug"]
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / "source.zip"
    if not archive.exists() or archive.stat().st_size == 0:
        request = urllib.request.Request(item["download_url"], headers={"User-Agent": "VoiceInspect dataset importer/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    digest = sha256_file(archive)
    extracted = folder / "extracted"
    if not extracted.exists() or not any(extracted.iterdir()):
        safe_extract(archive, extracted)
    return {"status": "downloaded", "archive": str(archive.relative_to(ROOT)), "sha256": digest}


def card_text(item: dict, asset: dict) -> str:
    modality = "、".join(item.get("modality", []))
    equipment = "、".join(item.get("equipment_types", []))
    rows = [
        f"# 数据集卡片：{item['name']}",
        "",
        "## 用途边界",
        item["applicability"],
        "这是数据集元数据和算法验证依据，不是某个现场设备的原厂维修手册。诊断回答必须把数据集规律与现场观察区分开，并在证据不足时拒答。",
        "",
        "## 数据概况",
        f"设备类型：{equipment}",
        f"数据模态：{modality}",
        f"样本数：{item.get('instances') or '来源未提供'}；特征数：{item.get('features') or '来源未提供'}。",
        f"原始数据状态：{asset.get('status')}。本地资产路径：{asset.get('archive', '未下载')}。",
        "",
        "## 来源与许可",
        f"发布机构：{item['publisher']}",
        f"来源页面：{item['source_url']}",
        f"下载地址：{item['download_url']}",
        f"许可证：{item['license']}",
        f"论文/引用：{item['citation']}",
        f"本地压缩包 SHA-256：{asset.get('sha256', '未下载')}。",
        "",
        "## VoiceInspect 使用说明",
        "只有已发布的卡片会进入 RAG。卡片可以帮助回答数据字段、故障类别和适用范围问题；原始 CSV、TXT、音频等文件暂不直接参与自然语言检索，避免把训练数据误当成现场证据。",
    ]
    return "\n".join(rows)


async def import_cards(items: list[dict], assets: dict[str, dict], publish: bool) -> None:
    init_db()
    seed_demo_data()
    settings = get_settings()
    service = KnowledgeService(OllamaProvider(settings))
    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.username == settings.demo_knowledge_admin_username))
        if not admin:
            raise RuntimeError("knowledge admin demo account is not available")
        for item in items:
            asset = assets.get(item["slug"], {"status": "not_requested"})
            content = card_text(item, asset)
            metadata = {
                "source_url": item["source_url"],
                "publisher": item["publisher"],
                "license": item["license"],
                "document_type": item["document_type"],
                "language": item["language"],
                "applicability": item["applicability"],
                "dataset_slug": item["slug"],
                "modality": item["modality"],
                "equipment_types": item["equipment_types"],
                "asset": asset,
            }
            document = await service.ingest_text(db, f"数据集卡片｜{item['name']}", content, "1", None, admin.organization_id, metadata)
            if publish:
                db.query(KnowledgeDoc).filter(KnowledgeDoc.name == document.name, KnowledgeDoc.id != document.id, KnowledgeDoc.status == "published").update({"status": "retired"})
                document.status = "published"
            db.add(AuditEvent(trace_id=new_id(), actor_id=admin.id, action="knowledge.dataset_imported", target=document.id, details={"dataset_slug": item["slug"], "published": publish, "asset": asset}))
            db.commit()
            print(f"{item['slug']}: {document.status}; asset={asset['status']}; chunks={len(document.chunks)}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="导入可追溯的开源工业数据集资产")
    parser.add_argument("--download", action="store_true", help="下载 catalog.json 中许可明确的数据集")
    parser.add_argument("--publish", action="store_true", help="将数据集卡片发布到 RAG")
    parser.add_argument("--datasets", help="逗号分隔 slug，默认处理整个目录")
    args = parser.parse_args()
    items = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    selected = set(args.datasets.split(",")) if args.datasets else {item["slug"] for item in items}
    items = [item for item in items if item["slug"] in selected]
    unknown = selected - {item["slug"] for item in items}
    if unknown:
        raise SystemExit(f"未知数据集 slug: {', '.join(sorted(unknown))}")
    assets = {item["slug"]: download(item) if args.download else existing_asset(item) for item in items}
    asyncio.run(import_cards(items, assets, args.publish))


if __name__ == "__main__":
    main()
