import json
import re
from typing import Optional

import httpx

from src.config.config import config
from src.types.types import TrackEntry

BATCH_PROMPT = """\
You are analyzing YouTube comments to find a tracklist comment.
A tracklist comment has multiple lines each pairing a timestamp (0:00, 3:45, 1:02:34) with a song title — for a continuous music mix or album video.

Comments:
{comments}

If you find a tracklist comment, respond ONLY with this JSON:
{{"found": true, "index": <number>, "tracks": [{{"timestamp": "0:00", "title": "Song Name"}}]}}

If no tracklist comment exists, respond ONLY with:
{{"found": false}}

Rules:
- A real tracklist has at least 3 timestamp+title pairs.
- Respond with ONLY the JSON object, no other text.\
"""


def _timestamp_to_seconds(ts: str) -> int:
    parts = [int(p) for p in ts.strip().split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return 0


class TracklistDetector:
    async def detect_from_batch(self, comments: list[dict]) -> Optional[dict]:
        entries = []
        for i, c in enumerate(comments):
            text = c.get("text", "").strip().replace("\n", " | ")
            if len(text) > 500:
                text = text[:500] + "..."
            entries.append(f"[{i}] {text}")

        prompt = BATCH_PROMPT.format(comments="\n".join(entries))

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{config['ollama_url']}/api/generate",
                json={"model": config["ollama_model"], "prompt": prompt, "stream": False},
                timeout=120.0,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip()

        parsed = _parse_json(raw)
        if parsed is None or not parsed.get("found"):
            return None

        idx = parsed.get("index")
        if idx is None or not (0 <= idx < len(comments)):
            return None

        tracks = []
        for t in parsed.get("tracks", []):
            ts = t.get("timestamp", "0:00")
            title = t.get("title", "").strip()
            if ts and title:
                tracks.append(TrackEntry(timestamp=ts, seconds=_timestamp_to_seconds(ts), title=title))

        if not tracks:
            return None

        comment = comments[idx]
        return {
            "comment_author": comment.get("author_name", ""),
            "comment_text": comment.get("text", ""),
            "like_count": comment.get("like_count", 0),
            "tracks": tracks,
        }


def _parse_json(raw: str) -> Optional[dict]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None
