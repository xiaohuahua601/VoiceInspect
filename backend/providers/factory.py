"""Provider selection for local Ollama and Qwen cloud inference."""
from __future__ import annotations

from backend.core.config import Settings
from backend.providers.ollama import OllamaProvider
from backend.providers.qwen import QwenProvider
from backend.providers.vision import OllamaVision, QwenVision


def use_qwen(settings: Settings) -> bool:
    return settings.model_provider.strip().lower() in {"qwen", "dashscope"}


def create_llm_provider(settings: Settings):
    return QwenProvider(settings) if use_qwen(settings) else OllamaProvider(settings)


def create_embedding_provider(settings: Settings):
    # Existing local vectors remain valid. A cloud embedding migration requires a full re-index.
    return OllamaProvider(settings)


def create_vision_provider(settings: Settings):
    return QwenVision(settings) if use_qwen(settings) else OllamaVision(settings)
