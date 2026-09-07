import json
import shutil
import zipfile
from pathlib import Path

import pytest

from scripts.import_open_datasets import safe_extract


ROOT = Path(__file__).resolve().parents[2]


def test_dataset_catalog_has_traceable_license_and_source() -> None:
    catalog = json.loads((ROOT / "data/datasets/catalog.json").read_text(encoding="utf-8"))
    assert len(catalog) >= 5
    assert {item["slug"] for item in catalog} >= {"metropt-3", "ai4i-2020", "hydraulic-systems-447"}
    for item in catalog:
        assert item["source_url"].startswith("https://")
        assert item["publisher"]
        assert item["license"]
        assert item["document_type"] in {"dataset_card", "dataset_catalog_only"}


def test_safe_extract_rejects_path_traversal() -> None:
    test_root = ROOT / "data/datasets/.test-security"
    shutil.rmtree(test_root, ignore_errors=True)
    test_root.mkdir(parents=True)
    archive = test_root / "malicious.zip"
    try:
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../escaped.txt", "should not be extracted")
        with pytest.raises(RuntimeError, match="路径穿越"):
            safe_extract(archive, test_root / "out")
    finally:
        shutil.rmtree(test_root, ignore_errors=True)