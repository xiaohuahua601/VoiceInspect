"""Ollama-compatible vision adapter with strict JSON validation."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.core.config import get_settings
from backend.providers.contracts import ProviderHealth, VisionObservation


class VisionPayload(BaseModel):
    scene_summary: str = ""
    observations: list[str] = Field(default_factory=list)
    suspected_anomalies: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)

    @field_validator("observations", "suspected_anomalies", "uncertainties", "safety_flags", mode="before")
    @classmethod
    def normalize_items(cls, value: object) -> list[str]:
        """Keep the external contract string-based while accepting safe object details."""
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("视觉列表字段必须是数组")
        normalized: list[str] = []
        for item in value:
            if isinstance(item, str):
                normalized.append(item)
            elif isinstance(item, dict):
                parts = [str(item[key]) for key in ("type", "description", "detail", "reason") if item.get(key)]
                normalized.append("：".join(parts) if parts else json.dumps(item, ensure_ascii=False))
            else:
                raise ValueError("视觉列表元素必须是字符串或对象")
        return normalized

def parse_vision_payload(raw: str) -> VisionObservation:
    try:
        parsed = VisionPayload.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise RuntimeError("视觉模型未返回符合契约的 JSON") from exc
    if not parsed.observations:
        raise RuntimeError("视觉模型返回了空观察结果")
    if not parsed.suspected_anomalies:
        raise RuntimeError("视觉模型未返回异常判断")
    return VisionObservation(**parsed.model_dump())


class OllamaVision:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def analyze(self, path: Path, prompt: str) -> VisionObservation:
        if not self.settings.ollama_vision_model:
            raise RuntimeError("未配置 OLLAMA_VISION_MODEL")
        image = base64.b64encode(path.read_bytes()).decode("ascii")
        instruction = (
            "你是工业设备现场异常检测助手，不是普通看图描述器。只依据图像和现场问题判断可见异常，不要输出 Markdown。"
            "只返回一个 JSON 对象，字段必须完整，结构为："
            '{"scene_summary":"场景概述","observations":["可见读数或部件"],"suspected_anomalies":["异常：现象；证据：图中可见依据；置信度：高/中/低"],"uncertainties":["图像无法确认的内容"],"safety_flags":["必要安全提示"]}'
            "先逐条记录客观事实：仪表读数、温度、报警灯、开盖状态、泄漏、裂纹、锈蚀、松动、烧蚀、异物和部件缺失。"
            "再判断异常：只要读数明显偏高/偏低，出现泄漏、损伤、报警、异常颜色或不安全状态，必须写入 suspected_anomalies，并引用对应观察证据。"
            "suspected_anomalies 必须至少填写 1 条；若未见明确异常，填写‘未见可从图像确认的明确异常’，并在 uncertainties 说明还需什么数据。"
            "必须区分客观观察、疑似异常、不确定性和安全提示；禁止从图片不存在的内容推断故障。\n现场问题：" + prompt
        )
        payload = {
            "model": self.settings.ollama_vision_model,
            "prompt": instruction,
            "images": [image],
            "stream": False,
            "format": "json",
        }
        async with httpx.AsyncClient(timeout=self.settings.ollama_timeout_seconds, trust_env=False) as client:
            response = await client.post(f"{self.settings.ollama_base_url}/api/generate", json=payload)
            response.raise_for_status()
            raw = response.json().get("response", "")
        return parse_vision_payload(raw)

    async def health(self) -> ProviderHealth:
        if not self.settings.ollama_vision_model:
            return ProviderHealth("ollama-vision", False, "未配置 OLLAMA_VISION_MODEL")
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                response = await client.get(f"{self.settings.ollama_base_url}/api/tags")
                response.raise_for_status()
                names = {m.get("name") for m in response.json().get("models", [])}
            available = self.settings.ollama_vision_model in names
            return ProviderHealth(
                "ollama-vision", available,
                None if available else "视觉模型未安装", self.settings.ollama_vision_model,
            )
        except Exception as exc:
            return ProviderHealth("ollama-vision", False, str(exc), self.settings.ollama_vision_model)
