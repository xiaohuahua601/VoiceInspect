"""Ollama-compatible vision adapter with strict JSON validation."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, ValidationError

from backend.core.config import get_settings
from backend.providers.contracts import ProviderHealth, VisionObservation


class VisionPayload(BaseModel):
    scene_summary: str = ""
    observations: list[str] = Field(default_factory=list)
    suspected_anomalies: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)


class OllamaVision:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def analyze(self, path: Path, prompt: str) -> VisionObservation:
        if not self.settings.ollama_vision_model:
            raise RuntimeError("未配置 OLLAMA_VISION_MODEL")
        image = base64.b64encode(path.read_bytes()).decode("ascii")
        instruction = (
            "你是工业设备图片观察器。只输出 JSON，不要 Markdown。"
            "必须区分客观观察、疑似异常、不确定性和安全提示。"
            "禁止从图片不存在的内容推断故障。字段必须完整。\n" + prompt
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
        try:
            parsed = VisionPayload.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError("视觉模型未返回符合契约的 JSON") from exc
        return VisionObservation(**parsed.model_dump())

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
