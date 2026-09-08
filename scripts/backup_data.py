"""Create a portable VoiceInspect data backup without secrets or virtual environments."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INCLUDE = ("db", "uploads", "knowledge", "qdrant", "logs", "exports", "datasets")

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def main() -> None:
    parser = argparse.ArgumentParser(description="备份 VoiceInspect 数据，不包含 .env 和模型权重")
    parser.add_argument("--output", type=Path, help="备份目录；默认 data/backups/<timestamp>")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = (args.output or DATA / "backups" / f"voiceinspect-{stamp}").resolve()
    target.mkdir(parents=True, exist_ok=False)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "source": str(DATA), "files": []}
    for name in INCLUDE:
        source = DATA / name
        if not source.exists():
            continue
        destination = target / name
        if source.is_dir():
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns("*.tmp", "*.lock"))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for path in target.rglob("*"):
        if path.is_file():
            manifest["files"].append({"path": str(path.relative_to(target)), "bytes": path.stat().st_size, "sha256": sha256(path)})
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)

if __name__ == "__main__":
    main()
