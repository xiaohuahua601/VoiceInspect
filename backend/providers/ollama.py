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

    def build_prompt(self, prompt: str, context: list[str] | None = None) -> str:
        system = (
            "你是 VoiceInspect 工业设备诊断助手，只能依据用户问题、当前设备上下文和资料依据回答。"
            "回答必须严格使用以下 Markdown 结构，标题必须独占一行且按顺序出现：\n"
            "## 结论\n用 1-2 句话直接回答；无法确定时明确写‘无法确认’。\n"
            "## 资料依据\n用项目符号列出资料事实；没有资料时写‘未检索到足够资料’。\n"
            "## 排查步骤\n用编号列表给出可执行、由先到后的检查步骤。\n"
            "## 安全提示\n用引用块写出停机、泄压、断电或 PPE 等必要安全措施；没有额外提示时写‘按现场安全规程执行’。\n"
            "## 不确定性\n说明哪些内容是现场观察、哪些是推断，以及还需要什么证据。\n"
            "每个标题之间保留一个空行；不要添加开场白或结尾客套话。"
            "不要输出原始 HTML、脚本、危险链接或 JSON；不要编造手册章节、页码、数值和引用。"
            "如果资料依据中出现[图片现场证据]，必须把其中的疑似异常写进## 结论，并同时引用对应的客观观察；没有手册资料也不能忽略图像异常。"
        )
        evidence = "\n\n".join(context or []) or "（没有检索到可靠资料）"
        return f"{system}\n\n资料依据：\n{evidence}\n\n用户问题：{prompt}"

    async def generate(self, prompt: str, context: list[str] | None = None) -> tuple[str, dict]:
        composed = self.build_prompt(prompt, context)
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

    async def stream_generate(self, prompt: str, context: list[str] | None = None) -> AsyncIterator[dict]:
        composed = self.build_prompt(prompt, context)
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    f"{self.settings.ollama_base_url}/api/generate",
                    json={"model": self.settings.ollama_llm_model, "prompt": composed, "stream": True, "options": {"temperature": 0.1}},
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        content = data.get("response", "")
                        if content:
                            yield {"type": "chunk", "content": content}
                        if data.get("done"):
                            yield {
                                "type": "done",
                                "metadata": {
                                    "provider": "ollama",
                                    "model": self.settings.ollama_llm_model,
                                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                                },
                            }
                            return
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
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

