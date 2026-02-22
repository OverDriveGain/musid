from pydantic import BaseModel


class TagRequest(BaseModel):
    directory: str


class TagResult(BaseModel):
    file: str
    status: str
    title: str = ""
    artist: str = ""
    album: str = ""
    message: str = ""


class AlbumRecognizeRequest(BaseModel):
    file: str
    chunk_duration: int = 15  # seconds


class TrackResult(BaseModel):
    title: str
    artist: str
    start_time: float   # seconds from start of file
    end_time: float     # seconds from start of file
    confidence: int     # number of chunks that matched
    output_file: str = ""
