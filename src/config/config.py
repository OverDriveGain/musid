import os
from dotenv import load_dotenv

load_dotenv()

config = {
    "port": int(os.getenv("PORT", 3001)),
    "youtube_service_url": os.getenv("YOUTUBE_SERVICE_URL", "http://localhost:10084"),
    "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
    "anthropic_model": os.getenv("ANTHROPIC_MODEL", "claude-opus-4-6"),
    "redis_url": os.getenv("REDIS_URL", ""),
    "music_path": os.getenv("MUSIC_PATH", "/mnt/music"),
    "download_folder": os.getenv("DOWNLOAD_FOLDER", "YoutubeDownloads"),
    "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
}
