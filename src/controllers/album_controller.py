from fastapi import HTTPException
from src.services.album_recognizer import AlbumRecognizer
from src.types.types import AlbumRecognizeRequest

recognizer = AlbumRecognizer()


async def recognize_album(req: AlbumRecognizeRequest) -> dict:
    try:
        tracks = await recognizer.recognize_album(req.file, req.chunk_duration)
        return {
            "status": "success",
            "total_tracks": len(tracks),
            "data": [t.dict() for t in tracks],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
