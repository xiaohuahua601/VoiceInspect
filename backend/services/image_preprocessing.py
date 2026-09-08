"""Lossless original retention plus VLM-friendly image normalization."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps


def prepare_image_bytes(path: Path, max_size: int = 1600) -> bytes:
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=90, optimize=True)
        return output.getvalue()