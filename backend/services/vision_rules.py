"""Deterministic safety and boundary checks for vision evidence."""
from __future__ import annotations

from typing import Any

from backend.domain.device_profiles import equipment_type, get_profile

TYPE_ALIASES = {
    "空压机": "compressor", "压缩机": "compressor",
    "液压系统": "hydraulic_system", "液压": "hydraulic_system",
    "驱动电机": "motor", "电机": "motor",
    "加工设备": "industrial_machine", "机床": "industrial_machine",
}
RISK_WORDS = {"泄漏": "发现疑似泄漏迹象", "渗油": "发现疑似油液渗漏迹象", "裸露": "发现裸露部件或带电风险迹象", "开盖": "发现防护盖或柜门打开迹象", "打开": "发现防护盖或柜门打开迹象", "烧蚀": "发现烧蚀或过热痕迹", "裂纹": "发现裂纹或结构损伤迹象", "报警": "发现报警灯或报警信息", "故障码": "发现故障码信息"}
ANOMALY_WORDS = {
    "开盖": ("OPEN_PANEL", "发现防护盖或柜门打开，存在暴露部件风险"),
    "打开": ("OPEN_PANEL", "发现防护盖或柜门打开，存在暴露部件风险"),
    "裸露": ("EXPOSED_COMPONENT", "发现部件裸露，需先确认能源隔离"),
    "泄漏": ("LEAK_SUSPECTED", "发现疑似泄漏迹象"),
    "渗油": ("OIL_LEAK_SUSPECTED", "发现疑似油液渗漏迹象"),
    "烧蚀": ("BURN_MARK_SUSPECTED", "发现疑似烧蚀或过热痕迹"),
    "报警": ("ALARM_VISIBLE", "发现报警灯或报警信息"),
    "故障码": ("FAULT_CODE_VISIBLE", "发现故障码信息"),
}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def apply_visual_rules(observation: dict[str, Any], device: Any | None) -> dict[str, Any]:
    """Add explainable candidates; never turn a visual guess into a confirmed fault."""
    result = {**observation}
    result["image_quality"] = {**(observation.get("image_quality") or {})}
    result["image_quality"].setdefault("issues", [])
    result["observations"] = list(observation.get("observations") or [])
    result["measurements"] = list(observation.get("measurements") or [])
    result["candidate_anomalies"] = list(observation.get("candidate_anomalies") or [])
    result["uncertainties"] = list(observation.get("uncertainties") or [])
    result["safety_flags"] = list(observation.get("safety_flags") or [])

    expected = equipment_type(device)
    detected = TYPE_ALIASES.get(str(result.get("equipment_type") or ""), result.get("equipment_type"))
    if expected and detected and detected != expected:
        result["image_quality"]["usable"] = False
        result["image_quality"]["issues"].append("图片设备类型与当前选择不一致")
        result["uncertainties"].append("无法将图片观察可靠绑定到当前设备")

    profile = get_profile(expected or detected)
    ranges = profile.get("ranges", {})
    known_evidence = set()
    for item in result["observations"]:
        text = item.get("description", "") if isinstance(item, dict) else str(item)
        known_evidence.update({text, str(item.get("evidence", "")) if isinstance(item, dict) else text})
        for word, warning in RISK_WORDS.items():
            if word in text and warning not in result["safety_flags"]:
                result["safety_flags"].append(warning)
        for word, (code, description) in ANOMALY_WORDS.items():
            if word in text and not any(item.get("code") == code for item in result["candidate_anomalies"] if isinstance(item, dict)):
                result["candidate_anomalies"].append({"code": code, "description": description, "evidence": [text], "severity": "medium", "confidence": 0.9})
    for item in result["measurements"]:
        if isinstance(item, dict):
            known_evidence.add(str(item.get("name", "")))

    for measurement in result["measurements"]:
        if not isinstance(measurement, dict):
            continue
        name = str(measurement.get("name", "")).lower()
        value = _number(measurement.get("value"))
        rule = ranges.get("temperature_c") if value is not None and ("temp" in name or "温度" in name) else None
        if rule and value > float(rule.get("high")):
            code = "HIGH_TEMPERATURE"
            if not any(item.get("code") == code for item in result["candidate_anomalies"] if isinstance(item, dict)):
                result["candidate_anomalies"].append({"code": code, "description": "测得温度超过当前设备通用筛查阈值", "evidence": [str(measurement.get("name"))], "severity": "medium", "confidence": 0.95})
            result["uncertainties"].append("数值阈值是通用筛查规则，需以该设备制造商限值复核")

    valid_candidates = []
    for item in result["candidate_anomalies"]:
        if not isinstance(item, dict):
            continue
        evidence = [str(value) for value in (item.get("evidence") or []) if str(value).strip()]
        if evidence and any(value in known_evidence or any(value in known for known in known_evidence) for value in evidence):
            item["evidence"] = evidence
            valid_candidates.append(item)
        else:
            result["uncertainties"].append(f"异常“{item.get('description', '未命名')}”缺少可回溯图片证据")
    result["equipment_type"] = detected or result.get("equipment_type")
    result["candidate_anomalies"] = valid_candidates
    result["suspected_anomalies"] = [item.get("description", "") for item in valid_candidates]
    result["uncertainties"] = list(dict.fromkeys(result["uncertainties"]))
    result["safety_flags"] = list(dict.fromkeys(result["safety_flags"]))
    return result


def needs_visual_review(observation: dict[str, Any]) -> bool:
    quality = observation.get("image_quality") or {}
    return not quality.get("usable", True) or not observation.get("observations") or not observation.get("candidate_anomalies")