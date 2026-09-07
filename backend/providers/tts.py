"""Local TTS adapters. Windows SAPI is used only on a Windows host."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from backend.providers.contracts import ProviderHealth


class WindowsSapiTTS:
    name = "windows-sapi"

    async def synthesize(self, text: str, output: Path) -> Path:
        if os.name != "nt":
            raise RuntimeError("Windows SAPI 仅支持 Windows 宿主机")
        def run():
            try:
                import pyttsx3
            except ImportError as exc:
                raise RuntimeError("pyttsx3 未安装") from exc
            engine = pyttsx3.init()
            engine.save_to_file(text, str(output))
            engine.runAndWait()
            return output

        return await asyncio.to_thread(run)

    async def health(self) -> ProviderHealth:
        if os.name != "nt":
            return ProviderHealth(self.name, False, "Windows SAPI 仅支持 Windows 宿主机")
        try:
            import pyttsx3  # noqa: F401
        except ImportError:
            return ProviderHealth(self.name, False, "pyttsx3 未安装")
        return ProviderHealth(self.name, True)
