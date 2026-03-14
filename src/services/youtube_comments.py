import httpx

from src.config.config import config


class YoutubeCommentsService:
    async def get_comments(self, youtube_url: str, max_results: int = 100) -> list[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{config['youtube_service_url']}/comments",
                params={"url": youtube_url, "max_results": max_results, "order": "relevance"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("comments", [])

    async def get_description(self, youtube_url: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{config['youtube_service_url']}/description",
                params={"url": youtube_url},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("description", "")
