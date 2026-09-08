"""Shared server-side pagination contract for admin list endpoints."""

from __future__ import annotations

from math import ceil

from backend.core.errors import AppError


def normalize_page(page: int | None, page_size: int) -> tuple[int, int] | None:
    if page is None:
        return None
    if page < 1 or page_size < 1 or page_size > 100:
        raise AppError("PAGINATION_INVALID", "分页参数无效，页码从 1 开始且每页最多 100 条", 422, False, "api")
    return page, page_size


def page_result(items: list[dict], total: int, page: int, page_size: int) -> dict:
    return {
        "items": items,
        "meta": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": max(1, ceil(total / page_size)) if total else 0,
        },
    }
