import json

from backend.providers.vision import parse_vision_payload
from backend.services.vision_rules import apply_visual_rules, needs_visual_review


def test_structured_vision_payload_accepts_observations_and_measurements():
    result = parse_vision_payload(json.dumps({
        "scene_summary": "空压机控制面板",
        "equipment_type": "compressor",
        "component": "cooling_system",
        "image_quality": {"usable": True, "issues": []},
        "observations": [{"description": "显示屏温度 86°C", "evidence": "右上角显示屏", "confidence": 0.86}],
        "measurements": [{"name": "temperature", "value": 86, "unit": "°C", "confidence": 0.78}],
        "candidate_anomalies": [{"code": "HIGH_TEMPERATURE", "description": "温度可能偏高", "evidence": ["temperature"], "severity": "medium", "confidence": 0.75}],
        "suspected_anomalies": ["温度可能偏高"],
        "uncertainties": [],
        "safety_flags": [],
    }, ensure_ascii=False))
    assert result.measurements[0]["value"] == 86
    assert result.candidate_anomalies[0]["evidence"] == ["temperature"]


def test_visual_rules_add_threshold_candidate_and_require_evidence():
    raw = {
        "equipment_type": "compressor",
        "image_quality": {"usable": True, "issues": []},
        "observations": [{"description": "显示屏温度 86°C", "evidence": "右上角显示屏"}],
        "measurements": [{"name": "temperature", "value": 86, "unit": "°C"}],
        "candidate_anomalies": [{"code": "GUESS", "description": "无证据猜测", "evidence": []}],
        "uncertainties": [], "safety_flags": [],
    }
    result = apply_visual_rules(raw, type("Device", (), {"model": "COMPRESSOR-A", "metadata_json": {"equipment_type": "compressor"}})())
    assert any(item["code"] == "HIGH_TEMPERATURE" for item in result["candidate_anomalies"])
    assert all(item["evidence"] for item in result["candidate_anomalies"])
    assert not needs_visual_review(result)


def test_visual_rules_mark_mismatch_for_review():
    result = apply_visual_rules({
        "equipment_type": "motor", "image_quality": {"usable": True, "issues": []},
        "observations": [{"description": "电机外观", "evidence": "设备主体"}],
        "measurements": [], "candidate_anomalies": [], "uncertainties": [], "safety_flags": [],
    }, type("Device", (), {"model": "COMPRESSOR-A", "metadata_json": {"equipment_type": "compressor"}})())
    assert result["image_quality"]["usable"] is False
    assert needs_visual_review(result)