from fastapi import HTTPException
from src.services.shazam_tagger import ShazamTagger
from src.types.types import TagRequest, TagResult

tagger = ShazamTagger()


async def tag_directory(req: TagRequest) -> dict:
    try:
        results = await tagger.tag_directory(req.directory)
        return {
            "status": "success",
            "data": [r.dict() for r in results],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
