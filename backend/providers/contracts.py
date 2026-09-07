"""Provider contracts shared by local AI capability adapters.

Providers deliberately return typed, capability-specific results.  Business
services decide whether a partial result is safe to use; providers never
silently manufacture a successful answer when a model is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Protocol


@dataclass
class ProviderHealth:
    name: str
    available: bool
    detail: str | None = None
    model: str | None = None
    latency_ms: int | None = None


@dataclass
class Transcript:
    text: str
    language: str | None = None
    duration_ms: int | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class VisionObservation:
    scene_summary: str
    observations: list[str]
    suspected_anomalies: list[str]
    uncertainties: list[str]
    safety_flags: list[str]


class STTProvider(Protocol):
    async def transcribe(self, path: Path) -> Transcript: ...
    async def health(self) -> ProviderHealth: ...


class VisionProvider(Protocol):
    async def analyze(self, path: Path, prompt: str) -> VisionObservation: ...
    async def health(self) -> ProviderHealth: ...


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...
    async def health(self) -> ProviderHealth: ...


class LLMProvider(Protocol):
    async def stream(self, prompt: str) -> AsyncIterator[str]: ...
    async def health(self) -> ProviderHealth: ...


class TTSProvider(Protocol):
    async def synthesize(self, text: str, output: Path) -> Path: ...
    async def health(self) -> ProviderHealth: ...
