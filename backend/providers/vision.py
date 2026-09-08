"""Ollama-compatible two-pass vision adapter with strict structured validation."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.core.config import get_settings
from backend.providers.contracts import ProviderHealth, VisionObservation
from backend.services.image_preprocessing import prepare_image_bytes


class ImageQuality(BaseModel):
    usable: bool = True
    issues: list[str] = Field(default_factory=list)


class ObservationItem(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    evidence: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: object) -> float:
        if isinstance(value, str):
            labels = {"high": 0.85, "medium": 0.6, "low": 0.3, "高": 0.85, "中": 0.6, "低": 0.3}
            key = value.strip().lower()
            if key in labels:
                return labels[key]
        return float(value)



class MeasurementItem(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    value: float | None = None
    unit: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: object) -> float:
        if isinstance(value, str):
            labels = {"high": 0.85, "medium": 0.6, "low": 0.3, "高": 0.85, "中": 0.6, "低": 0.3}
            key = value.strip().lower()
            if key in labels:
                return labels[key]
        return float(value)



class CandidateAnomaly(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    evidence: list[str] = Field(default_factory=list)
    severity: str = "medium"
    confidence: float = Field(default=0.5, ge=0, le=1)
    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: object) -> float:
        if isinstance(value, str):
            labels = {"high": 0.85, "medium": 0.6, "low": 0.3, "高": 0.85, "中": 0.6, "低": 0.3}
            key = value.strip().lower()
            if key in labels:
                return labels[key]
        return float(value)



class VisionPayload(BaseModel):
    scene_summary: str = ""
    equipment_type: str | None = None
    component: str | None = None
    image_quality: ImageQuality = Field(default_factory=ImageQuality)
    observations: list[ObservationItem] = Field(default_factory=list)
    measurements: list[MeasurementItem] = Field(default_factory=list)
    candidate_anomalies: list[CandidateAnomaly] = Field(default_factory=list)
    # Kept for compatibility with previously stored messages and the UI contract.
    suspected_anomalies: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)

    @field_validator("component", mode="before")
    @classmethod
    def normalize_component(cls, value: object) -> str | None:
        if value is None: return None
        if isinstance(value, list):
            return "、".join(str(item.get("description") if isinstance(item, dict) else item) for item in value)
        return str(value)

    @field_validator("measurements", "candidate_anomalies", mode="before")
    @classmethod
    def normalize_singleton_arrays(cls, value: object) -> object:
        if value is None: return []
        return [value] if isinstance(value, dict) else value

    @field_validator("observations", mode="before")
    @classmethod
    def normalize_observations(cls, value: object) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("observations 必须是数组")
        normalized: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, str):
                normalized.append({"description": item, "evidence": "", "confidence": 0.5})
            elif isinstance(item, dict):
                normalized.append(item)
            else:
                raise ValueError("观察项必须是字符串或对象")
        return normalized

    @field_validator("suspected_anomalies", "uncertainties", "safety_flags", mode="before")
    @classmethod
    def normalize_strings(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("视觉列表字段必须是数组")
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                parts = [item.get("type"), item.get("description"), item.get("detail")]
                parts = [str(value) for value in parts if value]
                result.append("：".join(parts) if parts else str(item))
            else:
                raise ValueError("视觉列表元素必须是字符串或对象")
        return result


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("视觉模型未返回符合契约的 JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("视觉模型返回的 JSON 顶层必须是对象")
    return data


def parse_vision_payload(raw: str, require_observation: bool = True) -> VisionObservation:
    try:
        parsed = VisionPayload.model_validate(_parse_json(raw))
    except ValidationError as exc:
        raise RuntimeError("视觉模型未返回符合契约的结构化结果") from exc
    if require_observation and not parsed.observations:
        raise RuntimeError("视觉模型返回了空观察结果")
    data = parsed.model_dump()
    data["image_quality"] = parsed.image_quality.model_dump()
    data["observations"] = [item.model_dump() for item in parsed.observations]
    data["measurements"] = [item.model_dump() for item in parsed.measurements]
    data["candidate_anomalies"] = [item.model_dump() for item in parsed.candidate_anomalies]
    return VisionObservation(**data)


class OllamaVision:
    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()

    async def _generate_json(self, image: str, instruction: str) -> dict[str, Any]:
        payload = {
            "model": self.settings.ollama_vision_model,
            "prompt": instruction,
            "images": [image],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_thread": self.settings.ollama_num_threads,
                "num_ctx": self.settings.ollama_num_ctx,
                "num_predict": self.settings.ollama_vision_num_predict,
            },
        }
        async with httpx.AsyncClient(timeout=self.settings.ollama_timeout_seconds, trust_env=False) as client:
            response = await client.post(f"{self.settings.ollama_base_url}/api/generate", json=payload)
            response.raise_for_status()
            return _parse_json(response.json().get("response", ""))

    async def analyze(self, path: Path, prompt: str) -> VisionObservation:
        if not self.settings.ollama_vision_model:
            raise RuntimeError("未配置 OLLAMA_VISION_MODEL")
        image = base64.b64encode(prepare_image_bytes(path, max_size=self.settings.vision_image_max_size)).decode("ascii")
        fact_instruction = (
            "你是工业设备视觉取证助手。第一轮只记录图片中能直接看见的客观事实，不要猜测内部故障。"
            "只返回 JSON，字段必须为 scene_summary, equipment_type, component, image_quality, observations, measurements, candidate_anomalies, uncertainties, safety_flags。"
            "image_quality 包含 usable 和 issues；observations 是对象数组，每项包含 description、evidence、confidence(0到1)；"
            "measurements 是 name、value、unit、confidence；无法读出的值填 null。"
            "candidate_anomalies 是有图片证据支持的疑似异常数组，每项包含 code、description、evidence、severity、confidence；没有证据时返回空数组。"
            "请特别检查仪表读数、报警灯/故障码、开盖或裸露部件、泄漏、裂纹、烧蚀、异常颜色、锈蚀和部件缺失。"
            "设备上下文和现场问题：\n" + prompt
        )
        facts = await self._generate_json(image, fact_instruction)
        fact_result = parse_vision_payload(json.dumps(facts, ensure_ascii=False))
        fact_dump = json.dumps({
            "scene_summary": fact_result.scene_summary,
            "equipment_type": fact_result.equipment_type,
            "component": fact_result.component,
            "image_quality": fact_result.image_quality,
            "observations": fact_result.observations,
            "measurements": fact_result.measurements,
            "uncertainties": fact_result.uncertainties,
            "safety_flags": fact_result.safety_flags,
        }, ensure_ascii=False)
        anomaly_instruction = (
            "你是工业设备异常复核助手。第二轮只能根据同一张图片和下面的客观事实判断候选异常，禁止补造图片中不存在的证据。"
            "只返回 JSON，字段必须为 candidate_anomalies、suspected_anomalies、uncertainties、safety_flags。"
            "candidate_anomalies 每项包含 code、description、evidence(必须引用 observations 或 measurements 中的描述/name)、severity、confidence。"
            "如果没有充分证据，candidate_anomalies 返回空数组，并在 uncertainties 说明需要补充的照片或数据；不得为了满足格式强行报故障。"
            "\n客观事实：" + fact_dump + "\n现场问题：" + prompt
        )
        if self.settings.vision_anomaly_second_pass:
            try:
                anomaly = await self._generate_json(image, anomaly_instruction)
                anomaly_payload = VisionPayload.model_validate({**facts, **anomaly})
                fact_result.candidate_anomalies = [item.model_dump() for item in anomaly_payload.candidate_anomalies]
                fact_result.suspected_anomalies = anomaly_payload.suspected_anomalies
                fact_result.uncertainties = list(dict.fromkeys(fact_result.uncertainties + anomaly_payload.uncertainties))
                fact_result.safety_flags = list(dict.fromkeys(fact_result.safety_flags + anomaly_payload.safety_flags))
            except (RuntimeError, ValidationError, httpx.HTTPError):
                # Objective observations remain useful when the second judgment pass fails.
                fact_result.uncertainties = list(dict.fromkeys(fact_result.uncertainties + ["异常复核阶段不可用，候选异常需要人工确认"]))
        else:
            fact_result.uncertainties = list(dict.fromkeys(fact_result.uncertainties + ["当前使用单轮视觉分析，疑似异常需要人工确认"]))
        return fact_result

    async def health(self) -> ProviderHealth:
        if not self.settings.ollama_vision_model:
            return ProviderHealth("ollama-vision", False, "未配置 OLLAMA_VISION_MODEL")
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                response = await client.get(f"{self.settings.ollama_base_url}/api/tags")
                response.raise_for_status()
                names = {m.get("name") for m in response.json().get("models", [])}
            available = self.settings.ollama_vision_model in names
            return ProviderHealth("ollama-vision", available, None if available else "视觉模型未安装", self.settings.ollama_vision_model)
        except Exception as exc:
            return ProviderHealth("ollama-vision", False, str(exc), self.settings.ollama_vision_model)
