"""Optional headless Piper TTS adapter for Docker/Linux deployments."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from backend.core.config import get_settings
from backend.providers.contracts import ProviderHealth


class PiperTTS:
    name = "piper"

    def __init__(self) -> None:
        settings = get_settings()
        self.executable = getattr(settings, "piper_executable", "piper")
        self.voice = getattr(settings, "piper_voice", "")

    async def synthesize(self, text: str, output: Path) -> Path:
        if not self.voice:
            raise RuntimeError("未配置 PIPER_VOICE")

        def run() -> Path:
            completed = subprocess.run(
                [self.executable, "--model", self.voice, "--output_file", str(output)],
                input=text,
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or "Piper 合成失败")
            return output

        return await asyncio.to_thread(run)

    async def health(self) -> ProviderHealth:
        if not self.voice:
            return ProviderHealth(self.name, False, "未配置 PIPER_VOICE")
        if not Path(self.voice).exists():
            return ProviderHealth(self.name, False, "Piper voice 文件不存在", self.voice)
        if not Path(self.executable).exists() and not os.path.isabs(self.executable):
            return ProviderHealth(self.name, False, "Piper 可执行文件不可用", self.voice)
        return ProviderHealth(self.name, True, model=self.voice)
