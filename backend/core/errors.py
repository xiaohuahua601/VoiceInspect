from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass
class AppError(Exception):
    code: str
    message: str
    status_code: int = 400
    retryable: bool = False
    stage: str = "api"
    details: dict | None = None


def error_payload(error: AppError, trace_id: str) -> dict:
    data = {
        "code": error.code,
        "message": error.message,
        "retryable": error.retryable,
        "stage": error.stage,
        "trace_id": trace_id,
    }
    if error.details:
        data["details"] = error.details
    return {"error": data}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", "unknown")
    return JSONResponse(status_code=exc.status_code, content=error_payload(exc, trace_id))
