import os
from dotenv import load_dotenv

load_dotenv()

config = {
    "port": int(os.getenv("PORT", 3001)),
    "youtube_service_url": os.getenv("YOUTUBE_SERVICE_URL", "http://localhost:10084"),
    "ollama_url": os.getenv("OLLAMA_URL", "https://ollama.kaxtus.com"),
    "ollama_model": os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct"),
    "redis_url": os.getenv("REDIS_URL", ""),
    "music_path": os.getenv("MUSIC_PATH", "/mnt/music"),
    "download_folder": os.getenv("DOWNLOAD_FOLDER", "YoutubeDownloads"),
}
