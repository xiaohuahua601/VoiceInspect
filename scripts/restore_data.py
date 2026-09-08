"""Restore a previously created data backup into an explicitly selected data directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def main() -> None:
    parser = argparse.ArgumentParser(description="恢复 VoiceInspect 数据；会覆盖目标数据子目录")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--target", type=Path, default=ROOT / "data")
    parser.add_argument("--confirm", action="store_true", help="明确确认覆盖目标数据")
    args = parser.parse_args()
    archive = args.archive.resolve(); target = args.target.resolve()
    manifest_path = archive / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit("备份缺少 manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        path = archive / entry["path"]
        if not path.is_file() or sha256(path) != entry["sha256"]:
            raise SystemExit(f"备份校验失败: {entry['path']}")
    if not args.confirm:
        raise SystemExit("恢复会覆盖目标数据，请重新执行并添加 --confirm")
    target.mkdir(parents=True, exist_ok=True)
    for child in archive.iterdir():
        if child.name == "manifest.json":
            continue
        destination = target / child.name
        if destination.exists():
            if destination.is_dir(): shutil.rmtree(destination)
            else: destination.unlink()
        if child.is_dir(): shutil.copytree(child, destination)
        else: shutil.copy2(child, destination)
    print(f"restored to {target}")

if __name__ == "__main__":
    main()
