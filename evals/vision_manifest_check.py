"""Report coverage and label hygiene for the local visual evaluation manifest."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/vision/manifest.jsonl"


def load() -> list[dict]:
    return [json.loads(line) for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    items = load()
    by_type = defaultdict(list)
    for item in items:
        by_type[item["device_type"]].append(item)
    print(json.dumps({
        "total_manifest": len(items),
        "local_assets": sum(bool(item.get("path")) and (ROOT / "data/vision" / item["path"]).exists() for item in items),
        "by_device_type": {
            key: {"manifest": len(value), "local": sum(bool(item.get("path")) and (ROOT / "data/vision" / item["path"]).exists() for item in value), "states": dict(Counter(item["state"] for item in value))}
            for key, value in sorted(by_type.items())
        },
        "release_gate": "blocked until each device type has >=12 local labeled images",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()