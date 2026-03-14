import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.config.config import config
from src.middleware.error_handler import error_handler
from src.routes.tag_routes import router
from src.routes.tracklist_routes import router as tracklist_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = None
    if config.get("redis_url"):
        from src.workers.download_worker import run_worker
        worker_task = asyncio.create_task(run_worker(config["redis_url"]))
        print("[App] Download worker started")
    yield
    if worker_task:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)

app.add_exception_handler(Exception, error_handler)

app.include_router(router, prefix="/api")
app.include_router(tracklist_router, prefix="/api")


@app.get("/api/health")
async def health():
    return JSONResponse({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.app:app", host="0.0.0.0", port=config["port"], reload=True)
