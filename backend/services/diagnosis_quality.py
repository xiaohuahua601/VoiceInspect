"""Build an auditable diagnostic evidence envelope around model prose."""
from __future__ import annotations

from typing import Any

from backend.domain.device_profiles import equipment_type, get_profile


def build_diagnosis_result(vision: dict[str, Any] | None, citations: list[dict[str, Any]], device: Any | None) -> dict[str, Any]:
    vision = vision or {}
    anomalies = [item for item in (vision.get("candidate_anomalies") or []) if isinstance(item, dict) and item.get("evidence")]
    observations = [item for item in (vision.get("observations") or []) if item]
    profile = get_profile(equipment_type(device))
    checks = list(profile.get("evidence_prompts") or [])
    if anomalies:
        checks.insert(0, "核对异常对应的仪表读数、报警代码和历史趋势，再按设备手册执行检查")
    safety = list(dict.fromkeys((vision.get("safety_flags") or []) + (profile.get("safety") or [])))
    uncertainties = list(dict.fromkeys(vision.get("uncertainties") or []))
    if not observations:
        uncertainties.append("图片没有提供可验证的客观观察")
    if not citations:
        uncertainties.append("当前没有检索到可绑定的已发布知识依据")
    confidence = "low" if uncertainties or not anomalies else "medium"
    return {
        "summary": "发现带图片证据的候选异常，仍需人工确认" if anomalies else "已识别设备或场景，但未发现具有充分证据的明确异常",
        "observed_evidence": observations,
        "candidate_causes": [
            {"description": item.get("description", ""), "evidence": item.get("evidence", []), "severity": item.get("severity", "medium"), "confidence": item.get("confidence", 0.5)}
            for item in anomalies
        ],
        "recommended_checks": checks,
        "safety_actions": safety,
        "uncertainties": uncertainties,
        "confidence": confidence,
        "citations": [
            {"citation_id": item.get("citation_id"), "document": item.get("document"), "section": item.get("section"), "score": item.get("score")}
            for item in citations
        ],
    }