import re
from typing import List, Optional, TypeVar

import anthropic
from pydantic import BaseModel, Field

from src.config.config import config
from src.types.types import TrackEntry

T = TypeVar("T", bound=BaseModel)

# Limits — Claude has a huge context window, so we can be generous,
# but cap total comments so we don't blow tokens on noisy threads.
MAX_COMMENTS = 30           # max number of comments sent to Claude
PER_COMMENT_CHARS = 4000    # per-comment truncation cap
DESCRIPTION_CHARS = 15000   # description truncation cap
MAX_TOKENS = 4096           # plenty of room for a long tracklist response


class _Track(BaseModel):
    timestamp: str = Field(description="Timestamp like '0:00', '3:45' or '1:02:34'")
    title: str = Field(description="Song title")


class _DescriptionResult(BaseModel):
    found: bool
    tracks: List[_Track] = Field(default_factory=list)


class _BatchResult(BaseModel):
    found: bool
    index: Optional[int] = None
    tracks: List[_Track] = Field(default_factory=list)


DESCRIPTION_SYSTEM = (
    "You extract song tracklists from YouTube video descriptions. "
    "A tracklist pairs timestamps (0:00, 3:45, 1:02:34) with song titles. "
    "Only return found=true if you see at least 3 timestamp+title pairs."
)

BATCH_SYSTEM = (
    "You find tracklist comments under YouTube videos. "
    "A tracklist comment has multiple lines pairing timestamps (0:00, 3:45, 1:02:34) "
    "with song titles, for a continuous music mix or album video. "
    "Only return found=true if a single comment contains at least 3 timestamp+title pairs. "
    "Set 'index' to the index of that comment."
)


_TS_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")


def _timestamp_to_seconds(ts: str) -> int:
    parts = [int(p) for p in ts.strip().split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return 0


def _tracklist_score(text: str) -> int:
    """Comments with more timestamps are more likely to be tracklists."""
    return len(_TS_RE.findall(text))


def _select_comments(comments: list[dict], limit: int) -> list[dict]:
    """
    Pick comments most likely to be tracklists, capped at `limit`.
    Prefers comments with many timestamp matches; falls back to original order.
    """
    indexed = list(enumerate(comments))
    indexed.sort(key=lambda x: (-_tracklist_score(x[1].get("text", "")), x[0]))
    return [c for _, c in indexed[:limit]]


def _extract_parsed(response) -> Optional[BaseModel]:
    for block in response.content:
        parsed = getattr(block, "parsed_output", None)
        if parsed is not None:
            return parsed
    return None


def _to_track_entries(tracks: List[_Track]) -> List[TrackEntry]:
    out: List[TrackEntry] = []
    for t in tracks:
        title = (t.title or "").strip()
        ts = (t.timestamp or "").strip()
        if not title or not ts:
            continue
        out.append(TrackEntry(timestamp=ts, seconds=_timestamp_to_seconds(ts), title=title))
    return out


class TracklistDetector:
    def __init__(self):
        api_key = config["anthropic_api_key"]
        if not api_key:
            print("[Claude] Warning: ANTHROPIC_API_KEY is not set")
        self._client = anthropic.AsyncAnthropic(api_key=api_key or None)
        self._model = config["anthropic_model"]

    async def detect_from_description(self, description: str) -> Optional[dict]:
        text = description[:DESCRIPTION_CHARS]
        print(f"[Claude] Analyzing description ({len(text)} chars) ...")
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=DESCRIPTION_SYSTEM,
                messages=[{"role": "user", "content": f"Description:\n{text}"}],
                output_format=_DescriptionResult,
            )
        except Exception as e:
            print(f"[Claude]   error: {e}")
            return None

        result: Optional[_DescriptionResult] = _extract_parsed(response)
        if not result or not result.found or not result.tracks:
            print(f"[Claude]   no tracklist found in description")
            return None

        tracks = _to_track_entries(result.tracks)
        if not tracks:
            return None
        print(f"[Claude]   ✓ Found {len(tracks)} tracks in description")
        return {
            "tracks": tracks,
            "comment_author": "",
            "comment_text": "",
            "like_count": 0,
        }

    async def detect_from_batch(self, comments: list[dict]) -> Optional[dict]:
        selected = _select_comments(comments, MAX_COMMENTS)
        if not selected:
            return None

        entries = []
        for i, c in enumerate(selected):
            text = c.get("text", "").strip()
            if len(text) > PER_COMMENT_CHARS:
                text = text[:PER_COMMENT_CHARS] + "..."
            entries.append(f"[{i}]\n{text}")

        prompt = "Comments:\n\n" + "\n\n---\n\n".join(entries)
        print(
            f"[Claude] Analyzing {len(selected)} of {len(comments)} comments "
            f"({sum(len(e) for e in entries)} chars total) ..."
        )

        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=BATCH_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_format=_BatchResult,
            )
        except Exception as e:
            print(f"[Claude]   error: {e}")
            return None

        result: Optional[_BatchResult] = _extract_parsed(response)
        if not result or not result.found or result.index is None or not result.tracks:
            print(f"[Claude]   no tracklist comment found")
            return None

        if not (0 <= result.index < len(selected)):
            print(f"[Claude]   invalid comment index {result.index}")
            return None

        tracks = _to_track_entries(result.tracks)
        if not tracks:
            return None

        comment = selected[result.index]
        print(
            f"[Claude]   ✓ Found {len(tracks)} tracks in comment by "
            f"{comment.get('author_name', '?')}"
        )
        return {
            "comment_author": comment.get("author_name", ""),
            "comment_text": comment.get("text", ""),
            "like_count": comment.get("like_count", 0),
            "tracks": tracks,
        }
