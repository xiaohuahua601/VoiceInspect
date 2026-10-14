"""Qwen cloud adapter using Alibaba Cloud's OpenAI-compatible API."""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.providers.ollama import OllamaProvider


class QwenProvider(OllamaProvider):
    """Text provider for Qwen; embedding remains local Ollama by design."""

    @property
    def model_name(self) -> str:
        return self.settings.qwen_model

    def _headers(self) -> dict[str, str]:
        if not self.settings.qwen_api_key:
            raise AppError("MODEL_NOT_CONFIGURED", "未配置千问 API Key", 503, False, "llm")
        return {"Authorization": f"Bearer {self.settings.qwen_api_key}", "Content-Type": "application/json"}

    def _endpoint(self) -> str:
        return self.settings.qwen_base_url.rstrip("/") + "/chat/completions"

    @staticmethod
    def _content(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in value)
        return str(value or "")

    @staticmethod
    def _parse_json_content(raw: str) -> dict[str, Any]:
        text = raw.strip()
        fence = chr(96) * 3
        if text.startswith(fence):
            text = text[3:]
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
            if text.rstrip().endswith(fence):
                text = text.rstrip()[:-3]
            text = text.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise
            parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("vision JSON top level must be an object")
        return parsed

    def _request_body(self, prompt: str, *, stream: bool, image: str | None = None) -> dict[str, Any]:
        user_content: Any = prompt
        if image:
            user_content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
            ]
        return {
            "model": self.model_name,
            "messages": [{"role": "user", "content": user_content}],
            "stream": stream,
            "temperature": 0.1,
            "max_tokens": self.settings.qwen_max_tokens,
            "enable_thinking": self.settings.qwen_enable_thinking if not image else False,
        }

    async def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        if not self.settings.qwen_api_key:
            return {"available": False, "latency_ms": 0, "reason": "未配置 QWEN_API_KEY", "models": [], "model": self.model_name}
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                response = await client.get(self.settings.qwen_base_url.rstrip("/") + "/models", headers=self._headers())
                response.raise_for_status()
                data = response.json()
            models = [str(item.get("id")) for item in data.get("data", []) if item.get("id")]
            return {"available": True, "latency_ms": round((time.perf_counter() - started) * 1000, 1), "models": models, "model": self.model_name}
        except (httpx.HTTPError, ValueError, AppError) as exc:
            return {"available": False, "latency_ms": round((time.perf_counter() - started) * 1000, 1), "reason": str(exc), "models": [], "model": self.model_name}

    async def generate(self, prompt: str, context: list[str] | None = None) -> tuple[str, dict[str, Any]]:
        composed = self.build_prompt(prompt, context)
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.settings.qwen_timeout_seconds, trust_env=False) as client:
                response = await client.post(self._endpoint(), headers=self._headers(), json=self._request_body(composed, stream=False))
                response.raise_for_status()
                data = response.json()
            choices = data.get("choices") or []
            answer = self._content((choices[0].get("message") or {}).get("content")) if choices else ""
            return answer.strip(), self._metadata(data, started)
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("MODEL_UNAVAILABLE", "千问模型暂时不可用", 503, True, "llm", {"reason": str(exc)[:300]}) from exc

    async def stream_generate(self, prompt: str, context: list[str] | None = None) -> AsyncIterator[dict[str, Any]]:
        composed = self.build_prompt(prompt, context)
        started = time.perf_counter()
        final_data: dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=self.settings.qwen_timeout_seconds, trust_env=False) as client:
                async with client.stream("POST", self._endpoint(), headers=self._headers(), json=self._request_body(composed, stream=True)) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        raw = line.strip()
                        if not raw or raw.startswith(":"):
                            continue
                        if raw.startswith("data:"):
                            raw = raw[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        final_data = data
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield {"type": "chunk", "content": self._content(content)}
            yield {"type": "done", "metadata": self._metadata(final_data, started)}
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("MODEL_UNAVAILABLE", "千问模型暂时不可用", 503, True, "llm", {"reason": str(exc)[:300]}) from exc

    async def vision_json(self, image: str, instruction: str) -> dict[str, Any]:
        """Send one image and request a JSON object for the vision contract."""
        body = self._request_body(instruction, stream=False, image=image)
        body["response_format"] = {"type": "json_object"}
        body["max_tokens"] = self.settings.qwen_vision_max_tokens
        try:
            async with httpx.AsyncClient(timeout=self.settings.qwen_timeout_seconds, trust_env=False) as client:
                response = await client.post(self._endpoint(), headers=self._headers(), json=body)
                response.raise_for_status()
                data = response.json()
            choices = data.get("choices") or []
            raw = self._content((choices[0].get("message") or {}).get("content")) if choices else ""
            return self._parse_json_content(raw)
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError("千问视觉模型未返回符合契约的 JSON") from exc

    def _metadata(self, data: dict[str, Any], started: float) -> dict[str, Any]:
        usage = data.get("usage") or {}
        return {
            "provider": "qwen",
            "model": self.model_name,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "finish_reason": ((data.get("choices") or [{}])[0] or {}).get("finish_reason"),
        }

