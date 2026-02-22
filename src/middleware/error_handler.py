from fastapi import Request
from fastapi.responses import JSONResponse


async def error_handler(request: Request, exc: Exception) -> JSONResponse:
    print(f"[Error] {exc}")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(exc)},
    )
