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
    # musdowlow, for the post-recognition "add to playlist" callback (it owns the
    # Navidrome integration). Token = musdowlow's FILE_LINK_MINT_TOKEN.
    "musdowlow_url": os.getenv("MUSDOWLOW_URL", ""),
    "musdowlow_token": os.getenv("MUSDOWLOW_MINT_TOKEN", ""),
}
