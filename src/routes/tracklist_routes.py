from fastapi import APIRouter, Query

from src.controllers.tracklist_controller import detect_tracklist

router = APIRouter()


@router.get("/tracklist")
async def get_tracklist(
    music_id: str = Query(..., description="YouTube URL or video ID"),
    max_comments: int = Query(100, ge=1, le=200, description="Max comments to scan"),
):
    return await detect_tracklist(music_id, max_comments)
