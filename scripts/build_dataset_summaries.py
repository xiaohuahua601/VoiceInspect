"""Create explainable dataset summary cards without ingesting raw rows into diagnostic RAG."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data/datasets/catalog.json"
RAW = ROOT / "data/datasets/raw"
OUT = ROOT / "data/datasets/derived"


def find_csv(folder: Path) -> Path | None:
    return next(iter(sorted(folder.rglob("*.csv"))), None) if folder.exists() else None


def summarize(item: dict) -> str | None:
    source = find_csv(RAW / item["slug"] / "extracted")
    if not source:
        return None
    with source.open(encoding="utf-8-sig", newline="", errors="replace") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        rows = list(reader)
    numeric = {}
    for key in headers:
        values = []
        for row in rows:
            try: values.append(float(row.get(key, "")))
            except (TypeError, ValueError): pass
        if values: numeric[key] = {"min": min(values), "max": max(values)}
    label_counts = {}
    for key in headers:
        if any(token in key.lower() for token in ("machine failure", "failure", "label", "class", "status")):
            label_counts[key] = dict(Counter(row.get(key, "") for row in rows))
    return "\n".join([
        f"# ETL 数据摘要：{item['name']}", "", "## 处理边界",
        "这是由本地原始数据生成的字段与统计摘要，用于算法验证和数据字段问答，不是现场维修证据，也不替代制造商手册。",
        "", "## 数据概况", f"设备类型：{'、'.join(item.get('equipment_types', []))}", f"行数：{len(rows)}；字段数：{len(headers)}。",
        "字段：" + "、".join(headers), "", "## 数值范围摘要", json.dumps(numeric, ensure_ascii=False),
        "", "## 故障标签摘要", json.dumps(label_counts, ensure_ascii=False),
        "", "## 来源", f"来源页面：{item['source_url']}", f"许可证：{item['license']}",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--slugs"); args = parser.parse_args()
    selected = set(args.slugs.split(",")) if args.slugs else None
    OUT.mkdir(parents=True, exist_ok=True)
    for item in json.loads(CATALOG.read_text(encoding="utf-8")):
        if selected and item["slug"] not in selected: continue
        text = summarize(item)
        if text:
            path = OUT / f"{item['slug']}-summary.md"; path.write_text(text, encoding="utf-8"); print(path.relative_to(ROOT))
        else: print(f"{item['slug']}: no local CSV, skipped")


if __name__ == "__main__": main()