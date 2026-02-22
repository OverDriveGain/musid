from fastapi import APIRouter
from src.types.types import TagRequest
from src.controllers.tag_controller import tag_directory
from src.controllers.album_controller import recognize_album

router = APIRouter()

router.post("/tag")(tag_directory)
router.post("/recognize-album")(recognize_album)
