"""Optional local faster-whisper adapter."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from backend.core.config import get_settings
from backend.providers.contracts import ProviderHealth, STTProvider, Transcript


class FasterWhisperSTT:
    name = "faster-whisper"

    def __init__(self) -> None:
        settings = get_settings()
        self.model_size = settings.stt_model_size
        self.device = settings.stt_device
        self.compute_type = settings.stt_compute_type
        self.model_path = settings.stt_model_path
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper 未安装") from exc
        kwargs = {"device": self.device, "compute_type": self.compute_type}
        if self.model_path:
            kwargs["download_root"] = self.model_path
        self._model = WhisperModel(self.model_size, **kwargs)
        return self._model

    async def transcribe(self, path: Path) -> Transcript:
        started = time.perf_counter()

        def run():
            model = self._load()
            segments, info = model.transcribe(str(path), beam_size=5, vad_filter=True)
            rows = []
            parts = []
            for segment in segments:
                text = segment.text.strip()
                if text:
                    parts.append(text)
                    rows.append({"start": segment.start, "end": segment.end, "text": text})
            duration_ms = int(getattr(info, "duration", 0) * 1000) if info else None
            return Transcript(" ".join(parts), getattr(info, "language", None), duration_ms, rows)

        result = await asyncio.to_thread(run)
        result.segments.append({"latency_ms": int((time.perf_counter() - started) * 1000)})
        return result

    async def health(self) -> ProviderHealth:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return ProviderHealth(self.name, False, "faster-whisper 未安装", self.model_size)
        return ProviderHealth(self.name, True, model=self.model_size)
