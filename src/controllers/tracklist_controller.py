from fastapi import HTTPException

from src.services.tracklist_detector import TracklistDetector
from src.services.youtube_comments import YoutubeCommentsService

youtube_service = YoutubeCommentsService()
detector = TracklistDetector()


async def detect_tracklist(music_id: str, max_comments: int = 100) -> dict:
    try:
        comments = await youtube_service.get_comments(music_id, max_results=max_comments)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch comments from YouTube service: {e}")

    if not comments:
        return {"status": "not_found", "message": "No comments returned for this video"}

    try:
        result = await detector.detect_from_batch(comments)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    if result:
        return {
            "status": "found",
            "music_id": music_id,
            **result,
            "tracks": [t.dict() for t in result["tracks"]],
        }

    return {"status": "not_found", "message": "No tracklist comment found"}
