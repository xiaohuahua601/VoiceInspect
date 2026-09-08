"""Configurable device knowledge profiles used by deterministic checks and prompts."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "data" / "device-profiles.json"


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, dict[str, Any]]:
    if not PROFILE_PATH.exists():
        return {}
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def get_profile(equipment_type: str | None) -> dict[str, Any]:
    if not equipment_type:
        return {}
    return load_profiles().get(equipment_type, {})


def equipment_type(device: Any | None) -> str | None:
    metadata = getattr(device, "metadata_json", None) or {}
    value = metadata.get("equipment_type")
    if value:
        return str(value)
    model = str(getattr(device, "model", "")).lower()
    if "compress" in model:
        return "compressor"
    if "hydraulic" in model:
        return "hydraulic_system"
    if "motor" in model or "drive" in model:
        return "motor"
    if model:
        return "industrial_machine"
    return None