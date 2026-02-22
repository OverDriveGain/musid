from fastapi import FastAPI
from fastapi.responses import JSONResponse
from datetime import datetime, timezone

from src.config.config import config
from src.routes.tag_routes import router
from src.routes.tracklist_routes import router as tracklist_router
from src.middleware.error_handler import error_handler

app = FastAPI()

app.add_exception_handler(Exception, error_handler)

app.include_router(router, prefix="/api")
app.include_router(tracklist_router, prefix="/api")


@app.get("/api/health")
async def health():
    return JSONResponse({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.app:app", host="0.0.0.0", port=config["port"], reload=True)
