import json
import time
from collections.abc import AsyncIterator

import httpx

from backend.core.config import Settings
from backend.core.errors import AppError


class OllamaProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def health(self) -> dict:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                response = await client.get(f"{self.settings.ollama_base_url}/api/tags")
                response.raise_for_status()
                models = [item.get("name") for item in response.json().get("models", [])]
            return {"available": True, "latency_ms": round((time.perf_counter() - started) * 1000, 1), "models": models}
        except (httpx.HTTPError, ValueError) as exc:
            return {"available": False, "latency_ms": round((time.perf_counter() - started) * 1000, 1), "reason": str(exc)}

    async def generate(self, prompt: str, context: list[str] | None = None) -> tuple[str, dict]:
        system = (
            "你是 VoiceInspect 工业设备诊断助手。只能根据给出的用户问题和资料依据回答。"
            "区分可观察事实、资料依据、推断建议和安全提示；资料不足时明确说资料不足，不要编造手册引用。"
            "可以使用安全的标准 Markdown（标题、粗体、列表、引用、代码和表格）组织回答，不要输出原始 HTML、脚本或危险链接。"
        )
        evidence = "\n\n".join(context or []) or "（没有检索到可靠资料）"
        composed = f"{system}\n\n资料依据：\n{evidence}\n\n用户问题：{prompt}"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                response = await client.post(
                    f"{self.settings.ollama_base_url}/api/generate",
                    json={"model": self.settings.ollama_llm_model, "prompt": composed, "stream": False, "options": {"temperature": 0.1}},
                )
                response.raise_for_status()
                data = response.json()
            return data.get("response", "").strip(), {
                "provider": "ollama",
                "model": self.settings.ollama_llm_model,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError("MODEL_UNAVAILABLE", "本地模型暂时不可用", 503, True, "llm", {"reason": str(exc)}) from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                response = await client.post(
                    f"{self.settings.ollama_base_url}/api/embed",
                    json={"model": self.settings.ollama_embed_model, "input": texts},
                )
                response.raise_for_status()
                data = response.json()
            return data["embeddings"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise AppError("RAG_EMBED_FAILED", "知识向量生成失败", 503, True, "rag", {"reason": str(exc)}) from exc

